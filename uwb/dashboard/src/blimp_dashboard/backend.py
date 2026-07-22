"""Thread-safe MAVLink transport for the real blimp autopilot.

The dashboard is a ground-control station.  It never generates simulated
vehicle positions and it does not continuously stream flight setpoints.  All
state-changing commands wait for their MAVLink acknowledgement; mission upload
uses the standard request/response transaction.
"""

from __future__ import annotations

from copy import deepcopy
import logging
import math
import threading
import time
from typing import Callable, Sequence

try:  # Allow the UWB-only dashboard to start when MAVLink is not configured.
    from pymavlink import mavutil
except ImportError:  # pragma: no cover - exercised indirectly by server tests
    mavutil = None


logger = logging.getLogger(__name__)


class MAVLinkError(RuntimeError):
    """Base class for errors that can safely be exposed by the HTTP layer."""


class MAVLinkConnectionError(MAVLinkError):
    """The configured MAVLink endpoint did not yield the expected autopilot."""


class MAVLinkTimeoutError(MAVLinkError):
    """The autopilot did not complete a MAVLink transaction in time."""

    def __init__(self, message: str, *, acknowledged: bool = False) -> None:
        super().__init__(message)
        self.acknowledged = acknowledged


class MAVLinkRejectedError(MAVLinkError):
    """The autopilot explicitly rejected a command or mission."""


class MAVLinkBackend:
    """Own a single real MAVLink connection and serialize its transactions.

    ``connection_factory`` and ``start_telemetry`` exist to make the transport
    testable without opening a serial port or UDP socket.  Production callers
    normally leave both at their defaults.
    """

    def __init__(
        self,
        connection_string: str,
        *,
        baud: int = 115200,
        heartbeat_timeout: float = 10.0,
        link_timeout: float = 5.0,
        command_timeout: float = 5.0,
        command_retries: int = 3,
        mission_timeout: float = 30.0,
        source_system: int = 255,
        source_component: int = 190,
        expected_target_system: int | None = None,
        expected_target_component: int | None = None,
        connection_factory: Callable[..., object] | None = None,
        start_telemetry: bool = True,
    ) -> None:
        if not connection_string:
            raise ValueError("MAVLink connection string must not be empty")
        if heartbeat_timeout <= 0 or link_timeout <= 0:
            raise ValueError("MAVLink timeouts must be positive")
        if command_timeout <= 0 or mission_timeout <= 0:
            raise ValueError("MAVLink transaction timeouts must be positive")
        if command_retries <= 0:
            raise ValueError("MAVLink command retries must be positive")
        if not 1 <= source_system <= 255 or not 1 <= source_component <= 255:
            raise ValueError("MAVLink source ids must be in range 1..255")

        if connection_factory is None:
            if mavutil is None:
                raise MAVLinkConnectionError(
                    "pymavlink is not installed; install the dashboard package "
                    "with its declared dependencies"
                )
            connection_factory = mavutil.mavlink_connection

        self.connection_string = connection_string
        self.link_timeout = float(link_timeout)
        self.command_timeout = float(command_timeout)
        self.command_retries = int(command_retries)
        self.mission_timeout = float(mission_timeout)
        self.source_system = source_system
        self.source_component = source_component
        self._io_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_heartbeat_monotonic: float | None = None
        self._last_error: str | None = None

        self.telemetry = {
            "position": {
                "lat": None,
                "lon": None,
                "alt": None,
                "relative_alt": None,
            },
            "local_position": {"x": None, "y": None, "z": None},
            "battery": {"voltage": None, "current": None, "remaining": None},
            "mode": None,
            "armed": None,
        }

        logger.info("Opening MAVLink endpoint %s", connection_string)
        self.master = None
        try:
            self.master = connection_factory(
                connection_string,
                baud=baud,
                source_system=source_system,
                source_component=source_component,
            )
            heartbeat = self._wait_for_target_heartbeat(
                heartbeat_timeout,
                expected_target_system,
                expected_target_component,
            )
        except Exception as exc:
            if self.master is not None:
                with self._suppress_close_errors():
                    self.master.close()
            raise MAVLinkConnectionError(
                f"could not open MAVLink endpoint or receive heartbeat: {exc}"
            ) from exc

        if heartbeat is None:
            with self._suppress_close_errors():
                self.master.close()
            raise MAVLinkConnectionError(
                f"no autopilot heartbeat within {heartbeat_timeout:g} seconds"
            )

        # pymavlink's wait_heartbeat locks target_system, but target_component
        # normally stays at its default 0.  Commands must target the component
        # that actually emitted the autopilot heartbeat (usually component 1).
        source_system = self._message_source_system(heartbeat)
        source_component = self._message_source_component(heartbeat)
        self.target_system = int(
            source_system if source_system is not None else self.master.target_system
        )
        self.target_component = int(
            source_component
            if source_component is not None
            else getattr(self._mavlink(), "MAV_COMP_ID_AUTOPILOT1", 1)
        )
        if not 1 <= self.target_system <= 255:
            self.master.close()
            raise MAVLinkConnectionError("heartbeat did not identify a target system")
        if not 1 <= self.target_component <= 255:
            self.master.close()
            raise MAVLinkConnectionError("heartbeat did not identify a target component")
        if expected_target_system is not None and self.target_system != expected_target_system:
            self.master.close()
            raise MAVLinkConnectionError(
                f"expected MAVLink system {expected_target_system}, got {self.target_system}"
            )
        if (
            expected_target_component is not None
            and self.target_component != expected_target_component
        ):
            self.master.close()
            raise MAVLinkConnectionError(
                "expected MAVLink component "
                f"{expected_target_component}, got {self.target_component}"
            )
        self.master.target_system = self.target_system
        self.master.target_component = self.target_component
        self.autopilot_type = int(getattr(heartbeat, "autopilot", 0))
        self.vehicle_type = int(getattr(heartbeat, "type", 0))

        self._mark_heartbeat()
        self._process_message(heartbeat)
        logger.info(
            "MAVLink autopilot connected: system=%d component=%d",
            self.target_system,
            self.target_component,
        )
        if start_telemetry:
            self.start_telemetry_loop()

    def _wait_for_target_heartbeat(
        self,
        timeout: float,
        expected_system: int | None,
        expected_component: int | None,
    ):
        """Wait for an autopilot heartbeat, ignoring GCS/other-system traffic."""

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            heartbeat = self.master.wait_heartbeat(timeout=remaining)
            if heartbeat is None:
                return None

            detector = getattr(self.master, "probably_vehicle_heartbeat", None)
            if detector is not None:
                try:
                    if not detector(heartbeat):
                        continue
                except Exception:
                    continue
            elif mavutil is not None:
                mav = self._mavlink()
                if getattr(heartbeat, "autopilot", None) == mav.MAV_AUTOPILOT_INVALID:
                    continue

            source_system = self._message_source_system(heartbeat)
            source_component = self._message_source_component(heartbeat)
            if expected_system is not None and source_system != expected_system:
                continue
            if expected_component is not None and source_component != expected_component:
                continue
            return heartbeat

    @staticmethod
    def _suppress_close_errors():
        """Tiny local helper to avoid importing contextlib on the hot path."""

        class _Suppress:
            def __enter__(self):
                return None

            def __exit__(self, *_args):
                return True

        return _Suppress()

    def _mavlink(self):
        if mavutil is None:
            raise MAVLinkConnectionError("pymavlink is not available")
        return mavutil.mavlink

    def _mark_heartbeat(self) -> None:
        with self._state_lock:
            self._last_heartbeat_monotonic = time.monotonic()
            self._last_error = None

    @property
    def is_connected(self) -> bool:
        with self._state_lock:
            last = self._last_heartbeat_monotonic
        return last is not None and time.monotonic() - last <= self.link_timeout

    def start_telemetry_loop(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._telemetry_loop,
            name="blimp-mavlink",
            daemon=True,
        )
        self._thread.start()

    def _telemetry_loop(self) -> None:
        """Read real telemetry and emit only a low-rate GCS heartbeat.

        Stream-rate requests and fake origins are deliberately absent: both
        mutate the real link/autopilot and should be configured on the vehicle.
        """

        next_gcs_heartbeat = 0.0
        while not self._stop_event.is_set():
            if not self._io_lock.acquire(timeout=0.2):
                continue
            try:
                now = time.monotonic()
                if now >= next_gcs_heartbeat:
                    self._send_heartbeat_locked()
                    next_gcs_heartbeat = now + 1.0
                msg = self.master.recv_match(blocking=True, timeout=0.2)
            except Exception as exc:  # keep the web process alive on link loss
                with self._state_lock:
                    self._last_error = str(exc)
                logger.warning("MAVLink receive failed: %s", exc)
                msg = None
            finally:
                self._io_lock.release()
            if msg is not None:
                self._process_message(msg)

    def _process_message(self, msg) -> None:
        msg_type = msg.get_type()
        if msg_type == "BAD_DATA":
            return
        if not self._is_from_target(msg):
            return

        if msg_type == "HEARTBEAT":
            self._mark_heartbeat()
            mode = None
            if mavutil is not None:
                try:
                    mode = mavutil.mode_string_v10(msg)
                except Exception:
                    mode = None
            base_mode = int(getattr(msg, "base_mode", 0))
            armed_flag = getattr(
                self._mavlink(), "MAV_MODE_FLAG_SAFETY_ARMED", 128
            )
            with self._state_lock:
                self.telemetry["mode"] = mode or str(
                    getattr(msg, "custom_mode", "UNKNOWN")
                )
                self.telemetry["armed"] = bool(base_mode & armed_flag)
            return

        with self._state_lock:
            if msg_type == "LOCAL_POSITION_NED":
                self.telemetry["local_position"] = {
                    "x": float(msg.x),
                    "y": float(msg.y),
                    "z": float(msg.z),
                }
            elif msg_type == "GLOBAL_POSITION_INT":
                self.telemetry["position"] = {
                    "lat": msg.lat / 1e7,
                    "lon": msg.lon / 1e7,
                    "alt": msg.alt / 1000.0,
                    "relative_alt": msg.relative_alt / 1000.0,
                }
            elif msg_type == "SYS_STATUS":
                self.telemetry["battery"] = {
                    "voltage": (
                        None if msg.voltage_battery == 65535
                        else msg.voltage_battery / 1000.0
                    ),
                    "current": (
                        None if msg.current_battery == -1
                        else msg.current_battery / 100.0
                    ),
                    "remaining": (
                        None if msg.battery_remaining == -1
                        else int(msg.battery_remaining)
                    ),
                }

    @staticmethod
    def _message_source_system(msg) -> int | None:
        getter = getattr(msg, "get_srcSystem", None)
        if not getter:
            return None
        try:
            return int(getter())
        except Exception:
            return None

    @staticmethod
    def _message_source_component(msg) -> int | None:
        getter = getattr(msg, "get_srcComponent", None)
        if not getter:
            return None
        try:
            return int(getter())
        except Exception:
            return None

    def _is_from_target(self, msg) -> bool:
        """Reject transaction packets injected by another MAVLink system."""

        source_system = self._message_source_system(msg)
        source_component = self._message_source_component(msg)
        return (
            source_system in (None, self.target_system)
            and source_component in (None, self.target_component)
        )

    def _is_addressed_to_us(self, msg) -> bool:
        """Accept MAVLink1/broadcast packets, reject another GCS's replies."""

        target_system = getattr(msg, "target_system", None)
        target_component = getattr(msg, "target_component", None)
        return (
            target_system in (None, 0, self.source_system)
            and target_component in (None, 0, self.source_component)
        )

    def _send_heartbeat_locked(self) -> None:
        mav = self._mavlink()
        self.master.mav.heartbeat_send(
            mav.MAV_TYPE_GCS,
            mav.MAV_AUTOPILOT_INVALID,
            0,
            0,
            0,
        )

    def send_heartbeat(self) -> None:
        with self._io_lock:
            self._send_heartbeat_locked()

    def _ensure_connected(self) -> None:
        if not self.is_connected:
            raise MAVLinkConnectionError("autopilot heartbeat is missing or stale")

    def _recv_until_locked(self, accepted_types: set[str], deadline: float):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            msg = self.master.recv_match(
                blocking=True,
                timeout=min(remaining, 0.25),
            )
            if msg is None:
                continue
            msg_type = msg.get_type()
            if (
                msg_type in accepted_types
                and self._is_from_target(msg)
                and self._is_addressed_to_us(msg)
            ):
                return msg
            self._process_message(msg)

    def _wait_command_ack_locked(self, command: int, timeout: float):
        mav = self._mavlink()
        deadline = time.monotonic() + timeout
        saw_progress = False
        while True:
            ack = self._recv_until_locked({"COMMAND_ACK"}, deadline)
            if ack is None:
                raise MAVLinkTimeoutError(
                    f"timeout waiting for COMMAND_ACK for command {command}",
                    acknowledged=saw_progress,
                )
            if int(ack.command) != int(command):
                continue
            result = int(ack.result)
            if result == mav.MAV_RESULT_IN_PROGRESS:
                saw_progress = True
                deadline = time.monotonic() + timeout
                continue
            if result != mav.MAV_RESULT_ACCEPTED:
                raise MAVLinkRejectedError(
                    f"command {command} rejected with MAV_RESULT {result}"
                )
            return ack

    def _command_long(self, command: int, params: Sequence[float]):
        self._ensure_connected()
        values = [float(v) for v in params]
        if len(values) != 7 or not all(math.isfinite(v) for v in values):
            raise ValueError("MAVLink COMMAND_LONG requires seven finite parameters")
        with self._io_lock:
            for confirmation in range(self.command_retries):
                self.master.mav.command_long_send(
                    self.target_system,
                    self.target_component,
                    command,
                    confirmation,
                    *values,
                )
                try:
                    return self._wait_command_ack_locked(command, self.command_timeout)
                except MAVLinkTimeoutError as exc:
                    # A long-running command that already reported progress
                    # must not be restarted.  Otherwise retry according to the
                    # COMMAND_LONG protocol with an incremented confirmation.
                    if exc.acknowledged or confirmation + 1 == self.command_retries:
                        raise
                    logger.warning(
                        "No ACK for command %d; retrying (%d/%d)",
                        command,
                        confirmation + 2,
                        self.command_retries,
                    )
        raise AssertionError("unreachable")

    def set_mode(self, mode_name: str) -> str:
        mapping = self.master.mode_mapping() or {}
        normalized = mode_name.strip().upper()
        if normalized not in mapping:
            raise ValueError(f"autopilot does not advertise flight mode {normalized!r}")
        mav = self._mavlink()
        self._command_long(
            mav.MAV_CMD_DO_SET_MODE,
            [mav.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, mapping[normalized], 0, 0, 0, 0, 0],
        )
        logger.info("Autopilot accepted flight mode %s", normalized)
        return normalized

    def arm(self) -> None:
        mav = self._mavlink()
        self._command_long(
            mav.MAV_CMD_COMPONENT_ARM_DISARM,
            [1, 0, 0, 0, 0, 0, 0],
        )
        logger.info("Autopilot accepted ARM")

    def disarm(self) -> None:
        mav = self._mavlink()
        self._command_long(
            mav.MAV_CMD_COMPONENT_ARM_DISARM,
            [0, 0, 0, 0, 0, 0, 0],
        )
        logger.info("Autopilot accepted DISARM")

    def takeoff(self, altitude: float) -> None:
        if not math.isfinite(altitude) or altitude <= 0:
            raise ValueError("takeoff altitude must be a positive finite value")
        mav = self._mavlink()
        self._command_long(
            mav.MAV_CMD_NAV_TAKEOFF,
            [0, 0, 0, 0, 0, 0, altitude],
        )
        logger.info("Autopilot accepted TAKEOFF to %.2f m", altitude)

    def start_mission(self) -> None:
        mav = self._mavlink()
        self._command_long(
            mav.MAV_CMD_MISSION_START,
            [0, 0, 0, 0, 0, 0, 0],
        )
        logger.info("Autopilot accepted MISSION_START")

    def set_gps_origin(
        self,
        lat: float,
        lon: float,
        alt: float,
        *,
        confirmation_timeout: float | None = None,
    ) -> None:
        """Explicitly set and verify the vehicle origin.

        This is intentionally never called by the background loop.  It is only
        used when the operator opts into ``--set-origin-on-upload``.
        """

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("origin latitude/longitude are outside WGS84 bounds")
        if not all(math.isfinite(v) for v in (lat, lon, alt)):
            raise ValueError("origin coordinates must be finite")
        self._ensure_connected()
        timeout = confirmation_timeout or self.command_timeout
        lat_e7, lon_e7, alt_mm = int(round(lat * 1e7)), int(round(lon * 1e7)), int(
            round(alt * 1000)
        )
        with self._io_lock:
            self.master.mav.set_gps_global_origin_send(
                self.target_system,
                lat_e7,
                lon_e7,
                alt_mm,
            )
            deadline = time.monotonic() + timeout
            while True:
                reply = self._recv_until_locked({"GPS_GLOBAL_ORIGIN"}, deadline)
                if reply is None:
                    raise MAVLinkTimeoutError(
                        "autopilot did not confirm SET_GPS_GLOBAL_ORIGIN"
                    )
                if (
                    int(reply.latitude) == lat_e7
                    and int(reply.longitude) == lon_e7
                    and int(reply.altitude) == alt_mm
                ):
                    break
        logger.warning(
            "Autopilot origin explicitly changed to lat=%.7f lon=%.7f alt=%.2f",
            lat,
            lon,
            alt,
        )

    def upload_mission(self, waypoints: Sequence[Sequence[float]]) -> dict:
        """Upload global waypoints with *relative* altitude via MAVLink.

        Each waypoint is ``(latitude_deg, longitude_deg, relative_altitude_m)``.
        ``MISSION_COUNT`` starts the transaction; the vehicle then requests
        every sequence number and receives ``MISSION_ITEM_INT``.  The method
        succeeds only after ``MISSION_ACK(MAV_MISSION_ACCEPTED)``.
        """

        if not waypoints:
            raise ValueError("mission must contain at least one waypoint")
        normalized: list[tuple[float, float, float]] = []
        for index, point in enumerate(waypoints):
            if len(point) != 3:
                raise ValueError(f"mission waypoint {index} must have three values")
            lat, lon, relative_alt = (float(value) for value in point)
            if not all(math.isfinite(v) for v in (lat, lon, relative_alt)):
                raise ValueError(f"mission waypoint {index} contains a non-finite value")
            if not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise ValueError(f"mission waypoint {index} is outside WGS84 bounds")
            if relative_alt < 0:
                raise ValueError(
                    f"mission waypoint {index} has a negative relative altitude"
                )
            normalized.append((lat, lon, relative_alt))

        mav = self._mavlink()
        self._ensure_connected()
        mission_type = getattr(mav, "MAV_MISSION_TYPE_MISSION", 0)
        frame = getattr(
            mav,
            "MAV_FRAME_GLOBAL_RELATIVE_ALT_INT",
            mav.MAV_FRAME_GLOBAL_RELATIVE_ALT,
        )
        accepted = mav.MAV_MISSION_ACCEPTED
        max_requests = max(len(normalized) * 4, len(normalized) + 5)

        logger.info("Uploading mission with %d waypoints", len(normalized))
        with self._io_lock:
            deadline = time.monotonic() + self.mission_timeout
            retry_interval = min(2.0, self.mission_timeout / 3.0)
            count_attempts = 0
            next_count_retry = 0.0
            request_count = 0
            sent_sequences: set[int] = set()

            while True:
                now = time.monotonic()
                if not sent_sequences and now >= next_count_retry and count_attempts < 3:
                    self._mission_count_send_locked(len(normalized), mission_type)
                    count_attempts += 1
                    next_count_retry = now + retry_interval
                receive_deadline = deadline
                if not sent_sequences and count_attempts < 3:
                    receive_deadline = min(deadline, next_count_retry)
                msg = self._recv_until_locked(
                    {"MISSION_REQUEST_INT", "MISSION_REQUEST", "MISSION_ACK"},
                    receive_deadline,
                )
                if msg is None:
                    if not sent_sequences and count_attempts < 3:
                        continue
                    raise MAVLinkTimeoutError(
                        "mission upload timed out before MISSION_ACK"
                    )

                if msg.get_type() == "MISSION_ACK":
                    ack_mission_type = int(
                        getattr(msg, "mission_type", mission_type)
                    )
                    if ack_mission_type != mission_type:
                        raise MAVLinkRejectedError(
                            "autopilot acknowledged a different mission type "
                            f"({ack_mission_type})"
                        )
                    result = int(msg.type)
                    if result != accepted:
                        raise MAVLinkRejectedError(
                            f"mission rejected with MAV_MISSION_RESULT {result}"
                        )
                    if len(sent_sequences) != len(normalized):
                        raise MAVLinkRejectedError(
                            "autopilot accepted mission before requesting every waypoint"
                        )
                    opaque_id = int(getattr(msg, "opaque_id", 0) or 0)
                    logger.info("Mission upload accepted (opaque_id=%d)", opaque_id)
                    return {
                        "count": len(normalized),
                        "opaque_id": opaque_id,
                    }

                requested_type = int(getattr(msg, "mission_type", mission_type))
                if requested_type != mission_type:
                    raise MAVLinkRejectedError(
                        f"autopilot requested unsupported mission type {requested_type}"
                    )
                seq = int(msg.seq)
                if not 0 <= seq < len(normalized):
                    raise MAVLinkRejectedError(
                        f"autopilot requested invalid mission sequence {seq}"
                    )
                request_count += 1
                if request_count > max_requests:
                    raise MAVLinkTimeoutError(
                        "autopilot repeatedly requested mission items without accepting"
                    )

                lat, lon, relative_alt = normalized[seq]
                self._mission_item_int_send_locked(
                    seq=seq,
                    frame=frame,
                    command=mav.MAV_CMD_NAV_WAYPOINT,
                    latitude_e7=int(round(lat * 1e7)),
                    longitude_e7=int(round(lon * 1e7)),
                    relative_alt=relative_alt,
                    mission_type=mission_type,
                )
                sent_sequences.add(seq)

    def _mission_count_send_locked(self, count: int, mission_type: int) -> None:
        """Send MAVLink 2 extensions when available, with MAVLink 1 fallback."""

        try:
            self.master.mav.mission_count_send(
                self.target_system,
                self.target_component,
                count,
                mission_type,
            )
        except TypeError:
            self.master.mav.mission_count_send(
                self.target_system,
                self.target_component,
                count,
            )

    def _mission_item_int_send_locked(
        self,
        *,
        seq: int,
        frame: int,
        command: int,
        latitude_e7: int,
        longitude_e7: int,
        relative_alt: float,
        mission_type: int,
    ) -> None:
        args = (
            self.target_system,
            self.target_component,
            seq,
            frame,
            command,
            0,  # no item is made current merely by uploading it
            1,
            0,
            0,
            0,
            0,
            latitude_e7,
            longitude_e7,
            relative_alt,
        )
        try:
            self.master.mav.mission_item_int_send(*args, mission_type)
        except TypeError:
            self.master.mav.mission_item_int_send(*args)

    def get_telemetry(self) -> dict:
        with self._state_lock:
            return deepcopy(self.telemetry)

    def get_status(self) -> dict:
        with self._state_lock:
            last = self._last_heartbeat_monotonic
            last_error = self._last_error
            telemetry = deepcopy(self.telemetry)
        age = None if last is None else max(0.0, time.monotonic() - last)
        return {
            "configured": True,
            "connected": age is not None and age <= self.link_timeout,
            "target_system": self.target_system,
            "target_component": self.target_component,
            "autopilot_type": self.autopilot_type,
            "vehicle_type": self.vehicle_type,
            "last_heartbeat_age_s": None if age is None else round(age, 3),
            "last_error": last_error,
            "telemetry": telemetry,
        }

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        acquired = self._io_lock.acquire(timeout=1.0)
        try:
            with self._suppress_close_errors():
                self.master.close()
        finally:
            if acquired:
                self._io_lock.release()
