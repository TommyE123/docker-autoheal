# Testing

## Overview

Unit tests live in `app/tests/unit/`. They run entirely against fakes and mocks:
**no Docker daemon and no running Auto-Heal service are required**, and no
external network calls are made. This is what CI runs.

The older scripts directly under `app/tests/` and in the repository root
(`test_notifications.py`, `test_proactive_scan.py`, ...) are manual /
integration helpers that *do* require a live environment. They're excluded
from the default pytest run via `testpaths` in `pytest.ini`, and are not
currently part of the CI job - they're not yet in a state (real assertions,
no live-environment dependencies) that's safe to run automatically. Turning
them into a proper CI-integrated integration suite is separate follow-up
work.

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

## Coverage floor

`.coveragerc` sets `fail_under = 35`: an initial floor, not a target. `pytest`
fails if total coverage drops below it. Raise this deliberately as coverage
improves - never lower it just to turn a red build green.

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

## CI

`.github/workflows/tests.yml` runs the unit suite with coverage on every push
to `main` and on every pull request, against the Python version the
production `Dockerfile` uses (read from its `FROM python:X.Y-slim` line), so
CI tests the runtime that actually ships. Coverage output goes to the job log
and to a `coverage.xml` artifact.
