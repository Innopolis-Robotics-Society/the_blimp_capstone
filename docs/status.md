# Current status and roadmap

The project should be read as a candid engineering proof of concept. Different subsystems reached different levels of evidence, and the labels below are intentionally conservative.

## Evidence summary

| Capability | Status | Evidence and qualification |
|---|---|---|
| Four-motor propulsion | **Bench-tested** | All four motors responded in the Betaflight setup. Motor mapping and thrust allocation are not documented as a reproducible configuration. |
| Manual lighter-than-air flight | **Flight-tested** | The reduced-mass, one-tag configuration achieved remote flight; the report describes it as not yet robust. |
| UWB network and console | **Bench-tested** | Network data were received and parsed; observed noise was approximately ±10 cm. |
| Dual-tag heading bridge | **Bench-verified, retired from baseline** | ESP32 aggregation produced position and yaw; it was removed to recover lift. |
| Native non-ROS parser | **Implemented and tested** | Recorded LinkTrack frames, fragmentation, CLI replay, and UDP output have automated tests. |
| Single-tag dashboard | **Implemented in software** | Live position, anchors, trace, CSV capture, telemetry, controls, and route editing are present. |
| Real MAVLink transaction layer | **Implemented and unit-tested** | Heartbeat binding, source filtering, command retries, ACK handling, mission upload, and reconnect logic are covered by tests. |
| Physical dashboard-to-airship integration | **Requires recommissioning** | The report predates the current single-tag backend and records physical integration as unfinished. |
| Autonomous UWB-guided mission | **Not flight-validated** | Requires a suitable ArduPilot vehicle configuration, EKF validation, and staged safety tests. |
| RC, UWB, and low-battery failsafes | **Not validated** | Explicit roadmap items. |

## Development evolution

### Weeks 0–2 — measurement before design

The team built a helium-cylinder safety stand and a one-motor familiarisation bench, tuned lightweight ePLA-LW printing, measured the first envelope, and selected a double-envelope direction after the single-envelope lift budget proved insufficient.

### Week 3 — UWB integration bench

The UWB pipeline, Raspberry Pi operator station, and early receive/process/transmit software were assembled. A two-tag ESP32 path was explored because one UART could not serve both devices in that experiment. The measured position and heading noise exposed the need for filtering and careful anchor geometry.

### Weeks 4–5 — physical assembly and dashboard MVP

Motor delivery delayed integration. The team used the interval to iterate the gondola and motor mounts and to build a custom dashboard after rejecting a conventional outdoor ground station for local hall waypoint planning.

### Week 6 — lift crisis and first flight

Air ingress into a previously filled envelope reduced available lift. The team removed the magnetic lid, ESP32, and second tag, then achieved remote flight with one tag and Betaflight. This compromise established the current single-tag baseline.

### Week 7 — safety incident

The propellers started unexpectedly during an arming procedure, pierced an envelope, and caused a helium leak. This incident is a hard boundary in the evidence record: the prototype must be repaired and recommissioned before further powered testing.

## Key technical decisions

1. **Double envelope.** Real lift measurements, rather than the initial CAD model, drove the airframe configuration.
2. **AIO flight electronics.** The MicoAir H743 V2 combines flight controller and ESC functions to preserve mass.
3. **Single-tag baseline.** Heading from a second UWB tag was exchanged for a lower airborne mass; heading must now come from the controller's sensors.
4. **Betaflight before autonomy.** Manual flight separated basic propulsion and balance questions from the more difficult custom autonomous stack.
5. **Custom ground dashboard.** Indoor local coordinates and UWB observability are central to this project, whereas conventional ground stations are oriented around global maps.
6. **Complete mission upload.** The ground system sends an accepted mission, not a continuous stream of setpoints, so the planned control loop remains on board.

## Next engineering gates

The order matters. A later gate must not be attempted simply because its software is available.

1. Repair or replace the damaged envelope and repeat leak and lift measurements.
2. Produce a frozen mass table for the exact flight configuration.
3. Document motor numbering, propeller orientation, power wiring, and a propeller-off controller configuration.
4. Validate the direct P-AS-to-H743 serial link and UWB position inside the controller.
5. Select and bench-test the ArduPilot vehicle target and four-motor mixer.
6. Verify RC loss, low-battery, stale-UWB, and operator emergency procedures on a restrained platform.
7. Validate the Backpack MAVLink path and read back an uploaded mission from the controller.
8. Conduct tethered or otherwise contained position-control tests.
9. Only then attempt a short autonomous mission in a cleared indoor area.

## Information still required for a reproducible airframe

- final CAD revision and print settings;
- final all-up mass and component masses;
- motor numbering, direction, propeller assignment, and thrust vectors;
- battery capacity, connector, C-rating, and charging procedure;
- definitive ELRS receiver model and configuration;
- flight-controller pin map and complete firmware configuration export;
- measured UWB anchor locations and calibration record;
- tested failsafe thresholds and responses.

Until these artefacts are recorded, this handbook is authoritative for the software and for the reported engineering history, but it is not a complete manufacturing package.
