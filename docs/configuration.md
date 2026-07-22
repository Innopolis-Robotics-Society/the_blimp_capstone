# Configuration reference

Configuration is divided into four domains: the UWB console reader, dashboard server, real MAVLink link, and on-board controller. Freeze all four for a test; changing one without updating the test record makes results difficult to reproduce.

## Dashboard command-line options

| Option | Default | Purpose |
|---|---:|---|
| `--http-host` | `0.0.0.0` | Address used by the web server |
| `--http-port` | `8000` | Browser and HTTP API port |
| `--udp-port` | `9999` | Incoming UWB JSON datagram port |
| `--anchors` | `anchors.json` | Persistent anchor-coordinate file |
| `--uwb-tag-id` | `1` | The only tag ID forwarded to browsers |
| `--mavlink` | disabled | Real `pymavlink` endpoint, for example `udpin:0.0.0.0:14550` or `/dev/ttyUSB0` |
| `--mavlink-baud` | `115200` | Baud rate when the endpoint is serial |
| `--mavlink-heartbeat-timeout` | `10` s | Time allowed for the initial real heartbeat |
| `--mavlink-link-timeout` | `5` s | Maximum accepted age of the latest heartbeat |
| `--mavlink-command-timeout` | `5` s | Wait for each command acknowledgement |
| `--mavlink-mission-timeout` | `30` s | Overall mission exchange timeout |
| `--mavlink-reconnect-delay` | `3` s | Delay between connection attempts |
| `--mavlink-target-system` | unset | Accept only this MAVLink system ID |
| `--mavlink-target-component` | unset | Accept only this MAVLink component ID |
| `--origin-lat` | `55.7522` | WGS84 reference latitude for hall-to-mission conversion |
| `--origin-lon` | `48.7446` | WGS84 reference longitude |
| `--origin-alt` | `120.0` m | Reference altitude used only when explicitly setting FC origin |
| `--set-origin-on-upload` | off | Change and verify FC origin before each upload |
| `--min-mission-altitude` | `0.2` m | Smallest accepted waypoint or take-off height |
| `--max-mission-altitude` | `10.0` m | Largest accepted waypoint or take-off height |
| `--max-waypoint-distance` | `100.0` m | Maximum horizontal radius from local origin |
| `--max-mission-waypoints` | `100` | Maximum route length |

Command-line values override environment-backed defaults where the option is supplied.

## Environment variables

| Variable | Compose default | Corresponding function |
|---|---|---|
| `BLIMP_UWB_TAG_ID` | `1` | Active tag filter |
| `BLIMP_MAVLINK_ENDPOINT` | `udpin:0.0.0.0:14550` in `live`; empty in `replay` | Real autopilot link |
| `BLIMP_MAVLINK_BAUD` | `115200` | Serial MAVLink speed |
| `BLIMP_MAVLINK_HEARTBEAT_TIMEOUT` | `10` | Initial heartbeat wait |
| `BLIMP_MAVLINK_LINK_TIMEOUT` | `5` | Heartbeat freshness limit |
| `BLIMP_MAVLINK_COMMAND_TIMEOUT` | `5` | Command ACK wait |
| `BLIMP_MAVLINK_MISSION_TIMEOUT` | `30` | Mission transaction timeout |
| `BLIMP_MAVLINK_RECONNECT_DELAY` | `3` | Reconnect delay |
| `BLIMP_MAVLINK_TARGET_SYSTEM` | empty | Expected autopilot system ID |
| `BLIMP_MAVLINK_TARGET_COMPONENT` | empty | Expected autopilot component ID |
| `BLIMP_ORIGIN_LAT` | `55.7522` | Local-frame reference latitude |
| `BLIMP_ORIGIN_LON` | `48.7446` | Local-frame reference longitude |
| `BLIMP_ORIGIN_ALT` | `120.0` | Origin altitude in metres |
| `BLIMP_SET_ORIGIN_ON_UPLOAD` | `false` | Opt-in FC origin change |
| `BLIMP_MIN_MISSION_ALTITUDE` | `0.2` | Lower route limit |
| `BLIMP_MAX_MISSION_ALTITUDE` | `10.0` | Upper route limit |
| `BLIMP_MAX_WAYPOINT_DISTANCE` | `100.0` | Hall-radius limit |
| `BLIMP_MAX_MISSION_WAYPOINTS` | `100` | Route-count limit |
| `UWB_PORT` | `/dev/ttyCH343USB0` | P-A console serial device in Compose |
| `UWB_BAUD` | `921600` | P-A console serial speed |
| `MAVLINK_SERIAL_DEVICE` | `/dev/null` | Host serial device mapped to `/dev/mavlink` |

!!! note
    The latitude, longitude, altitude, device paths, and mission limits above are software defaults, not surveyed or safety-approved values for a new hall.

## Anchor file

The file is a JSON object with a unique integer ID and three finite coordinates per anchor:

```json
{
  "anchors": [
    {"id": 0, "pos": [0.0, 0.0, 1.3]},
    {"id": 1, "pos": [0.257, 2.134, 1.3]}
  ]
}
```

`pos` is `[x, y, z]` in metres in the UWB hall frame. The server rejects duplicate IDs, non-integer IDs, missing coordinates, and non-finite values. It does not judge whether the geometry is physically useful.

For Docker, `uwb/dashboard/anchors.json` is mounted into the container as `/config/anchors.json`. Changes made in the dashboard therefore persist back to the host file.

## Local mission frame and origin

The dashboard interprets route input as:

- `X`: north displacement in metres;
- `Y`: east displacement in metres;
- `Z`: altitude above flight-controller Home in metres.

The backend converts only the horizontal values to latitude and longitude. Mission items use `MAV_FRAME_GLOBAL_RELATIVE_ALT_INT`, so the submitted `Z` remains relative. The configured `origin-alt` is used only when `set-origin-on-upload` is explicitly enabled.

Before enabling that option:

1. survey the hall reference point;
2. enter its WGS84 latitude, longitude, and altitude;
3. verify the same reference in the flight controller;
4. check axis direction by moving the tag a known distance north and east;
5. check the relationship between UWB `Z=0` and flight-controller Home;
6. upload a short mission while disarmed and inspect it on the controller side.

## Nooploop tag and flight controller

The project specification proposes the following single-tag baseline for ArduPilot:

| Device | Parameter | Baseline |
|---|---|---|
| P-AS tag | Output protocol | `Node_Frame2` |
| P-AS tag | Baud rate | `921600` |
| P-AS tag | Update rate | `25 Hz` in the project specification |
| Flight controller | Beacon type | `BCN_TYPE = 3` |
| Flight controller | Serial protocol | `SERIALx_PROTOCOL = 13` |
| Flight controller | Serial baud parameter | value corresponding to `921600` for the installed firmware |
| Flight controller | Heading source | compass / inertial estimate, not a second tag |

Replace `x` with the verified physical UART. ArduPilot parameter names and enumerations can depend on the firmware build; confirm them on the exact controller rather than copying this table blindly. Also verify electrical compatibility between the selected H743 UART and the P-AS hardware before installing either device in the envelope.

## ELRS Backpack and MAVLink

The ground dashboard can use either:

- UDP input such as `udpin:0.0.0.0:14550`; or
- a serial device such as `/dev/serial/by-id/...`.

Use a stable `/dev/serial/by-id/` path when possible. Configure the ELRS transmitter, receiver, and Backpack for the intended MAVLink mode and verify bidirectional traffic on a propeller-off bench. If the autopilot system ID is known, set `BLIMP_MAVLINK_TARGET_SYSTEM`; source binding is safer than accepting the first heartbeat on a shared network.

## Configuration freeze record

For each physical test, record at least:

- Git commit;
- dashboard command or Compose environment file;
- `anchors.json` checksum or copy;
- flight-controller firmware version and parameter export;
- ELRS and Backpack versions/settings;
- tag protocol, baud rate, ID, and update rate;
- physical anchor survey and UWB origin;
- battery identity and measured voltage;
- airframe mass and lift measurement.
