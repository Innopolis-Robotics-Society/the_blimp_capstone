import json
import threading

from fastapi.testclient import TestClient
import pytest

from blimp_dashboard.server import (
    STATIC_DIR,
    create_app,
    filter_uwb_datagram,
    local_to_global_gps,
)


CONTROL_HEADERS = {"X-Blimp-Control": "dashboard"}


class FakeBackend:
    is_connected = True

    def __init__(self):
        self.calls = []
        self.uploaded = None

    def get_status(self):
        return {
            "configured": True,
            "connected": True,
            "target_system": 1,
            "target_component": 1,
            "last_heartbeat_age_s": 0.1,
            "last_error": None,
            "telemetry": {
                "position": {"lat": None, "lon": None, "alt": None, "relative_alt": None},
                "local_position": {"x": None, "y": None, "z": None},
                "battery": {"voltage": 7.8, "current": 1.2, "remaining": 80},
                "mode": "AUTO",
                "armed": True,
            },
        }

    def arm(self):
        self.calls.append(("arm",))

    def disarm(self):
        self.calls.append(("disarm",))

    def set_mode(self, mode):
        self.calls.append(("mode", mode))
        return mode

    def takeoff(self, altitude):
        self.calls.append(("takeoff", altitude))

    def start_mission(self):
        self.calls.append(("mission_start",))

    def upload_mission(self, mission):
        self.uploaded = mission
        return {"count": len(mission), "opaque_id": 7}

    def stop(self):
        self.calls.append(("stop",))


def inject_backend(app, backend):
    with app.state.mavlink_state_lock:
        app.state.mavlink = backend


def test_anchor_frame_is_reduced_to_exactly_one_configured_tag():
    frame = {
        "frame_type": "anchorframe0",
        "voltage": 4.9,
        "nodes": [
            {"id": 1, "role": 2, "pos_3d": [1, 2, 3]},
            {"id": 2, "role": 2, "pos_3d": [4, 5, 6]},
            {"id": 9, "role": 0, "pos_3d": [7, 8, 9]},
        ],
    }

    filtered = json.loads(filter_uwb_datagram(json.dumps(frame).encode(), tag_id=2))

    assert filtered["nodes"] == [{"id": 2, "role": 2, "pos_3d": [4, 5, 6]}]


def test_frames_for_another_standalone_tag_are_dropped():
    assert filter_uwb_datagram(b'{"frame_type":"tagframe0","id":2}', 1) is None
    assert (
        filter_uwb_datagram(
            b'{"frame_type":"nodeframe2","role":2,"id":2,"pos_3d":[4,5,6]}',
            1,
        )
        is None
    )


def test_global_conversion_keeps_z_as_relative_altitude():
    lat, lon, altitude = local_to_global_gps(1.0, 2.0, 1.2)

    assert lat > 55.7522
    assert lon > 48.7446
    assert altitude == pytest.approx(1.2)


def test_real_mavlink_api_contract_and_status(tmp_path):
    app = create_app(
        0,
        tmp_path / "anchors.json",
        mavlink_endpoint="fake-real-link",
    )
    backend = FakeBackend()
    inject_backend(app, backend)
    client = TestClient(app)

    status = client.get("/api/mavlink/status").json()
    assert status["configured"] is True
    assert status["connected"] is True
    assert status["mode"] == "AUTO"
    assert status["armed"] is True
    assert status["mission_ready"] is False

    response = client.post(
        "/action/mode",
        json={"mode": "auto"},
        headers=CONTROL_HEADERS,
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "command": "set_mode",
        "mode": "AUTO",
        "acknowledged": True,
    }

    response = client.post("/action/mission/start", headers=CONTROL_HEADERS)
    assert response.status_code == 409
    assert ("mission_start",) not in backend.calls


def test_route_upload_sends_relative_height_and_does_not_start_mission(tmp_path):
    app = create_app(
        0,
        tmp_path / "anchors.json",
        mavlink_endpoint="fake-real-link",
    )
    backend = FakeBackend()
    inject_backend(app, backend)
    client = TestClient(app)

    response = client.post(
        "/upload_route",
        json=[{"x": 1.0, "y": 2.0, "z": 1.2}],
        headers=CONTROL_HEADERS,
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "message": "mission uploaded and acknowledged by autopilot",
        "count": 1,
        "opaque_id": 7,
        "started": False,
    }
    assert backend.uploaded[0][2] == pytest.approx(1.2)
    assert ("mission_start",) not in backend.calls

    assert client.get("/api/mavlink/status").json()["mission_ready"] is True
    start = client.post("/action/mission/start", headers=CONTROL_HEADERS)
    assert start.status_code == 200
    assert backend.calls[-1] == ("mission_start",)


def test_route_safety_limits_are_enforced_before_any_mavlink_send(tmp_path):
    app = create_app(
        0,
        tmp_path / "anchors.json",
        mavlink_endpoint="fake-real-link",
    )
    backend = FakeBackend()
    inject_backend(app, backend)
    client = TestClient(app)

    response = client.post(
        "/upload_route",
        json=[{"x": 1.0, "y": 2.0, "z": 121.2}],
        headers=CONTROL_HEADERS,
    )

    assert response.status_code == 422
    assert backend.uploaded is None


def test_control_is_unavailable_until_real_endpoint_is_configured(tmp_path):
    app = create_app(0, tmp_path / "anchors.json")
    client = TestClient(app)

    response = client.post("/action/arm", headers=CONTROL_HEADERS)

    assert response.status_code == 503
    assert response.json()["detail"] == "MAVLink is not configured"


def test_flight_commands_require_same_origin_control_header(tmp_path):
    app = create_app(0, tmp_path / "anchors.json", mavlink_endpoint="configured")
    inject_backend(app, FakeBackend())
    client = TestClient(app)

    response = client.post("/action/arm")

    assert response.status_code == 403
    assert response.json()["detail"] == "missing dashboard control header"


def test_arm_is_sent_exactly_once(tmp_path):
    app = create_app(0, tmp_path / "anchors.json", mavlink_endpoint="configured")
    backend = FakeBackend()
    inject_backend(app, backend)
    client = TestClient(app)

    response = client.post("/action/arm", headers=CONTROL_HEADERS)

    assert response.status_code == 200
    assert backend.calls == [("arm",)]


def test_bundled_ui_attaches_the_control_header():
    source = (STATIC_DIR / "app.js").read_text()

    assert "'X-Blimp-Control': 'dashboard'" in source


def test_mission_start_is_invalidated_when_backend_is_replaced(tmp_path):
    app = create_app(0, tmp_path / "anchors.json", mavlink_endpoint="configured")
    first_backend = FakeBackend()
    inject_backend(app, first_backend)
    client = TestClient(app)

    uploaded = client.post(
        "/upload_route",
        json=[{"x": 1.0, "y": 2.0, "z": 1.2}],
        headers=CONTROL_HEADERS,
    )
    assert uploaded.status_code == 200

    replacement_backend = FakeBackend()
    inject_backend(app, replacement_backend)
    assert client.get("/api/mavlink/status").json()["mission_ready"] is False

    start = client.post("/action/mission/start", headers=CONTROL_HEADERS)
    assert start.status_code == 409
    assert replacement_backend.calls == []


def test_connection_loop_recovers_when_autopilot_is_powered_on_late(tmp_path):
    connected = threading.Event()
    backend = FakeBackend()
    attempts = 0

    def factory(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("no heartbeat yet")
        connected.set()
        return backend

    app = create_app(
        0,
        tmp_path / "anchors.json",
        mavlink_endpoint="fake-real-link",
        mavlink_reconnect_delay=0.01,
        mavlink_factory=factory,
        bind_udp=False,
    )

    with TestClient(app) as client:
        assert connected.wait(0.5)
        for _attempt in range(20):
            status = client.get("/api/mavlink/status").json()
            if status["connected"]:
                break
        assert status["connected"] is True
        assert attempts >= 2

    assert ("stop",) in backend.calls
