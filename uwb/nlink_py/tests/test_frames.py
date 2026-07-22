"""Field-level checks against golden frames.

Expected values are taken verbatim from the upstream gtest
(nlink_parser/test/test_nlink_parser.cpp), so this verifies that the Python
bindings expose exactly what the reference ROS node would have published.
"""

import pytest
from golden_frames import GOLDEN_FRAMES

from nlink_py import LinkTrackExtractor

ABS = 0.001


def parse(data: bytes):
    frames = []
    extractor = LinkTrackExtractor()
    extractor.set_callback(lambda frame_type, frame: frames.append((frame_type, frame)))
    extractor.feed(data)
    return frames


def parse_one(name: str):
    frames = parse(GOLDEN_FRAMES[name])
    assert [t for t, _ in frames] == [name]
    return frames[0][1]


def test_tagframe0():
    f = parse_one("tagframe0")
    assert f["id"] == 1
    assert f["role"] == 2  # LINKTRACK_ROLE_TAG
    assert f["pos_3d"] == pytest.approx([2.702, -0.091, 1], abs=ABS)
    assert f["vel_3d"] == pytest.approx([-0.0038, -0.0006, 0], abs=0.0001)
    assert f["dis_arr"] == pytest.approx([3.125, 5.539, 6.861, 4.684, 0, 0, 0, 0], abs=ABS)
    assert f["imu_gyro_3d"] == pytest.approx([0.02767, 0.008514, -0.045762], abs=0.00001)
    assert f["imu_acc_3d"] == pytest.approx([0.251265, 9.74908, -0.040681], abs=0.00001)
    assert f["angle_3d"] == pytest.approx([144.49, 97.17, -14.68], abs=0.01)
    assert f["quaternion"] == pytest.approx([-0.656777, -0.125699, -0.739489, 0.0512801], abs=0.00001)
    assert f["eop_3d"] == pytest.approx([0.11, 0.16, 2.55], abs=0.01)
    assert f["local_time"] == 44556
    assert f["system_time"] == 71627
    assert f["voltage"] == pytest.approx(4.948, abs=ABS)


def test_anchorframe0():
    f = parse_one("anchorframe0")
    assert f["local_time"] == 33313
    assert f["system_time"] == 32000
    assert f["voltage"] == pytest.approx(4.995, abs=ABS)
    assert len(f["nodes"]) == 2
    assert f["nodes"][0]["pos_3d"] == pytest.approx([2.895, 2.419, -0.263], abs=ABS)
    assert f["nodes"][0]["dis_arr"] == pytest.approx([3.64, 3.34, 4.9, 4.93, 0, 0, 0, 0], abs=ABS)
    assert f["nodes"][1]["pos_3d"] == pytest.approx([2.435, 2.399, -1.117], abs=ABS)
    assert f["nodes"][1]["dis_arr"] == pytest.approx([3.18, 2.98, 5.3, 5.31, 0, 0, 0, 0], abs=ABS)


def test_nodeframe0():
    f = parse_one("nodeframe0")
    assert len(f["nodes"]) == 2
    assert f["nodes"][0]["data"] == bytes.fromhex("112233445566778899")
    assert len(f["nodes"][1]["data"]) == 37


def test_nodeframe1():
    f = parse_one("nodeframe1")
    assert f["system_time"] == 33000
    assert f["local_time"] == 34304
    assert f["voltage"] == pytest.approx(4.936, abs=ABS)
    assert f["nodes"][0]["pos_3d"] == pytest.approx([2.911, 2.438, -0.101], abs=ABS)
    assert f["nodes"][1]["pos_3d"] == pytest.approx([2.451, 2.373, -0.828], abs=ABS)


def test_nodeframe2():
    f = parse_one("nodeframe2")
    assert f["pos_3d"] == pytest.approx([2.782, -0.033, 1], abs=ABS)
    assert f["vel_3d"] == pytest.approx([-0.0006, 0.0026, 0], abs=0.0001)
    assert f["imu_gyro_3d"] == pytest.approx([0.02767, 0.00958, -0.04576], abs=0.00001)
    assert f["imu_acc_3d"] == pytest.approx([0.224942, 9.73712, -0.05504], abs=0.00001)
    assert f["angle_3d"] == pytest.approx([90.69, 91.93, -88.48], abs=0.01)
    assert f["quaternion"] == pytest.approx([0.691282, 0.694677, 0.154792, -0.110552], abs=0.00001)
    assert f["eop_3d"] == pytest.approx([0.06, 0.09, 2.55], abs=0.01)
    assert f["local_time"] == 9157
    assert f["system_time"] == 1926842
    assert f["voltage"] == pytest.approx(4.973, abs=ABS)
    expected_nodes = [(3.179, -88.5, -79.5), (5.548, -90, -80.5),
                      (6.728, -101, -79.5), (4.651, -99, -80)]
    assert len(f["nodes"]) == len(expected_nodes)
    for node, (dis, fp_rssi, rx_rssi) in zip(f["nodes"], expected_nodes):
        assert node["dis"] == pytest.approx(dis, abs=ABS)
        assert node["fp_rssi"] == pytest.approx(fp_rssi, abs=ABS)
        assert node["rx_rssi"] == pytest.approx(rx_rssi, abs=ABS)


RANGING_NODES = [(2.85, -90.5, -79.5), (6.051, -91, -80),
                 (7.304, -85, -79.5), (5.35, -92, -80)]


@pytest.mark.parametrize("name", ["nodeframe3", "nodeframe5"])
def test_ranging_frames(name):
    f = parse_one(name)
    assert f["local_time"] == 463352
    assert f["system_time"] == 7262319
    assert f["voltage"] == pytest.approx(4.954, abs=ABS)
    assert len(f["nodes"]) == len(RANGING_NODES)
    for node, (dis, fp_rssi, rx_rssi) in zip(f["nodes"], RANGING_NODES):
        assert node["dis"] == pytest.approx(dis, abs=ABS)
        assert node["fp_rssi"] == pytest.approx(fp_rssi, abs=ABS)
        assert node["rx_rssi"] == pytest.approx(rx_rssi, abs=ABS)


def test_nodeframe4():
    # The golden capture contains four consecutive frames; expectations from
    # the upstream gtest describe the last one.
    frames = parse(GOLDEN_FRAMES["nodeframe4"])
    assert [t for t, _ in frames] == ["nodeframe4"] * 4
    f = frames[-1][1]
    assert f["local_time"] == 106020
    assert f["system_time"] == 106020
    assert f["voltage"] == pytest.approx(4.44, abs=ABS)
    expected_tags = [
        (2, 4.45, [(0, 2.422), (1, 1.729), (2, 2.107), (3, 1.762)]),
        (5, 3.65, [(0, 2.701), (1, 1.429), (2, 2.378), (3, 1.33)]),
    ]
    assert len(f["tags"]) == len(expected_tags)
    for tag, (tag_id, voltage, anchors) in zip(f["tags"], expected_tags):
        assert tag["id"] == tag_id
        assert tag["voltage"] == pytest.approx(voltage, abs=ABS)
        assert [a["id"] for a in tag["anchors"]] == [a for a, _ in anchors]
        assert [a["dis"] for a in tag["anchors"]] == pytest.approx(
            [d for _, d in anchors], abs=ABS)


def test_nodeframe6():
    f = parse_one("nodeframe6")
    assert len(f["nodes"]) == 2
    assert len(f["nodes"][0]["data"]) == 9
    assert len(f["nodes"][1]["data"]) == 37
