#!/usr/bin/env bash
set -euo pipefail

# Runs the UI E2E suite against the development stack on the Dev Container's isolated
# Docker daemon. The VS Code task "Autoheal: Run UI E2E" and the UI E2E workflow both
# call this, so local and CI runs follow the same steps. Run it inside the Dev Container.
#
#   bash frontend/e2e-ui/run.sh [scope] [mode]
#
# scope: smoke (default) | full | containers | monitoring | events | configuration |
#        notifications | errors | regression
# mode:  headless (default) | headed (needs a display) | ui (Playwright UI on port 9323)
#
# Exit codes: 0 passed, 1 a test failed, 2 bad arguments, 3 the environment could not
# be set up (the stack did not start), so setup failures stay distinguishable from tests.

scope="${1:-smoke}"
mode="${2:-headless}"

args=()
case "${scope}" in
full) ;;
smoke | containers | monitoring | events | configuration | notifications | errors | regression)
  args+=(--grep "@${scope}")
  ;;
*)
  echo "Unknown scope '${scope}'" >&2
  exit 2
  ;;
esac
case "${mode}" in
headless) ;;
headed)
  if [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    echo "Headed mode needs a display, and none is available here (DISPLAY and" >&2
    echo "WAYLAND_DISPLAY are unset). Use the headless or ui mode instead." >&2
    exit 2
  fi
  args+=(--headed)
  ;;
ui) args+=(--ui-host=0.0.0.0 --ui-port=9323) ;;
*)
  echo "Unknown mode '${mode}'" >&2
  exit 2
  ;;
esac

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

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

status=0
npm --prefix frontend run test:ui-e2e -- "${args[@]}" || status=$?
if [ "${status}" -ne 0 ]; then
  "${compose[@]}" logs --tail=50 autoheal || true
fi
exit "${status}"
