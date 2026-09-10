# Container Labels

## Enabling auto-healing

Add the `autoheal` label to any container you want Docker Auto-Heal to monitor:

```yaml
services:
  myapp:
    image: myapp:latest
    labels:
      autoheal: "true"
```

```bash
docker run -d --name my-app --label autoheal=true nginx:alpine
```

Auto-Heal picks this up two ways: it scans all existing containers for the label when it
starts, and it listens for Docker `start` events afterwards — so both containers already
running and containers started later are picked up automatically, without restarting the
Auto-Heal service.

The label key and value are configurable (`monitor.label_key` / `monitor.label_value` in
[Configuration](configuration.md)), but default to `autoheal` / `true`.

You can also enable monitoring for a container from the **Containers** tab in the web UI
without adding a label — this stores an explicit selection that persists in
`config.json`.

### `include_all` mode

If `monitor.include_all` is set, every container is monitored regardless of labels
(subject to the whitelist/blacklist filters in [Configuration](configuration.md)). The
`autoheal` label and UI-based selection/exclusion still take priority when set.

## There is no per-container timeout label

Older documentation for this project referenced an `autoheal.stop.timeout` label for
customizing how long Auto-Heal waits before force-stopping a container. **This label does
not exist in the current implementation.** Restart timeout is a fixed 10-second default
applied by the Docker client wrapper and is not currently configurable per container.

## Stable container identity

Container IDs and even auto-generated names change when a container is recreated (for
example, after `docker compose up` rebuilds an image). To keep restart counts,
quarantine state, and monitoring selection stable across recreation, Auto-Heal resolves
each container to a **stable identifier**, in this priority order:

1. A `monitoring.id` label, if you set one explicitly:
   ```yaml
   labels:
     autoheal: "true"
     monitoring.id: "my-stable-service-name"
   ```
2. `com.docker.compose.project` + `com.docker.compose.service` (automatically present on
   containers started by Docker Compose)
3. The container's name, as a fallback

Use an explicit `monitoring.id` label when you want restart history and quarantine state
to survive container recreation outside of Compose, or when you're renaming a service and
want to keep its history.

## See also

- [Configuration](configuration.md)
- [Health checks](health-checks.md)
