# Operator procedure

This procedure separates software operation from permission to energise or fly the vehicle. A working dashboard does not make the airframe safe.

## Mandatory preconditions

!!! danger "Propeller-off commissioning first"
    The project has already experienced unexpected motor rotation during arming and an envelope puncture. Perform initial link, receiver, mode, mission, and arm/disarm checks with all propellers removed and the airframe unfilled or kept outside the propulsion bench.

Before opening a flight session:

1. identify a test lead and a pilot with direct access to manual disarm;
2. clear and control the test area;
3. inspect the repaired envelopes and complete a leak check;
4. verify the exact payload mass, available lift, centre of mass, and centre of buoyancy;
5. inspect all motor mounts, propellers, wiring, restraints, and strain relief;
6. verify battery condition and voltage;
7. confirm RC-loss, low-battery, and UWB-loss responses for the installed firmware;
8. freeze the configuration listed in [Configuration reference](configuration.md).

## Start-up order

1. Place and power the UWB anchors; allow the network to stabilise.
2. Connect the P-A console to the ground host.
3. Start `nlink-dump` and confirm frames from the intended tag ID.
4. Start the dashboard and verify anchor coordinates, axes, and tag motion.
5. Power the transmitter and establish the ELRS link.
6. Start or verify the MAVLink bridge.
7. Power the flight controller without propellers during commissioning.
8. Confirm the reported MAVLink system/component, mode, armed state, and battery.
9. Compare UWB movement with controller telemetry before considering any mission operation.

## Read the dashboard

The interface is organised into three functional columns.

### UWB and anchors

The left side shows the configured tag ID, raw position, update frequency, tag voltage, packet age, trail controls, and editable anchor coordinates. Exponential smoothing affects only the display. CSV experiment records retain raw coordinates without the display offset or smoothing.

Anchor edits are written immediately to the configured JSON file. Use **Reload** to discard unsaved table edits; do not use an approximate anchor layout during a flight decision.

### Hall map

The central canvas is a top view. `X` points north and `Y` east under the mission convention. Double-clicking adds a waypoint. Anchor range lines and the tag trail are diagnostic overlays, not independent localisation solutions.

### MAVLink and mission controls

The right side presents connection state, reported telemetry, flight commands, route editing, and experiment recording. Controls remain unavailable until a fresh autopilot heartbeat is present. The UI asks for confirmation before a flight-changing request.

## UWB validation

Before route work:

1. confirm that only the configured tag appears;
2. place it at the marked origin and at two surveyed points;
3. verify axis signs and scale;
4. lift it through known heights and assess Z stability;
5. check packet age and update frequency;
6. compare displayed ranges with tape-measured distances;
7. save a short labelled CSV record for the test log.

Stop if another tag appears as the active vehicle, the position jumps outside the hall, Z is not observable, or frames become stale.

## Mission workflow

### 1. Verify the real target

Open `/api/mavlink/status` or the dashboard status panel. Confirm:

- connected state;
- target system and component IDs;
- expected flight mode and DISARMED state;
- plausible battery and position telemetry;
- a recent heartbeat.

### 2. Build a conservative route

Use a short route well inside the surveyed operating volume. Each point must satisfy the configured altitude, radius, and count limits. Remember that UWB `Z` and mission `Z above Home` are not automatically the same datum.

### 3. Upload while disarmed

Select mission upload and approve the confirmation. The backend converts the route and completes the MAVLink mission transaction. A success message means the controller returned an accepted `MISSION_ACK`; it does not mean the mission has started.

The current software does not download or read back the mission. During bench integration, inspect the received mission through an independent controller-side tool before enabling propulsion.

### 4. Re-upload after any change

Editing or deleting a waypoint invalidates the displayed mission-ready state. A reconnect also invalidates it. Upload the current route again and wait for acceptance.

### 5. Start only under the approved test plan

Mission start emits `MAV_CMD_MISSION_START` and waits for `COMMAND_ACK`. It must be the final action in a staged test, not the first proof that the mixer, EKF, origin, or failsafes are correct.

## Experiment recording

The browser can record the active tag to a local CSV file with:

- elapsed time;
- tag ID;
- raw X, Y, and Z in metres;
- reported UWB voltage;
- an operator note and local timestamp in comment lines.

Recording is held in browser memory until stopped, then downloaded as `blimp_uwb_<timestamp>.csv`. Closing or reloading the page before stopping loses the in-memory record.

## Normal shutdown

1. Stop or complete the mission using the approved controller procedure.
2. DISARM and independently verify that all motors are stopped.
3. Disconnect the flight battery.
4. Stop `nlink-dump` and the dashboard.
5. Power down the UWB network and transmitter.
6. Inspect the envelope, mounts, motors, and wiring.
7. Save the CSV, configuration freeze, observations, and incident notes.

## Troubleshooting

| Symptom | Checks |
|---|---|
| No UWB frames | Confirm device path, permissions, `921600` baud, tag/console mode, cable, and submodule-built parser. Run `nlink-dump` without `--quiet` first. |
| WebSocket connected but no active tag | Confirm `BLIMP_UWB_TAG_ID`; inspect frame type and IDs in CLI output; verify the P-A console sees the intended tag. |
| Position appears but Z is unstable | Survey anchors, introduce vertical separation, verify antenna orientation and line of sight, and repeat a static test. |
| MAVLink remains unconfigured | Supply `--mavlink` or `BLIMP_MAVLINK_ENDPOINT`; replay intentionally leaves it empty. |
| Waiting for heartbeat | Check Backpack routing, UDP bind/port, serial baud, controller telemetry, and expected system/component filters. |
| Command returns 403 | Use the bundled same-origin UI or supply `X-Blimp-Control: dashboard` from an authorised client. |
| Command times out or is rejected | Read the HTTP detail and controller logs; verify mode support, pre-arm checks, target IDs, and radio quality. Do not repeat blindly. |
| Mission cannot start after reconnect | Upload the current route again; mission-ready state is tied to one live backend instance. |
| Anchor changes do not persist | Check that the anchors file or Compose-mounted host file is writable. |
