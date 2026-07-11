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
            # --- НОВОЕ: Локальные координаты из симулятора ---
            "local_position": {"x": 0.0, "y": 0.0, "z": 0.0},
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
        # Переменные времени для периодических запросов
        last_heartbeat = 0
        last_stream_req = 0

        while self.running:
            now = time.time()

            # 1. Шлем HEARTBEAT раз в секунду, чтобы SITL знал, что мы - активная GCS
            if now - last_heartbeat >= 1.0:
                self.send_heartbeat()
                last_heartbeat = now

            # 2. Каждые 5 секунд принудительно требуем у SITL начать слать координаты
            if now - last_stream_req >= 5.0:
                try:
                    # MAV_DATA_STREAM_ALL запрашивает все основные потоки (включая позицию)
                    self.master.mav.request_data_stream_send(
                        self.master.target_system,
                        self.master.target_component,
                        mavutil.mavlink.MAV_DATA_STREAM_ALL,
                        10,  # Частота отправки координат (10 кадров в секунду)
                        1    # 1 = начать отправку, 0 = остановить
                    )
                    # logger.info("Requested data stream from SITL")
                except Exception as e:
                    logger.error(f"Failed to request data stream: {e}")
                last_stream_req = now

            # 3. Слушаем входящие сообщения
            msg = self.master.recv_match(blocking=True, timeout=0.1)
            if msg:
                self._process_message(msg)

    def _process_message(self, msg):
        msg_type = msg.get_type()

        # --- [НОВОЕ] Получаем локальные метры от симулятора ---
        if msg_type == 'LOCAL_POSITION_NED':
            self.telemetry["local_position"] = {
                "x": msg.x,  # North (наш X)
                "y": msg.y,  # East (наш Y)
                "z": msg.z  # Down (наш -Z)
            }

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

    def set_mode(self, mode_name: str):
        # Ищем ID режима по его имени (например, 'GUIDED')
        if mode_name not in self.master.mode_mapping():
            logger.error(f"Unknown mode: {mode_name}")
            return False

        mode_id = self.master.mode_mapping()[mode_name]
        self.master.mav.set_mode_send(
            self.master.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mode_id
        )
        logger.info(f"Command sent: Change mode to {mode_name}")
        return True

    def arm(self):
        # Отправляем команду MAV_CMD_COMPONENT_ARM_DISARM
        self.master.mav.command_long_send(
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,  # confirmation
            1,  # 1 = Arm, 0 = Disarm
            0, 0, 0, 0, 0, 0
        )
        logger.info("Command sent: ARM")

    def takeoff(self, altitude: float):
        # Отправляем команду MAV_CMD_NAV_TAKEOFF
        # Внимание: для взлета высота (param 7) указывается положительной (вверх)
        self.master.mav.command_long_send(
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0,  # confirmation
            0, 0, 0, 0, 0, 0,
            altitude  # Target altitude
        )
        logger.info(f"Command sent: TAKEOFF to {altitude}m")

    def get_telemetry(self):
        return self.telemetry.copy()

    def stop(self):
        self.running = False
        self.master.close()
