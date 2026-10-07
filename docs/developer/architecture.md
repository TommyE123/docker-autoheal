# Architecture

## Overview

Docker Auto-Heal is a single Python process (FastAPI + asyncio) that talks to the Docker
Engine API, plus a React single-page app served by that same process. There's no
database — all state is JSON files under `/data`.

```text
┌──────────────────────────────────────────────────────────┐
│  docker-autoheal container                                │
│                                                             │
│  ┌────────────────┐        ┌───────────────────────────┐ │
│  │ React UI        │──────▶│ FastAPI app (app/api)      │ │
│  │ (built, served   │       │  - REST endpoints           │ │
│  │  as static files)│       │  - serves the React build   │ │
│  └────────────────┘        └──────────────┬──────────────┘ │
│                                             │                │
│                              ┌──────────────▼──────────────┐│
│                              │ MonitoringEngine             ││
│                              │  (app/monitor)                ││
│                              │  - per-cycle container checks ││
│                              │  - Docker event listener       ││
│                              │  - restart/backoff/quarantine  ││
│                              └──────┬─────────────┬──────────┘│
│                                     │             │            │
│                    ┌────────────────▼──┐   ┌──────▼──────────┐│
│                    │ DockerClientWrapper│   │ NotificationMgr  ││
│                    │ (app/docker_client)│   │ (app/notifications)││
│                    └────────┬───────────┘   └──────────────────┘│
│                              │                                   │
│                    ┌─────────▼─────────┐   ┌────────────────────┐│
│                    │ ConfigManager      │   │ UptimeKumaMonitor   ││
│                    │ (app/config)       │   │ (app/monitor,       ││
│                    │  - reads/writes    │   │  app/uptime_kuma)   ││
│                    │    /data/*.json    │   │  optional integration││
│                    └────────────────────┘   └────────────────────┘│
└──────────────────────────────┬──────────────────────────────────┘
                                │
                                ▼
                     /var/run/docker.sock
                                │
                                ▼
                        Docker Engine (host)
```

## Request/monitoring flow

1. **Startup** (`app/main.py`): connects to Docker, constructs the `MonitoringEngine`,
   initializes the API, optionally starts the Prometheus metrics server, starts the
   `NotificationManager`, then starts the monitoring engine and (if enabled) the Uptime
   Kuma monitor. The FastAPI server and the monitoring engine run concurrently as asyncio
   tasks.

2. **Monitoring loop** (`MonitoringEngine._monitor_loop`): every `monitor.interval_seconds`,
   lists all containers (including stopped ones) and evaluates each one:
   - `should_monitor_container` — applies the label filter, `include_all`, explicit
     selection/exclusion, and whitelist/blacklist filters.
   - `_evaluate_container_health` — checks exit status, custom health checks, Docker's
     native health status, and (if enabled) the Uptime Kuma monitor's status.
   - `_handle_container_restart` — applies cooldown, backoff, and the restart threshold;
     restarts the container or quarantines it.

   In parallel, `_event_listener_loop` subscribes to Docker's container-start events (via
   a background thread feeding an asyncio queue) so containers labelled `autoheal=true`
   are picked up the moment they start, without waiting for the next polling cycle.

3. **REST API** (`app/api/api.py`, routes in `app/api/routes/`): a FastAPI app exposing
   `/api/*` endpoints for containers, configuration, health checks, maintenance mode,
   notifications, and Uptime Kuma integration, plus static file serving for the built
   React app (with a catch-all route so React Router's client-side routes work on
   refresh).

4. **Persistence** (`app/config/config_manager.py`): a `ConfigManager` singleton, guarded
   by a re-entrant lock, that owns `/data/config.json`, `/data/events.json`,
   `/data/quarantine.json`, and `/data/maintenance.json`. There is no database — every
   write goes straight to disk as JSON.

## Stable container identity

Because container IDs (and often names) change when a container is recreated, the
monitoring engine never keys restart counts, quarantine state, or selection on the raw
Docker ID. Instead it resolves a **stable identifier** per container — see
[Labels: stable container identity](../user/labels.md#stable-container-identity) for the
resolution order. This is why a container's restart count in the UI can differ from
Docker's own `State.RestartCount`: the UI shows Auto-Heal's own tracked count
(`config.containers.restart_counts`, keyed by stable ID), not Docker's native counter,
which resets on recreation and includes restarts from Docker's own `restart:` policy.

Recovery state (restart counts, cooldown, backoff and quarantine) is keyed by a
per-replica *recovery identifier* rather than the stable identifier itself:
`recovery_identifier()` in `app/docker_client/docker_client_wrapper.py`, used by
`MonitoringEngine.get_recovery_identifier()` and exposed by the wrapper as
`info["recovery_id"]` for the API. It appends `-N` for Compose replica *N* > 1 and is
otherwise the stable identifier, so state persisted before per-replica keys still
applies to replica 1. Configuration (selection, custom health checks, Uptime Kuma
mappings) stays keyed by the per-service stable identifier.

## Notifications

`NotificationManager` runs an async worker consuming a queue, so a slow or failing
notification endpoint never blocks the monitoring loop. `MonitoringEngine` and the API
layer both call `notification_manager.send_event_notification()` after logging an event;
the manager checks `notifications.enabled` and the event filter before queuing, then
dispatches to each configured service by type (`app/notifications/notification_manager.py`
has one `_send_<service>` method per supported service type).

## Frontend

The frontend is a separate React app (`frontend/`) built with Vite and served as static
files by the FastAPI app in production — see [Frontend Development](frontend.md) and
[Project Structure](project-structure.md).
