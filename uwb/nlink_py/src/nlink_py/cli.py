"""nlink-dump: read a LinkTrack serial stream (or a recording) and emit
parsed frames as JSON lines to stdout and/or JSON datagrams over UDP."""

from __future__ import annotations

import argparse
import os
import sys
import time

from ._nlink_native import LinkTrackExtractor
from .reader import FileReplayReader, SerialReader
from .udp import UdpJsonPublisher, json_dumps


def _parse_udp(value: str):
    host, sep, port = value.rpartition(":")
    if not sep or not port.isdigit():
        raise argparse.ArgumentTypeError("expected HOST:PORT, e.g. 127.0.0.1:9999")
    return host or "127.0.0.1", int(port)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nlink-dump",
        description="Parse Nooploop LinkTrack NLink frames from a serial port "
                    "or a raw recording.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--port", help="serial port, e.g. /dev/ttyUSB0")
    source.add_argument("--replay", metavar="FILE",
                        help="replay a raw stream recorded with --record")
    parser.add_argument("--baud", type=int, default=921600,
                        help="serial baud rate (default: %(default)s)")
    parser.add_argument("--udp", type=_parse_udp, metavar="HOST:PORT",
                        help="publish each frame as a JSON datagram")
    parser.add_argument("--record", metavar="FILE",
                        help="append the raw serial stream to FILE")
    parser.add_argument("--replay-delay", type=float, default=0.0,
                        help="seconds between replayed 512-byte chunks")
    parser.add_argument("--quiet", action="store_true",
                        help="do not print JSON lines to stdout")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.record and not args.port:
        build_parser().error("--record requires --port")

    publisher = UdpJsonPublisher(*args.udp) if args.udp else None

    def on_frame(frame_type: str, frame: dict) -> None:
        frame["frame_type"] = frame_type
        frame["recv_time"] = time.time()
        if not args.quiet:
            print(json_dumps(frame), flush=True)
        if publisher:
            publisher.send(frame)

    extractor = LinkTrackExtractor()
    extractor.set_callback(on_frame)

    if args.port:
        reader = SerialReader(args.port, args.baud, record_path=args.record)
    else:
        reader = FileReplayReader(args.replay, chunk_delay=args.replay_delay)

    try:
        reader.run(extractor.feed)
    except KeyboardInterrupt:
        pass
    except BrokenPipeError:
        # downstream consumer (e.g. `head`) closed our stdout
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    finally:
        if publisher:
            publisher.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
