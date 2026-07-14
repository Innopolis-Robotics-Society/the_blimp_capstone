# blimp-dashboard

FastAPI dashboard for one Nooploop UWB tag and a real MAVLink autopilot.  UWB
JSON arrives from `nlink-dump` on UDP; mission and flight commands are sent only
after an autopilot heartbeat is present and must receive protocol-level
acknowledgements.

MAVLink control is disabled by default.  A real endpoint must be selected
explicitly, for example:

```bash
blimp-dashboard \
  --uwb-tag-id 1 \
  --mavlink udpin:0.0.0.0:14550 \
  --anchors anchors.json
```

The equivalent environment variables are `BLIMP_UWB_TAG_ID` and
`BLIMP_MAVLINK_ENDPOINT`.  The origin, safety limits, timeouts, expected target
IDs and serial baud rate are also configurable; see `blimp-dashboard --help`.
Changing the autopilot origin during route upload is opt-in via
`--set-origin-on-upload`.

Mission sequence numbers are sent exactly as the dashboard route (`seq=0` is
the first selected point).  ArduPilot's special handling of the Home/`seq=0`
slot must be checked by reading the mission back from the real FC during the
propeller-off bench test; the dashboard does not silently add or duplicate a
waypoint.

Flight-changing HTTP requests require the same-origin header
`X-Blimp-Control: dashboard`; the bundled UI adds it automatically.  This is a
CSRF barrier, not authentication.  Run the dashboard only on a trusted LAN or
put authenticated TLS access in front of it before exposing it to any wider
network.
