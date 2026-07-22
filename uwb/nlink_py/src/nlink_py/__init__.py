"""Non-ROS parser for the Nooploop LinkTrack UWB NLink protocol.

Frame slicing and unpacking are done by the untouched upstream C/C++ code
(nooploop-dev/protocol_extracter + nooploop-dev/nlink_unpack); this package
adds serial/file readers and a JSON-over-UDP publisher on top.
"""

from ._nlink_native import LinkTrackExtractor
from .reader import FileReplayReader, SerialReader
from .udp import UdpJsonPublisher, json_dumps

FRAME_TYPES = (
    "anchorframe0",
    "tagframe0",
    "nodeframe0",
    "nodeframe1",
    "nodeframe2",
    "nodeframe3",
    "nodeframe4",
    "nodeframe5",
    "nodeframe6",
)

__version__ = "0.1.0"

__all__ = [
    "LinkTrackExtractor",
    "SerialReader",
    "FileReplayReader",
    "UdpJsonPublisher",
    "json_dumps",
    "FRAME_TYPES",
]
