from collections import deque
from types import SimpleNamespace

import pytest

import blimp_dashboard.backend as backend_module
from blimp_dashboard.backend import (
    MAVLinkBackend,
    MAVLinkRejectedError,
    MAVLinkTimeoutError,
)


class Constants:
    MAV_TYPE_GCS = 6
    MAV_AUTOPILOT_INVALID = 8
    MAV_AUTOPILOT_ARDUPILOTMEGA = 3
    MAV_COMP_ID_AUTOPILOT1 = 1
    MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 1
    MAV_MODE_FLAG_SAFETY_ARMED = 128
    MAV_CMD_DO_SET_MODE = 176
    MAV_CMD_NAV_TAKEOFF = 22
    MAV_CMD_MISSION_START = 300
    MAV_CMD_COMPONENT_ARM_DISARM = 400
    MAV_CMD_NAV_WAYPOINT = 16
    MAV_RESULT_ACCEPTED = 0
    MAV_RESULT_IN_PROGRESS = 5
    MAV_MISSION_ACCEPTED = 0
    MAV_MISSION_TYPE_MISSION = 0
    MAV_FRAME_GLOBAL_RELATIVE_ALT = 3
    MAV_FRAME_GLOBAL_RELATIVE_ALT_INT = 6


class Message:
    def __init__(self, message_type, *, src_system=1, src_component=1, **fields):
        self._message_type = message_type
        self._src_system = src_system
        self._src_component = src_component
        for name, value in fields.items():
            setattr(self, name, value)

    def get_type(self):
        return self._message_type

    def get_srcSystem(self):
        return self._src_system

    def get_srcComponent(self):
        return self._src_component


class Sender:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args):
            self.calls.append((name, args))

        return record


class Master:
    target_system = 1
    target_component = 0  # pymavlink leaves this at 0 after wait_heartbeat

    def __init__(self, incoming=(), *, autopilot=12):
        self.mav = Sender()
        self.incoming = deque(incoming)
        self.closed = False
        self.autopilot = autopilot

    def wait_heartbeat(self, timeout):
        return Message(
            "HEARTBEAT",
            base_mode=0,
            custom_mode=0,
            autopilot=self.autopilot,
            type=13,
        )

    def recv_match(self, **_kwargs):
        return self.incoming.popleft() if self.incoming else None

    def mode_mapping(self):
        return {"AUTO": 10, "GUIDED": 4}

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def fake_mavutil(monkeypatch):
    monkeypatch.setattr(
        backend_module,
        "mavutil",
        SimpleNamespace(
            mavlink=Constants,
            mode_string_v10=lambda message: f"MODE_{message.custom_mode}",
        ),
    )


def make_backend(master, **kwargs):
    options = {
        "link_timeout": 60,
        "command_timeout": 0.1,
        "mission_timeout": 0.15,
    }
    options.update(kwargs)
    return MAVLinkBackend(
        "fake",
        connection_factory=lambda *_args, **_kwargs: master,
        start_telemetry=False,
        **options,
    )


def test_arm_is_packed_as_command_long_and_requires_accepted_ack():
    master = Master(
        [Message("COMMAND_ACK", command=Constants.MAV_CMD_COMPONENT_ARM_DISARM, result=0)]
    )
    backend = make_backend(master)

    backend.arm()

    name, args = master.mav.calls[-1]
    assert name == "command_long_send"
    assert args[:4] == (1, 1, Constants.MAV_CMD_COMPONENT_ARM_DISARM, 0)
    assert args[4:] == (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    assert master.target_component == 1


def test_command_ack_from_another_system_cannot_complete_transaction():
    master = Master(
        [
            Message(
                "COMMAND_ACK",
                src_system=2,
                command=Constants.MAV_CMD_DO_SET_MODE,
                result=0,
            ),
            Message("COMMAND_ACK", command=Constants.MAV_CMD_DO_SET_MODE, result=0),
        ]
    )
    backend = make_backend(master)

    assert backend.set_mode("auto") == "AUTO"


def test_command_ack_addressed_to_another_gcs_is_ignored():
    master = Master(
        [
            Message(
                "COMMAND_ACK",
                target_system=42,
                target_component=190,
                command=Constants.MAV_CMD_COMPONENT_ARM_DISARM,
                result=0,
            ),
            Message(
                "COMMAND_ACK",
                target_system=255,
                target_component=190,
                command=Constants.MAV_CMD_COMPONENT_ARM_DISARM,
                result=0,
            ),
        ]
    )
    backend = make_backend(master)

    backend.arm()

    assert len(master.incoming) == 0


def test_rejected_command_is_not_reported_as_success():
    master = Master(
        [Message("COMMAND_ACK", command=Constants.MAV_CMD_MISSION_START, result=4)]
    )
    backend = make_backend(master)

    with pytest.raises(MAVLinkRejectedError, match="MAV_RESULT 4"):
        backend.start_mission()


def test_command_is_retried_with_incremented_confirmation_when_ack_is_lost():
    master = Master()
    backend = make_backend(master, command_timeout=0.01)

    with pytest.raises(MAVLinkTimeoutError):
        backend.arm()

    calls = [args for name, args in master.mav.calls if name == "command_long_send"]
    assert [args[3] for args in calls] == [0, 1, 2]


def test_mission_transaction_handles_both_request_types_and_relative_altitude():
    master = Master(
        [
            Message("MISSION_REQUEST", seq=0, mission_type=0),
            Message("MISSION_REQUEST_INT", seq=1, mission_type=0),
            Message("MISSION_ACK", type=0, mission_type=0, opaque_id=42),
        ]
    )
    backend = make_backend(master)

    result = backend.upload_mission(
        [(55.7522, 48.7446, 1.2), (55.75221, 48.74461, 1.6)]
    )

    assert result == {"count": 2, "opaque_id": 42}
    names = [name for name, _args in master.mav.calls]
    assert names == ["mission_count_send", "mission_item_int_send", "mission_item_int_send"]
    first_item = master.mav.calls[1][1]
    assert first_item[3] == Constants.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
    assert first_item[5] == 0  # upload does not silently make an item current
    assert first_item[13] == pytest.approx(1.2)
    assert "waypoint_clear_all_send" not in names


def test_mission_packets_addressed_to_another_gcs_cannot_complete_upload():
    master = Master(
        [
            Message(
                "MISSION_REQUEST_INT",
                target_system=42,
                target_component=190,
                seq=0,
                mission_type=0,
            ),
            Message(
                "MISSION_REQUEST_INT",
                target_system=255,
                target_component=190,
                seq=0,
                mission_type=0,
            ),
            Message(
                "MISSION_ACK",
                target_system=42,
                target_component=190,
                type=0,
                mission_type=0,
            ),
            Message(
                "MISSION_ACK",
                target_system=255,
                target_component=190,
                type=0,
                mission_type=0,
            ),
        ]
    )
    backend = make_backend(master)

    result = backend.upload_mission([(55.7522, 48.7446, 1.2)])

    assert result["count"] == 1
    assert [name for name, _args in master.mav.calls].count(
        "mission_item_int_send"
    ) == 1


def test_mission_count_is_retried_three_times_on_packet_loss():
    master = Master()
    backend = make_backend(master, mission_timeout=0.06)

    with pytest.raises(MAVLinkTimeoutError):
        backend.upload_mission([(55.7522, 48.7446, 1.2)])

    assert [name for name, _args in master.mav.calls].count("mission_count_send") == 3


def test_no_origin_or_stream_request_is_sent_during_connection():
    master = Master()
    make_backend(master)

    assert master.mav.calls == []
