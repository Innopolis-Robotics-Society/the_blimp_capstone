"""FastAPI service for one real UWB tag and one real MAVLink autopilot."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import math
import os
from pathlib import Path
import threading

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .backend import (
    MAVLinkBackend,
    MAVLinkConnectionError,
    MAVLinkRejectedError,
    MAVLinkTimeoutError,
)


log = logging.getLogger("blimp_dashboard")

STATIC_DIR = Path(__file__).parent / "static"
EARTH_RADIUS_M = 6_378_137.0
DEFAULT_ORIGIN_LAT = 55.7522
DEFAULT_ORIGIN_LON = 48.7446
DEFAULT_ORIGIN_ALT = 120.0

DEFAULT_ANCHORS = {
    "anchors": [
        {"id": 0, "pos": [0.0, 0.0, 0.0]},
        {"id": 1, "pos": [4.0, 0.0, 0.0]},
        {"id": 2, "pos": [4.0, 4.0, 0.0]},
        {"id": 3, "pos": [0.0, 4.0, 0.0]},
    ]
}


class TakeoffReq(BaseModel):
    alt: float


class ModeReq(BaseModel):
    mode: str


class DashWaypoint(BaseModel):
    x: float
    y: float
    z: float


def local_to_global_gps(
    x: float,
    y: float,
    relative_alt: float,
    *,
    origin_lat: float = DEFAULT_ORIGIN_LAT,
    origin_lon: float = DEFAULT_ORIGIN_LON,
) -> tuple[float, float, float]:
    """Map hall ``X=north, Y=east, Z=up`` to a global mission item.

    The third return value deliberately stays *relative altitude*.  It is sent
    in ``MAV_FRAME_GLOBAL_RELATIVE_ALT_INT`` and must never include the MSL
    altitude of the configured origin.
    """

    if not all(math.isfinite(value) for value in (x, y, relative_alt)):
        raise ValueError("local waypoint values must be finite")
    if not -90 <= origin_lat <= 90 or not -180 <= origin_lon <= 180:
        raise ValueError("origin is outside WGS84 bounds")
    cos_lat = math.cos(math.radians(origin_lat))
    if abs(cos_lat) < 1e-9:
        raise ValueError("origin is too close to a pole for local conversion")
    lat = origin_lat + math.degrees(x / EARTH_RADIUS_M)
    lon = origin_lon + math.degrees(y / (EARTH_RADIUS_M * cos_lat))
    return lat, lon, relative_alt


def filter_uwb_datagram(data: bytes, tag_id: int) -> str | None:
    """Return a JSON frame containing only the configured UWB tag.

    ``anchorframe0`` is the live console frame consumed by the dashboard.  Its
    ``nodes`` array is reduced to the selected tag; anchors themselves come
    from ``anchors.json``.  Other known tag containers are filtered as well so
    a second tag can never leak to a browser client.
    """

    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        log.warning("dropping malformed UWB JSON datagram")
        return None
    if not isinstance(payload, dict):
        return None

    frame_type = payload.get("frame_type")
    if frame_type == "anchorframe0":
        nodes = payload.get("nodes")
        if not isinstance(nodes, list):
            return None
        payload["nodes"] = [
            node
            for node in nodes
            if isinstance(node, dict)
            and node.get("role") == 2
            and node.get("id") == tag_id
        ]
    elif frame_type == "tagframe0" and payload.get("id") != tag_id:
        return None
    elif payload.get("role") == 2 and payload.get("id") != tag_id:
        # nodeframe2 and other tag-originated formats carry the tag identity at
        # top level rather than in a ``tags``/``nodes`` collection.
        return None
    else:
        nodes = payload.get("nodes")
        if isinstance(nodes, list):
            payload["nodes"] = [
                node
                for node in nodes
                if not isinstance(node, dict)
                or node.get("role") != 2
                or node.get("id") == tag_id
            ]
        tags = payload.get("tags")
        if isinstance(tags, list):
            payload["tags"] = [
                tag
                for tag in tags
                if isinstance(tag, dict) and tag.get("id") == tag_id
            ]

    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


class FrameRelay:
    """Fan incoming single-tag UDP frames out to connected WebSockets."""

    def __init__(self, tag_id: int) -> None:
        self.tag_id = tag_id
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()

    def datagram_received(self, data: bytes) -> None:
        text = filter_uwb_datagram(data, self.tag_id)
        if text is None or self._loop is None:
            return
        for websocket in list(self._clients):
            self._loop.create_task(self._send(websocket, text))

    async def _send(self, websocket: WebSocket, text: str) -> None:
        try:
            await websocket.send_text(text)
        except Exception:
            self._clients.discard(websocket)

    async def handle_client(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        try:
            while True:  # inbound data is ignored; receive detects disconnect
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            self._clients.discard(websocket)


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, relay: FrameRelay):
        self._relay = relay

    def datagram_received(self, data: bytes, _addr) -> None:
        self._relay.datagram_received(data)


def load_anchors(path: Path) -> dict:
    if not path.exists():
        return DEFAULT_ANCHORS
    return validate_anchors(json.loads(path.read_text()))


def validate_anchors(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("expected {'anchors': [...]}")
    anchors = payload.get("anchors")
    if not isinstance(anchors, list):
        raise ValueError("expected {'anchors': [...]}")
    ids: set[int] = set()
    normalized = []
    for anchor in anchors:
        if (
            not isinstance(anchor, dict)
            or not isinstance(anchor.get("id"), int)
            or isinstance(anchor.get("id"), bool)
        ):
            raise ValueError("anchor id must be int")
        anchor_id = anchor["id"]
        if anchor_id in ids:
            raise ValueError("anchor ids must be unique")
        position = anchor.get("pos")
        if (
            not isinstance(position, list)
            or len(position) != 3
            or not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in position
            )
        ):
            raise ValueError("anchor pos must be three finite numbers [x, y, z]")
        ids.add(anchor_id)
        normalized.append({"id": anchor_id, "pos": list(position)})
    return {"anchors": normalized}


def _empty_telemetry() -> dict:
    return {
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


def create_app(
    udp_port: int,
    anchors_path: Path,
    *,
    uwb_tag_id: int = 1,
    mavlink_endpoint: str | None = None,
    mavlink_baud: int = 115200,
    mavlink_heartbeat_timeout: float = 10.0,
    mavlink_link_timeout: float = 5.0,
    mavlink_command_timeout: float = 5.0,
    mavlink_mission_timeout: float = 30.0,
    mavlink_reconnect_delay: float = 3.0,
    expected_target_system: int | None = None,
    expected_target_component: int | None = None,
    origin_lat: float = DEFAULT_ORIGIN_LAT,
    origin_lon: float = DEFAULT_ORIGIN_LON,
    origin_alt: float = DEFAULT_ORIGIN_ALT,
    set_origin_on_upload: bool = False,
    min_mission_altitude: float = 0.2,
    max_mission_altitude: float = 10.0,
    max_waypoint_distance: float = 100.0,
    max_mission_waypoints: int = 100,
    mavlink_factory=MAVLinkBackend,
    bind_udp: bool = True,
) -> FastAPI:
    if mavlink_endpoint is not None:
        mavlink_endpoint = mavlink_endpoint.strip() or None
    if not 0 <= udp_port <= 65535:
        raise ValueError("UDP port must be in range 0..65535")
    if isinstance(uwb_tag_id, bool) or not 0 <= uwb_tag_id <= 255:
        raise ValueError("UWB tag id must be in range 0..255")
    if mavlink_baud <= 0:
        raise ValueError("MAVLink baud rate must be positive")
    if not all(
        math.isfinite(value) and value > 0
        for value in (
            mavlink_heartbeat_timeout,
            mavlink_link_timeout,
            mavlink_command_timeout,
            mavlink_mission_timeout,
            mavlink_reconnect_delay,
        )
    ):
        raise ValueError("MAVLink timeouts must be positive and finite")
    for name, value in (
        ("target system", expected_target_system),
        ("target component", expected_target_component),
    ):
        if value is not None and (isinstance(value, bool) or not 1 <= value <= 255):
            raise ValueError(f"MAVLink {name} id must be in range 1..255")
    if not all(
        math.isfinite(value)
        for value in (
            origin_lat,
            origin_lon,
            origin_alt,
            min_mission_altitude,
            max_mission_altitude,
            max_waypoint_distance,
        )
    ):
        raise ValueError("origin and mission limits must be finite")
    if not -90 <= origin_lat <= 90 or not -180 <= origin_lon <= 180:
        raise ValueError("origin is outside WGS84 bounds")
    if not (0 <= min_mission_altitude < max_mission_altitude):
        raise ValueError("mission altitude limits are invalid")
    if max_waypoint_distance <= 0 or max_mission_waypoints <= 0:
        raise ValueError("mission limits must be positive")
    relay = FrameRelay(uwb_tag_id)

    @contextlib.asynccontextmanager
    async def _lifespan(lifespan_app: FastAPI):
        lifespan_app.state.mavlink_stop.clear()
        relay.start()
        if bind_udp:
            loop = asyncio.get_running_loop()
            transport, _ = await loop.create_datagram_endpoint(
                lambda: _UdpProtocol(relay),
                local_addr=("0.0.0.0", udp_port),
            )
            lifespan_app.state.udp_transport = transport
            log.info(
                "listening for UWB tag %d datagrams on UDP :%d",
                uwb_tag_id,
                udp_port,
            )

        if mavlink_endpoint:
            lifespan_app.state.mavlink_thread = threading.Thread(
                target=_connect_mavlink_loop,
                name="blimp-mavlink-connect",
                daemon=True,
            )
            lifespan_app.state.mavlink_thread.start()
        else:
            log.warning(
                "MAVLink control disabled: configure --mavlink or "
                "BLIMP_MAVLINK_ENDPOINT"
            )

        try:
            yield
        finally:
            lifespan_app.state.mavlink_stop.set()
            thread = getattr(lifespan_app.state, "mavlink_thread", None)
            if thread and thread.is_alive():
                await asyncio.to_thread(thread.join, 1.5)
            if thread and thread.is_alive():
                with lifespan_app.state.mavlink_state_lock:
                    backend = lifespan_app.state.mavlink
                if backend:
                    await asyncio.to_thread(backend.stop)
            transport = getattr(lifespan_app.state, "udp_transport", None)
            if transport:
                with contextlib.suppress(Exception):
                    transport.close()

    app = FastAPI(title="blimp UWB dashboard", lifespan=_lifespan)
    app.state.mavlink = None
    app.state.mavlink_error = None
    app.state.mavlink_connecting = False
    app.state.mavlink_stop = threading.Event()
    app.state.mavlink_state_lock = threading.Lock()
    app.state.mavlink_operation_lock = asyncio.Lock()
    # Mission start is allowed only for a mission acknowledged on the current
    # backend instance.  A stale heartbeat makes the reconnect loop replace the
    # backend, which deliberately invalidates this marker.
    app.state.uploaded_mission_backend = None

    def _connect_mavlink_loop() -> None:
        while not app.state.mavlink_stop.is_set():
            with app.state.mavlink_state_lock:
                app.state.mavlink_connecting = True
                app.state.mavlink_error = None
            try:
                backend = mavlink_factory(
                    mavlink_endpoint,
                    baud=mavlink_baud,
                    heartbeat_timeout=mavlink_heartbeat_timeout,
                    link_timeout=mavlink_link_timeout,
                    command_timeout=mavlink_command_timeout,
                    mission_timeout=mavlink_mission_timeout,
                    expected_target_system=expected_target_system,
                    expected_target_component=expected_target_component,
                )
            except Exception as exc:
                with app.state.mavlink_state_lock:
                    app.state.mavlink_error = str(exc)
                    app.state.mavlink_connecting = False
                log.warning("MAVLink connection attempt failed: %s", exc)
                app.state.mavlink_stop.wait(mavlink_reconnect_delay)
                continue

            with app.state.mavlink_state_lock:
                app.state.mavlink = backend
                app.state.mavlink_connecting = False
            while not app.state.mavlink_stop.wait(0.5):
                if backend.is_connected:
                    continue
                with app.state.mavlink_state_lock:
                    app.state.mavlink_error = "autopilot heartbeat became stale"
                break
            backend.stop()
            with app.state.mavlink_state_lock:
                if app.state.mavlink is backend:
                    app.state.mavlink = None
            if not app.state.mavlink_stop.is_set():
                app.state.mavlink_stop.wait(mavlink_reconnect_delay)

    def _require_mavlink():
        with app.state.mavlink_state_lock:
            backend = app.state.mavlink
            error = app.state.mavlink_error
            connecting = app.state.mavlink_connecting
        if backend is None:
            if not mavlink_endpoint:
                detail = "MAVLink is not configured"
            elif connecting:
                detail = "waiting for an autopilot heartbeat"
            else:
                detail = error or "autopilot is not connected"
            raise HTTPException(status_code=503, detail=detail)
        if not backend.is_connected:
            raise HTTPException(status_code=503, detail="autopilot heartbeat is stale")
        return backend

    async def _run_mavlink_call(function, *args):
        try:
            return await asyncio.to_thread(function, *args)
        except MAVLinkTimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except MAVLinkRejectedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except MAVLinkConnectionError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            log.exception("unexpected MAVLink operation failure")
            raise HTTPException(status_code=502, detail="MAVLink operation failed") from exc

    async def _mavlink_call(function, *args):
        async with app.state.mavlink_operation_lock:
            return await _run_mavlink_call(function, *args)

    def _require_control_request(request: Request) -> None:
        # This fixed custom header is a same-origin/CSRF barrier, not a secret.
        # Browsers cannot attach it to a cross-origin HTML form, and no CORS
        # middleware is enabled.  Network-level access control is still needed.
        if request.headers.get("X-Blimp-Control") != "dashboard":
            raise HTTPException(
                status_code=403,
                detail="missing dashboard control header",
            )

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/config")
    async def get_config() -> dict:
        return {
            "uwb_tag_id": uwb_tag_id,
            "mavlink_configured": bool(mavlink_endpoint),
            "origin": {"lat": origin_lat, "lon": origin_lon, "alt": origin_alt},
            "set_origin_on_upload": set_origin_on_upload,
            "mission_limits": {
                "min_altitude": min_mission_altitude,
                "max_altitude": max_mission_altitude,
                "max_waypoint_distance": max_waypoint_distance,
                "max_waypoints": max_mission_waypoints,
            },
        }

    @app.get("/api/anchors")
    async def get_anchors() -> dict:
        try:
            return load_anchors(anchors_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail=f"invalid anchors config: {exc}")

    @app.put("/api/anchors")
    async def put_anchors(payload: dict) -> dict:
        try:
            data = validate_anchors(payload)
            anchors_path.write_text(json.dumps(data, indent=2) + "\n")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return data

    @app.get("/api/mavlink/status")
    async def mavlink_status() -> dict:
        with app.state.mavlink_state_lock:
            backend = app.state.mavlink
            connecting = app.state.mavlink_connecting
            error = app.state.mavlink_error
        if backend:
            status = backend.get_status()
        else:
            status = {
                "configured": bool(mavlink_endpoint),
                "connected": False,
                "target_system": None,
                "target_component": None,
                "last_heartbeat_age_s": None,
                "last_error": error,
                "telemetry": _empty_telemetry(),
            }
        status["configured"] = bool(mavlink_endpoint)
        status["connecting"] = connecting
        status["mission_ready"] = bool(
            backend is not None
            and backend.is_connected
            and app.state.uploaded_mission_backend is backend
        )
        telemetry = status["telemetry"]
        status["mode"] = telemetry["mode"]
        status["armed"] = telemetry["armed"]
        status["battery"] = telemetry["battery"]
        status["position"] = telemetry["position"]
        status["local_position"] = telemetry["local_position"]
        return status

    @app.post("/action/arm")
    async def action_arm(request: Request) -> dict:
        _require_control_request(request)
        backend = _require_mavlink()
        await _mavlink_call(backend.arm)
        return {"status": "success", "command": "arm", "acknowledged": True}

    @app.post("/action/disarm")
    async def action_disarm(request: Request) -> dict:
        _require_control_request(request)
        backend = _require_mavlink()
        await _mavlink_call(backend.disarm)
        return {"status": "success", "command": "disarm", "acknowledged": True}

    @app.post("/action/mode")
    async def action_mode(request: Request, command: ModeReq) -> dict:
        _require_control_request(request)
        backend = _require_mavlink()
        mode = command.mode.strip().upper()
        if not mode:
            raise HTTPException(status_code=422, detail="flight mode must not be empty")
        accepted_mode = await _mavlink_call(backend.set_mode, mode)
        return {
            "status": "success",
            "command": "set_mode",
            "mode": accepted_mode,
            "acknowledged": True,
        }

    @app.post("/action/takeoff")
    async def action_takeoff(request: Request, command: TakeoffReq) -> dict:
        _require_control_request(request)
        if (
            not math.isfinite(command.alt)
            or not min_mission_altitude <= command.alt <= max_mission_altitude
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "takeoff altitude must be between "
                    f"{min_mission_altitude:g} and {max_mission_altitude:g} metres"
                ),
            )
        backend = _require_mavlink()
        await _mavlink_call(backend.takeoff, command.alt)
        return {
            "status": "success",
            "command": "takeoff",
            "altitude": command.alt,
            "acknowledged": True,
        }

    @app.post("/action/mission/start")
    async def action_mission_start(request: Request) -> dict:
        _require_control_request(request)
        backend = _require_mavlink()
        async with app.state.mavlink_operation_lock:
            if app.state.uploaded_mission_backend is not backend:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "no mission was acknowledged on the current autopilot "
                        "connection; upload it again"
                    ),
                )
            await _run_mavlink_call(backend.start_mission)
        return {
            "status": "success",
            "command": "mission_start",
            "acknowledged": True,
        }

    @app.post("/upload_route")
    async def upload_route(request: Request, waypoints: list[DashWaypoint]) -> dict:
        _require_control_request(request)
        if not waypoints:
            raise HTTPException(status_code=422, detail="route must not be empty")
        if len(waypoints) > max_mission_waypoints:
            raise HTTPException(
                status_code=422,
                detail=f"route exceeds {max_mission_waypoints} waypoints",
            )

        mission = []
        for index, waypoint in enumerate(waypoints):
            values = (waypoint.x, waypoint.y, waypoint.z)
            if not all(math.isfinite(value) for value in values):
                raise HTTPException(
                    status_code=422,
                    detail=f"waypoint {index} contains a non-finite value",
                )
            if math.hypot(waypoint.x, waypoint.y) > max_waypoint_distance:
                raise HTTPException(
                    status_code=422,
                    detail=f"waypoint {index} is outside the configured hall radius",
                )
            if not min_mission_altitude <= waypoint.z <= max_mission_altitude:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"waypoint {index} altitude must be between "
                        f"{min_mission_altitude:g} and {max_mission_altitude:g} metres"
                    ),
                )
            mission.append(
                local_to_global_gps(
                    waypoint.x,
                    waypoint.y,
                    waypoint.z,
                    origin_lat=origin_lat,
                    origin_lon=origin_lon,
                )
            )

        backend = _require_mavlink()
        # Origin change and upload form one HTTP-level transaction so no ARM,
        # mode or mission-start request can interleave between them.
        async with app.state.mavlink_operation_lock:
            # A failed or partial replacement must never leave the previous
            # mission eligible for a later start command.
            app.state.uploaded_mission_backend = None
            if set_origin_on_upload:
                await _run_mavlink_call(
                    backend.set_gps_origin,
                    origin_lat,
                    origin_lon,
                    origin_alt,
                )
            result = await _run_mavlink_call(backend.upload_mission, mission)
            app.state.uploaded_mission_backend = backend
        return {
            "status": "success",
            "message": "mission uploaded and acknowledged by autopilot",
            "count": result["count"],
            "opaque_id": result["opaque_id"],
            "started": False,
        }

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await relay.handle_client(websocket)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def _env_int(name: str, default: int | None) -> int | None:
    value = os.getenv(name)
    return default if value in (None, "") else int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value in (None, "") else float(value)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="blimp-dashboard",
        description="Single-tag UWB dashboard and MAVLink mission uploader.",
    )
    parser.add_argument("--http-host", default="0.0.0.0")
    parser.add_argument("--http-port", type=int, default=8000)
    parser.add_argument("--udp-port", type=int, default=9999)
    parser.add_argument("--anchors", default="anchors.json")
    parser.add_argument(
        "--uwb-tag-id",
        type=int,
        default=_env_int("BLIMP_UWB_TAG_ID", 1),
        help="the only UWB tag id forwarded to the browser (default: 1)",
    )
    parser.add_argument(
        "--mavlink",
        default=os.getenv("BLIMP_MAVLINK_ENDPOINT"),
        help=(
            "real pymavlink endpoint, e.g. udpin:0.0.0.0:14550 or /dev/ttyUSB0; "
            "disabled when omitted"
        ),
    )
    parser.add_argument(
        "--mavlink-baud",
        type=int,
        default=_env_int("BLIMP_MAVLINK_BAUD", 115200),
    )
    parser.add_argument(
        "--mavlink-heartbeat-timeout",
        type=float,
        default=_env_float("BLIMP_MAVLINK_HEARTBEAT_TIMEOUT", 10.0),
    )
    parser.add_argument(
        "--mavlink-link-timeout",
        type=float,
        default=_env_float("BLIMP_MAVLINK_LINK_TIMEOUT", 5.0),
    )
    parser.add_argument(
        "--mavlink-command-timeout",
        type=float,
        default=_env_float("BLIMP_MAVLINK_COMMAND_TIMEOUT", 5.0),
    )
    parser.add_argument(
        "--mavlink-mission-timeout",
        type=float,
        default=_env_float("BLIMP_MAVLINK_MISSION_TIMEOUT", 30.0),
    )
    parser.add_argument(
        "--mavlink-reconnect-delay",
        type=float,
        default=_env_float("BLIMP_MAVLINK_RECONNECT_DELAY", 3.0),
    )
    parser.add_argument(
        "--mavlink-target-system",
        type=int,
        default=_env_int("BLIMP_MAVLINK_TARGET_SYSTEM", None),
        help="reject heartbeats from a different MAVLink system id",
    )
    parser.add_argument(
        "--mavlink-target-component",
        type=int,
        default=_env_int("BLIMP_MAVLINK_TARGET_COMPONENT", None),
    )
    parser.add_argument(
        "--origin-lat",
        type=float,
        default=_env_float("BLIMP_ORIGIN_LAT", DEFAULT_ORIGIN_LAT),
    )
    parser.add_argument(
        "--origin-lon",
        type=float,
        default=_env_float("BLIMP_ORIGIN_LON", DEFAULT_ORIGIN_LON),
    )
    parser.add_argument(
        "--origin-alt",
        type=float,
        default=_env_float("BLIMP_ORIGIN_ALT", DEFAULT_ORIGIN_ALT),
    )
    parser.add_argument(
        "--set-origin-on-upload",
        action="store_true",
        default=_env_bool("BLIMP_SET_ORIGIN_ON_UPLOAD"),
        help="explicitly change and verify the autopilot origin before upload",
    )
    parser.add_argument(
        "--min-mission-altitude",
        type=float,
        default=_env_float("BLIMP_MIN_MISSION_ALTITUDE", 0.2),
    )
    parser.add_argument(
        "--max-mission-altitude",
        type=float,
        default=_env_float("BLIMP_MAX_MISSION_ALTITUDE", 10.0),
    )
    parser.add_argument(
        "--max-waypoint-distance",
        type=float,
        default=_env_float("BLIMP_MAX_WAYPOINT_DISTANCE", 100.0),
    )
    parser.add_argument(
        "--max-mission-waypoints",
        type=int,
        default=_env_int("BLIMP_MAX_MISSION_WAYPOINTS", 100),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    app = create_app(
        args.udp_port,
        Path(args.anchors),
        uwb_tag_id=args.uwb_tag_id,
        mavlink_endpoint=args.mavlink,
        mavlink_baud=args.mavlink_baud,
        mavlink_heartbeat_timeout=args.mavlink_heartbeat_timeout,
        mavlink_link_timeout=args.mavlink_link_timeout,
        mavlink_command_timeout=args.mavlink_command_timeout,
        mavlink_mission_timeout=args.mavlink_mission_timeout,
        mavlink_reconnect_delay=args.mavlink_reconnect_delay,
        expected_target_system=args.mavlink_target_system,
        expected_target_component=args.mavlink_target_component,
        origin_lat=args.origin_lat,
        origin_lon=args.origin_lon,
        origin_alt=args.origin_alt,
        set_origin_on_upload=args.set_origin_on_upload,
        min_mission_altitude=args.min_mission_altitude,
        max_mission_altitude=args.max_mission_altitude,
        max_waypoint_distance=args.max_waypoint_distance,
        max_mission_waypoints=args.max_mission_waypoints,
    )
    uvicorn.run(app, host=args.http_host, port=args.http_port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
