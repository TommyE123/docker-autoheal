# Project Restructuring (historical)

> **Historical document.** This describes a code reorganization that was completed in the
> past — flat root-level Python files (`main.py`, `api.py`, `config.py`,
> `docker_client.py`, `monitor.py`) were moved into the `app/` package that exists today.
> The migration is finished; the old root-level files no longer exist. This page is kept
> for historical context only. For the current layout, see
> [Project Structure](../developer/project-structure.md).

The project was originally a flat collection of Python scripts at the repository root:

```text
docker-autoheal/
├── main.py
├── api.py
├── config.py
├── docker_client.py
├── monitor.py
├── demo.py
├── test_auto_monitor.py
└── test_service.py
```

It was reorganized into a standard Python package layout:

```text
docker-autoheal/
├── app/
│   ├── main.py
│   ├── api/api.py
│   ├── config/config_manager.py
│   ├── docker_client/docker_client_wrapper.py
│   └── monitor/monitoring_engine.py
└── run.py
```

Import changes made at the time:

| Old import | New import |
|---|---|
| `from config import config_manager` | `from app.config.config_manager import config_manager` |
| `from docker_client import DockerClientWrapper` | `from app.docker_client.docker_client_wrapper import DockerClientWrapper` |
| `from monitor import MonitoringEngine` | `from app.monitor.monitoring_engine import MonitoringEngine` |
| `from api import app, init_api` | `from app.api.api import app, init_api` |

Running the application was, and still is, done with `python -m app.main` or `python
run.py`. The Dockerfile was updated at the same time to copy `app/` instead of loose
`*.py` files.
