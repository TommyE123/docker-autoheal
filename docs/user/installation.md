# Installation

## Requirements

- Docker Engine 20.10+
- Access to `/var/run/docker.sock` (or your platform's equivalent)
- Ports `3131` (web UI + API) and `9090` (Prometheus metrics) available on the host, or
  remapped to ports of your choosing

## Option A: Docker Compose (recommended)

```yaml
services:
  autoheal:
    image: swaya1125/docker-autoheal:latest
    container_name: docker-autoheal
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./data:/data              # persists config, events, and quarantine state
    ports:
      - "3131:3131"                # Web UI + API
      - "9090:9090"                # Prometheus metrics
    labels:
      - "autoheal=false"           # exclude the monitor from monitoring itself
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3131/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

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
  swaya1125/docker-autoheal:latest
```

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

## Try it with a sample container

```bash
docker run -d \
  --name test-nginx \
  --label autoheal=true \
  -p 8081:80 \
  nginx:alpine

# Kill it and watch Auto-Heal restart it
docker kill test-nginx
```

Check the **Events** tab in the web UI, or:

```bash
curl http://localhost:3131/api/events | jq
```

You should see a `restart` event for `test-nginx`.

## Building the image yourself

The published image (`swaya1125/docker-autoheal`) is a multi-stage build: it builds the
React frontend with Node 18 in the first stage, then copies the build output into a
Python 3.11 image. To build it locally:

```bash
git clone https://github.com/TommyE123/docker-autoheal.git
cd docker-autoheal
docker build -t docker-autoheal .
```

See [Development Setup](../developer/development-setup.md) if you want to run the
backend and frontend outside Docker.

## Next steps

- [Configuration](configuration.md) — tune monitoring interval, restart policy, and
  filters
- [Labels](labels.md) — how to enable auto-healing on your own containers
- [Usage](usage.md) — a tour of the web UI
