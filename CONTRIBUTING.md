# Contributing to Docker Auto-Heal

Thanks for your interest in contributing. This page gets you from a fresh clone to a
running dev environment and a passing test suite. Deeper technical detail — architecture,
project layout, frontend tooling, testing internals — lives under
[docs/developer/](docs/developer/).

## Ways to contribute

- Report bugs or propose features via [GitHub Issues](https://github.com/TommyE123/docker-autoheal/issues).
- Fix bugs or implement features and open a pull request.
- Improve documentation — see [docs/README.md](docs/README.md) for the documentation map.

## Getting set up

You'll need:

- Python 3.11 or 3.12
- Node.js 18+ and npm (only if you're working on the web UI)
- Docker (to run the service the way users do, and for integration testing)

Full setup instructions — installing dependencies, running the backend and frontend dev
servers, and building a local Docker image — are in
[docs/developer/development-setup.md](docs/developer/development-setup.md).

## Before opening a pull request

1. **Run the unit test suite:**
   ```bash
   pip install -r requirements-dev.txt
   pytest --cov=app --cov-report=term-missing
   ```
   See [docs/developer/testing.md](docs/developer/testing.md) for what's covered and how
   the test fixtures work.

2. **If you changed the frontend**, confirm the production build succeeds:
   ```bash
   cd frontend
   npm run build
   ```
   (`npm run lint` exists in `package.json` but has no ESLint config file yet, so it
   currently fails regardless of code changes — see
   [docs/developer/frontend.md](docs/developer/frontend.md#linting).)

3. **Keep documentation in sync.** If your change affects user-facing behavior
   (configuration fields, API endpoints, ports, labels), update the relevant page under
   [docs/user/](docs/user/) in the same PR.

4. CI (`.github/workflows/tests.yml`) runs the unit test suite on Python 3.11 and 3.12 for
   every pull request. It must pass before a PR can be merged.

## Pull request guidelines

- Keep changes focused — a PR that fixes one bug or adds one feature is easier to review
  than one that bundles several.
- Describe *why* a change is needed, not just what it does.
- Don't change configuration formats or application behavior purely for documentation or
  stylistic reasons.

## Project structure and architecture

See [docs/developer/project-structure.md](docs/developer/project-structure.md) and
[docs/developer/architecture.md](docs/developer/architecture.md) for how the codebase is
organized and how a monitoring cycle flows through it.

## Dependency updates

Dependencies are kept current by Renovate. See
[docs/maintainer/dependency-management.md](docs/maintainer/dependency-management.md) if
you need to understand how versions are pinned or how automerge is gated.
