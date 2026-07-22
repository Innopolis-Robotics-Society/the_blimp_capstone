# Installation and launch

This guide starts with an offline replay and progresses to the real P-A console and real MAVLink endpoint. Run the replay first: it validates the local build without energising the airframe.

## Prerequisites

For a native installation:

- Linux or Raspberry Pi OS is the intended host environment;
- Python 3.10 or newer for the combined parser and dashboard;
- Git with submodule support;
- CMake 3.18 or newer and a C/C++ compiler;
- access to the UWB serial device for live operation.

For the container path, use Docker Engine with the Compose plugin. Host USB-device mapping is Linux-oriented. For the live profile, the host must be connected to the Backpack Wi-Fi network used by the controller. That network may not provide internet access, so Docker images should be built or pulled in advance on a network with internet access.

## Obtain the complete source tree

```bash
git clone --recurse-submodules \
  https://github.com/Innopolis-Robotics-Society/the_blimp_capstone.git
cd the_blimp_capstone
```

For an existing checkout:

```bash
git submodule update --init --recursive
```

Both Nooploop submodules are required to compile `nlink-py`. Empty `uwb/extern/` directories indicate an incomplete checkout.

## Native installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e uwb/nlink_py -e uwb/dashboard
```

Confirm both commands are available:

```bash
nlink-dump --help
blimp-dashboard --help
```

## First launch: UWB replay only

Open two terminals in the repository root with the virtual environment active.

Terminal 1 — dashboard with MAVLink explicitly disabled:

```bash
BLIMP_MAVLINK_ENDPOINT= blimp-dashboard \
  --anchors uwb/dashboard/anchors.json \
  --uwb-tag-id 1
```

Terminal 2 — recorded NLink input:

```bash
nlink-dump \
  --replay uwb/recordings/uwb_live.bin \
  --replay-delay 0.05 \
  --loop \
  --udp 127.0.0.1:9999 \
  --quiet
```

Open <http://localhost:8000>. The WebSocket and UWB indicators should become active. MAVLink must remain disabled. This mode proves parsing and display only.

## Live UWB plus MAVLink over UDP

Configure the Backpack to deliver MAVLink to UDP port `14550` on the ground host. Then start the dashboard:

```bash
blimp-dashboard \
  --http-port 8000 \
  --udp-port 9999 \
  --anchors uwb/dashboard/anchors.json \
  --uwb-tag-id 1 \
  --mavlink udpin:0.0.0.0:14550 \
  --origin-lat 55.7522 \
  --origin-lon 48.7446 \
  --origin-alt 120.0
```

In a second terminal, start the P-A console reader:

```bash
nlink-dump \
  --port /dev/ttyCH343USB0 \
  --baud 921600 \
  --udp 127.0.0.1:9999 \
  --quiet
```

Replace device paths and origin values with verified installation data. Do not use the sample coordinates for flight.

## MAVLink over serial

```bash
blimp-dashboard \
  --anchors uwb/dashboard/anchors.json \
  --uwb-tag-id 1 \
  --mavlink /dev/serial/by-id/REPLACE_WITH_REAL_DEVICE \
  --mavlink-baud 115200 \
  --origin-lat REPLACE_WITH_SURVEYED_LAT \
  --origin-lon REPLACE_WITH_SURVEYED_LON \
  --origin-alt REPLACE_WITH_SURVEYED_ALT
```

Check `/api/mavlink/status` and confirm the target system/component IDs before using any control endpoint.

## Docker Compose

### Replay profile

```bash
cd uwb
docker compose --profile replay up --build
```

The replay profile forces an empty MAVLink endpoint and does not require Backpack Wi-Fi or a live flight controller connection.

### Live profile

This profile is intended to run while the host is connected to the Backpack Wi-Fi network. If the images are not already cached locally, `docker compose --build` will try to reach Docker Hub and may fail on that network. Build the images once on a network with internet access, then run the live profile without `--build` on the Backpack Wi-Fi.

One-time prebuild on an internet-connected network:

```bash
cd uwb
docker compose --profile live build
```

Live launch on the Backpack Wi-Fi network:

```bash
cd uwb
UWB_PORT=/dev/ttyCH343USB0 \
BLIMP_MAVLINK_ENDPOINT=udpin:0.0.0.0:14550 \
docker compose --profile live up
```

For serial MAVLink inside the container:

```bash
cd uwb
MAVLINK_SERIAL_DEVICE=/dev/serial/by-id/REPLACE_WITH_REAL_DEVICE \
BLIMP_MAVLINK_ENDPOINT=/dev/mavlink \
BLIMP_MAVLINK_BAUD=115200 \
docker compose --profile live up --build
```

## Basic health checks

```bash
curl http://localhost:8000/api/config
curl http://localhost:8000/api/anchors
curl http://localhost:8000/api/mavlink/status
```

Expected states:

- replay: UWB frames arrive; `mavlink_configured` is false;
- live before FC power: dashboard remains available and reports waiting/reconnect state;
- live after FC power: `connected` becomes true only after a real heartbeat;
- `mission_ready` remains false until the current connection accepts a route.

## Stop the system

For native processes, press `Ctrl+C` in the parser and dashboard terminals. For Compose:

```bash
docker compose --profile live down
```

Stopping software is not an emergency motor stop. The flight battery and pilot safety procedure remain authoritative.
