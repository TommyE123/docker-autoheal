# Troubleshooting

## Service won't start

Check Docker is running and the socket is accessible:

```bash
docker info
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock alpine ls -l /var/run/docker.sock
```

Then check the container's own logs for the actual error:

```bash
docker logs docker-autoheal
```

## Web UI isn't reachable

- Confirm the container is running: `docker ps | grep autoheal`
- Confirm port `3131` (or whatever host port you mapped it to) isn't already in use by
  something else on the host
- Confirm the health endpoint responds from inside the same network the container is on:
  `curl http://localhost:3131/health`
- If you get `<h1>Docker Auto-Heal Service</h1> ... React UI not found`, the image's
  frontend build is missing — this shouldn't happen with the published image, but if
  you're building locally, make sure the multi-stage Docker build completed successfully
  (see [Development Setup](../developer/development-setup.md)).

## A container isn't being monitored

1. Does it have the `autoheal=true` label? (Skip this if `monitor.include_all` is
   enabled.)
   ```bash
   docker inspect <container> --format '{{json .Config.Labels}}'
   ```
2. Is it in the excluded list? Check **Configuration → Container Selection** in the UI, or
   `GET /api/config` and inspect `containers.excluded`.
3. Does it fail a whitelist/blacklist filter? See [Configuration](configuration.md#filters).
4. Check the **Events** tab — an `auto_monitor` event confirms Auto-Heal picked it up.
5. Turn on `DEBUG` logging (`observability.log_level`) and check
   `docker logs docker-autoheal` for the monitoring decision.

## A container keeps getting quarantined

This means it hit `restart.max_restarts` restarts within
`restart.max_restarts_window_seconds` — Auto-Heal has stopped trying to restart it
automatically. That almost always means the container has a real, recurring problem.

1. Check the container's own logs to find the underlying failure.
2. View it in the **Containers** tab (marked quarantined) or `GET /api/containers`.
3. Fix the underlying issue.
4. It will auto-unquarantine on its own once it's healthy again, or you can un-quarantine
   manually from the UI or `POST /api/containers/{id}/unquarantine`.

If containers are being quarantined too aggressively, increase `cooldown_seconds` or
`max_restarts` in [Configuration](configuration.md).

## Restart count looks wrong / doesn't match Docker

Auto-Heal tracks its own restart count per container (stored in `config.json`, keyed by
the container's [stable identifier](labels.md#stable-container-identity)) — this is
**not** the same as Docker's native `RestartCount` on the container object. Auto-Heal's
count only increases when *it* restarts a container, and it persists across container
recreation; Docker's own count resets when the container is recreated and also includes
restarts from Docker's own `restart:` policy. If you need to reset the tracked count, use
un-quarantine (which clears it) or edit `containers.restart_counts` in `config.json`
directly.

## Notifications aren't arriving

1. Confirm notifications are enabled (**Notifications** tab, or `GET
   /api/notifications/config`).
2. Confirm the event type you're expecting is in the event filter list (or the filter
   list is empty, meaning "all events").
3. Use **Test** on the service to confirm its credentials/URL are correct.
4. Check `docker logs docker-autoheal` for delivery errors — failed notifications are
   logged but don't affect monitoring.

## Getting more detail

Set `observability.log_level` to `DEBUG` from the Configuration tab (or `PUT
/api/config/observability`) and watch the logs:

```bash
docker logs -f docker-autoheal
```

## See also

- [Configuration](configuration.md)
- [Health checks](health-checks.md)
- [Monitoring & metrics](monitoring-and-metrics.md)
