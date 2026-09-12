# Docker Auto-Heal Service

[![Unit Tests](https://github.com/TommyE123/docker-autoheal/actions/workflows/tests.yml/badge.svg)](https://github.com/TommyE123/docker-autoheal/actions/workflows/tests.yml)
[![Docker Pulls](https://img.shields.io/docker/pulls/swaya1125/docker-autoheal)](https://hub.docker.com/r/swaya1125/docker-autoheal)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Docker Auto-Heal watches your Docker containers and restarts the ones that fail or go
unhealthy, so you don't have to. It runs as a single container with a web dashboard, a
REST API, and Prometheus metrics.

## Why use it

- **Automatic recovery** — containers that exit with an error or fail their health check
  are restarted for you, with cooldowns and exponential backoff so a broken container
  doesn't restart in a tight loop.
- **Quarantine for flapping containers** — a container that keeps failing past a
  configurable threshold is quarantined (auto-healing paused for it) and automatically
  un-quarantined once it recovers.
- **No YAML to hand-write** — enable monitoring with a single Docker label, or manage it
  entirely from the web UI.
- **Custom health checks** — beyond Docker's native `HEALTHCHECK`, you can define HTTP,
  TCP, or exec-based checks per container.
- **Observability built in** — a Prometheus metrics endpoint, an event log of every
  restart/quarantine decision, and optional notifications to Discord, Slack, Telegram,
  ntfy, Gotify, Pushover, or a generic webhook.

### Project status

Docker Auto-Heal is under active development. The core monitoring/restart engine, web
UI, REST API, and notification system are implemented and covered by an automated test
suite (see [Unit Tests workflow](.github/workflows/tests.yml)). Configuration is stored
on disk in `/data` and managed through the web UI or the REST API — there are currently
no environment-variable settings for tuning monitoring behavior (see
[Configuration](docs/user/configuration.md)).

## Quick Start

Run the service with the Docker socket mounted so it can see and manage your containers:

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

Or with Docker Compose:

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
      - "3131:3131"  # Web UI
      - "9090:9090"  # Prometheus metrics
    labels:
      - "autoheal=false"  # don't monitor the monitor itself
```

```bash
docker compose up -d
```

Open **<http://localhost:3131>** — that's the dashboard. Docker Auto-Heal is now running
and ready to monitor containers.

For a from-scratch walkthrough (requirements, verifying the socket mount, testing with a
sample container), see [Installation](docs/user/installation.md).

## Enabling Auto-Healing for a Container

Add the `autoheal` label to any container you want monitored:

```yaml
services:
  webapp:
    image: nginx:latest
    labels:
      autoheal: "true"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost"]
      interval: 30s
      timeout: 10s
      retries: 3
```

Docker Auto-Heal picks up labelled containers automatically — both containers that are
already running when it starts, and new ones as they start. A container's Docker
`healthcheck` (if it has one) determines when Auto-Heal considers it unhealthy; without a
health check, Auto-Heal still restarts the container if it exits with a non-zero code.
You can also select containers to monitor from the web UI without adding a label at all.

See [Labels](docs/user/labels.md) and [Health Checks](docs/user/health-checks.md) for the
full picture, including restart policy, cooldowns, and quarantine behavior.

## Web UI

The dashboard at `http://<host>:3131` shows every container's status, lets you toggle
auto-healing per container, view the event log, edit configuration, and manage custom
health checks and notifications — see [Usage](docs/user/usage.md).

Interactive API documentation (Swagger UI) is available at `http://<host>:3131/docs`.

## Metrics

Prometheus metrics are exposed on a separate port (`9090` by default) at `/metrics`:

```bash
curl http://localhost:9090/metrics
```

See [Monitoring & Metrics](docs/user/monitoring-and-metrics.md) for the full metric list.

## Troubleshooting

**Container not being monitored?** Check it has the `autoheal=true` label (unless you
enabled "monitor all containers"), isn't in the excluded list, and check the Events tab
in the UI for the monitoring decision.

**Service won't start?** Confirm the Docker socket is mounted and readable, and that
ports 3131 and 9090 are free.

For more, see the full [Troubleshooting guide](docs/user/troubleshooting.md).

## Documentation

| For users | For developers | For maintainers |
|---|---|---|
| [Installation](docs/user/installation.md) | [Development setup](docs/developer/development-setup.md) | [Dependency management](docs/maintainer/dependency-management.md) |
| [Configuration](docs/user/configuration.md) | [Architecture](docs/developer/architecture.md) | [Publishing](docs/maintainer/publishing.md) |
| [Usage](docs/user/usage.md) | [Project structure](docs/developer/project-structure.md) | [Release process](docs/maintainer/release-process.md) |
| [Labels](docs/user/labels.md) | [Frontend development](docs/developer/frontend.md) | |
| [Health checks](docs/user/health-checks.md) | [Testing](docs/developer/testing.md) | |
| [Monitoring & metrics](docs/user/monitoring-and-metrics.md) | | |
| [Notifications](docs/user/notifications.md) | | |
| [Maintenance mode](docs/user/maintenance-mode.md) | | |
| [Troubleshooting](docs/user/troubleshooting.md) | | |

The full documentation index, including historical/superseded documents, is in
[docs/README.md](docs/README.md).

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) to get set up, and
[docs/developer/](docs/developer/) for architecture and project structure.

## License

[MIT](LICENSE)
