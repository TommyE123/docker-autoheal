#!/usr/bin/env bash
set -euo pipefail

# Runs the UI E2E suite. Two targets, one script, so local and CI runs follow the same
# steps:
#   - Development (the VS Code task "Autoheal: Run UI E2E"): the dev stack from
#     docker-compose.dev.yml, started here, on the Dev Container's isolated Docker
#     daemon. Run it inside the Dev Container.
#   - CI (production-smoke-test.yml): an already-running instance of the built image,
#     selected by setting UI_E2E_BASE_URL. Nothing is built or started here.
#
#   bash frontend/e2e-ui/run.sh [scope] [mode]
#
# scope: smoke (default) | full | containers | monitoring | events | configuration |
#        notifications | errors | regression
# mode:  headless (default) | ui (Playwright UI on port 9323)
#
# Exit codes: 0 passed, 1 a test failed, 2 bad arguments, 3 the environment could not
# be set up (the stack did not start, or Docker is not an isolated local daemon), so setup
# failures stay distinguishable from tests.

scope="${1:-smoke}"
mode="${2:-headless}"

args=()
case "${scope}" in
full)
  # The whole suite, even if UI_E2E_TAG is already set in the calling shell.
  unset UI_E2E_TAG
  ;;
smoke | containers | monitoring | events | configuration | notifications | errors | regression)
  # A per-project filter (see playwright.ui.config.js), not --grep: --grep would still
  # run every test of the `parallel` project that the `exclusive` project depends on.
  export UI_E2E_TAG="@${scope}"
  ;;
*)
  echo "Unknown scope '${scope}'" >&2
  exit 2
  ;;
esac
case "${mode}" in
headless) ;;
ui) args+=(--ui-host=0.0.0.0 --ui-port=9323) ;;
*)
  echo "Unknown mode '${mode}'" >&2
  exit 2
  ;;
esac

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

# Refuse to continue unless Docker here is this environment's own daemon. The same checks
# as .devcontainer/verify-isolation.sh and frontend/e2e-ui/docker.js; they run before
# Compose, and also for an already-running instance (the tests create containers on this
# daemon either way), so a host or production daemon is never built on or acted on.
if [ -n "${DOCKER_HOST:-}${DOCKER_CONTEXT:-}" ]; then
  echo "::error::UI E2E refused to start: DOCKER_HOST or DOCKER_CONTEXT is set, so Docker may not be the local daemon" >&2
  exit 3
fi
if ! pgrep -x dockerd >/dev/null; then
  echo "::error::UI E2E refused to start: no dockerd runs here, so Docker is not the Dev Container's own daemon (#460 / PR #461)" >&2
  exit 3
fi
daemon_name="$(docker info --format '{{.Name}}' 2>/dev/null || true)"
if [ "${daemon_name}" != "$(hostname)" ]; then
  echo "::error::UI E2E refused to start: Docker daemon '${daemon_name}' is not this environment's own ('$(hostname)')" >&2
  exit 3
fi

status=0
if [ -n "${UI_E2E_BASE_URL:-}" ]; then
  # An instance something else started, e.g. the built image in CI. It must monitor
  # autoheal.dev=true: the fixtures read that from /api/config and refuse otherwise.
  echo "UI E2E (${scope}, ${mode}) against ${UI_E2E_BASE_URL}; using the running instance"
  npm --prefix frontend run test:ui-e2e -- "${args[@]}" || status=$?
  exit "${status}"
fi

compose=(docker compose -p docker-autoheal-dev -f docker-compose.yml -f docker-compose.dev.yml)

# Leave a stack that was already running alone; remove one this script started.
started_here=false
if [ -z "$("${compose[@]}" ps -q autoheal)" ]; then
  started_here=true
  trap '"${compose[@]}" down' EXIT
fi

if ! "${compose[@]}" up --build -d --wait autoheal; then
  echo "::error::UI E2E environment setup failed: the dev stack did not become healthy"
  "${compose[@]}" logs --tail=50 autoheal || true
  exit 3
fi

port="$("${compose[@]}" port autoheal 3131)"
export UI_E2E_BASE_URL="http://localhost:${port##*:}"
echo "UI E2E (${scope}, ${mode}) against ${UI_E2E_BASE_URL}; stack started here: ${started_here}"

npm --prefix frontend run test:ui-e2e -- "${args[@]}" || status=$?
if [ "${status}" -ne 0 ]; then
  "${compose[@]}" logs --tail=50 autoheal || true
fi
exit "${status}"
