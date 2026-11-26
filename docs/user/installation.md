# Installation

## Requirements

- Docker Engine 20.10+ to run the published image. Engine 25.0+ runs the image's 5-second start
  probe; older engines use the 30-second interval.
- Building from source needs BuildKit, the default in current Docker releases. The legacy builder
  (`DOCKER_BUILDKIT=0`) does not accept the Dockerfile's `RUN --mount`.
- Access to `/var/run/docker.sock` (or your platform's equivalent)
- Ports `3131` (web UI + API) and `9090` (Prometheus metrics) available on the host, or
  remapped to ports of your choosing

## Option A: Docker Compose (recommended)

```yaml
services:
  autoheal:
    image: tommye123/docker-autoheal:latest  # or ghcr.io/tommye123/docker-autoheal:latest
    container_name: docker-autoheal
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./data:/data              # persists config, events, and quarantine state
    ports:
      - "3131:3131"                # Web UI + API
      - "9090:9090"                # Prometheus metrics
    labels:
      - "autoheal=false"           # keeps the monitor unselected under the default label-based
                                    # selection; see docs/user/labels.md if you enable include_all
```

The image defines its own health check, so the Compose file does not need one.

```bash
docker compose up -d
```

## Option B: `docker run`

```bash
docker run -d \
  --name docker-autoheal \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v ./data:/data \
  -p 3131:3131 \
  -p 9090:9090 \
  tommye123/docker-autoheal:latest
```

Images are also published to GitHub Container Registry as
`ghcr.io/tommye123/docker-autoheal:latest`.

## Verify it's running

```bash
# Health check
curl http://localhost:3131/health

# Logs
docker logs -f docker-autoheal
```

Open `http://localhost:3131` — you should see the dashboard with a total container count
and service status.

## Persistent data

Mounting `./data:/data` persists:

- `config.json` — your monitoring, restart, alerting, and notification configuration
- `events.json` — the auto-heal event log
- `quarantine.json` — currently quarantined containers
- `maintenance.json` — maintenance mode state
- `logs/autoheal.log` — application logs

If `/data` isn't writable, the service falls back to `./data` relative to its working
directory inside the container — but without a volume mount, that state is lost when the
container is removed.

## Shutdown

`docker stop` sends `SIGTERM`, then `SIGKILL` once the stop timeout runs out (10 seconds by
default). Docker Autoheal shuts down in two steps, one after the other:

1. The web server stops accepting connections and gives requests already in progress up to
   3 seconds to finish, then cancels the rest.
2. The service stops the Uptime Kuma monitor, then stops the monitoring and delivers queued
   notifications side by side. Each of those two has a 5 second timeout. The 5 second delivery
   window starts as soon as the stop begins, so a notification already being sent can be cut off
   earlier than if the two ran one after the other.

That adds up to about 8 seconds, as an estimate, which normally fits in Docker's default once
startup has finished. If the stop arrives while the service is still starting, for example while
it waits on an unreachable Uptime Kuma server, the service first gives startup up to 5 more
seconds, so the total can reach about 13 seconds and exceed the default (tracked in
[#342](https://github.com/TommyE123/docker-autoheal/issues/342)). The log line
`Docker Autoheal stopped` marks the end of the service's cleanup, not proof that it was clean:
check the warnings logged before it for any step that failed. Notifications still queued when
the 5 seconds run out are dropped, with a warning in the log.

The deadline is not guaranteed. Some work runs in background worker threads, for example a
manual container restart from the web UI or a Docker call made by a monitoring check. Cancelling
the request or the monitoring does not stop that thread, and the Python runtime waits for those
threads before the process exits, so the process can still outlive the stop timeout and be
killed by Docker. This is a known limitation of the current shutdown, tracked in
[#343](https://github.com/TommyE123/docker-autoheal/issues/343).

To give it more time, raise the stop timeout with `stop_grace_period` in Compose (see the
commented example in `docker-compose.yml`) or `docker stop --time <seconds>`.

## Try it with a sample container

```bash
docker run -d \
  --name test-nginx \
  --label autoheal=true \
  -p 8081:80 \
  nginx:alpine

# Kill it and watch Docker Autoheal restart it
docker kill test-nginx
```

Check the **Events** tab in the web UI, or:

```bash
curl http://localhost:3131/api/events | jq
```

You should see a `restart` event for `test-nginx`.

## Building the image yourself

The published image (`tommye123/docker-autoheal`, also mirrored to
`ghcr.io/tommye123/docker-autoheal`) is a multi-stage build: it builds the React frontend
with Node in the first stage, then copies the build output into a Python image (the
version is whatever the `Dockerfile`'s `FROM python:X.Y-slim` line currently pins). To
build it locally:

```bash
git clone https://github.com/TommyE123/docker-autoheal.git
cd docker-autoheal
docker compose up --build -d
```

This builds the image from your checkout (the `build:` key in `docker-compose.yml`) and
starts it. To build the image without starting it, run `docker build -t docker-autoheal .`.

See [Development Setup](../developer/development-setup.md) if you want to run the
backend and frontend outside Docker.

## Next steps

- [Configuration](configuration.md) — tune monitoring interval, restart policy, and
  filters
- [Labels](labels.md) — how to enable auto-healing on your own containers
- [Usage](usage.md) — a tour of the web UI
