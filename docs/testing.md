# Test and safety plan

Verification is staged from deterministic software checks to restrained hardware tests. Passing one stage authorises investigation of the next stage; it does not prove the next stage safe.

## 1. Automated software tests

Create a fresh environment and install both test extras:

```bash
git submodule update --init --recursive
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e 'uwb/nlink_py[dev]' -e 'uwb/dashboard[test]'
python -m pytest uwb/nlink_py/tests uwb/dashboard/tests
```

The repository tests exercise:

- vendor-derived golden frames for supported NLink messages;
- fragmented, concatenated, and garbage-prefixed streams;
- CLI replay and UDP output;
- single-tag filtering and route conversion;
- input limits before any MAVLink send;
- command packing, retries, source/target filtering, acceptance, and rejection;
- mission request variants, packet loss, and final mission acceptance;
- reconnect behaviour and invalidation of stale mission readiness;
- presence of the browser control header.

They use recordings and fake MAVLink connections. They do not validate an actual tag, serial adapter, ELRS link, controller firmware, browser rendering, motor mixer, or autonomous vehicle.

## 2. Documentation build

```bash
python -m pip install -r docs/requirements.txt
python -m mkdocs build --strict
```

The same strict build runs for documentation pull requests. Deployment runs only after a successful build on `main` or a manual workflow dispatch.

## 3. Offline replay acceptance

| Check | Acceptance criterion |
|---|---|
| Parser starts | Recorded stream is decoded without an exception |
| UDP relay | Dashboard receives frames on port `9999` |
| Tag filter | Only the configured ID reaches the browser |
| Map | Position, trail, and anchors render in the expected hall frame |
| CSV | Stopping a recording downloads raw X/Y/Z rows with a note |
| MAVLink isolation | Replay reports MAVLink disabled and no flight control is available |

## 4. UWB hardware bench

Keep the flight battery disconnected.

1. Survey and mark the UWB origin and anchor coordinates.
2. Test each anchor and the P-A console independently.
3. Place the tag at several known static points and heights.
4. Record position bias, spread, update rate, stale periods, ranges, and voltage.
5. Move along known X and Y directions to verify axis signs.
6. Introduce the final envelope and electronics to identify attenuation or reflections.
7. Repeat after every anchor movement.

The report observed approximately ±10 cm position noise in an earlier bench. Use new measurements for acceptance thresholds; do not promote that observation to a guaranteed specification.

## 5. Flight-controller integration bench

!!! danger "Remove all propellers"
    Perform this stage on a restrained bench with propellers removed. The recorded arming incident demonstrates that software state alone is insufficient protection.

Required checks:

1. power and polarity inspection;
2. controller firmware identity and full parameter export;
3. ELRS channel map, arm switch, manual disarm, and RC-loss response;
4. one motor at a time: number, direction, output, and safe idle;
5. direct P-AS UART communication and update rate;
6. on-controller UWB position, axes, origin, and stale-data behaviour;
7. MAVLink target IDs, heartbeat, mode, battery, and position telemetry;
8. DISARM command before any ARM test;
9. ARM followed by immediate DISARM with no propellers;
10. mode-command acceptance and rejection paths;
11. mission upload followed by independent mission readback;
12. controller response to Backpack loss and dashboard shutdown.

Stop on unexpected output, motor activity, stale position accepted as valid, wrong target ID, origin change, or any command whose controller-side result cannot be explained.

## 6. Propulsion and airframe bench

This stage still does not permit free flight.

- Use a non-buoyant or securely restrained configuration where practical.
- Fit propellers only after verified motor order and direction.
- Keep envelope material completely outside the propeller swept volumes.
- Measure current, voltage sag, temperature, vibration, thrust direction, and command response.
- Verify the emergency power-disconnect method.
- Repeat arm/disarm and RC-loss checks under the final power system.
- Inspect mounts, fasteners, printed parts, wires, and propellers after every run.

## 7. Lift, balance, and leak test

Record one configuration-specific budget:

| Measurement | Required record |
|---|---|
| Envelope condition | revision, damage/repair, fill date, leak result |
| Environment | temperature and relevant test conditions |
| Gross lift | measured method and value |
| Airframe payload | each major component and total mass |
| Net buoyancy | value for the exact assembled vehicle |
| Balance | centre of mass relative to centre of buoyancy |
| Clearance | minimum envelope/strap/wire distance from each propeller disc |

The historical values of 68 g, 120 g, and 70 g came from different conditions. The new test must supersede them for flight decisions.

## 8. Contained control tests

Progress conservatively:

1. manual motor response with the vehicle restrained;
2. low-power manual translation and yaw checks;
3. RC-loss and low-battery behaviour;
4. UWB-loss and recovery behaviour;
5. heading and position-estimator consistency;
6. tethered or otherwise contained position control;
7. mission upload and readback without start;
8. one short mission at low energy in a cleared volume.

Define quantitative pass/fail criteria before each test: maximum position error, maximum stale duration, acceptable attitude excursion, minimum link quality, battery abort threshold, and emergency actions.

## Stop conditions

Immediately disarm and remove power for any of the following:

- uncommanded motor motion;
- damaged, loosening, or hot propulsion hardware;
- envelope contact with a propeller or mount;
- helium leak or loss of required buoyancy;
- incorrect tag, origin, axis, or altitude datum;
- stale or implausible UWB accepted by the controller;
- loss of pilot control or ambiguous arm state;
- unexpected mode transition;
- low or rapidly sagging battery;
- MAVLink command or mission addressed to an unexpected system;
- any person entering the controlled test volume.

## Evidence package

Each test should produce:

- date, participants, location, and objective;
- exact Git commit and configuration freeze;
- preconditions and pass/fail criteria;
- photographs of the as-tested setup;
- controller logs and parameter export;
- dashboard/UWB CSV where relevant;
- observed result, deviations, and incident record;
- explicit decision: repeat, modify, advance, or stop.

This discipline is particularly important for a mass-constrained physical prototype: small undocumented changes can alter lift, balance, radio quality, and propeller clearance simultaneously.
