# Testing

## Overview

Unit tests live in `app/tests/unit/`. They run entirely against fakes and mocks:
**no Docker daemon and no running Auto-Heal service are required**, and no
external network calls are made.

The older scripts directly under `app/tests/` and in the repository root
(`test_notifications.py`, `test_proactive_scan.py`, ...) are manual /
integration helpers that *do* require a live environment. They are deliberately
excluded from the default pytest run via `testpaths` in `pytest.ini`. See
"Integration tests" below for their current state and what running them in
CI would actually require.

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

## Coverage baseline

`.coveragerc` pins a `fail_under` floor (currently 37%) to the coverage the
unit-test suite actually measures on `main`. `pytest-cov` reads this
automatically, so `pytest --cov=app ...` - locally or in CI - fails if total
coverage drops below that floor, even if every test still passes. This is a
ratchet, not a target: raise the number deliberately, in the same PR that
earns the improvement, as coverage grows. Never lower it just to turn a red
build green.

On every pull request, the CI job also posts (and keeps updated) a comment
on the PR with the same "Total coverage: X%" line pytest-cov prints, so the
number is visible without opening the Actions log. That comment is
best-effort (it silently no-ops on fork PRs, where `GITHUB_TOKEN` is
read-only) - the actual enforcement is the `fail_under` gate above, which
always runs.

This baseline covers the **unit** suite only. If/when the integration suite
(see below) starts running in CI, it should get its own coverage report
(e.g. `--cov-report=xml:coverage-integration.xml` in a separate job) rather
than being merged into this number - mixing them would make regressions in
either suite harder to see, and could inflate `app` coverage with paths only
ever hit by a live-Docker test run.

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

## Integration tests

The scripts under `app/tests/` (outside `unit/`) and at the repository root
are **not** an automated integration suite today - they're ad hoc manual
scripts, most with no assertions (they `print()` results for a human to
read), several requiring a live Docker daemon and/or a running Auto-Heal
service on `localhost:3131`, one (`test_uptime_kuma_api.py`) hard-coding a
plaintext password for a live Uptime Kuma instance, and one
(`test_proactive_scan.py`) that's empty. None of them use `pytest.mark.skip`
or otherwise degrade gracefully when their live dependency is missing - run
under plain `pytest`, most either error out or hang waiting on `input()`.
They are excluded from `testpaths` for exactly this reason.

To actually run a Docker-backed integration suite in GitHub Actions, the
following would be needed:

1. **Real pytest tests, not print scripts.** Each script needs rewriting
   with real `assert`s and automatic setup/teardown of whatever containers
   it creates, so a failure fails the run instead of scrolling past in
   stdout, and a re-run doesn't fail because a previous run's disposable
   container is still around.
2. **A place to put them that's clearly separate from the unit suite** -
   e.g. `app/tests/integration/`, collected by its own `pytest.ini`
   `testpaths`/marker and run as its own CI job, so a Docker-dependent
   failure never blocks the fast, Docker-free unit job (or is masked by it).
3. **Docker itself** - GitHub's `ubuntu-latest` runners already ship a
   working Docker Engine and don't need Docker-in-Docker; a job simply
   needs `/var/run/docker.sock` available, which it is by default. The
   harder part is credentials-free coverage of container recreation,
   restart counts, etc., which several of today's scripts already exercise
   in principle.
4. **No hard dependency on a live Uptime Kuma instance or outbound network
   calls** (`test_uptime_kuma_api.py` talks to a specific `localhost:3001`
   server with a hard-coded password; `test_notifications.py` posts to
   `https://httpbin.org`). A CI-safe version would need a disposable
   Uptime-Kuma container (e.g. as a GitHub Actions `services:` entry) or
   to be dropped/rescoped, and the plaintext credential removed regardless
   of where it ends up.
5. **A CI decision on scope**, since this is real, separate effort - not a
   one-line workflow change. An unmerged PR (#21, "convert legacy
   manual/integration scripts into a marked integration suite") already
   did most of item 1 and 2 above (moving genuinely-mocked scripts into
   `app/tests/unit/`, converting the rest into a `pytest`-skip-if-no-Docker
   `app/tests/integration/` suite), but deliberately left it running
   locally only - not wired into CI - judging Docker-in-CI not worth the
   added complexity for that change. Wiring a suite like that into a real
   CI job (item 3) and removing the live Uptime-Kuma/network dependency
   (item 4) is the remaining work; this PR does not attempt it, per the
   "don't replace integration tests with mocks just to make CI green"
   ground rule - that would mean either standing up real Docker/Uptime-Kuma
   in CI, or leaving these tests un-run and saying so, not faking them.

## CI

`.github/workflows/tests.yml` runs the unit suite with coverage on every
push to `main` and on every pull request, against the Python version
`FROM python:X.Y-slim` in the production `Dockerfile` (not a fixed version
and not a version matrix) - the Docker image is what actually ships, so
that's what CI tests against. A PR also gets a coverage summary comment;
see "Coverage baseline" above. Integration tests do not currently run in
CI - see "Integration tests" above.
