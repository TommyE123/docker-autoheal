# Usage

The web UI lives at `http://<host>:3131` and is the primary way to operate Docker
Auto-Heal day to day.

## Dashboard

The landing page shows:

- Total containers, monitored containers, quarantined containers
- Service status (monitoring active, Docker connection state)
- An **Enter Maintenance Mode** / **Exit Maintenance** toggle — see
  [Maintenance mode](maintenance-mode.md)

## Containers tab

- Lists every container Docker knows about, with its status, health, and monitoring state
- Check/uncheck containers to enable or disable auto-healing for them, independent of
  labels
- Manually restart a container
- Un-quarantine a container
- Add a [custom health check](health-checks.md) to a container

## Events tab

A running log of every decision Auto-Heal made: restarts (success or failure),
quarantines, auto-unquarantines, and containers auto-added to monitoring because they
started with the `autoheal=true` label. The UI shows the most recent entries (up to
`ui.max_log_entries`, 50 by default); fetch more via the API:

```bash
curl "http://localhost:3131/api/events?limit=200"
```

Clear the log with `DELETE /api/events` or the "Clear Events" control in the UI.

## Configuration tab

Edit monitor settings, restart policy, filters, and observability settings; export or
import the full configuration as JSON. See [Configuration](configuration.md) for what
each field does.

## Notifications tab

Add, edit, test, and delete notification services (Discord, Slack, Telegram, ntfy,
Gotify, Pushover, or a generic webhook), and choose which event types trigger a
notification. See [Notifications](notifications.md).

## REST API

Everything the UI does is backed by a REST API under `/api`. Interactive, always-current
documentation (Swagger UI) is available at:

```text
http://localhost:3131/docs
```

A few endpoints you're likely to use directly:

| Endpoint | Purpose |
|---|---|
| `GET /health` | Service health check (used by the container's own `HEALTHCHECK`) |
| `GET /api/status` | Overall system status and current config |
| `GET /api/containers` | List containers with monitoring/health/quarantine state |
| `POST /api/containers/{id}/restart` | Manually restart a container |
| `POST /api/containers/{id}/unquarantine` | Remove a container from quarantine |
| `GET /api/events` | Recent auto-heal events |
| `GET /api/config` / `PUT /api/config` | Read/replace full configuration |

## See also

- [Labels](labels.md)
- [Health checks](health-checks.md)
- [Monitoring & metrics](monitoring-and-metrics.md)
- [Troubleshooting](troubleshooting.md)
