# Browser Demo

The public demo at <https://tommye123.github.io/docker-autoheal/> is the real React UI
running against a simulated backend, entirely in the visitor's browser. There is no
server, no Docker daemon and no shared state: each visitor (and each browser tab) gets
its own simulation, and a refresh or **Reset demo** puts it back to the start.

## How it works

`npm run build:demo` (`vite build --mode demo`) builds the normal frontend with three
differences, all switched on by the `demo` mode:

- `src/main.jsx` loads `src/demo/index.jsx` instead of rendering the app directly, and
  doesn't register the service worker. The condition is a build-time constant, so the
  production build (`npm run build`) contains none of the demo code.
- `vite.config.js` sets the base path to `/docker-autoheal/` (the Pages sub-path),
  writes the build to `frontend/dist/` instead of `../static`, and disables
  `vite-plugin-pwa`.
- `src/demo/index.jsx` replaces the axios adapter on the shared API client
  (`src/services/api.js`) and on global axios, so every request the UI makes is
  answered in the browser. Above the app it renders a banner saying the environment is
  simulated, which version it shows, and the controls visitors use to break and fix
  containers.

| File                           | What it is                                                                                                                                                                                           |
|--------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `src/demo/engine.js`           | A small fake Docker host (containers that run, crash, crash-loop and fail health checks) and a port of the monitoring cycle that watches it: `monitoring_engine.py`, `selection.py` and `health.py`. |
| `src/demo/recovery.js`         | A port of `RecoveryPolicy` (`app/monitor/recovery.py`): cooldown, backoff, restart waits and quarantine release.                                                                                     |
| `src/demo/mockApi.js`          | The axios adapter: one handler per route in `app/api/routes/`, with the same response shapes, status codes and `{"detail": ...}` error bodies.                                                       |
| `src/demo/schema.js`           | Validates request data against the backend's JSON Schemas (`contract/schemas.json`) with Pydantic's lax conversion rules and error messages.                                                         |
| `src/demo/contract/`           | The backend's answers the demo is checked against in CI (see [Keeping it accurate](#keeping-it-accurate)).                                                                                           |
| `src/demo/default-config.json` | The backend's default configuration, `AutoHealConfig().model_dump(mode="json")`.                                                                                                                     |
| `src/demo/DemoBanner.jsx`      | The banner and the per-container controls.                                                                                                                                                           |

The simulation runs in real time. To make a full restart-to-quarantine cycle take about a
minute, the demo starts with shorter timings than the defaults (5s checks, 10s cooldown,
5s initial backoff, restart mode `both`). These are ordinary configuration values, shown
and editable on the Config page.

Some things can't be simulated and say so when used: notification tests report that
nothing was sent, and Uptime Kuma reports it isn't available.

## Keeping it accurate

The demo must not show behaviour the real service doesn't have, so CI checks it against
the backend. `app/tests/unit/test_demo_contract.py` computes the real backend's answers
and compares them with a stored copy in `frontend/src/demo/contract/`; `contract.test.js`
checks the demo against the same stored answers:

| File                | Holds                                                                                                                    | The demo must                                                    |
|---------------------|--------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------|
| `api-contract.json` | Every `/health` and `/api/*` route and method, and the `ContainerInfo` and `SystemStatus` fields                         | answer every route and return every field                        |
| `schemas.json`      | The configuration models' JSON Schemas                                                                                   | (used directly: `schema.js` validates request data against them) |
| `validation.json`   | Inputs for `AutoHealConfig`, `HealthCheckConfig` and `NotificationService`, with the real models' values or errors       | give the same value, or the same errors in the same order        |
| `scenarios.json`    | Timelines of container states, with the real monitoring engine's restarts, events and quarantine decisions at each check | make the same decisions                                          |

So a backend change that the stored cases cover fails CI until the demo copies it. The
cases cover every route and response field, the configuration models' schemas (an
unfamiliar schema keyword such as an `enum` fails `schema.test.js` until `schema.js`
supports it), the validation inputs in `validation.json`, and the restart timelines in
`scenarios.json`, including how containers are identified. Behaviour no case exercises,
such as custom health checks, maintenance mode or filters in the engine, isn't compared:
add a case when you change it. To bring the demo up to date:

1. Refresh the stored answers, then format them:

   ```bash
   UPDATE_DEMO_CONTRACT=1 pytest app/tests/unit/test_demo_contract.py
   cd frontend && npx prettier --write src/demo/contract
   ```

2. Review the diff, then change `engine.js`, `recovery.js` or `mockApi.js` until
   `npm test` passes. Validation usually needs no change, because it follows `schemas.json`.

To cover a new case, add its input to `validation.json` or a timeline to `scenarios.json`
and run step 1. The default configuration has its own check:
`app/tests/unit/test_demo_default_config.py` fails until `default-config.json` is
regenerated:

```bash
python -c 'import json; from app.config.config_manager import AutoHealConfig; print(json.dumps(AutoHealConfig().model_dump(mode="json"), indent=2))' > frontend/src/demo/default-config.json
```

A new API call in the UI also needs a handler, or the demo answers it with a 404 and the
smoke test fails.

## Running it locally

In the Dev Container, run **Terminal → Run Task → Autoheal: Run Demo** and open
`http://localhost:3133/docker-autoheal/` (hot reload; a page reload resets the simulation).
To see the production-style build instead:

```bash
cd frontend
npm run build:demo
npx vite preview --mode demo
# open http://localhost:4173/docker-autoheal/
```

## Testing

Unit tests sit next to each module in `src/demo/`. `e2e-demo/demo.spec.js` is a
Playwright smoke test of the built demo, which fails on any console error, so a UI call
the mock doesn't answer is caught:

```bash
cd frontend
npm run build:demo
npm run test:demo-e2e
```

It runs in CI on every pull request (`frontend-tests` in `tests.yml`) and before each
deployment. See [Testing](testing.md#browser-demo-smoke-test-playwright).

## Deployment

`.github/workflows/demo-pages.yml` builds the demo and deploys it to GitHub Pages. Each
deployment is listed in the repository's Deployments panel under the `github-pages`
environment.

- **When a release is published**, it deploys that release's tag.
- **Manually** (Actions → Demo (GitHub Pages) → Run workflow), it deploys the branch or
  tag picked in "Use workflow from": `main` to show merged work before the next release,
  or a release tag to go back to a release.

There is one demo, so each deployment replaces the last one. If the build or its smoke
test fails, nothing is deployed and the live demo stays as it was. The banner shows the release tag, or the
branch and short commit for anything else.

One-off repository setup:

1. **Settings → Pages → Build and deployment → Source:** GitHub Actions.
2. **Settings → Environments → `github-pages` → Deployment branches and tags:** add a
   tag rule for `v*`. Release deployments run from the release tag, and the
   environment's default rule only allows the default branch.
3. **Optional analytics:** to count visitors, add a site in Cloudflare Web Analytics and
   save its site token as the repository **variable** `CF_ANALYTICS_TOKEN` (Settings →
   Secrets and variables → Actions → Variables). The token is public: it ends up in the
   page. The beacon only records page views, sets no cookies and is added to the demo
   build only. Without the variable, the demo has no analytics.
