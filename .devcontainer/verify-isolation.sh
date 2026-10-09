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

# Check which daemon the client talks to before mutating anything. A dockerd process alone
# does not prove it: the daemon's reported name is its own host's name, which is this
# container's hostname only when the client is bound to the local (inner) daemon.
echo "== Inner daemon =="
pgrep -x dockerd >/dev/null || {
  echo "::error::No dockerd process in this container; Docker is not the isolated daemon" >&2
  exit 1
}
daemon_name="$(docker info --format '{{.Name}}')"
if [ "${daemon_name}" != "$(hostname)" ]; then
  echo "::error::Docker daemon '${daemon_name}' is not this container's own daemon ('$(hostname)')" >&2
  exit 1
fi
echo "Daemon ${daemon_name} is local. Containers on it:"
docker ps -a --format '  {{.Names}}'

trap cleanup EXIT
cleanup

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
if [ "${label_key}=${label_value}" != "autoheal.dev=true" ]; then
  echo "::error::${base_url} monitors ${label_key}=${label_value}, not the dev label autoheal.dev=true" >&2
  exit 1
fi

# Exits non-zero shortly after starting; --restart no leaves recovery to Autoheal. The event log
# persists in data-dev, so success is matched on this run's container ID, not on the fixed name.
victim_id="$(docker run -d --name "${victim}" --restart no --label "${label_key}=${label_value}" \
  alpine sh -c 'sleep 5; exit 1')"

recovered=false
deadline=$((SECONDS + timeout_seconds))
while [ "${SECONDS}" -lt "${deadline}" ]; do
  if curl -fsS "${base_url}/api/events?event_type=restart&container=${victim}" |
    python3 -c 'import json,sys; sys.exit(0 if any(e["status"] == "success" and e["container_id"] == sys.argv[1] for e in json.load(sys.stdin)) else 1)' "${victim_id}"; then
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
