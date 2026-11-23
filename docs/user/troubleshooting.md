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
- If you get `<h1>Docker Autoheal</h1> ... React UI not found`, the image's
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
4. Check the **Events** tab — an `auto_monitor` event confirms Docker Autoheal picked it up.
5. Turn on `DEBUG` logging (`observability.log_level`) and check
   `docker logs docker-autoheal` for the monitoring decision.

## A container keeps getting quarantined

This means it hit `restart.max_restarts` restarts within
`restart.max_restarts_window_seconds` — Docker Autoheal has stopped trying to restart it
automatically. That almost always means the container has a real, recurring problem.

1. Check the container's own logs to find the underlying failure.
2. View it in the **Containers** tab (marked quarantined) or `GET /api/containers`.
3. Fix the underlying issue.
4. It will auto-unquarantine on its own once it has stayed healthy for 3 consecutive
   checks and has been up for at least 3 monitoring intervals, or you can un-quarantine
   manually from the UI or `POST /api/containers/{id}/unquarantine`.

If containers are being quarantined too aggressively, increase `cooldown_seconds` or
`max_restarts` in [Configuration](configuration.md).

## Restart count looks wrong / doesn't match Docker

Docker Autoheal tracks its own restart count per container (stored in `config.json`, keyed by
the container's [stable identifier](labels.md#stable-container-identity)) — this is
**not** the same as Docker's native `RestartCount` on the container object. Docker Autoheal's
count only increases when *it* restarts a container, and it persists across container
recreation; Docker's own count resets when the container is recreated and also includes
restarts from Docker's own `restart:` policy. If you need to reset the tracked count, use
un-quarantine (which clears it) or edit `containers.restart_counts` in `config.json`
directly; `PUT /api/config` ignores the restart counts and history in its request body. Quarantine
is decided by `containers.restart_history` instead: only restarts within
the last `max_restarts_window_seconds` count towards `max_restarts`, so older restarts age out
on their own. Counts recorded by versions that did not track timestamps have no history and
never count towards quarantine.

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

## Inspecting a running container

When Autoheal hangs, stops healing, or uses a lot of CPU, the logs may not show where it is
stuck. The image includes Python's built-in tools for inspecting a live process, so you don't
need to change code, restart Autoheal, or install anything. Autoheal is PID 1 in its container,
so the commands below use `1`. They assume the default container name `docker-autoheal`.

These tools read a running process's memory and don't pause it by default. Avoid the `--blocking`
option, which stops every thread while it samples.

### It's stuck: see what each task is waiting for

```bash
docker exec docker-autoheal python -m asyncio pstree 1
```

This prints the tree of asyncio tasks and what each one is awaiting. If two tasks await each
other, `pstree` prints the cycle instead of a tree, which is the usual sign of a deadlock:

```text
ERROR: await-graph contains cycles - cannot print a tree!

cycle: Task-2 → Task-3 → Task-2
```

For a flat table that lists each task's coroutine stack and awaiter:

```bash
docker exec docker-autoheal python -m asyncio ps 1
```

To see the stack of every thread (for example the Docker event reader or the health-check
workers, which run outside the event loop):

```bash
docker exec docker-autoheal python -m profiling.sampling dump -a 1
```

To see the stacks of the asyncio tasks instead, use `--async-aware`. Don't combine it with `-a`,
which the tool rejects.

```bash
docker exec docker-autoheal python -m profiling.sampling dump --async-aware 1
```

Autoheal doesn't name its tasks yet, so they show as `Task-1`, `Task-2`, and so on.

### High CPU: see what the process is doing

Run a live, top-style view in your terminal and press `q` to quit:

```bash
docker exec -it docker-autoheal python -m profiling.sampling attach --live 1
```

For a sample you can save, add `--mode cpu` to count only threads that are running on a CPU.
Use `--pstats` for a table or `--flamegraph` for an HTML flame graph, and write it to a file
inside the container. Copy it to the host with `docker cp`:

```bash
docker exec docker-autoheal python -m profiling.sampling attach --mode cpu --pstats \
  -a -d 10 -o /tmp/autoheal-cpu.pstats 1
docker cp docker-autoheal:/tmp/autoheal-cpu.pstats .
```

### Files for a bug report

When reporting a hang or high CPU, include the output of `pstree 1` (or its cycle line) and of
`dump -a 1`. You can also attach a flame graph:

```bash
docker exec docker-autoheal python -m profiling.sampling attach --flamegraph -a -d 10 \
  -o /tmp/autoheal-flame.html 1
docker cp docker-autoheal:/tmp/autoheal-flame.html .
```

The output shows module and function names and file paths, not configuration values. Check it
before you post it anyway.

### Permissions

The tools attach to the process the way a debugger does. The image runs as root (it has no
`USER` instruction), and Docker's default capabilities don't include `SYS_PTRACE`. If a command
fails with `Operation not permitted` or a ptrace error, add the capability to the service in your
Compose file, then recreate the container:

```yaml
services:
  autoheal:
    cap_add:
      - SYS_PTRACE
```

This widens what the container is allowed to do, so remove it once you've finished diagnosing.

### Last resort: remote debugger

Maintainers can attach the standard debugger to the running process:

```bash
docker exec -it docker-autoheal python -m pdb -p 1
```

Unlike the commands above, this runs code inside Autoheal and can pause it, so use it only when
the other tools haven't found the cause.

## See also

- [Configuration](configuration.md)
- [Health checks](health-checks.md)
- [Monitoring & metrics](monitoring-and-metrics.md)
