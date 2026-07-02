"""FastAPI backend: relays UDP frames from nlink-dump to WebSocket clients
and serves the static three.js frontend plus the anchor-position config."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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


def create_app(udp_port: int, anchors_path: Path) -> FastAPI:
    app = FastAPI(title="blimp UWB dashboard")
    relay = FrameRelay()

    @app.on_event("startup")
    async def _startup() -> None:
        relay.start()
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _UdpProtocol(relay), local_addr=("0.0.0.0", udp_port))
        app.state.udp_transport = transport
        log.info("listening for nlink-dump datagrams on UDP :%d", udp_port)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
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
