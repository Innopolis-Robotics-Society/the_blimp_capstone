"""FastAPI backend: relays UDP frames from nlink-dump to WebSocket clients
and serves the static three.js frontend plus the anchor-position config."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
from pathlib import Path
from pydantic import BaseModel
from typing import List

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# [НОВОЕ] Импортируем класс связи с дирижаблем от команды SWP
from .backend import MAVLinkBackend

class TakeoffReq(BaseModel):
    alt: float

class DashWaypoint(BaseModel):
    x: float
    y: float
    z: float

def reached(current_x: float, current_y: float, target_x: float, target_y: float, eps: float = 0.35) -> bool:
    return ((current_x - target_x) ** 2 + (current_y - target_y) ** 2) ** 0.5 < eps

log = logging.getLogger("blimp_dashboard")

STATIC_DIR = Path(__file__).parent / "static"

DEFAULT_ANCHORS = {
    "anchors": [
        {"id": 0, "pos": [0.0, 0.0, 0.0]},
        {"id": 1, "pos": [4.0, 0.0, 0.0]},
        {"id": 2, "pos": [4.0, 4.0, 0.0]},
        {"id": 3, "pos": [0.0, 4.0, 0.0]},
    ]
}


class FrameRelay:
    """Fans incoming UDP datagrams out to all connected WebSockets."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()

    def datagram_received(self, data: bytes) -> None:
        text = data.decode(errors="replace")
        for ws in list(self._clients):
            asyncio.ensure_future(self._send(ws, text))

    async def _send(self, ws: WebSocket, text: str) -> None:
        try:
            await ws.send_text(text)
        except Exception:
            self._clients.discard(ws)

    async def handle_client(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        try:
            while True:  # we never expect inbound messages; this detects close
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            self._clients.discard(ws)


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, relay: FrameRelay):
        self._relay = relay

    def datagram_received(self, data: bytes, addr) -> None:
        self._relay.datagram_received(data)


def load_anchors(path: Path) -> dict:
    if not path.exists():
        return DEFAULT_ANCHORS
    return json.loads(path.read_text())


def validate_anchors(payload: dict) -> dict:
    anchors = payload.get("anchors")
    if not isinstance(anchors, list):
        raise ValueError("expected {'anchors': [...]}")
    for a in anchors:
        if not isinstance(a.get("id"), int):
            raise ValueError("anchor id must be int")
        pos = a.get("pos")
        if (not isinstance(pos, list) or len(pos) != 3
                or not all(isinstance(v, (int, float)) for v in pos)):
            raise ValueError("anchor pos must be [x, y, z]")
    return {"anchors": anchors}


async def sitl_telemetry_broadcaster(app: FastAPI, relay: FrameRelay):
    """Каждые 100мс шлет координаты симулятора во все открытые вкладки браузера"""
    while True:
        await asyncio.sleep(0.1) # 10 Гц
        mav = getattr(app.state, "mavlink", None)
        if mav and mav.telemetry:
            loc = mav.telemetry.get("local_position", {"x": 0.0, "y": 0.0, "z": 0.0})
            payload = {
                "frame_type": "sitl_frame",
                "x": loc["x"],
                "y": loc["y"],
                "z": -loc["z"], # Инвертируем Z, так как в NED высота отрицательная
                "voltage": mav.telemetry["battery"]["voltage"],
                "mode": mav.telemetry.get("status", "SITL")
            }
            # Шлем JSON всем подключенным WebSockets
            text = json.dumps(payload)
            for ws in list(relay._clients):
                asyncio.ensure_future(relay._send(ws, text))


def create_app(udp_port: int, anchors_path: Path) -> FastAPI:
    app = FastAPI(title="blimp UWB dashboard")
    relay = FrameRelay()

    @app.on_event("startup")
    async def _startup() -> None:
        import threading  # Подключаем библиотеку потоков

        # --- Старт UWB ---
        relay.start()
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _UdpProtocol(relay), local_addr=("0.0.0.0", udp_port))
        app.state.udp_transport = transport
        log.info("listening for nlink-dump datagrams on UDP :%d", udp_port)

        # --- [ИСПРАВЛЕНО] Старт связи с Дирижаблем/SITL ---
        app.state.mavlink = None  # Изначально автопилот не подключен

        def init_mavlink():
            try:
                # Используем порт 14551 (свободный выход симулятора)
                app.state.mavlink = MAVLinkBackend('udpin:127.0.0.1:14551')
                log.info("MAVLink Backend успешно запущен!")
            except Exception as e:
                log.error(f"Не удалось запустить MAVLink: {e}")

        threading.Thread(target=init_mavlink, daemon=True).start()

        asyncio.create_task(sitl_telemetry_broadcaster(app, relay))

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        # --- [НОВОЕ] Корректное закрытие MAVLink ---
        mav = getattr(app.state, "mavlink", None)
        if mav:
            mav.stop()

        with contextlib.suppress(Exception):
            app.state.udp_transport.close()

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/anchors")
    async def get_anchors() -> dict:
        return load_anchors(anchors_path)

    @app.put("/api/anchors")
    async def put_anchors(payload: dict) -> dict:
        try:
            data = validate_anchors(payload)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        anchors_path.write_text(json.dumps(data, indent=2) + "\n")
        return data

    @app.post("/action/arm")
    async def action_arm() -> dict:
        mav = getattr(app.state, "mavlink", None)
        if not mav: raise HTTPException(status_code=503, detail="Автопилот не подключен!")

        # Для взлета дирижабль обязательно должен быть в режиме GUIDED
        mav.set_mode("GUIDED")
        await asyncio.sleep(0.5)  # Ждем полсекунды применения режима
        mav.arm()

        return {"status": "success", "message": "Моторы заведены (ARMED)!"}

    @app.post("/action/takeoff")
    async def action_takeoff(req: TakeoffReq) -> dict:
        mav = getattr(app.state, "mavlink", None)
        if not mav: raise HTTPException(status_code=503, detail="Автопилот не подключен!")

        mav.takeoff(req.alt)
        return {"status": "success", "message": f"Взлет на {req.alt}м!"}

    # =================================================================
    # [НОВОЕ] Обработка кликнутого маршрута из вашего нового дашборда
    # =================================================================
    @app.post("/upload_route")
    async def upload_route(waypoints: List[DashWaypoint]) -> dict:
        log.info(f"\n[МИССИЯ] Старт умного полета! Количество точек: {len(waypoints)}")
        mav = getattr(app.state, "mavlink", None)
        if not mav:
            raise HTTPException(status_code=503, detail="Автопилот не подключен!")

        target_z_ned = -1.2  # Летим на высоте 1.2 метра

        async def fly_smart_mission():
            for i, target in enumerate(waypoints):
                log.info(f"[МИССИЯ] Летим к точке {i + 1}: X={target.x:.2f}, Y={target.y:.2f}")

                # Отправляем команду автопилоту
                mav.send_setpoint(target.x, target.y, target_z_ned)

                # Цикл проверки достижения точки
                while True:
                    await asyncio.sleep(0.3)  # Проверяем часто (3 раза в секунду)

                    # Получаем текущие координаты из UWB
                    # (Мы можем брать их из вашей глобальной переменной telemetry в main.py,
                    # но для универсальности сделаем адаптивный выбор: UWB или SITL)
                    current_x = 0.0
                    current_y = 0.0

                    # Если есть живой симулятор, берем его координаты для теста
                    if mav.telemetry:
                        loc = mav.telemetry.get("local_position", {})
                        current_x = loc.get("x", 0.0)
                        current_y = loc.get("y", 0.0)

                    # Считаем расстояние до цели
                    if reached(current_x, current_y, target.x, target.y, eps=0.35):
                        log.info(f"[МИССИЯ] Точка {i + 1} достигнута! Зависаем на 3 секунды...")
                        await asyncio.sleep(3.0)  # Зависание на 3 секунды перед следующей точкой
                        break

            log.info("[МИССИЯ] Маршрут полностью выполнен!")

        # Запускаем полет в фоновой задаче FastAPI, чтобы не вешать браузер
        asyncio.create_task(fly_smart_mission())
        return {"status": "success", "message": "Умная миссия запущена"}
    # =================================================================

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await relay.handle_client(ws)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="blimp-dashboard",
        description="3D dashboard for the blimp UWB network; feed it with "
                    "`nlink-dump --udp HOST:UDP_PORT`.")
    parser.add_argument("--http-host", default="0.0.0.0")
    parser.add_argument("--http-port", type=int, default=8000)
    parser.add_argument("--udp-port", type=int, default=9999,
                        help="UDP port to receive nlink-dump datagrams on")
    parser.add_argument("--anchors", default="anchors.json",
                        help="path to the anchor-positions config")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    app = create_app(args.udp_port, Path(args.anchors))
    uvicorn.run(app, host=args.http_host, port=args.http_port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
