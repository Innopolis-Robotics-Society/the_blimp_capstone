"""Byte-stream sources feeding a LinkTrackExtractor."""

from __future__ import annotations

import time
from typing import Callable, Optional


class SerialReader:
    """Reads a serial port and feeds raw bytes to `feed`.

    Optionally mirrors the raw stream into a record file, so a session can be
    replayed later with FileReplayReader (no hardware needed).
    """

    def __init__(self, port: str, baud: int = 921600,
                 record_path: Optional[str] = None):
        self._port = port
        self._baud = baud
        self._record_path = record_path

    def run(self, feed: Callable[[bytes], None],
            should_stop: Optional[Callable[[], bool]] = None) -> None:
        import serial  # deferred so replay-only usage works without a port

        record = open(self._record_path, "ab") if self._record_path else None
        try:
            with serial.Serial(self._port, self._baud, timeout=0.05) as ser:
                while not (should_stop and should_stop()):
                    chunk = ser.read(ser.in_waiting or 1)
                    if not chunk:
                        continue
                    if record:
                        record.write(chunk)
                    feed(chunk)
        finally:
            if record:
                record.close()


class FileReplayReader:
    """Replays a recorded raw stream in chunks.

    `chunk_delay` (seconds between chunks) throttles the replay; 0 replays as
    fast as possible. With `loop=True` the file is replayed from the start
    again once exhausted (endless demo stream).
    """

    def __init__(self, path: str, chunk_size: int = 512,
                 chunk_delay: float = 0.0, loop: bool = False):
        self._path = path
        self._chunk_size = chunk_size
        self._chunk_delay = chunk_delay
        self._loop = loop

    def run(self, feed: Callable[[bytes], None],
            should_stop: Optional[Callable[[], bool]] = None) -> None:
        while True:
            with open(self._path, "rb") as f:
                while not (should_stop and should_stop()):
                    chunk = f.read(self._chunk_size)
                    if not chunk:
                        break
                    feed(chunk)
                    if self._chunk_delay > 0:
                        time.sleep(self._chunk_delay)
            if not self._loop or (should_stop and should_stop()):
                break
