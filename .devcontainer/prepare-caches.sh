#!/usr/bin/env bash
set -euo pipefail

# Two jobs: make the cache volumes writable, which container setup depends
# on, and purge them if they're stale, which it doesn't.

# Fresh volume mounts and Dev Container features both leave directories
# root-owned, so chown the whole ~/.cache and ~/.local trees rather than only
# the cache subdirectories below - pip's user-site fallback and per-tool
# cache files land directly under the parents.
sudo mkdir -p "${HOME}/.cache/pip" "${HOME}/.npm" "${HOME}/.local/share/gh"
sudo chown -R "$(id -u):$(id -g)" "${HOME}/.cache" "${HOME}/.npm" "${HOME}/.local"

# Sits outside every path the purge below wipes, so it survives its own purge.
marker="${HOME}/.local/share/gh/.devcontainer-cache-purge-marker"
max_age_days=7

if [[ -f "$marker" ]]; then
  last_purge_epoch="$(date -r "$marker" +%s)"
  now_epoch="$(date +%s)"
  age_days=$(((now_epoch - last_purge_epoch) / 86400))
  if ((age_days < max_age_days)); then
    exit 0
  fi
fi

echo "Cache is unpurged or older than ${max_age_days} days - purging pip/npm/gh caches..."
pip cache purge || true
npm cache clean --force || true
rm -rf "${HOME}/.local/share/gh/extensions"/*

touch "$marker"
