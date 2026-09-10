# Monitoring & Metrics

## Prometheus metrics

By default, Prometheus metrics are exposed on port **9090** at `/metrics`
(`observability.prometheus_enabled` / `observability.metrics_port` in
[Configuration](configuration.md)):

```bash
curl http://localhost:9090/metrics
```

Metrics defined by the service:

| Metric | Type | Labels | Description |
|---|---|---|---|
| `autoheal_container_restarts_total` | Counter | `container_name` | Total restarts performed |
| `autoheal_containers_monitored` | Gauge | — | Number of containers currently monitored |
| `autoheal_containers_quarantined` | Gauge | — | Number of containers currently quarantined |
| `autoheal_health_checks_total` | Counter | — | Total health checks performed |
| `autoheal_health_checks_failed` | Counter | `container_name` | Failed health checks |

The metrics server runs on its own port, separate from the web UI/API port (`3131`), so
you can restrict access to it independently (for example, only exposing it to your
Prometheus scraper's network).

## Health endpoint

The service exposes its own health check, used by the container's Docker `HEALTHCHECK`
and suitable for external monitoring:

```bash
curl http://localhost:3131/health
```

```json
{
  "status": "healthy",
  "timestamp": "2026-01-01T00:00:00+00:00",
  "docker_connected": true,
  "monitoring_active": true
}
```

## System status

`GET /api/status` (or the Dashboard tab) returns a fuller picture: total/monitored/
quarantined container counts, maintenance mode state, and the full current configuration.

## Event log

Every restart, quarantine, auto-unquarantine, and auto-monitoring decision is recorded
and available via the **Events** tab or `GET /api/events` — see
[Usage](usage.md#events-tab).

## Logs

```bash
docker logs -f docker-autoheal
```

Logs are also written to `/data/logs/autoheal.log` inside the persistent data volume.
Adjust verbosity with `observability.log_level` (`DEBUG`, `INFO`, `WARNING`, `ERROR`, or
`CRITICAL`) from the Configuration tab.

## Optional: Uptime Kuma integration

If you run [Uptime Kuma](https://github.com/louislam/uptime-kuma), Docker Auto-Heal can
treat a mapped monitor's DOWN status as an additional restart trigger. This is opt-in and
disabled by default — see [Configuration](configuration.md#uptime_kuma-optional-integration).

## See also

- [Health checks](health-checks.md)
- [Notifications](notifications.md)
- [Troubleshooting](troubleshooting.md)
