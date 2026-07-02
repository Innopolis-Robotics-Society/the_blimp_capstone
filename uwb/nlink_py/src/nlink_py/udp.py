"""JSON serialization and UDP publishing of parsed frames."""

from __future__ import annotations

import json
import socket


def _json_default(obj):
    if isinstance(obj, (bytes, bytearray)):
        return obj.hex()
    raise TypeError(f"not JSON serializable: {type(obj)!r}")


def json_dumps(frame: dict) -> str:
    """Serialize a parsed frame; raw payload bytes become hex strings."""
    return json.dumps(frame, default=_json_default)


class UdpJsonPublisher:
    """Sends one JSON datagram per parsed frame."""

    def __init__(self, host: str, port: int):
        self._addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, frame: dict) -> None:
        self._sock.sendto(json_dumps(frame).encode(), self._addr)

    def close(self) -> None:
        self._sock.close()
