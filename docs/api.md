# Dashboard API

The FastAPI service exposes the bundled operator interface, a small configuration and telemetry API, flight-changing actions, and one UWB WebSocket. Interactive OpenAPI documentation is available at `/docs` when the service is running.

!!! danger
    The API can command a real connected autopilot. Use examples only on an isolated propeller-off bench unless a formal flight test has authorised the operation.

## Access model

Read endpoints are unauthenticated. Flight-changing HTTP requests require:

```http
X-Blimp-Control: dashboard
```

The header prevents ordinary cross-origin HTML forms from issuing commands, but it is public and fixed. It is not a password, an operator identity, or an authorisation system. The service also has no built-in TLS.

## Read and configuration endpoints

### `GET /api/config`

Returns the active UWB tag, MAVLink configuration state, origin, and route limits.

```json
{
  "uwb_tag_id": 1,
  "mavlink_configured": true,
  "origin": {"lat": 55.7522, "lon": 48.7446, "alt": 120.0},
  "set_origin_on_upload": false,
  "mission_limits": {
    "min_altitude": 0.2,
    "max_altitude": 10.0,
    "max_waypoint_distance": 100.0,
    "max_waypoints": 100
  }
}
```

### `GET /api/anchors`

Returns the current display and range-comparison geometry.

### `PUT /api/anchors`

Validates and replaces the configured anchors file.

```json
{
  "anchors": [
    {"id": 0, "pos": [0.0, 0.0, 1.3]},
    {"id": 1, "pos": [6.0, 0.0, 2.5]}
  ]
}
```

This endpoint does **not** configure the physical UWB network or the flight controller. It currently does not require the control header, so the service must remain on a trusted network.

### `GET /api/mavlink/status`

Returns connection state, selected target, heartbeat age, mission readiness, and the latest processed telemetry.

Important fields are:

| Field | Meaning |
|---|---|
| `configured` | A non-empty endpoint was supplied |
| `connecting` | The reconnect loop is waiting for a real heartbeat |
| `connected` | The current backend has a fresh target heartbeat |
| `target_system`, `target_component` | MAVLink source bound to the connection |
| `last_heartbeat_age_s` | Age of the latest accepted target heartbeat |
| `mission_ready` | A mission was accepted on this exact backend instance |
| `mode`, `armed` | State decoded from heartbeat telemetry |
| `battery` | Values decoded from `SYS_STATUS`, where available |
| `position` | Values decoded from `GLOBAL_POSITION_INT` |
| `local_position` | Values decoded from `LOCAL_POSITION_NED` |

## Flight actions

All examples below require the fixed control header and a fresh real autopilot heartbeat.

### ARM and DISARM

```bash
curl -X POST \
  -H 'X-Blimp-Control: dashboard' \
  http://localhost:8000/action/disarm
```

Replace the final path with `/action/arm` only in an authorised, propeller-off test. Success is returned after an accepted `COMMAND_ACK`.

### Set flight mode

`POST /action/mode`

```json
{"mode": "AUTO"}
```

The requested name must be present in the mode mapping advertised through `pymavlink` for the connected autopilot.

### Take-off command

`POST /action/takeoff`

```json
{"alt": 1.2}
```

The altitude must be inside the configured mission limits. This endpoint is implemented but is not exposed as a button in the bundled UI.

### Upload route

`POST /upload_route`

```json
[
  {"x": 0.5, "y": 0.5, "z": 1.2},
  {"x": 2.0, "y": 0.5, "z": 1.2}
]
```

The request validates the route, optionally sets and verifies origin, performs a complete MAVLink mission exchange, and returns only after `MISSION_ACK` accepts the upload. It does not start the mission.

The first dashboard point is transmitted as sequence `0`; the software does not silently insert or duplicate a Home item. Verify the connected controller's sequence-zero behaviour during mission readback on the bench.

### Start accepted mission

`POST /action/mission/start`

The server accepts this call only if the current backend instance accepted an upload. A link reconnect invalidates readiness and requires another upload.

## WebSocket UWB stream

Connect to `ws://HOST:8000/ws` or `wss://.../ws` behind a TLS reverse proxy. Every outgoing text message is one filtered JSON frame from the selected tag.

The server ignores inbound WebSocket text; inbound messages are used only to detect disconnects. There is no replay request, subscription filter, acknowledgement, or delivery guarantee at this layer.

Example `anchorframe0` shape after filtering:

```json
{
  "frame_type": "anchorframe0",
  "recv_time": 1784700000.0,
  "nodes": [
    {
      "id": 1,
      "role": 2,
      "pos_3d": [1.25, 0.80, 1.10]
    }
  ]
}
```

Fields beyond `frame_type` and `recv_time` follow the decoded Nooploop frame and can vary by frame type.

## Error semantics

| HTTP status | Meaning |
|---:|---|
| `403` | Missing control header |
| `409` | Autopilot rejected the operation, or no mission is ready on this connection |
| `422` | Invalid mode, route, altitude, origin, or other request value |
| `502` | Unexpected MAVLink operation failure |
| `503` | MAVLink disabled, connecting, unavailable, or stale |
| `504` | Timed out waiting for the required MAVLink acknowledgement |

Do not convert these errors into automatic retries at the browser or proxy layer. A repeated ARM, mode, or mission request can have physical consequences; the operator must assess the vehicle and controller state first.

## Deployment guidance

- Bind the service only to the required interface when practical.
- Use an isolated test LAN.
- Restrict UDP `9999` to the trusted parser host; unauthenticated datagrams can influence the display.
- Add authenticated TLS at a reverse proxy before any wider network exposure.
- Restrict write access to the anchors file.
- Treat API logs and controller logs as part of the test record.
