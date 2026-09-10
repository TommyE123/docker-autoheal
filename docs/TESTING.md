# Testing

## Overview

Unit tests live in `app/tests/unit/`. They run entirely against fakes and mocks:
**no Docker daemon and no running Auto-Heal service are required**, and no
external network calls are made.

An integration suite lives in `app/tests/integration/`. Those tests exercise a
real Docker daemon and/or a running Auto-Heal service (`http://localhost:3131`)
and are **not** collected by a plain `pytest` run - `pytest.ini`'s `testpaths`
only points at `app/tests/unit`. Run them explicitly (see below) when you have
the resources they need available.

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

## Running the integration suite

The integration suite requires a real Docker daemon reachable at the default
socket (`unix://var/run/docker.sock`), and some of its tests additionally
require a running Auto-Heal service on `http://localhost:3131` (e.g. via
`docker-compose up`). Every test skips itself - rather than failing - when the
resource it needs isn't available, so it's safe to run with only some of those
resources present.

```bash
# Everything the daemon you have access to can run
pytest app/tests/integration

# Only the tests that need Docker but not a running service
pytest app/tests/integration/test_container_recreation.py app/tests/integration/test_restart_count.py

# Only the tests that need a running service (start it first: docker-compose up -d)
pytest app/tests/integration/test_service_smoke.py app/tests/integration/test_clear_events_api.py app/tests/integration/test_auto_monitor.py
```

Every test in the directory also carries the `integration` marker, so
`pytest -m integration <path>` works if you point pytest at a tree that
includes both suites.

| Area | File |
| --- | --- |
| Container-ID-vs-stable-ID tracking across real recreation | `test_container_recreation.py` |
| `DockerClientWrapper` restart count reading against a real container | `test_restart_count.py` |
| Auto-discovery of `autoheal=true` labelled containers | `test_auto_monitor.py` |
| `/health`, `/api/status`, the React UI, and Prometheus metrics | `test_service_smoke.py` |
| `DELETE /api/events` | `test_clear_events_api.py` |

### CI

This suite is **not** run in CI. It needs a live Docker daemon and, for most
of its tests, a running Auto-Heal service - standing up Docker-in-Docker (or
an equivalent) for that was judged not worth the added CI complexity for now.
`.github/workflows/tests.yml` continues to run only the unit-test suite (see
above), unaffected by this suite's existence. Run the integration suite
locally before releases or when touching the areas above.

### Legacy script triage

The manual/demo scripts formerly under `app/tests/` and the repository root
were triaged as part of converting this suite:

| Script | Outcome |
| --- | --- |
| `app/tests/test_auto_monitor.py` | Converted → `app/tests/integration/test_auto_monitor.py` |
| `app/tests/test_clear_events_api.py` | Converted → `app/tests/integration/test_clear_events_api.py` |
| `app/tests/test_service.py` | Converted → `app/tests/integration/test_service_smoke.py` |
| `app/tests/test_container_id_bug_fix.py` | Rewritten → `app/tests/integration/test_container_recreation.py`. The original script had a corrupted/unterminated docstring and was not valid Python (never actually ran); its regression scenario (restart/quarantine/monitoring state surviving container recreation) was rebuilt against a real Docker daemon. |
| `app/tests/test_clear_events.py` | Converted to a unit test → `app/tests/unit/test_events_persistence.py`, since it only exercised `config_manager`'s event log with no Docker/service dependency once isolated from the real data directory. |
| `app/tests/test_auto_unquarantine.py` | Moved as-is → `app/tests/unit/test_auto_unquarantine.py`. It already used mocks exclusively and needed no live Docker/service. |
| `app/tests/test_init_defaults.py` | Moved as-is → `app/tests/unit/test_init_defaults.py`. Pure filesystem/temp-dir test; already unit-test quality. |
| `app/tests/test_prometheus_start.py` | Moved as-is → `app/tests/unit/test_prometheus_start.py`. Fully mocked; already unit-test quality. |
| `app/tests/test_unquarantine_fix.py` | Removed. It never called any application code - it demonstrated the bug/fix using local variables/sets, so moving it anywhere would add no regression coverage. The real behaviour (dual short/full-ID and name-based lookup) is covered by `test_container_recreation.py` and the existing unit suite. |
| `test_notifications.py` (root) | Converted to unit tests with a faked HTTP session → `app/tests/unit/test_notification_manager.py`. The original sent a real webhook to `https://httpbin.org/post`; nothing about the scenario (event filtering, webhook delivery, `test_notification`) actually required a live network call once the `aiohttp` session is faked. |
| `test_proactive_scan.py` (root) | Removed. The file was empty (a single blank line) with no test content to convert. |
| `test_restart_count.py` (root) | Rewritten → `app/tests/integration/test_restart_count.py`. The original was a debug print script with no assertions, inspecting whatever containers already happened to be running on the host; rebuilt as a real assertion against a disposable container that Docker actually restarts. |
| `test_uptime_kuma_api.py` (root) | Removed. It hard-coded a plaintext password for a local Uptime-Kuma instance directly in the script - a credential-hygiene problem independent of the live-service dependency. Uptime-Kuma integration is not currently covered by either suite; re-adding coverage should read credentials from environment variables rather than hard-coding them. |

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

`.github/workflows/tests.yml` runs the suite with coverage on every push to
`main` and on every pull request, against Python 3.11 and 3.12.
