# Project Structure

```text
docker-autoheal/
├── app/                          # Python application package
│   ├── main.py                   # Entry point: wires everything together, starts the API + monitoring loop
│   ├── api/
│   │   └── api.py                # FastAPI app: all /api/* routes + static/React serving
│   ├── config/
│   │   ├── config_manager.py     # Pydantic config models + thread-safe JSON persistence
│   │   └── init_defaults.py      # Writes default config.json/events.json/etc. on first run
│   ├── docker_client/
│   │   └── docker_client_wrapper.py  # Thin wrapper around the `docker` SDK
│   ├── monitor/
│   │   ├── monitoring_engine.py  # Core monitoring loop, restart/backoff/quarantine logic
│   │   └── uptime_kuma_monitor.py
│   ├── notifications/
│   │   └── notification_manager.py   # Async notification dispatch (Discord/Slack/Telegram/ntfy/Gotify/Pushover/webhook)
│   ├── uptime_kuma/
│   │   └── uptime_kuma_client.py     # HTTP/websocket client for the Uptime Kuma API
│   ├── scripts/
│   │   └── demo.py               # Manual demo/exploration script (not part of the test suite)
│   ├── models/, services/, utils/    # Currently near-empty; reserved for future growth
│   └── tests/
│       ├── unit/                 # Automated unit test suite (see docs/developer/testing.md)
│       └── test_*.py             # Manual/integration scripts requiring a live Docker daemon
│
├── frontend/                     # React UI (Vite)
│   ├── src/
│   │   ├── components/           # Page and feature components
│   │   ├── services/api.js       # Axios client for the backend API
│   │   ├── hooks/
│   │   └── styles/
│   ├── package.json
│   └── vite.config.js
│
├── docs/
│   ├── user/                     # End-user documentation
│   ├── developer/                # This section
│   ├── maintainer/               # Repository maintenance documentation
│   └── historical/                # Superseded documents, kept for context
│
├── requirements.txt              # Runtime Python dependencies
├── requirements-dev.txt          # Test dependencies (pytest, coverage, etc.)
├── pytest.ini / .coveragerc
├── run.py                        # Convenience entry point (`python run.py`)
├── Dockerfile                    # Multi-stage build: Node (frontend) → Python (backend)
├── Dockerfile.simple             # Python-only build; expects a pre-built frontend/static/
├── docker-compose.yml            # Production compose file, pulls the published image
├── docker-compose.simple.yml     # Builds with Dockerfile.simple
├── docker-compose.example.yml    # Demonstrates auto-monitoring with several sample services
├── docker-compose.test.yml       # Test environment with sample containers
└── test_*.py                     # Root-level manual test/verification scripts (require a live service)
```

## Module responsibilities

- **`app/main.py`** — process entry point: logging setup, Docker client and monitoring
  engine construction, Prometheus metrics server startup, signal handling, and running
  the FastAPI server and monitoring engine concurrently via `asyncio.gather`.
- **`app/api/api.py`** — every HTTP endpoint. Also serves the built React app (including a
  catch-all route for client-side routing) and PWA assets.
- **`app/config/config_manager.py`** — the single source of truth for configuration and
  persisted state (events, quarantine, maintenance mode, restart counts). All reads/writes
  go through a `ConfigManager` singleton guarded by a lock.
- **`app/docker_client/docker_client_wrapper.py`** — all direct interaction with the
  `docker` SDK: listing containers, restarting/stopping them, HTTP/TCP/exec health checks,
  and reading Docker's native health status.
- **`app/monitor/monitoring_engine.py`** — the core auto-healing logic described in
  [Architecture](architecture.md).
- **`app/notifications/notification_manager.py`** — async, queue-based notification
  delivery to external services.
- **`app/uptime_kuma/`** and **`app/monitor/uptime_kuma_monitor.py`** — the optional
  Uptime Kuma integration.

## Running things from this layout

```bash
python -m app.main      # module syntax
python run.py           # convenience wrapper, equivalent to the above
pytest                  # unit test suite (app/tests/unit, per pytest.ini)
```

## See also

- [Architecture](architecture.md)
- [Testing](testing.md)
- [Frontend Development](frontend.md)
