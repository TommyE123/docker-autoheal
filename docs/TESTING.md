# Testing

## Overview

Unit tests live in `app/tests/unit/`. They run entirely against fakes and mocks:
**no Docker daemon and no running Auto-Heal service are required**, and no
external network calls are made. This is what CI runs.

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

## Coverage floor

`.coveragerc` sets `fail_under = 50` (raised from an initial 35% once the
converted tests and the RestartCount regression test cleared that bar): a
floor, not a target. `pytest` fails if total coverage drops below it. Raise
this deliberately as coverage improves - never lower it just to turn a red
build green.

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
pytest app/tests/integration/test_service_smoke.py app/tests/integration/test_auto_monitor.py
```

Every module in the directory sets `pytestmark = pytest.mark.integration`, so
`pytest -m integration <path>` works if you point pytest at a tree that
includes both suites.

| Area | File |
| --- | --- |
| Container-ID-vs-stable-ID tracking across real recreation | `test_container_recreation.py` |
| Native restart count after a policy-triggered restart | `test_restart_count.py` |
| Auto-discovery of `autoheal=true` labelled containers | `test_auto_monitor.py` |
| `/health`, `/api/status`, the React UI, and Prometheus metrics | `test_service_smoke.py` |

### Isolation against a real Auto-Heal instance

`http://localhost:3131` may be someone's real, already-running instance, not a
throwaway test fixture - these tests only do things a real user's actions
would also do, and undo the ones with lasting effect:

* Containers are uniquely named (`autoheal-*-<uuid>`) and force-removed by
  `disposable_container`, so they never collide with anything already running.
* `test_auto_monitor.py` removes the container it caused to be auto-selected
  from `containers.selected` afterward (via `GET`/`PUT /api/config` - not
  `POST /api/containers/select`, which moves it to `containers.excluded`
  instead of clearing it). The `auto_monitor` event itself is left in the
  log, same as it would be from real usage, because the API only exposes
  clearing the *entire* log, not one event.
* Nothing in this suite calls `DELETE /api/events`. An earlier version of
  `test_clear_events_api.py` did, against whatever instance happens to be
  running - unacceptable against a real installation's history, and the API
  has no way to delete just one event. That test now lives in
  `app/tests/unit/test_events_api.py` instead, calling the endpoint functions
  directly against an isolated `config_manager`: same code path, no real
  service or Docker daemon required, and no risk to anyone's data.

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
| `app/tests/test_clear_events_api.py` | Converted → `app/tests/unit/test_events_api.py` (calls the API functions directly against an isolated `config_manager`, so it never touches a real running instance's event log) |
| `app/tests/test_service.py` | Converted → `app/tests/integration/test_service_smoke.py` |
| `app/tests/test_container_id_bug_fix.py` | Rewritten → `app/tests/integration/test_container_recreation.py`. The original script had a corrupted/unterminated docstring and was not valid Python (never actually ran); its regression scenario (restart/quarantine/monitoring state surviving container recreation) was rebuilt against a real Docker daemon. |
| `app/tests/test_clear_events.py` | Converted to a unit test → `app/tests/unit/test_events_persistence.py`, since it only exercised `config_manager`'s event log with no Docker/service dependency once isolated from the real data directory. |
| `app/tests/test_auto_unquarantine.py` | Moved as-is → `app/tests/unit/test_auto_unquarantine.py`. It already used mocks exclusively and needed no live Docker/service. |
| `app/tests/test_init_defaults.py` | Moved as-is → `app/tests/unit/test_init_defaults.py`. Pure filesystem/temp-dir test; already unit-test quality. |
| `app/tests/test_prometheus_start.py` | Moved as-is → `app/tests/unit/test_prometheus_start.py`. Fully mocked; already unit-test quality. |
| `app/tests/test_unquarantine_fix.py` | Removed. It never called any application code - it demonstrated the bug/fix using local variables/sets, so moving it anywhere would add no regression coverage. The real behaviour (dual short/full-ID and name-based lookup) is covered by `test_container_recreation.py` and the existing unit suite. |
| `test_notifications.py` (root) | Converted to unit tests with a faked HTTP session → `app/tests/unit/test_notification_manager.py`. The original sent a real webhook to `https://httpbin.org/post`; nothing about the scenario (event filtering, webhook delivery, `test_notification`) actually required a live network call once the `aiohttp` session is faked. |
| `test_proactive_scan.py` (root) | Removed. The file was empty (a single blank line) with no test content to convert. |
| `test_restart_count.py` (root) | Rewritten → `app/tests/integration/test_restart_count.py`. The original was a debug print script with no assertions, inspecting whatever containers already happened to be running on the host; rebuilt against a disposable container with an `on-failure` restart policy, so Docker itself performs a real restart and increments `RestartCount` (a manual `container.restart()` does not - see below). |
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

`.github/workflows/tests.yml` runs the unit suite with coverage on every push
to `main` and on every pull request, against the Python version the
production `Dockerfile` uses (read from its `FROM python:X.Y-slim` line), so
CI tests the runtime that actually ships. Coverage output is reported in the
GitHub Actions job log.
