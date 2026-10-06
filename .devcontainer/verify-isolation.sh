#!/usr/bin/env bash
set -euo pipefail

# Proves, from inside the Dev Container, that Docker here is an isolated daemon and that the
# development Autoheal recovers a container on it. It creates two disposable probes and removes
# them afterwards. Start the dev stack first (task "Autoheal: Run Docker Stack"). Host-side
# checks (production containers invisible here, probes invisible there) are in
# docs/developer/development-setup.md.

base_url="${AUTOHEAL_BASE_URL:-http://localhost:3132}"
web=autoheal-isolation-web
victim=autoheal-isolation-victim
timeout_seconds=150

cleanup() {
  docker rm -f "${web}" "${victim}" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

echo "== Inner daemon =="
pgrep -x dockerd >/dev/null || {
  echo "::error::No dockerd process in this container; Docker is not the isolated daemon" >&2
  exit 1
}
echo "Containers on this daemon:"
docker ps -a --format '  {{.Names}}'

echo "== ${web}: create, stop, restart, remove =="
docker run -d --name "${web}" nginx:alpine >/dev/null
docker ps --filter "name=^${web}$" --format '{{.Names}}' | grep -qx "${web}"
docker stop "${web}" >/dev/null
docker start "${web}" >/dev/null
docker restart "${web}" >/dev/null
docker rm -f "${web}" >/dev/null
echo "ok"

echo "== ${victim}: Autoheal recovery =="
curl -fsS "${base_url}/health" >/dev/null || {
  echo "::error::Dev Autoheal is not reachable at ${base_url}; start the dev stack first" >&2
  exit 1
}
config="$(curl -fsS "${base_url}/api/config")"
label_key="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["monitor"]["label_key"])' <<<"${config}")"
label_value="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["monitor"]["label_value"])' <<<"${config}")"
if [ "${label_key}" = "autoheal" ]; then
  echo "::error::${base_url} monitors the production label autoheal=true, not the dev label" >&2
  exit 1
fi

# Exits non-zero shortly after starting; --restart no leaves recovery to Autoheal.
docker run -d --name "${victim}" --restart no --label "${label_key}=${label_value}" \
  alpine sh -c 'sleep 5; exit 1' >/dev/null

recovered=false
deadline=$((SECONDS + timeout_seconds))
while [ "${SECONDS}" -lt "${deadline}" ]; do
  if curl -fsS "${base_url}/api/events?event_type=restart&container=${victim}" |
    python3 -c 'import json,sys; sys.exit(0 if any(e["status"] == "success" for e in json.load(sys.stdin)) else 1)'; then
    recovered=true
    break
  fi
  sleep 5
done
if [ "${recovered}" != "true" ]; then
  echo "::error::Autoheal did not restart ${victim} within ${timeout_seconds}s" >&2
  exit 1
fi
echo "ok: Autoheal restarted ${victim} on the isolated daemon"
