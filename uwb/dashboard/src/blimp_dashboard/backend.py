import time
import threading
import logging
import pymavlink.mavutil as mavutil

logger = logging.getLogger(__name__)


class MAVLinkBackend:
    def __init__(self, connection_string):
        logger.info(f"Connecting to {connection_string}...")
        self.master = mavutil.mavlink_connection(connection_string)

        logger.info("Waiting for HEARTBEAT...")
        self.master.wait_heartbeat()
        logger.info(f"Connected! System: {self.master.target_system}, Component: {self.master.target_component}")

        self.telemetry = {
            "position": {"lat": 0.0, "lon": 0.0, "alt": 0.0, "relative_alt": 0.0},
            "battery": {"voltage": 0.0, "current": 0.0, "remaining": 0},
            "status": "disconnected"
        }

        self.running = False
        self.start_telemetry_loop()

    def start_telemetry_loop(self):
        self.running = True
        thread = threading.Thread(target=self._telemetry_loop, daemon=True)
        thread.start()

    def _telemetry_loop(self):
        while self.running:
            msg = self.master.recv_match(blocking=True, timeout=0.1)
            if msg:
                self._process_message(msg)

    def _process_message(self, msg):
        msg_type = msg.get_type()

        if msg_type == 'GLOBAL_POSITION_INT':
            self.telemetry["position"] = {
                "lat": msg.lat / 1e7,
                "lon": msg.lon / 1e7,
                "alt": msg.alt / 1000.0,
                "relative_alt": msg.relative_alt / 1000.0
            }
        elif msg_type == 'SYS_STATUS':
            self.telemetry["battery"] = {
                "voltage": msg.voltage_battery / 1000.0,
                "current": msg.current_battery / 100.0,
                "remaining": msg.battery_remaining
            }
        elif msg_type == 'HEARTBEAT':
            self.telemetry["status"] = "connected"

    def send_heartbeat(self):
        self.master.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GCS,
            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
            0, 0, 0
        )

    def send_setpoint(self, x: float, y: float, z: float, yaw: float = 0.0):
        self.master.mav.set_position_target_local_ned_send(
            0,
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_FRAME_LOCAL_NED,
            0b0000111111111000,
            x, y, z,
            0, 0, 0,
            0, 0, 0,
            yaw, 0
        )
        logger.info(f"Setpoint sent: x={x}, y={y}, z={z}")

    def upload_mission(self, waypoints: list):
        logger.info(f"Uploading mission ({len(waypoints)} points)...")

        self.master.waypoint_clear_all_send()
        time.sleep(0.5)

        self.master.waypoint_count_send(len(waypoints))

        for i in range(len(waypoints)):
            msg = self.master.recv_match(type=['MISSION_REQUEST'], blocking=True, timeout=5)
            if msg is None:
                logger.error(f"Timeout waiting for MISSION_REQUEST for point {i}")
                return False

            lat, lon, alt = waypoints[i]

            self.master.mav.mission_item_int_send(
                self.master.target_system,
                self.master.target_component,
                msg.seq,
                mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                0, 1,
                0, 0, 0, 0,
                int(lat * 1e7),
                int(lon * 1e7),
                alt
            )
            logger.info(f"Point {msg.seq} sent")

        msg = self.master.recv_match(type=['MISSION_ACK'], blocking=True, timeout=5)
        if msg and msg.type == mavutil.mavlink.MAV_MISSION_ACCEPTED:
            logger.info("Mission uploaded successfully!")
            return True
        else:
            logger.error(f"Mission upload failed: {msg}")
            return False

    def get_telemetry(self):
        return self.telemetry.copy()

    def stop(self):
        self.running = False
        self.master.close()
