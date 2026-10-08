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

When a container with the configured label is discovered (at startup or on a `start`
event), its stable identifier is added to `containers.selected`, so it becomes an explicit
selection. That means it is monitored regardless of the whitelist/blacklist filters, and
removing the label later does not by itself stop monitoring: the selection must be removed
explicitly, for example from the **Containers** tab in the web UI or through the API.

You can also enable monitoring for a container from the **Containers** tab in the web UI
without adding a label — this stores an explicit selection that persists in
`config.json`.

### `include_all` mode

If `monitor.include_all` is set, every container is monitored regardless of the `autoheal`
label (subject to the whitelist/blacklist filters in [Configuration](configuration.md)) —
the label itself has no effect in this mode. An explicit UI/API selection or exclusion
(`containers.selected` / `containers.excluded`) is checked before the label or `include_all`
are even considered, and always wins either way.

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

### Scaled Compose services

Replicas of a scaled Compose service (`docker compose up --scale web=3`) share one stable
identifier, so selection, custom health checks and Uptime Kuma mappings apply to the
whole service. Restart counts, cooldown, backoff and quarantine are tracked per replica,
so one failing replica cannot use up its siblings' restart budget, keep them in
quarantine, or be released from quarantine because a sibling is healthy. Replica 1 uses
the stable identifier itself (`myapp_web`) and replica *N* uses it with the Compose
container number appended after `#` (`myapp_web#2`, `myapp_web#3`). Compose project and
service names cannot contain `#`, so these keys never clash with the identifier generated
for another Compose service. Compose keeps a replica's number when it recreates it, so its
state survives recreation.

An explicit `monitoring.id` label is never given a replica suffix: replicas that share
one `monitoring.id` also share their restart count, cooldown, backoff and quarantine.
Autoheal uses an explicit `monitoring.id` as it is, so don't set one that matches another
container's generated identifier (such as `myapp_web` or `myapp_web#2`), or the two
containers share that recovery state.

## See also

- [Configuration](configuration.md)
- [Health checks](health-checks.md)
