# Health Checks

Docker Auto-Heal decides whether a container needs healing based on `restart.mode`
(see [Configuration](configuration.md)):

- **`on-failure`** — restart when the container exits with a non-zero code (and hasn't
  hit its restart threshold / isn't in its cooldown period)
- **`health`** — restart when a health check reports the container unhealthy
- **`both`** (default is `on-failure`; `both` combines the two) — restart on either
  condition

A container that exits cleanly (exit code `0`) is **not** restarted by default —
`restart.respect_manual_stop` treats that as an intentional stop.

## Docker's native health check

If a container defines a `HEALTHCHECK` (in its Dockerfile or Compose `healthcheck:`
block), Auto-Heal reads Docker's reported health status directly — no extra
configuration needed:

```yaml
services:
  webapp:
    image: myapp:latest
    labels:
      autoheal: "true"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

## Custom health checks

For containers without a Docker-native `HEALTHCHECK`, you can define a custom check from
the **Containers** tab in the UI (click the health/heart icon) or via the API:

```bash
curl -X POST http://localhost:3131/api/healthchecks \
  -H "Content-Type: application/json" \
  -d '{
    "container_id": "my-container",
    "check_type": "http",
    "http_endpoint": "http://localhost:8080/health",
    "http_expected_status": 200,
    "interval_seconds": 30,
    "timeout_seconds": 10,
    "retries": 3
  }'
```

Supported `check_type` values:

| Type | Checks |
|---|---|
| `http` | Requests `http_endpoint` and compares the response status to `http_expected_status` (default `200`) |
| `tcp` | Attempts a TCP connection to `tcp_port` on the container |
| `exec` | Runs `exec_command` inside the container and checks its exit code |
| `docker` | Defers to Docker's native health status (equivalent to not setting a custom check) |

If a custom health check is configured, it's evaluated in addition to Docker's native
health status — either one reporting unhealthy is enough to trigger a restart.

Manage custom health checks with `GET /api/healthchecks`, `GET /api/healthchecks/{id}`,
and `DELETE /api/healthchecks/{id}`.

## Restart behavior once a check fails

1. **Cooldown** — if the container was restarted more recently than
   `restart.cooldown_seconds` ago, Auto-Heal waits.
2. **Backoff** — if `restart.backoff.enabled`, Auto-Heal waits an increasing delay
   (`initial_seconds`, then multiplied by `multiplier` on each subsequent restart of that
   container) before restarting.
3. **Threshold and quarantine** — once a container has been restarted `max_restarts`
   times within `max_restarts_window_seconds`, it's **quarantined**: Auto-Heal stops
   trying to restart it until you intervene, or until it becomes healthy on its own (see
   below).
4. **Auto-unquarantine** — on every monitoring cycle, Auto-Heal re-checks quarantined
   containers. If a quarantined container is running and passes its health check(s), it's
   automatically removed from quarantine and its restart count is reset. You can also
   un-quarantine manually from the UI or `POST /api/containers/{id}/unquarantine`.

## See also

- [Labels](labels.md)
- [Configuration](configuration.md)
- [Notifications](notifications.md) — get alerted on restarts and quarantines
