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
    image: nginx:alpine
    labels:
      autoheal: "true"
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost/"]
      interval: 30s
      timeout: 10s
      retries: 3
```

The `test` command runs inside `webapp`'s own container, not inside Auto-Heal's — make sure
whatever tool you use is actually installed in that image (`wget` here, because it ships
with `nginx:alpine`'s BusyBox base; the common `nginx:latest`/Debian image has neither
`curl` nor `wget` installed by default).

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

| Type     | Checks                                                                                              |
|----------|-----------------------------------------------------------------------------------------------------|
| `http`   | Requests `http_endpoint` and compares the response status to `http_expected_status` (default `200`) |
| `tcp`    | Attempts a TCP connection to `tcp_port` on the container                                            |
| `exec`   | Runs `exec_command` inside the container and checks its exit code                                   |
| `docker` | Defers to Docker's native health status (equivalent to not setting a custom check)                  |

Two more fields control when a custom check counts as failed:

- `interval_seconds` (default `30`) is how often the check runs. Checks happen on
  monitoring cycles, so the effective interval is rounded to the nearest whole
  `monitor.interval_seconds`, and a value below it runs the check every cycle. Between runs the
  last result stands.
- `retries` (default `3`) is how many consecutive failed runs it takes before the container
  counts as unhealthy and the restart steps below begin. A passing run resets the count. Each
  container keeps its own count, including each replica of a scaled Compose service, and a
  restart starts it again from zero. With the defaults a failing container is therefore
  restarted on the third failed run, about a minute after the first, plus any restart backoff. Set `retries` to `1` to act on the
  first failure.

Docker's native health status is not affected by either field.

Each type must supply the fields it uses (`http_endpoint` and `http_expected_status` for `http`,
`tcp_port` for `tcp`, `exec_command` for `exec`), and `check_type` must be one of the values
above. The values must also be usable: `tcp_port` between 1 and 65535, `exec_command` a
non-empty list whose first entry (the command) is not blank, and `http_endpoint` not
empty. `POST /api/healthchecks` returns `422` for anything else, rather than accepting a check
that could never pass and would restart the container every cycle.

A check already saved in `config.json` that fails these rules (including an unknown
`check_type`, or an unusable value such as `tcp_port: 0`) is skipped with a warning when the
configuration loads, so it no longer restarts the container and does not affect other checks. It
is removed from `config.json` the next time the configuration is saved. Importing a configuration that contains one is rejected as a whole.

If a custom health check is configured, it's evaluated in addition to Docker's native
health status — either one reporting unhealthy is enough to trigger a restart.

Manage custom health checks with `GET /api/healthchecks`, `GET /api/healthchecks/{id}`,
and `DELETE /api/healthchecks/{id}`.

## Restart behavior once a check fails

This applies once the check has failed `retries` times in a row (a custom check) or as soon as
Docker reports the container unhealthy.

1. **Cooldown** — if the container was restarted more recently than
   `restart.cooldown_seconds` ago, Auto-Heal waits.
2. **Backoff** — if `restart.backoff.enabled`, Auto-Heal waits an increasing delay
   (`initial_seconds`, then multiplied by `multiplier` on each subsequent restart of that
   container, up to `max_seconds`) before restarting. The delay goes back to
   `initial_seconds` once the container has stayed healthy for longer than the delay it
   would otherwise wait, so a container that crashes soon after each restart keeps
   escalating. The wait doesn't pause monitoring: other containers keep
   being checked, and the restart happens on the first monitoring cycle after the delay
   has passed, if the container is still unhealthy then. Because that is checked once per
   `monitor.interval_seconds`, the effective wait is rounded up to a whole interval. If the
   container is seen healthy at any check during the wait, the wait is cancelled and a later
   failure starts a new one, so a container that alternates between healthy and unhealthy on
   every check is not restarted. The same holds if the failure wasn't observed on every
   cycle, for example while the container was quarantined, during maintenance mode, or when
   the Docker connection was unavailable: the old wait is dropped and the next failure
   starts a fresh one, with the same delay, instead of restarting at once.
3. **Threshold and quarantine** — once a container has been restarted `max_restarts`
   times within `max_restarts_window_seconds`, it's **quarantined**: Auto-Heal stops
   trying to restart it until you intervene, or until it becomes healthy on its own (see
   below).
4. **Auto-unquarantine** — on every monitoring cycle, Auto-Heal re-checks quarantined
   containers. A custom check is run on every cycle for this, ignoring `interval_seconds` and
   `retries`. One that has been running and passing its health check(s) for 3
   consecutive checks of the same run, and has been up for at least 3 monitoring
   intervals, is removed from quarantine and its restart count reset. A single healthy
   snapshot isn't enough, since a crash-looping container is running between crashes,
   and Docker health `starting` doesn't count as healthy in the `health` and `both`
   modes. The check count is kept in memory, so restarting Auto-Heal starts it again
   from zero (the container stays quarantined meanwhile). You can also un-quarantine
   manually from the UI or `POST /api/containers/{id}/unquarantine`.

## See also

- [Labels](labels.md)
- [Configuration](configuration.md)
- [Notifications](notifications.md) — get alerted on restarts and quarantines
