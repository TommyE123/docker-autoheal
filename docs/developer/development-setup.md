# Development Setup

## Prerequisites

- Python 3 matching the version pinned in the `Dockerfile`'s `FROM python:X.Y-slim` line
  (CI tests against exactly that version, read dynamically from the Dockerfile — see
  [Testing](testing.md))
- Node.js 18+ and npm (only needed if you're touching the frontend)
- Docker and Docker Compose

## Backend

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt   # test dependencies

# Run directly against your local Docker socket
python -m app.main
# or the convenience wrapper:
python run.py
```

The backend listens on `0.0.0.0:3131` by default (`ui.listen_port` in
[Configuration](../user/configuration.md)) and needs access to `/var/run/docker.sock` to
do anything useful. Running it outside a container works fine on Linux/macOS as long as
your user can read the Docker socket.

Prometheus metrics, when enabled, are served separately on port `9090`.

## Frontend

The web UI is a Vite + React app in `frontend/`. See
[Frontend Development](frontend.md) for the full setup.

## Running the full stack with Docker

```bash
docker compose up --build
```

This builds the frontend and backend into a single image (see
[Architecture](architecture.md)) and runs it the same way an end user would, on port
`3131`.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest --cov=app --cov-report=term-missing
```

That runs the unit suite only (per `pytest.ini`'s `testpaths`) — no Docker daemon needed.
There's also an integration suite that exercises a real Docker daemon and, for some
tests, a running Auto-Heal instance; it's not run by a plain `pytest` and not run in CI.
See [Testing](testing.md) for what's covered, how to run the integration suite, and how
test isolation works.

## Linting

`.github/workflows/mega-linter.yml` runs [MegaLinter](https://megalinter.io/) on every
pull request targeting `main`, covering Python, JavaScript, YAML, Dockerfile, Markdown,
and several security scanners in one pass — see `.mega-linter.yml` for the exact set.
Several of those linters (`PYTHON_PYLINT`, `PYTHON_FLAKE8`, `PYTHON_RUFF`,`JAVASCRIPT_ES`,
`JAVASCRIPT_PRETTIER`, and others listed in `.mega-linter.yml`'s `DISABLE_ERRORS_LINTERS`)
currently have pre-existing findings and are configured not to fail the build over them;
they still run and report. There is no repository-wide Python formatter/import-sorter
enforced beyond what MegaLinter reports.

Markdown *is* fully enforced — neither `MARKDOWN_MARKDOWNLINT` nor
`MARKDOWN_MARKDOWN_TABLE_FORMATTER` is in that disabled list, so every Markdown file must
pass both. `.markdownlint.jsonc` at the repo root turns off only `MD013` (line length) and
`MD060` (table pipe spacing), which conflict with this repo's established long-prose
style — everything else is at markdownlint's defaults. Run both locally before pushing
docs changes:

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules" "#frontend/node_modules"
npx markdown-table-formatter --check "**/*.md"   # drop --check to auto-fix
```

The frontend has `npm run lint` (ESLint) and `npm run format:check` (Prettier) scripts —
see [Frontend Development](frontend.md#linting-and-formatting).

## Data directory when developing locally

Outside Docker, `ConfigManager` still targets `/data` first and falls back to `./data`
under the current working directory if `/data` isn't writable — so running `python -m
app.main` from the repo root will create a `./data/` directory there (already gitignored)
with `config.json`, `events.json`, etc.
