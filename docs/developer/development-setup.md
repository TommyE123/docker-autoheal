# Development Setup

## Prerequisites

- Python 3.11 or 3.12
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
[Frontend Development](frontend.md) for the full setup, including a port mismatch you
need to know about between the Vite dev server and the backend.

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

See [Testing](testing.md) for what's covered and how test isolation works.

## Linting

There is no configured Python linter/formatter in this repository at present. The
frontend has an `npm run lint` script (ESLint) but no ESLint configuration file yet — see
[Frontend Development](frontend.md#linting).

## Data directory when developing locally

Outside Docker, `ConfigManager` still targets `/data` first and falls back to `./data`
under the current working directory if `/data` isn't writable — so running `python -m
app.main` from the repo root will create a `./data/` directory there (already gitignored)
with `config.json`, `events.json`, etc.
