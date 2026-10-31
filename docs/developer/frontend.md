# Frontend Development

The web UI is a single React application built with Vite, living in `frontend/`. It is
the **only** UI the application ships — there is no separate "simple HTML" fallback in
the current codebase (older documentation describing one was referring to an earlier,
now-removed implementation).

## Setup

```bash
cd frontend
npm install
npm run dev
```

This starts the Vite dev server on **`http://localhost:3000`**, with hot module
replacement.

The Vite dev server proxies `/api` and `/health` requests to `http://localhost:3131`
(`frontend/vite.config.js`), matching the backend's default listen port (see
[Configuration](../user/configuration.md)), so it works against a locally running backend
with its defaults.

## Development workflow

```bash
# Terminal 1: backend
python -m app.main

# Terminal 2: frontend dev server
cd frontend
npm run dev
```

Edit files under `frontend/src/`; changes hot-reload in the browser at
`http://localhost:3000`.

## Building for production

```bash
cd frontend
npm run build
```

This runs `vite build`, which outputs to `../static` (i.e. `<repo root>/static/`, per
`build.outDir` in `vite.config.js`) — the directory the FastAPI backend serves as the web
UI. `static/` is gitignored; it's generated at build time (or inside the Docker multi-stage
build) rather than committed.

To see the production build served by the actual backend:

```bash
cd frontend && npm run build
cd ..
python -m app.main
# open http://localhost:3131
```

## PWA

`vite-plugin-pwa` (configured in `vite.config.js`) generates `sw.js` and a `workbox-*.js`
runtime into `static/` during `npm run build`; `src/main.jsx` registers the worker with
`registerSW` from `virtual:pwa-register`. The manifest is the hand-maintained
`public/manifest.json` (`manifest: false` in the plugin config), and FastAPI serves
`manifest.json`, `sw.js` and `workbox-*.js` from the root (`app/api/routes/ui.py`).

- `registerType: "autoUpdate"` with `skipWaiting`/`clientsClaim`: a new build activates
  immediately and reloads open pages, and `cleanupOutdatedCaches` drops old precaches.
- Only the app shell is precached. `/api/*` uses a `NetworkOnly` runtime rule and is
  excluded from the navigation fallback (as is `/health`), so API data is never cached
  and failed API calls are never answered with cached data or `index.html`. There is no
  offline support.
- `e2e-ui/parallel/pwa.spec.js` (`@pwa`) checks the service worker, Cache Storage, installability and
  offline `/api/*` behaviour against the production image; see `docs/developer/testing.md`.
- Tests resolve `virtual:pwa-register` to `src/test/pwa-register-stub.js` (`test.alias`).
- The service worker only exists in production builds. Check changes against
  `npm run build` served by the backend, not `npm run dev`.

## Project structure

```text
frontend/
├── public/                  # Static assets (icons, PWA manifest source, screenshots)
├── src/
│   ├── components/          # Page components (Dashboard, ContainersPage, EventsPage,
│   │                         #  ConfigPage, NotificationsPage, ...) and config/ subforms
│   ├── constants/            # Shared constants (EVENT_TYPES)
│   ├── hooks/                # Shared React hooks (useAlert, useConfigValidation)
│   ├── services/api.js       # Axios client — one function per backend endpoint
│   ├── styles/App.css
│   ├── App.jsx                # Routes and top-level layout
│   └── main.jsx                # Entry point
├── index.html
├── package.json
└── vite.config.js
```

## Stack

- **Vite** — dev server and build tool
- **React 19**
- **React Router** — client-side routing (the backend has a catch-all route that serves
  `index.html` for any non-API path so deep links and refreshes work)
- **react-bootstrap** / **Bootstrap 5** — UI components
- **Axios** — HTTP client (`src/services/api.js`)
- **date-fns** — date formatting

## Linting and formatting

- `npm run lint` — ESLint (`frontend/eslint.config.js`), covering JS/JSX code quality
  (correctness, React/JSX and React Hooks rules). ESLint does not enforce formatting;
  `eslint-config-prettier` disables the handful of stylistic rules that would otherwise
  conflict with Prettier.
- `npm run format` — Prettier, formats `src/**/*.{js,jsx}`.
- `npm run format:check` — Prettier, checks the same scope without writing changes.

These also run in CI via MegaLinter (`JAVASCRIPT_ES` and `JAVASCRIPT_PRETTIER`, scoped to
`frontend/`). ESLint errors fail the MegaLinter check. Prettier still has pre-existing
findings across `src/` that predate this tooling being wired up, so it is configured to
report them without failing the build (see `.linter-rules/.mega-linter.yml`'s `DISABLE_ERRORS_LINTERS`);
fix those incrementally rather than in one mass reformat.

### React lint rules

React/JSX rules come from `@eslint-react/eslint-plugin`, which replaced `eslint-plugin-react`
when ESLint moved to version 10 (`eslint-plugin-react` 7.x does not support ESLint 10). Its
`recommended` preset is not used: it overlaps with `eslint-plugin-react-hooks` and would add
many new rules at once. `eslint.config.js` instead enables the replacement for each
`eslint-plugin-react` rule the config used to enable (`recommended` plus `jsx-runtime`, with
`react/prop-types` off):

| `eslint-plugin-react` rule | Replacement                                                                                                                                                       | Status                                                                                                                                                                                                                                                                                            |
|----------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `display-name`             | `@eslint-react/no-missing-component-display-name`                                                                                                                 | Partial: only anonymous components wrapped in `memo` or `forwardRef` are reported; an anonymous default-exported function component is no longer an error. Accepted: `react-refresh/only-export-components` still warns on it, and `src/` has none                                                |
| `jsx-key`                  | `@eslint-react/no-missing-key`                                                                                                                                    | Direct equivalent                                                                                                                                                                                                                                                                                 |
| `jsx-no-comment-textnodes` | `@eslint-react/jsx-no-comment-textnodes`                                                                                                                          | Direct equivalent                                                                                                                                                                                                                                                                                 |
| `jsx-no-duplicate-props`   | `local/jsx-no-duplicate-props` (`frontend/eslint-rules/`)                                                                                                         | Custom rule: `@eslint-react` leaves this to the TypeScript compiler, and this frontend is plain JavaScript. It is a plain ESLint rule rather than one built with `@eslint-react/kit`: the kit is in beta and its helpers detect components and hooks, which an attribute-name check does not need |
| `jsx-no-target-blank`      | `@eslint-react/dom-no-unsafe-target-blank`                                                                                                                        | Partial: dynamic `href` values are no longer reported, and `rel="noopener"` without `noreferrer` is now accepted. Accepted: the one `target="_blank"` link is internal, and browsers now imply `noopener` for `target="_blank"`                                                                   |
| `jsx-no-undef`             | core `no-undef`                                                                                                                                                   | Direct equivalent: ESLint 10 tracks JSX references                                                                                                                                                                                                                                                |
| `jsx-uses-vars`            | core `no-unused-vars`                                                                                                                                             | Direct equivalent: ESLint 10 tracks JSX references                                                                                                                                                                                                                                                |
| `no-children-prop`         | `@eslint-react/jsx-no-children-prop`, `@eslint-react/jsx-no-children-prop-with-children`                                                                          | Direct equivalent (split across two rules)                                                                                                                                                                                                                                                        |
| `no-danger-with-children`  | `@eslint-react/dom-no-dangerously-set-innerhtml-with-children`                                                                                                    | Direct equivalent                                                                                                                                                                                                                                                                                 |
| `no-deprecated`            | `@eslint-react/no-component-will-mount`, `no-component-will-receive-props`, `no-component-will-update`, `dom-no-render`, `dom-no-hydrate`, `dom-no-find-dom-node` | Partial: `createClass`, `React.PropTypes`, `React.DOM`, `unmountComponentAtNode` and `renderToNodeStream` are not reported. Accepted: React 19 removed them, so using one fails at import or in tests                                                                                             |
| `no-direct-mutation-state` | `@eslint-react/no-direct-mutation-state`                                                                                                                          | Direct equivalent                                                                                                                                                                                                                                                                                 |
| `no-find-dom-node`         | `@eslint-react/dom-no-find-dom-node`                                                                                                                              | Direct equivalent                                                                                                                                                                                                                                                                                 |
| `no-is-mounted`            | None                                                                                                                                                              | No equivalent. Accepted: `isMounted` only existed on `createClass` components, which React 19 removed                                                                                                                                                                                             |
| `no-render-return-value`   | `@eslint-react/dom-no-render-return-value`                                                                                                                        | Direct equivalent                                                                                                                                                                                                                                                                                 |
| `no-string-refs`           | None                                                                                                                                                              | No equivalent. Accepted: React 19 removed string refs, and the only class component is a test fixture                                                                                                                                                                                             |
| `no-unescaped-entities`    | Parser                                                                                                                                                            | Partial: a raw `>` or `}` in JSX text is now a parsing error; stray quotes and apostrophes, which are only stylistic, are no longer reported                                                                                                                                                      |
| `no-unknown-property`      | `@eslint-react/dom-no-unknown-property`                                                                                                                           | Direct equivalent                                                                                                                                                                                                                                                                                 |
| `require-render-return`    | None                                                                                                                                                              | No equivalent. Accepted: the only class component is a test fixture, and a `render()` that returns nothing shows up as an empty component in tests                                                                                                                                                |

The rules the old config had off (`jsx-uses-react`, `react-in-jsx-scope`, `no-unsafe` and
`prop-types`) have no replacement enabled. Both plugins were never needed at the same time,
so there was no period of running them side by side.

## Docker build

The main `Dockerfile` builds the frontend in its first stage (Node 26) and copies the
output into the final Python image — see [Architecture](architecture.md). You don't need
Node.js installed locally to build or run the published image; it's only needed for
frontend development.
