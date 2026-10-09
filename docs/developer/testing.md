# Testing

## Overview

Unit tests live in `app/tests/unit/`. They run entirely against fakes and mocks:
**no Docker daemon and no running Auto-Heal service are required**, and no
external network calls are made. This is what CI runs.

An integration suite lives in `app/tests/integration/`. Those tests exercise a
real Docker daemon and/or a running Auto-Heal service (the dev stack on `http://localhost:3132`)
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

Coverage is reported to Codecov (see `.codecov.yml` and `.github/workflows/tests.yml`)
rather than enforced locally - `.coveragerc` no longer sets a `fail_under` floor.

Whether the tests would notice a change to the code, rather than merely execute it, is
measured separately by the informational mutation-testing workflow, which runs on pull
requests that change Python code, tests or the mutation tooling, and
on demand - see
[Mutation testing](mutation-testing.md). It is not part of `pytest` and is not a required
check.

## Running the integration suite

The integration suite requires a real Docker daemon reachable at the default
socket (`unix://var/run/docker.sock`), and some of its tests additionally
require a running Auto-Heal service on `http://localhost:3132` (the dev stack,
started with the **Autoheal: Run Docker Stack** task). Set `AUTOHEAL_BASE_URL` (and
`AUTOHEAL_METRICS_URL`, default `http://localhost:9091`) to test another instance. To test the
backend run directly with **Autoheal: Run Backend** (it listens on `3131`, metrics on `9090`,
inside the Dev Container), use `AUTOHEAL_BASE_URL=http://localhost:3131` and
`AUTOHEAL_METRICS_URL=http://localhost:9090`. In the
Dev Container, Docker is the isolated inner daemon, so these tests never touch production
containers; see [Docker isolation](development-setup.md#docker-isolation). Every test skips itself - rather than failing - when the
resource it needs isn't available, so it's safe to run with only some of those
resources present.

```bash
# Everything the daemon you have access to can run
pytest app/tests/integration

# Only the tests that need Docker but not a running service
pytest app/tests/integration/test_container_recreation.py app/tests/integration/test_restart_count.py

# Only the tests that need a running service (start the dev stack first)
pytest app/tests/integration/test_service_smoke.py app/tests/integration/test_auto_monitor.py
```

Every module in the directory sets `pytestmark = pytest.mark.integration`, so
`pytest -m integration <path>` works if you point pytest at a tree that
includes both suites.

| Area                                                           | File                           |
|----------------------------------------------------------------|--------------------------------|
| Container-ID-vs-stable-ID tracking across real recreation      | `test_container_recreation.py` |
| Native restart count after a policy-triggered restart          | `test_restart_count.py`        |
| Auto-discovery of containers with the service's monitor label  | `test_auto_monitor.py`         |
| `/health`, `/api/status`, the React UI, and Prometheus metrics | `test_service_smoke.py`        |

### Isolation against a real Auto-Heal instance

`AUTOHEAL_BASE_URL` may point at someone's real, already-running instance, not a
throwaway test fixture - these tests only do things a real user's actions
would also do, and undo the ones with lasting effect:

* Containers are uniquely named (`autoheal-*-<uuid>`) and force-removed by
  `disposable_container`, so they never collide with anything already running.
* `test_auto_monitor.py` labels its container with the running service's own
  configured monitor label (`autoheal.dev=true` for the dev stack) and removes the
  container it caused to be auto-selected from `containers.selected` afterward (via `GET`/`PUT /api/config` - not
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

### CI status

This suite is **not** run in CI. It needs a live Docker daemon and, for most
of its tests, a running Auto-Heal service - standing up Docker-in-Docker (or
an equivalent) for that was judged not worth the added CI complexity for now.
`.github/workflows/tests.yml` continues to run only the unit-test suite (see
above), unaffected by this suite's existence. Run the integration suite
locally before releases or when touching the areas above.

### Legacy script triage

The manual/demo scripts formerly under `app/tests/` and the repository root
were triaged as part of converting this suite:

| Script                                   | Outcome                                                                                                                                                                                                                                                                                                                                                                                                   |
|------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `app/tests/test_auto_monitor.py`         | Converted → `app/tests/integration/test_auto_monitor.py`                                                                                                                                                                                                                                                                                                                                                  |
| `app/tests/test_clear_events_api.py`     | Converted → `app/tests/unit/test_events_api.py` (calls the API functions directly against an isolated `config_manager`, so it never touches a real running instance's event log)                                                                                                                                                                                                                          |
| `app/tests/test_service.py`              | Converted → `app/tests/integration/test_service_smoke.py`                                                                                                                                                                                                                                                                                                                                                 |
| `app/tests/test_container_id_bug_fix.py` | Rewritten → `app/tests/integration/test_container_recreation.py`. The original script had a corrupted/unterminated docstring and was not valid Python (never actually ran); its regression scenario (restart/quarantine/monitoring state surviving container recreation) was rebuilt against a real Docker daemon.                                                                                        |
| `app/tests/test_clear_events.py`         | Converted to a unit test → `app/tests/unit/test_events_persistence.py`, since it only exercised `config_manager`'s event log with no Docker/service dependency once isolated from the real data directory.                                                                                                                                                                                                |
| `app/tests/test_auto_unquarantine.py`    | Moved as-is → `app/tests/unit/test_auto_unquarantine.py`. It already used mocks exclusively and needed no live Docker/service.                                                                                                                                                                                                                                                                            |
| `app/tests/test_init_defaults.py`        | Moved as-is → `app/tests/unit/test_init_defaults.py`. Pure filesystem/temp-dir test; already unit-test quality.                                                                                                                                                                                                                                                                                           |
| `app/tests/test_prometheus_start.py`     | Moved as-is → `app/tests/unit/test_prometheus_start.py`. Fully mocked; already unit-test quality.                                                                                                                                                                                                                                                                                                         |
| `app/tests/test_unquarantine_fix.py`     | Removed. It never called any application code - it demonstrated the bug/fix using local variables/sets, so moving it anywhere would add no regression coverage. The real behaviour (dual short/full-ID and name-based lookup) is covered by `test_container_recreation.py` and the existing unit suite.                                                                                                   |
| `test_notifications.py` (root)           | Converted to unit tests with a faked HTTP session → `app/tests/unit/test_notification_manager.py`. The original sent a real webhook to `https://httpbin.org/post`; nothing about the scenario (event filtering, webhook delivery, `test_notification`) actually required a live network call once the `aiohttp` session is faked.                                                                         |
| `test_proactive_scan.py` (root)          | Removed. The file was empty (a single blank line) with no test content to convert.                                                                                                                                                                                                                                                                                                                        |
| `test_restart_count.py` (root)           | Rewritten → `app/tests/integration/test_restart_count.py`. The original was a debug print script with no assertions, inspecting whatever containers already happened to be running on the host; rebuilt against a disposable container with an `on-failure` restart policy, so Docker itself performs a real restart and increments `RestartCount` (a manual `container.restart()` does not - see below). |
| `test_uptime_kuma_api.py` (root)         | Removed. It hard-coded a plaintext password for a local Uptime-Kuma instance directly in the script - a credential-hygiene problem independent of the live-service dependency. Uptime-Kuma integration is not currently covered by either suite; re-adding coverage should read credentials from environment variables rather than hard-coding them.                                                      |

## What is covered

The suite focuses on the monitoring engine and its restart/recovery behaviour:

| Area                                                                                | File                            |
|-------------------------------------------------------------------------------------|---------------------------------|
| Stable identifier and monitoring selection/filters                                  | `test_monitoring_identity.py`   |
| Health evaluation (exit codes, Docker health, custom checks, Uptime-Kuma)           | `test_health_evaluation.py`     |
| Cooldown, thresholds, quarantine, backoff, restart success/failure, alerts          | `test_restart_handling.py`      |
| Per-cycle checks, quarantine skip/auto-unquarantine, disappearance, Docker failures | `test_container_checks.py`      |
| Start/stop, monitor loop, event listener, auto-discovery                            | `test_engine_lifecycle.py`      |
| Docker client wrapper boundary behaviour                                            | `test_docker_client_wrapper.py` |

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

## Frontend

There is currently no automated frontend test suite. `npm run lint` (ESLint) is defined in
`frontend/package.json`, but there's no ESLint configuration file yet, so it doesn't
currently run successfully — see [Frontend Development](frontend.md#linting).

## UI E2E suite (Playwright)

A Playwright suite in `frontend/e2e-ui/` drives the real UI through real user journeys:
containers, monitoring, events, configuration and notifications, in Chromium. It is the
repository's only browser test suite. It replaced the earlier single-dashboard smoke test;
that check is now the `@smoke` test "the app starts on the containers dashboard". Tests are
selected by tag (see [Tags](#tags)).

The same specs run in two places, which differ in the instance they test and in who starts
it:

|               | CI                                                                          | Development                                                  |
|---------------|-----------------------------------------------------------------------------|--------------------------------------------------------------|
| Runs against  | The exact image `docker-build.yml` built for the commit (`sha-<short sha>`) | The dev stack from `docker-compose.dev.yml`, port `3132`     |
| Started by    | `production-smoke-test.yml`, which sets `UI_E2E_BASE_URL`                   | `frontend/e2e-ui/run.sh` (the **Autoheal: Run UI E2E** task) |
| Docker daemon | The GitHub-hosted runner's own, ephemeral daemon                            | The Dev Container's own Docker-in-Docker daemon              |
| Scope         | `full`, the whole suite, on every pull request                              | Your choice                                                  |
| Image         | The one built by that CI run; nothing is rebuilt                            | Built from your checkout; no published image is needed       |

Both use `playwright.ui.config.js` and the same `frontend/e2e-ui/run.sh`, so a CI failure
reproduces locally with the same scope. The base URL has its own variable,
`UI_E2E_BASE_URL` (default `http://localhost:3132`), so a stray environment value cannot
aim this suite at a production instance.

### Environment

The suite needs a Docker daemon of its own and an instance of the app that monitors
`autoheal.dev=true`:

* **Development**: the Dev Container (or Codespaces), where Docker is the isolated
  Docker-in-Docker daemon from [Docker isolation](development-setup.md#docker-isolation)
  (#460), and the dev stack from `docker-compose.dev.yml`, which `frontend/e2e-ui/run.sh`
  starts (and removes afterwards if it started it) at `http://localhost:3132`. Chromium is
  installed by `post-create.sh`.
* **CI**: the GitHub-hosted runner, whose Docker daemon is that ephemeral VM's own. The
  workflow refuses to continue on anything but a GitHub-hosted runner, and starts a
  throwaway instance of the built image on port `3132` with its own `/data` seeded with
  the `autoheal.dev` label.

Docker-backed tests create a few small, labelled `alpine` containers on that daemon and
remove them afterwards. Before the first Docker command the suite checks that the daemon
is the environment's own (the same checks as `.devcontainer/verify-isolation.sh`: no
`DOCKER_HOST` or `DOCKER_CONTEXT`, a `dockerd` process, and a daemon name equal to the
hostname) and that the app under test monitors `autoheal.dev=true`, and it refuses to
continue otherwise, so it cannot act on a host or production daemon. `run.sh` makes the
daemon check too, before it starts anything and also when `UI_E2E_BASE_URL` points at an
instance it did not start. The app check runs before every test, because even the tests
that need no Docker (configuration, notifications) change the app's state; only the
Docker daemon check is skipped for them. Neither check is relaxed for CI.

### Running it

In VS Code, run **Terminal → Run Task → Autoheal: Run UI E2E** and pick a scope and a
mode. From a terminal in the Dev Container:

```bash
bash frontend/e2e-ui/run.sh smoke          # the pull-request subset, headless
bash frontend/e2e-ui/run.sh full headless  # everything
bash frontend/e2e-ui/run.sh events ui      # one area, in Playwright's UI mode
```

The scope is `smoke`, `full`, or a functional tag below. The task's menu words these in plain
language ("Quick check of the basics", "Everything", "The event log" and so on); the script takes
the short names. The mode is one of two:

* `headless` ("In the background, no window"; the default): what CI runs. Fast, and nothing to
  watch.
* `ui` ("Watch and debug in a browser panel"): Playwright's UI mode, served on forwarded port
  9323 and opened in your own browser. You can watch each test run with a live view of the page,
  a timeline and screenshots, pause, step through and re-run single tests. This is the way to
  watch or debug a run.

Every mode runs the same specs. To run against an instance that is already running (the
dev stack you started yourself, or another instance that monitors `autoheal.dev=true`),
set `UI_E2E_BASE_URL`. `run.sh` then starts nothing; it still makes the Docker isolation
checks and applies the scope:

```bash
UI_E2E_BASE_URL=http://localhost:3132 bash frontend/e2e-ui/run.sh smoke
```

or use Playwright directly:

```bash
cd frontend
UI_E2E_BASE_URL=http://localhost:3132 UI_E2E_TAG=@events npm run test:ui-e2e
UI_E2E_BASE_URL=http://localhost:3132 npm run test:ui-e2e:smoke
```

Select by tag with `UI_E2E_TAG`, not `--grep`: Playwright does not apply `--grep` to a
dependency project, so `--grep @events` would also run every `parallel` test. `@smoke`
tests must live in `parallel/`, which is all `test:ui-e2e:smoke` runs. The `full` scope
unsets an inherited `UI_E2E_TAG`, so it always runs the whole suite.

### Tags

Tags select tests and are not mutually exclusive: one test can be
`@smoke @containers @regression`.

| Tag                                                                         | Meaning                                                                                   |
|-----------------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| `@smoke`                                                                    | The small pull-request subset: is the UI fundamentally working? Keep it small and stable. |
| `@regression`                                                               | Tests that guard a specific past or likely regression.                                    |
| `@containers`, `@monitoring`, `@events`, `@configuration`, `@notifications` | Functional areas                                                                          |
| `@errors`                                                                   | Loading, empty and failure handling, using `page.route` to fail one API call              |

### Parallelism and shared state

The app keeps one set of state in `/data` (configuration, notification services, the
event log), so tests are split into two Playwright projects:

* `parallel` (`e2e-ui/parallel/`): fully parallel. Tests either read a small set of
  containers shared by the whole run (running and monitored, running and unmonitored,
  unhealthy, exited) or create a container of their own, with a unique name.
* `exclusive` (`e2e-ui/exclusive/`): tests that change shared state, such as saving
  configuration, editing notification services or clearing the event log. It runs one
  worker at a time and only after `parallel` has passed, so nothing reads that state
  while it changes. The app configuration is snapshotted before each test and restored
  after it. The event log cannot be restored through the API; it only holds the dev
  stack's own events, and **Clear All** empties it.

Put a new test in `exclusive/` if it changes anything a test in another file could see.
`--no-deps --project=exclusive` runs that group alone. Because it depends on `parallel`,
a failure there skips it.

Run one UI E2E at a time per Dev Container: starting a run removes leftover containers
of earlier runs, which would also remove those of a run still in progress (for example
Playwright's UI mode left open while the task runs in a terminal).

Containers carry the label `autoheal.e2e.run=<run id>`. Global teardown removes them and
the configuration entries Autoheal made for them; the next run also removes any left over
by an interrupted one.

### Tests waiting on other work

A test for behaviour that is not on `main` yet is written now and marked `test.fixme()`,
so it shows as skipped in every report. When the blocking change merges, remove the
`fixme` and leave the assertions alone:

* #455: the empty-state alert covering the Add Service modal (`notifications.spec.js`)
* #431: the Events page filters (`events.spec.js`)

### CI

The suite runs in the "Production container smoke test" job (`production-smoke-test.yml`),
called from `docker-build.yml`, against the exact image that run built. There is no separate UI E2E
workflow. The job, for the same-repository pull requests that `docker-build.yml` pushes an
image for:

1. pulls `ghcr.io/<owner>/docker-autoheal:sha-<short sha>`, the `image_ref` output of the
   build job (not `pr-<N>`, not `latest`);
2. starts a throwaway container from it with its own `/data` seeded with the `autoheal.dev`
   label;
3. waits until `/health` responds, `/api/status` reports `docker_connected`, and
   `/api/config` reports the label;
4. runs `bash frontend/e2e-ui/run.sh full headless` against it with `UI_E2E_BASE_URL`
   set.

CI always runs the **`full`** suite, on every pull request including the Release Please PR.
There is no CI scope switch; the `smoke` subset and the functional tags are for local runs.

Any failing step fails the job. `run.sh` exits with 3 when the environment cannot be used
(including a failed isolation check) and 1 when a test fails; the log annotation says which. On
failure the Playwright HTML report, traces and screenshots are uploaded as the
`ui-e2e-report` artifact, and the diagnostics step prints the container's logs.
The real auto-heal restart of a failing container is covered by the suite itself
(@events: "Autoheal restarts a container that exits and logs the restart"). Whether the job blocks a merge depends on the repository's
branch-protection required checks.

Nothing in CI uses the development stack or `docker-compose.dev.yml`; that is the local
workflow above.

### Writing tests

Use role, text and label locators and wait for visible UI state, never fixed sleeps or
`networkidle`. Keep each test independent. Use `page.route` only to make one API call fail
or stall; the app itself is never faked. The settings forms and the modals do not yet link
labels to inputs or give dialogs accessible names, so those are found by role within their
form and by title (`dialogTitled`).

## CI

`.github/workflows/tests.yml` runs the unit suite with coverage on every push
to `main` and on every pull request, against the Python version the
production `Dockerfile` uses (read from its `FROM python:X.Y-slim` line), so
CI tests the runtime that actually ships. Coverage output is reported in the
GitHub Actions job log.
