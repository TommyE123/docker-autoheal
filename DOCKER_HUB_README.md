# Docker Auto-Heal Service

A container monitoring and auto-healing service with a web dashboard, REST API, and
Prometheus metrics. Docker Auto-Heal watches your containers and restarts the ones that
fail or go unhealthy, with cooldowns, exponential backoff, and automatic quarantine for
containers that keep failing.

Full documentation, including source, is at
[github.com/TommyE123/docker-autoheal](https://github.com/TommyE123/docker-autoheal).

## Quick Start

```bash
docker run -d \
  --name docker-autoheal \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v ./data:/data \
  -p 3131:3131 \
  -p 9090:9090 \
  --restart unless-stopped \
  swaya1125/docker-autoheal:latest
```

**Web UI:** <http://localhost:3131>

## What's included

- Python 3.11 backend (FastAPI) + React 18 web UI (built with Vite)
- Automated health monitoring: Docker-native health checks, plus optional HTTP/TCP/exec
  custom checks
- Smart restart logic: cooldowns, exponential backoff, restart thresholds, automatic
  quarantine and auto-unquarantine
- Prometheus metrics on a dedicated port
- Notifications to Discord, Slack, Telegram, ntfy, Gotify, Pushover, or a generic webhook
- All configuration and state stored in `/data`, editable through the web UI, the REST
  API, or `config.json` directly — **there are no environment-variable settings**

## Enabling auto-healing

```yaml
services:
  autoheal:
    image: swaya1125/docker-autoheal:latest
    container_name: docker-autoheal
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./data:/data
    ports:
      - "3131:3131"   # Web UI
      - "9090:9090"   # Prometheus metrics
    labels:
      - "autoheal=false"   # exclude Auto-Heal itself from monitoring

  webapp:
    image: nginx:latest
    labels:
      autoheal: "true"     # monitor this container
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost"]
      interval: 30s
      timeout: 10s
      retries: 3
```

```bash
docker compose up -d
```

Any container labelled `autoheal=true` is picked up automatically — both containers
already running when Auto-Heal starts, and new ones as they start.

## Configuration

All settings are managed through the web UI at `http://localhost:3131` (Configuration
tab) or the `/api/config*` REST endpoints — see the "Configuration" section of the
[full documentation](https://github.com/TommyE123/docker-autoheal/blob/main/docs/user/configuration.md)
for the complete field reference.

Configuration is automatically persisted to `/data/config.json`. Export/import as JSON is
available from the web UI.

## Monitoring & Metrics

```bash
# Prometheus metrics
curl http://localhost:9090/metrics

# Service health
curl http://localhost:3131/health

# Interactive API docs (Swagger UI)
http://localhost:3131/docs
```

```bash
docker logs -f docker-autoheal
```

## Requirements

- Docker Engine 20.10+
- Docker socket access (`/var/run/docker.sock`)

## Troubleshooting

**Container not being monitored?**

1. Check it has the `autoheal=true` label (unless "monitor all containers" is enabled).
2. Check it isn't in the excluded list (Configuration tab).
3. Check logs: `docker logs docker-autoheal` (set log level to `DEBUG` from the
   Configuration tab for more detail).

**Won't start?** Verify the Docker socket is accessible and ports 3131/9090 are free.

**Container quarantined?** It exceeded the configured restart threshold. View it in the
Web UI, fix the underlying issue, and it will auto-unquarantine once healthy — or
unquarantine it manually from the UI or `POST /api/containers/{id}/unquarantine`.

Full troubleshooting guide:
[docs/user/troubleshooting.md](https://github.com/TommyE123/docker-autoheal/blob/main/docs/user/troubleshooting.md)

## Security

This service requires read-only Docker socket access, which is a significant privilege.
Recommended for production:

- Mount the socket read-only (`:ro`, as shown above)
- Put the web UI behind a reverse proxy with authentication and TLS if exposing it beyond
  a trusted network — Auto-Heal does not implement its own authentication
- Restrict access to the Prometheus metrics port similarly
- Keep regular configuration backups (export from the UI)

## License

MIT — see the [LICENSE](https://github.com/TommyE123/docker-autoheal/blob/main/LICENSE) file.
