"""End-to-end smoke tests for the nlink-dump CLI (replay + UDP paths)."""

import json
import socket

import pytest
from golden_frames import GOLDEN_FRAMES

from nlink_py.cli import main

# 8 captures hold one frame each, the nodeframe4 capture holds four
EXPECTED_FRAME_COUNT = len(GOLDEN_FRAMES) + 3


@pytest.fixture
def sample_stream(tmp_path):
    path = tmp_path / "sample.bin"
    path.write_bytes(b"".join(GOLDEN_FRAMES.values()))
    return str(path)


def test_replay_prints_json_lines(sample_stream, capsys):
    assert main(["--replay", sample_stream]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    frames = [json.loads(line) for line in lines]
    assert len(frames) == EXPECTED_FRAME_COUNT
    assert {f["frame_type"] for f in frames} == set(GOLDEN_FRAMES)
    assert all("recv_time" in f for f in frames)


def test_replay_publishes_udp(sample_stream, capsys):
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(2)
    port = receiver.getsockname()[1]

    assert main(["--replay", sample_stream, "--udp", f"127.0.0.1:{port}",
                 "--quiet"]) == 0
    assert capsys.readouterr().out == ""

    frames = []
    for _ in range(EXPECTED_FRAME_COUNT):
        frames.append(json.loads(receiver.recv(65536)))
    receiver.close()
    assert {f["frame_type"] for f in frames} == set(GOLDEN_FRAMES)
