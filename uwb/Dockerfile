# Builds both packages: nlink_py (native NLink parser + nlink-dump)
# and the single-tag FastAPI ground station for a real MAVLink autopilot.
# There is no SITL process or 3D simulator in this image.
# Build context must be uwb/ (needs the extern/ submodules checked out).
FROM python:3.11-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY extern/ extern/
COPY nlink_py/ nlink_py/
COPY dashboard/ dashboard/
RUN pip wheel --no-cache-dir --wheel-dir /wheels ./nlink_py ./dashboard

FROM python:3.11-slim

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

EXPOSE 8000 9999/udp
CMD ["blimp-dashboard"]
