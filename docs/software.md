# Software

The current software baseline is a single-tag, non-ROS UWB pipeline and a browser-based ground station connected to a real MAVLink endpoint. It contains no simulated vehicle in the live path.

## Repository layout

```text
uwb/
├── Dockerfile                 combined parser + dashboard image
├── docker-compose.yml         live and UWB-only replay profiles
├── dashboard/
│   ├── anchors.json           measured hall anchor configuration
│   ├── src/blimp_dashboard/
│   │   ├── backend.py         real MAVLink transaction layer
│   │   ├── server.py          FastAPI, UDP relay and HTTP API
│   │   └── static/            browser dashboard
│   └── tests/                 API and MAVLink behaviour tests
├── nlink_py/
│   ├── src/cpp/               pybind11 bindings to Nooploop parsers
│   ├── src/nlink_py/          serial/replay readers, UDP publisher, CLI
│   └── tests/                 golden frames and stream-fragmentation tests
├── extern/                    required Nooploop git submodules
└── recordings/uwb_live.bin    recorded UWB stream for replay
```

The root `firmware/` directory contains earlier parser and dual-tag experiments. They are useful engineering history but are not the production route for the current one-tag dashboard.

## NLink parser package

`nlink-py` wraps the original Nooploop `protocol_extracter` and `nlink_unpack` code in a native Python extension. This keeps byte framing, checksums, packed structures, and SI-unit conversion aligned with the vendor implementation while removing the ROS dependency.

The package provides:

- serial input through `pyserial`;
- raw binary recording;
- deterministic file replay;
- JSON Lines output;
- one-JSON-datagram-per-frame UDP publication;
- a Python callback API through `LinkTrackExtractor`.

The native layer supports `anchorframe0`, `tagframe0`, and `nodeframe0` through `nodeframe6`. The browser currently renders the tag content used by `anchorframe0` and `tagframe0`; parser support for a frame does not imply that the UI visualises every field in that frame.

### Output contract

Each decoded dictionary retains the vendor-derived fields and gains:

| Field | Meaning |
|---|---|
| `frame_type` | Normalised parser frame name |
| `recv_time` | Unix timestamp assigned when the CLI receives the frame |

Binary payloads in data-transmission frames are represented as hexadecimal strings. `nlink-dump` sends each frame as a separate UDP datagram; it does not establish delivery, ordering, or retransmission guarantees.

## Dashboard service

`blimp-dashboard` is a FastAPI application with three responsibilities.

### 1. UWB relay

The server listens for JSON datagrams on UDP `9999`, validates their basic shape, removes tags other than the configured ID, and forwards accepted frames to connected WebSocket clients. Anchor locations come from a separate JSON file so the browser can compare measured ranges with the surveyed hall geometry.

### 2. Operator interface

The bundled HTML/JavaScript interface provides:

- WebSocket, UWB, and MAVLink connection indicators;
- raw X/Y/Z, tag voltage, update rate, and packet age;
- optional display-only exponential smoothing and a finite trail;
- editable anchor coordinates and range overlays;
- a top-down local map and double-click waypoint entry;
- route distance and estimated duration display;
- MAVLink ARM, DISARM, flight-mode, route-upload, and mission-start controls;
- client-side CSV recording of the raw active tag data.

The application UI is currently written in Russian; this English handbook describes its behaviour and operating sequence.

### 3. Real MAVLink backend

The backend uses `pymavlink` and binds itself to the first accepted real autopilot heartbeat, optionally constrained by expected system and component IDs. It processes:

- `HEARTBEAT` for mode, armed state, and link freshness;
- `LOCAL_POSITION_NED` for local telemetry;
- `GLOBAL_POSITION_INT` for global and relative altitude;
- `SYS_STATUS` for voltage, current, and remaining battery percentage.

Flight-changing operations are serialised so ARM, mode changes, origin changes, and mission transactions cannot interleave. Command success requires a matching accepted `COMMAND_ACK`. Mission upload follows the request/response transaction and requires `MISSION_ACK(MAV_MISSION_ACCEPTED)` after every requested sequence has been served.

## Mission processing

The dashboard accepts local waypoints as `{x, y, z}`:

1. values must be finite;
2. count, altitude, and horizontal radius limits are checked;
3. `X` is converted to northing and `Y` to easting around the configured WGS84 origin;
4. `Z` remains relative to flight-controller Home;
5. the complete mission is uploaded but not automatically started;
6. mission start is enabled only for a mission acknowledged on the current backend connection.

If the heartbeat becomes stale and the backend reconnects, the prior mission-ready marker is invalidated. The operator must upload the displayed route again before it can be started.

## Docker profiles

The single image contains both Python packages.

| Profile | Services | Purpose |
|---|---|---|
| `live` | `dashboard`, `nlink` | Real P-A console over USB plus a real MAVLink endpoint |
| `replay` | `dashboard-replay`, `replay` | Recorded UWB visualisation with MAVLink deliberately disabled |

The replay profile is an offline parser and UI check. It does not exercise flight control, emulate an autopilot, or make an autonomous-flight claim.

## Safety and security boundaries

- MAVLink control is disabled when no endpoint is configured.
- The server waits for a heartbeat instead of treating an open serial or UDP socket as a connected vehicle.
- Target-system filtering prevents an acknowledgement from another MAVLink system from completing a transaction.
- Flight-changing HTTP calls require `X-Blimp-Control: dashboard` and no CORS middleware is enabled.
- The fixed header is not authentication. Run the service only on a trusted isolated network, or place authenticated TLS access in front of it.
- Anchor editing is not protected by the control header; network access to the dashboard therefore also grants access to its local configuration file.
- The backend does not configure flight-controller telemetry rates or failsafes. Those remain controller-side responsibilities.

## Automated verification

The test suites cover:

- golden decoding for supported LinkTrack frames;
- arbitrarily fragmented and concatenated serial streams;
- CLI replay and UDP output;
- exact one-tag filtering;
- local-to-global altitude semantics;
- route limits before MAVLink transmission;
- control-header enforcement;
- real-endpoint gating and reconnect behaviour;
- command packing, retries, source filtering, acceptance, and rejection;
- both mission request variants and accepted mission completion.

These repository-level tests do not replace validation with the physical UWB network, radio link, flight controller, and restrained airframe.

## Known software limitations

1. There is no Guided setpoint API, trajectory planner, mission download, or mission readback implementation.
2. The UI does not render every frame type supported by the native parser.
3. CSV experiment capture exists only in the browser session; there is no server-side test database.
4. The checked-in anchor geometry is coplanar and must be replaced with a surveyed installation.
5. The dashboard does not authenticate operators or encrypt traffic.
6. Mission conversion uses a local tangent approximation suitable for hall-scale offsets, not long-range navigation.
7. A successful automated test is not evidence that the physical controller, Backpack, receiver, mixer, or airframe accepted the same operation.
8. The upstream native unpackers use global result objects; do not feed multiple extractors concurrently from different threads in one process.
9. A standalone live `nlink-dump` process does not reconnect a removed serial device. Compose mitigates process exit with `restart: unless-stopped`, but the operator must still verify recovered data.
