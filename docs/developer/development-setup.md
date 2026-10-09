# Development Setup

## Prerequisites

- Python 3 matching the version pinned in the `Dockerfile`'s `FROM python:X.Y-slim` line
  (CI tests against exactly that version, read dynamically from the Dockerfile — see
  [Testing](testing.md))
- Node.js 18+ and npm (only needed if you're touching the frontend)
- Docker and Docker Compose

Everything below can be installed by hand, or you can use the Dev Container, which
provides all of it pre-configured.

## Dev Container (recommended)

`.devcontainer/` defines a reproducible development environment. In VS Code with the
[Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
extension installed, open the repository and choose **Dev Containers: Reopen in
Container**. It also works as a GitHub Codespace.

The container provides:

- Python (matching the pinned base image in `.devcontainer/Dockerfile`) and Node.js 24
- Its own, isolated Docker daemon, via the `docker-in-docker` feature (see
  [Docker isolation](#docker-isolation))
- The GitHub CLI (`gh`). The `github/gh-aw` extension, for working on the agentic
  workflows, is not installed automatically: run **Autoheal: Install gh-aw** after
  `gh auth login` (see below)
- [mise](https://mise.jdx.dev), which installs the linter and security-scanning tools used
  by the Dev Container tasks at the versions pinned in `mise.toml` and `mise.lock`. The
  npm-based linters (markdownlint, prettier, stylelint and the rest) stay pinned in
  `.devcontainer/package.json`
- Shared VS Code settings, a shared set of installed VS Code extensions, and forwarded
  ports for the frontend (3000), the dev stack's UI/API (3132) and metrics (9091), and
  Playwright's UI (9323)

Application services are **not** started automatically — use the tasks below.

`postCreateCommand` runs `.devcontainer/post-create.sh`, which installs the dependencies
and tooling (`mise install --locked` for the pinned tools, then `mise prune` to remove
superseded versions). Three named Docker volumes keep downloads and installs across
rebuilds: `~/.cache` (the pip and npm caches, plus other tools' caches such as Trivy's
vulnerability database; npm is pointed at `~/.cache/npm` by `NPM_CONFIG_CACHE`), `gh`'s
data directory, and mise's tool installs. `.devcontainer/prepare-volumes.sh` makes them
writable by the container user. The container puts mise's shims on `PATH`, so the tasks
find the tools without activating mise.

### Cleaning up caches

Nothing purges the volumes automatically. mise's tool installs are the only part that
grows noticeably (about 800 MB in total, and roughly 300 MB more for each Semgrep version
bump), and `post-create.sh` already prunes them on every container creation. The pip and
npm caches are small (about 90 MB together) and only grow when dependency versions change;
other tools' caches under `~/.cache` also persist, so Trivy doesn't re-download its database
after every rebuild.
To reclaim space sooner, run these inside the container:

- `mise prune` removes superseded tool versions. Run it from the repository folder: it
  keeps only the versions that configurations mise has already seen require, so run
  anywhere else it can remove every installed tool until `mise install --locked` is run
  again.
- `pip cache purge` and `npm cache clean --force` empty the pip and npm caches. The next
  install downloads what it needs again.

To reset a volume completely, stop the container and remove the volume from the host with
`docker volume rm`. The volumes are `docker-autoheal-cache`, `docker-autoheal-gh-cache` and
`docker-autoheal-mise-data`; removing `docker-autoheal-cache` clears every cache under
`~/.cache` at once, and removing `docker-autoheal-mise-data` uninstalls the mise tools until
`mise install --locked` runs again. If you used an earlier version of this Dev Container,
its `docker-autoheal-pip-cache` and `docker-autoheal-npm-cache` volumes are no longer used
and can be removed the same way. The inner Docker daemon has its own volume,
`docker-autoheal-dind-<devcontainerId>`, which holds its images, volumes and containers; it
is not touched by these cleanups and is described under [Docker isolation](#docker-isolation).
Avoid running these cleanups while an install is in progress in another terminal.

### Tasks

`.vscode/tasks.json` wires the common workflows up to **Terminal → Run Task** (every
label is prefixed `Autoheal:`): running the backend and the frontend dev server, the unit
and integration suites, the frontend tests, the frontend build, starting and stopping
the app in Docker, and each linter and security scanner individually. The aggregate
entry points are **Run Local Checks**, **Check Python**, **Check Frontend**, **Check Shell
Scripts**, **Check Workflows**, **Check Markup and Data**, **Check Repository
Conventions** and **Run Security Scanners**.

**Autoheal: Run Docker Stack** builds the app from your checkout and runs it with
`docker compose -p docker-autoheal-dev -f docker-compose.yml -f docker-compose.dev.yml up --build autoheal`
(see [Running beside an existing deployment](#running-beside-an-existing-deployment)). The
`--build` flag is what makes `docker-compose.yml` build your changes instead of using the
published image. The result is tagged `docker-autoheal:dev` locally, so it does not replace
`tommye123/docker-autoheal:latest`. Open it at `http://localhost:3132` (VS Code forwards the port
to your desktop; see [Docker isolation](#docker-isolation) and the logging notes below).

**Autoheal: Run Playwright E2E Tests** starts the same dev stack in the background
(`up --build -d --wait`, which waits for the image's healthcheck), then runs
`npm run test:e2e` from `frontend/` against it, so the browser tests the Docker-served
app rather than the Vite dev server. It reads the published port back from Compose
(`3132` unless `AUTOHEAL_DEV_PORT` is set) and reaches it on `localhost`, because the
stack runs on the Dev Container's own Docker daemon and publishes its ports inside the
Dev Container. It removes the dev stack afterwards (printing its last logs first if the run failed), unless it was already running
when the task started, in which case it is left alone. Chromium
and its system libraries are installed by `post-create.sh`; after pulling this change into
an existing Dev Container, run **Dev Containers: Rebuild Container** once.

**Autoheal: Run Playwright E2E Tests (UI)** does the same setup but runs
`npm run test:e2e:ui`, which opens [Playwright's UI mode](https://playwright.dev/docs/test-ui-mode)
on port `9323`, so you can watch the browser run the smoke test with a timeline and
screenshots, and re-run it. Open the forwarded **Playwright UI** port (the Ports tab, or the
link in the terminal) in your browser. The task keeps running until you stop it (**Ctrl+C** in
its terminal), which also tears down the stack under the same rule as above. Rebuild the
Dev Container once to pick up the forwarded port.

**Autoheal: Install gh-aw** installs the `github/gh-aw` extension pinned to the
`compiler_version` recorded in the header of `.github/workflows/issue-triage.lock.yml`, so
recompiling the workflows doesn't churn the lock file. It needs `gh auth login` (or a
Codespaces token) first, replaces any installed copy, and is not part of any aggregate
task. The extension lives in the `gh` volume, so it survives rebuilds; run the task again
after the lock file is recompiled with a newer version.

**Autoheal: Stop Docker Stack** runs `docker compose down` with the same `-p` and `-f` options.
Stacks started with **Run Docker Stack** run on the Dev Container's own Docker daemon, so
they stop with the Dev Container and never appear on the host's daemon.

The tasks that need shell globbing run under `bash`, so outside the Dev Container they
need `bash` on `PATH` (Git Bash or WSL on Windows).

**Autoheal: Run Megalinter Cupcake** runs the same pinned MegaLinter image CI uses. It
mounts the current directory. Because the Dev Container has its own Docker daemon, the
container path is the path that daemon sees.

### Docker isolation

The Dev Container runs its own Docker daemon (the official `docker-in-docker` feature), so
Docker here is separate from the host's:

- Production containers on the host are **not** visible from the Dev Container. `docker ps`
  there lists only the Dev Container daemon's containers.
- Test containers created inside the Dev Container are **not** visible on the host's daemon,
  and nothing done to them can affect production containers.
- `/var/run/docker.sock` inside the Dev Container is the inner daemon's socket, so
  `docker-compose.yml`'s socket mount, the integration tests and the Compose tasks all use it.

Host-side commands are unchanged: `docker`, `docker compose` and `python -m app.main` run
on the host still use the host's (production) daemon. They are **not** made safe by this
setup and are not part of the isolated workflow. The isolated workflow is the Dev Container
(and Codespaces, which uses the same configuration).

**Trade-off.** Docker-in-Docker needs the Dev Container to run `privileged`. That is what
provides a separate daemon, but a privileged container has the usual host-escape
considerations, so only open this Dev Container with code you trust.

**Persistence.** The inner daemon's state (`/var/lib/docker`, which holds images, build
cache, named volumes and container metadata) lives in the named volume
`docker-autoheal-dind-<devcontainerId>` and survives rebuilds. That includes the containers
themselves: stopped containers are still there afterwards, and the dev stack, which inherits
`restart: unless-stopped` from `docker-compose.yml`, is brought back by its restart policy when
the Dev Container's daemon starts. Re-running `docker compose` (or the tasks) is safe, and
**Stop Docker Stack** removes it. Remove the volume from the host with `docker volume rm` to
discard the inner daemon's images, volumes and containers.

Relative bind mounts such as `./data-dev:/data` work as expected: the inner daemon runs in
the same container as the Compose client, so it sees your checkout.

To demonstrate the isolation, start the dev stack and run:

```bash
bash .devcontainer/verify-isolation.sh
```

It creates `autoheal-isolation-web` (an `nginx:alpine` container) and
`autoheal-isolation-victim` (an `alpine` container that exits with an error after a few
seconds, `--restart no`, labelled for the dev monitor), checks that the dev Autoheal restarts
the victim, and removes both. The probes are created on demand and are not part of any
Compose file. To confirm the other direction, run `docker ps` **on the host** while
the probes exist: neither appears, and the host's containers are unchanged.

**Migrating from the old setup.** Earlier versions used `docker-outside-of-docker`, which
left `docker-autoheal-dev` (and any other containers you created) running on the host
daemon. After rebuilding the Dev Container, remove them on the host once:
`docker rm -f docker-autoheal-dev` (and `docker compose -p docker-autoheal-dev down` from
a host shell if needed). The new Dev Container does not use or interact with them.

`.github/workflows/devcontainer.yml` builds the container and checks its tooling on pull
requests that touch it, and can also be run manually from the Actions tab.

## Backend

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt   # test dependencies

# Run directly against your local Docker socket
python -m app.main
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

### Running beside an existing deployment

`docker-compose.yml` fixes the container name (`docker-autoheal`) and host ports (`3131`,
`9090`), so it can't start on a Docker daemon that already runs an Autoheal deployment.
Add the dev override to run your checkout alongside it without touching the deployment:

```bash
docker compose -p docker-autoheal-dev -f docker-compose.yml -f docker-compose.dev.yml up --build -d
```

This uses the image `docker-autoheal:dev` (so `tommye123/docker-autoheal:latest` is not
replaced), the container name `docker-autoheal-dev`, the UI on `3132`, metrics on `9091`,
`./data-dev` for data, and its own Compose project, `docker-autoheal-dev`. Set
`AUTOHEAL_DEV_PORT` and `AUTOHEAL_DEV_METRICS_PORT` to change the ports. The override needs
Docker Compose v2.24.4 or later. Pass the same `-p` and `-f` options to `docker compose down`
to stop it.

Always pass `-p docker-autoheal-dev`. The `name:` in `docker-compose.dev.yml` is only a default:
Compose gives the `COMPOSE_PROJECT_NAME` environment variable precedence over it, so with that
variable set the stack would otherwise land in another project, and `docker compose down` could
remove that project's containers and networks. `-p` takes precedence over both.

The dev override sets the address shown in the startup logs to `localhost` and the published
port, so the logs print `Web UI available at http://localhost:3132` and
`API documentation available at http://localhost:3132/docs`. The application cannot know which
address anything else uses to reach it, so the override supplies this default (`AUTOHEAL_DEV_HOST`
overrides it, see below). With no host supplied, the app does not print a URL: it logs the
published port when `AUTOHEAL_PUBLIC_PORT` is set, otherwise just the listen address (for
example `Web UI listening on 0.0.0.0:3131`, as with the base `docker-compose.yml`).

**Inside the Dev Container (the isolated workflow)** that default is correct, so leave
`AUTOHEAL_DEV_HOST` unset and open `http://localhost:3132`. VS Code forwards port 3132 to your
desktop, so the same `http://localhost:3132` works in a browser on the machine running VS Code
(see the Ports tab). The inner Docker daemon publishes the port inside the Dev Container only:
it does not become a port on the Docker host's LAN address, so `http://<server-address>:3132`
does not reach the isolated dev stack, and the host's own `3131` is still production.

`AUTOHEAL_DEV_HOST` (passed to the app as `AUTOHEAL_PUBLIC_HOST`) only changes the address
printed in the startup logs, to `Web UI available at http://<value>:3132`. It does not expose,
publish or forward anything. Setting it to the server's address in the Dev Container would make
the logs advertise a URL that does not work, so don't. Compose reads a `.env` file next to
`docker-compose.yml` automatically, and the Dev Container mounts your checkout, so a `.env`
created for a host workflow also applies to the stack started inside the Dev Container. Delete
`AUTOHEAL_DEV_HOST` from it, or the file, if you see an unexpected URL in the logs.

The variable is only useful when you run this override from a host shell (not isolated: see
below), where the published port really is on the host's address. The default `localhost` is
right if you browse from that same host; from another machine, set it to the address you reach
the host at, in `.env` or the shell that runs the command:

```bash
echo 'AUTOHEAL_DEV_HOST=192.0.2.10' > .env
```

The log then shows `Web UI available at http://192.0.2.10:3132`. Nothing detects the address
for you, and the server still listens on `0.0.0.0:3131` inside the container. Outside this
override, `AUTOHEAL_PUBLIC_HOST` and `AUTOHEAL_PUBLIC_PORT` do the same job.

Inside the Dev Container the Docker socket belongs to the isolated inner daemon, so the
dev instance cannot see production containers at all. The override also seeds
`./data-dev/config.json` on first start with `monitor.label_key` set to `autoheal.dev`. Only
containers labelled `autoheal.dev=true` are discovered and auto-added; containers labelled
`autoheal=true` are not. Label your test containers accordingly.

The label is not the isolation boundary; it only controls automatic discovery. The boundary
is the separate Docker daemon (see [Docker isolation](#docker-isolation)). If you run this
override from a host shell instead, the dev instance shares the host's daemon, can see and
restart every container on it, and is not safe beside a production deployment.

An existing `./data-dev/config.json` is kept, so your own changes to the monitoring label
survive restarts; delete `./data-dev` to re-seed it. The container refuses to start, and logs
why, if the file is unreadable or its `monitor` section is invalid or still uses the production
`autoheal=true` label, or if the seed can't be written. Without that check the app would fall
back to its defaults and monitor `autoheal=true` containers.

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
pull request targeting `main`, covering Python, JavaScript, YAML, Dockerfile,
Markdown, and security checks provided by Ruff's `S` rules — see `.mega-linter.yml`
for the exact set. Several of those linters (`PYTHON_RUFF`,
`JAVASCRIPT_PRETTIER`, and others listed in `.mega-linter.yml`'s
`DISABLE_ERRORS_LINTERS`) currently have pre-existing findings and are configured not
to fail the build over them; they still run and report. There is no repository-wide Python
 formatter/import-sorter enforced beyond what MegaLinter reports.

Markdown *is* fully enforced — neither `MARKDOWN_MARKDOWNLINT` nor
`MARKDOWN_MARKDOWN_TABLE_FORMATTER` is in that disabled list, so every Markdown file must
pass both. `.linter-rules/.markdownlint.jsonc` turns off only `MD013` (line length) and
`MD060` (table pipe spacing), which conflict with this repo's established long-prose
style — everything else is at markdownlint's defaults. Run both locally before pushing
docs changes:

```bash
npx markdownlint-cli2 --config .linter-rules/.markdownlint.jsonc "**/*.md" "#node_modules" "#frontend/node_modules" "#.devcontainer/node_modules"
npx markdown-table-formatter --check "**/*.md"   # drop --check to auto-fix
```

In the Dev Container these are the **Autoheal: Check Markdown** and **Autoheal: Check
Markdown Tables** tasks, which lint tracked files only.

The frontend has `npm run lint` (ESLint) and `npm run format:check` (Prettier) scripts —
see [Frontend Development](frontend.md#linting-and-formatting).

Linter configuration is shared: the Dev Container tasks and MegaLinter both read it, so a
rule change applies in both places. MegaLinter's `LINTER_RULES_PATH` points at
`.linter-rules/`, which holds the Checkov, Trivy, markdownlint, yamllint, ls-lint, Ruff,
secretlint and Stylelint configuration and exceptions. The Dev Container tasks and editor settings pass
those paths explicitly, because these tools do not discover `.linter-rules/` on their own.
`.trufflehog-exclude.txt` there only applies to the local TruffleHog task: MegaLinter does
not read it. `.secretlintignore` stays at the repository root, because MegaLinter builds
its generated secretlint exclusion list only from the root copy. Configuration that must
stay beside the code it lints remains at the repository root (`pyrightconfig.json`,
`.editorconfig`) or in `frontend/` (`eslint.config.js`).

### What lints what

MegaLinter runs a different set of tools per file type, and only some of those tools are
formatters. `.vscode/settings.json` configures editor formatting and save-time lint fixes.
CSS uses Stylelint fixes on explicit save, while CI has no CSS formatter. Markdown uses
markdownlint fixes on explicit save; format-on-save is disabled because CI's table
formatter is CLI-only.

| File type       | Linters (CI)              | Formatter (CI)           | Fails the build?                       |
|-----------------|---------------------------|--------------------------|----------------------------------------|
| `.py`, `.pyi`   | pyright, ruff             | ruff-format              | No, report-only                        |
| `.js`, `.jsx`   | eslint                    | prettier                 | eslint: Yes; prettier: No, report-only |
| `.css`          | stylelint                 | none                     | No, report-only                        |
| `.json`         | jsonlint, v8r             | prettier                 | Yes                                    |
| `.yml`, `.yaml` | yamllint, v8r, actionlint | prettier                 | Yes                                    |
| `.md`           | markdownlint              | markdown-table-formatter | Yes                                    |
| `.html`, `.htm` | djlint, htmlhint          | none                     | Yes                                    |
| `.sh`           | shellcheck, bash-exec     | shfmt                    | Yes                                    |
| `Dockerfile*`   | hadolint                  | none                     | Yes                                    |
| Every file      | editorconfig-checker      | —                        | Yes                                    |

Workflow files are additionally scanned by zizmor, which is report-only. Repository-wide
scanners (checkov, semgrep, osv-scanner, trivy, trufflehog, betterleaks, secretlint,
ls-lint, git_diff) run against the project rather than a file type. The report-only
linters are the ones listed in `.mega-linter.yml`'s `DISABLE_ERRORS_LINTERS`.

The Dev Container installs an equivalent of each of these, so every row above has a
matching `Autoheal:` task. The binaries and Python tools are installed by mise from
`mise.toml`; the npm linters come from `.devcontainer/package.json`. editorconfig-checker
is exposed as `ec`, and reports its own version as 3.11.1 even though `mise.toml` pins the
3.11.2 release. shfmt reads indentation from `.editorconfig`, which is why the shell
scripts use two spaces.

To change a tool version, edit `mise.toml`, then run `mise lock --platform
linux-x64,linux-arm64` and commit `mise.lock` and the `.mise/locks/` directory with it.

## Data directory when developing locally

Outside Docker, `ConfigManager` still targets `/data` first and falls back to `./data`
under the current working directory if `/data` isn't writable — so running `python -m
app.main` from the repo root will create a `./data/` directory there (already gitignored)
with `config.json`, `events.json`, etc.
