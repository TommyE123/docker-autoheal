# Monitoring & Metrics

## Prometheus metrics

By default, Prometheus metrics are exposed on port **9090** at `/metrics`
(`observability.prometheus_enabled` / `observability.metrics_port` in
[Configuration](configuration.md)):

```bash
curl http://localhost:9090/metrics
```

Metrics defined by the service:

| Metric                                | Type    | Labels           | Description                                       |
|---------------------------------------|---------|------------------|---------------------------------------------------|
| `autoheal_container_restarts_total`   | Counter | `container_name` | Successful restarts performed by Autoheal         |
| `autoheal_containers_monitored`       | Gauge   | —                | Containers monitored in the last monitoring cycle |
| `autoheal_containers_quarantined`     | Gauge   | —                | Containers currently quarantined                  |
| `autoheal_health_checks_total`        | Counter | —                | Health checks that produced a result              |
| `autoheal_health_checks_failed_total` | Counter | `container_name` | Health checks that reported the container failing |

When each metric changes:

- **`autoheal_container_restarts_total`** goes up by one each time Autoheal restarts a
  container to recover it and Docker reports the restart succeeded. Failed restarts,
  restarts skipped for cooldown or backoff, quarantines, and restarts you trigger from the
  web UI or `POST /api/containers/{id}/restart` are not counted. `container_name` is the
  container's Docker name.
- **`autoheal_health_checks_total`** goes up by one for each custom health check that
  runs and each Docker native health status of `healthy` or `unhealthy` that Autoheal reads
  (see [Health checks](health-checks.md)). Health checks run only in the `health` and
  `both` restart modes. Nothing is counted for a container that is still starting, a
  stopped container whose exit code alone decides the outcome (a clean manual stop, or an
  exit-code restart in `both` mode), a Docker status of `starting`, a custom HTTP or TCP
  check skipped for host networking, or an Uptime Kuma DOWN status. A custom check of type
  `docker` reads the same Docker status, so it is counted once, not twice.
- **`autoheal_health_checks_failed_total`** goes up by one, with the container's name in
  `container_name`, for each of those checks that fails: a custom check that reports the
  container unhealthy or errors, or a Docker status of `unhealthy`. A failed custom check
  ends that container's evaluation, so its Docker status is not read that cycle.
- **`autoheal_containers_monitored`** is set at the end of each monitoring cycle to the
  number of containers selected for monitoring, quarantined ones included. It keeps its
  last value while maintenance mode is on, when Docker cannot be reached, lists no
  containers or fails to list them, and when Autoheal cannot read the details of any listed
  container. Listing inspects each container, so one failed inspection there fails the whole
  listing and no container is checked that cycle. If the listing succeeds but one
  container's details then cannot be read (for example, its image lookup fails), that
  container still counts if it was counted the cycle before, and is left out if it never
  was. It reads 0 until the first cycle completes.
- **`autoheal_containers_quarantined`** is read from the quarantine list each time
  Prometheus scrapes, so it matches the quarantined count on the Dashboard and in
  `GET /api/status`.

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

If you run [Uptime Kuma](https://github.com/louislam/uptime-kuma), Docker Autoheal can
treat a mapped monitor's DOWN status as an additional restart trigger. This is opt-in and
disabled by default — see [Configuration](configuration.md#uptime_kuma-optional-integration).

## See also

- [Health checks](health-checks.md)
- [Notifications](notifications.md)
- [Troubleshooting](troubleshooting.md)
