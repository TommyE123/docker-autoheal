# Usage

The web UI lives at `http://<host>:3131` and is the primary way to operate Docker
Auto-Heal day to day.

## Dashboard

The landing page shows:

- Total containers, monitored containers, quarantined containers
- Service status (monitoring active, Docker connection state)
- An **Enter Maintenance Mode** / **Exit Maintenance** toggle — see
  [Maintenance mode](maintenance-mode.md)

### Installing as an app (PWA)

The web UI is a Progressive Web App, so supported browsers can install it as a standalone
app window:

- **Chrome / Edge (desktop):** click the install icon in the address bar, or use the
  browser menu → *Install Docker Auto-Heal Service*.
- **Android (Chrome):** menu → *Install app* / *Add to Home screen*.
- **iOS / iPadOS (Safari):** Share → *Add to Home Screen*.

Browsers only offer installation on a secure origin: `https://`, or `http://localhost`.
A plain `http://<host>:3131` address is usually not installable, so put Auto-Heal behind
an HTTPS reverse proxy for remote installs.

Limitations: the app does not work offline. Only the static UI files are cached, so the
window opens without a network but shows no data. Every `/api/*` request goes straight
to the backend and is never cached, so what you see is always live container state. New
UI versions are picked up automatically; the open page reloads once the update is
installed, so unsaved form input can be lost.

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
`ui.max_log_entries`, 50 by default). Use the **Event Type**, **Container** and
**Limit** (25, 50 or 100) dropdowns above the list to narrow it; they are applied by
the API and kept across Refresh and the automatic 5-second refresh. **Clear Filters**
resets Event Type and Container but keeps Limit. Fetch more via the API:

```bash
curl "http://localhost:3131/api/events?limit=200"
```

`GET /api/events` also accepts optional filters, applied before `limit`:

| Parameter    | Meaning                                                                  |
|--------------|--------------------------------------------------------------------------|
| `limit`      | Maximum number of events to return, newest last (default 100, minimum 1) |
| `event_type` | Only events of this exact type, e.g. `restart` or `quarantine`           |
| `container`  | Only events whose container name contains this text (case-insensitive)   |

```bash
curl "http://localhost:3131/api/events?event_type=quarantine&container=web"
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

Everything the UI does is backed by a REST API under `/api`. For developers, interactive,
always-current documentation is available at:

```text
http://localhost:3131/api/swagger   # Swagger UI
http://localhost:3131/api/redoc     # ReDoc
http://localhost:3131/api/openapi.json
```

The documentation used to live at `/docs`, `/redoc` and `/openapi.json`. Those paths no
longer exist and do not redirect — update any bookmarks or scripts.

A few endpoints you're likely to use directly:

| Endpoint                                 | Purpose                                                          |
|------------------------------------------|------------------------------------------------------------------|
| `GET /health`                            | Service health check (used by the container's own `HEALTHCHECK`) |
| `GET /api/status`                        | Overall system status and current config                         |
| `GET /api/containers`                    | List containers with monitoring/health/quarantine state          |
| `POST /api/containers/{id}/restart`      | Manually restart a container                                     |
| `POST /api/containers/{id}/unquarantine` | Remove a container from quarantine                               |
| `GET /api/events`                        | Recent auto-heal events                                          |
| `GET /api/config` / `PUT /api/config`    | Read/replace full configuration                                  |

`PUT /api/config` keeps the current `containers.restart_counts` and
`containers.restart_history` and ignores those fields in the request body: they are runtime
state, reset by un-quarantining the container or by importing a configuration (see
[Configuration](configuration.md#container-selection-and-restart-counts)).

## See also

- [Labels](labels.md)
- [Health checks](health-checks.md)
- [Monitoring & metrics](monitoring-and-metrics.md)
- [Troubleshooting](troubleshooting.md)
