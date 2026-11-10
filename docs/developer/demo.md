# Browser Demo

The public demo at <https://tommye123.github.io/docker-autoheal/> is the real React UI
with sample data, running entirely in the visitor's browser. It's there so people can
see the layout and click around before installing. There is no server, no Docker and no
shared state: each visitor (and each browser tab) has its own copy, and a reload or
**Reset demo** starts again.

It is deliberately simple. The API calls the UI makes get fixed sample data and simple
changes to it (enable a container, clear the events, save a setting), but nothing is
validated and the monitoring engine isn't simulated: containers don't crash, restart or
get quarantined on their own. Notification tests and Uptime Kuma say they aren't
available in the demo.

## How it works

`npm run build:demo` (`vite build --mode demo`) builds the normal frontend with three
differences, all switched on by the `demo` mode:

- `src/main.jsx` loads `src/demo/index.jsx` instead of rendering the app directly, and
  doesn't register the service worker. The condition is a build-time constant, so the
  production build (`npm run build`) contains none of the demo code.
- `vite.config.js` sets the base path to `/docker-autoheal/` (the Pages sub-path),
  writes the build to `frontend/dist/` instead of `../static`, disables
  `vite-plugin-pwa` and leaves out the PWA manifest link.
- `src/demo/index.jsx` replaces the axios adapter on the shared API client
  (`src/services/api.js`) and on global axios, so every request the UI makes is
  answered in the browser, and renders a banner above the app.

| File                           | What it is                                                                                    |
|--------------------------------|-----------------------------------------------------------------------------------------------|
| `src/demo/mockApi.js`          | The sample data and a small handler for each API call the UI makes.                           |
| `src/demo/default-config.json` | The sample configuration (a copy of the backend's defaults, `AutoHealConfig().model_dump()`). |
| `src/demo/DemoBanner.jsx`      | The banner: says the data is sample data, shows the version, links to the install docs.       |

## Keeping it working

The demo only needs to keep the pages working, not to match the backend exactly. If the
UI starts calling a new API route, add a handler for it in `mockApi.js`; otherwise the
demo answers it with a 404, and the smoke test (below) fails on the console error. If a
page needs a new field, add it to the sample data.

## Running it locally

In the Dev Container, run **Terminal → Run Task → Autoheal: Run Demo** and open
`http://localhost:3133/docker-autoheal/` (hot reload; a page reload resets the sample data).
To see the production-style build instead:

```bash
cd frontend
npm run build:demo
npx vite preview --mode demo
# open http://localhost:4173/docker-autoheal/
```

## Testing

Unit tests sit next to each file in `src/demo/`. `e2e-demo/demo.spec.js` is a
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
