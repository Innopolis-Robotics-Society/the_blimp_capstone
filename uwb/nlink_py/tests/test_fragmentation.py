"""Frames must parse identically no matter how the byte stream is chopped up
or what garbage surrounds them (serial reads arrive in arbitrary chunks)."""

import pytest
from golden_frames import GOLDEN_FRAMES

from nlink_py import LinkTrackExtractor


def parse_chunked(data: bytes, chunk_size: int):
    frames = []
    extractor = LinkTrackExtractor()
    extractor.set_callback(lambda frame_type, frame: frames.append((frame_type, frame)))
    for i in range(0, len(data), chunk_size):
        extractor.feed(data[i:i + chunk_size])
    return frames


@pytest.mark.parametrize("chunk_size", [1, 3, 7, 64])
@pytest.mark.parametrize("name", sorted(GOLDEN_FRAMES))
def test_chunked_equals_whole(name, chunk_size):
    data = GOLDEN_FRAMES[name]
    whole = parse_chunked(data, len(data))
    chunked = parse_chunked(data, chunk_size)
    assert chunked == whole
    assert whole, "golden frame did not parse at all"


@pytest.mark.parametrize("chunk_size", [5, 1000])
def test_concatenated_stream_with_garbage(chunk_size):
    stream = b"\x12\x34\x00"
    expected_types = []
    for name, data in sorted(GOLDEN_FRAMES.items()):
        stream += data + b"\xde\xad\xbe\xef"
        count = 4 if name == "nodeframe4" else 1  # capture holds 4 frames
        expected_types += [name] * count
    stream += b"\x55"  # dangling header byte stays buffered, never emitted

    frames = parse_chunked(stream, chunk_size)
    assert sorted(t for t, _ in frames) == sorted(expected_types)
