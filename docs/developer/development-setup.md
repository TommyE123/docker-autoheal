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
- Access to the host's Docker daemon, via the `docker-outside-of-docker` feature
- The GitHub CLI (`gh`). The `github/gh-aw` extension, for working on the agentic
  workflows, is not installed automatically: run **Autoheal: Install gh-aw** after
  `gh auth login` (see below)
- [mise](https://mise.jdx.dev), which installs the linter and security-scanning tools used
  by the Dev Container tasks at the versions pinned in `mise.toml` and `mise.lock`. The
  npm-based linters (markdownlint, prettier, stylelint and the rest) stay pinned in
  `.devcontainer/package.json`
- Shared VS Code settings, a shared set of installed VS Code extensions, and forwarded
  ports for the frontend (3000), API (3131) and metrics (9090)

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
and can be removed the same way. Avoid running these cleanups while an install is in
progress in another terminal.

### Tasks

`.vscode/tasks.json` wires the common workflows up to **Terminal → Run Task** (every
label is prefixed `Autoheal:`): running the backend and the frontend dev server, the unit
and integration suites, the frontend tests, the frontend build, starting and stopping
the app in Docker, and each linter and security scanner individually. The aggregate
entry points are **Run Local Checks**, **Check Python**, **Check Frontend**, **Check Shell
Scripts**, **Check Workflows**, **Check Markup and Data**, **Check Repository
Conventions** and **Run Security Scanners**.

**Autoheal: Run Docker Stack** builds the app from your checkout and runs it with
`docker compose up --build autoheal`. The `--build` flag is what makes
`docker-compose.yml` build your changes instead of using the published image. The result is
tagged `tommye123/docker-autoheal:latest` locally, replacing any copy you had pulled; run
`docker compose pull` to get the published image back.

**Autoheal: Install gh-aw** installs the `github/gh-aw` extension pinned to the
`compiler_version` recorded in the header of `.github/workflows/issue-triage.lock.yml`, so
recompiling the workflows doesn't churn the lock file. It needs `gh auth login` (or a
Codespaces token) first, replaces any installed copy, and is not part of any aggregate
task. The extension lives in the `gh` volume, so it survives rebuilds; run the task again
after the lock file is recompiled with a newer version.

**Autoheal: Stop Docker Stack** runs `docker compose down`.
Stacks started with **Run Docker Stack** run on the host's Docker daemon (see below), so
they keep running when the Dev Container stops or is rebuilt until you stop them.

The tasks that need shell globbing run under `bash`, so outside the Dev Container they
need `bash` on `PATH` (Git Bash or WSL on Windows).

**Autoheal: Run Megalinter Cupcake** runs the same pinned MegaLinter image CI uses. It
mounts `$LOCAL_WORKSPACE_FOLDER` — set by `devcontainer.json` to the *host* path of your
checkout — rather than the container path, because the Docker daemon is the host's (see
below). Without that it would mount an empty directory, lint nothing, and pass.

### Docker Compose inside the Dev Container

`docker compose` talks to the Docker daemon through the `docker-outside-of-docker`
feature — the daemon is the host's, not the container's. Relative bind mounts in
`docker-compose.yml` (e.g. `./data:/data`) are resolved by the
Compose client to the container's path and handed to the host daemon as-is, which has no
such path and silently creates an empty directory there instead of binding your checkout.
The stack still starts and passes its health check, but persisted data (config, events,
logs) won't be visible in your working copy — use `docker compose logs`/`docker exec` to
inspect it instead. If the mount does resolve (for example when running Compose from the
host), the stack reads and writes the same `./data` a deployment from that checkout would
use, and stopping the stack doesn't revert changes made to it.

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

Inside the Dev Container this comes with a caveat — see
[Docker Compose inside the Dev Container](#docker-compose-inside-the-dev-container).

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
`JAVASCRIPT_ES`, `JAVASCRIPT_PRETTIER`, and others listed in `.mega-linter.yml`'s
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
`.linter-rules/`, which holds the Checkov, Trivy, markdownlint, yamllint, ls-lint and Ruff
configuration and exceptions. The Dev Container tasks and editor settings pass those paths
explicitly, because these tools do not discover `.linter-rules/` on their own. Configuration
that must stay beside the code it lints remains at the repository root
(`.stylelintrc.json`, `.secretlintrc.json`, `pyrightconfig.json`, `.editorconfig`) or in
`frontend/` (`eslint.config.js`). `.secretlintignore` and `.trufflehog-exclude.txt` are the exception: they
only apply to the local tasks, because MegaLinter passes secretlint and TruffleHog its own
generated exclusion lists.

### What lints what

MegaLinter runs a different set of tools per file type, and only some of those tools are
formatters. `.vscode/settings.json` configures editor formatting and save-time lint fixes.
CSS uses Stylelint fixes on explicit save, while CI has no CSS formatter. Markdown uses
markdownlint fixes on explicit save; format-on-save is disabled because CI's table
formatter is CLI-only.

| File type       | Linters (CI)              | Formatter (CI)           | Fails the build? |
|-----------------|---------------------------|--------------------------|------------------|
| `.py`, `.pyi`   | pyright, ruff             | ruff-format              | No, report-only  |
| `.js`, `.jsx`   | eslint                    | prettier                 | No, report-only  |
| `.css`          | stylelint                 | none                     | No, report-only  |
| `.json`         | jsonlint, v8r             | prettier                 | Yes              |
| `.yml`, `.yaml` | yamllint, v8r, actionlint | prettier                 | Yes              |
| `.md`           | markdownlint              | markdown-table-formatter | Yes              |
| `.html`, `.htm` | djlint, htmlhint          | none                     | Yes              |
| `.sh`           | shellcheck, bash-exec     | shfmt                    | Yes              |
| `Dockerfile*`   | hadolint                  | none                     | Yes              |
| Every file      | editorconfig-checker      | —                        | Yes              |

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
