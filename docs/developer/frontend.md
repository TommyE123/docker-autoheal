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

## Project structure

```text
frontend/
├── public/                  # Static assets (icons, PWA manifest source, screenshots)
├── src/
│   ├── components/          # Page components (Dashboard, ContainersPage, EventsPage,
│   │                         #  ConfigPage, NotificationsPage, ...) and config/ subforms
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
- **React 18**
- **React Router** — client-side routing (the backend has a catch-all route that serves
  `index.html` for any non-API path so deep links and refreshes work)
- **react-bootstrap** / **Bootstrap 5** — UI components
- **Axios** — HTTP client (`src/services/api.js`)
- **date-fns** — date formatting

`vite-plugin-pwa` is listed as a devDependency but is **not** currently registered as a
Vite plugin in `vite.config.js` — it has no effect on the current build. If you wire it up,
note that its `workbox-build` dependency declares `engines.node >= 20`, while the
project's Docker build stage uses Node 18 — see
[Dependency Management](../maintainer/dependency-management.md) for the details.

## Linting

`package.json` defines `npm run lint` (ESLint, with dependencies already in
`devDependencies`), but there is currently **no ESLint configuration file** in
`frontend/` — running it fails with "ESLint couldn't find a configuration file" until one
is added.

## Docker build

The main `Dockerfile` builds the frontend in its first stage (Node 18) and copies the
output into the final Python image — see [Architecture](architecture.md). You don't need
Node.js installed locally to build or run the published image; it's only needed for
frontend development.
