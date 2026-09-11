# Testing

## Overview

Unit tests live in `app/tests/unit/`. They run entirely against fakes and mocks:
**no Docker daemon and no running Auto-Heal service are required**, and no
external network calls are made.

The older scripts directly under `app/tests/` and in the repository root
(`test_notifications.py`, `test_proactive_scan.py`, ...) are manual /
integration helpers that *do* require a live environment. They are deliberately
excluded from the default pytest run via `testpaths` in `pytest.ini`.

## Running the tests

```bash
pip install -r requirements-dev.txt

# Run the unit-test suite
pytest

# Run with coverage
pytest --cov=app --cov-report=term-missing
```

Coverage settings live in `.coveragerc` (source `app`, branch coverage on,
tests and one-off scripts omitted).

## What is covered

The suite focuses on the monitoring engine and its restart/recovery behaviour:

| Area | File |
| --- | --- |
| Stable identifier and monitoring selection/filters | `test_monitoring_identity.py` |
| Health evaluation (exit codes, Docker health, custom checks, Uptime-Kuma) | `test_health_evaluation.py` |
| Cooldown, thresholds, quarantine, backoff, restart success/failure, alerts | `test_restart_handling.py` |
| Per-cycle checks, quarantine skip/auto-unquarantine, disappearance, Docker failures | `test_container_checks.py` |
| Start/stop, monitor loop, event listener, auto-discovery | `test_engine_lifecycle.py` |
| Docker client wrapper boundary behaviour | `test_docker_client_wrapper.py` |

## How isolation works

`app/tests/unit/conftest.py` provides the shared fixtures:

* `isolated_config_manager` (autouse) repoints the global `config_manager`
  singleton at a per-test temporary directory and resets its in-memory state, so
  tests never touch the real `/data` directory and never share state.
* `FakeDockerClient` is an in-memory stand-in for `DockerClientWrapper` that
  serves canned container information and records restart calls.
* `mock_notification_manager` (autouse) replaces the notification manager used
  by the monitoring engine, so no outbound requests are attempted.
* `recorded_sleeps` (autouse) replaces `asyncio.sleep`, so restart-backoff
  delays are recorded and asserted on rather than actually waited for.

## Manual / integration scripts

The Python scripts at the repository root (`test_notifications.py`,
`test_proactive_scan.py`, `test_restart_count.py`, `test_uptime_kuma_api.py`) and the
ad-hoc scripts under `app/tests/` (e.g. `test_service.py`, `test_auto_monitor.py`) are not
part of the pytest suite — they require a running Docker Auto-Heal instance and, in some
cases, live Docker containers or external services. Read each script's own docstring
before running it; they're intended for manual verification during development, not CI.

## Frontend

There is currently no automated frontend test suite. `npm run lint` (ESLint) is defined in
`frontend/package.json`, but there's no ESLint configuration file yet, so it doesn't
currently run successfully — see [Frontend Development](frontend.md#linting).

## CI

`.github/workflows/tests.yml` runs the suite with coverage on every push to
`main` and on every pull request, against Python 3.11 and 3.12.
