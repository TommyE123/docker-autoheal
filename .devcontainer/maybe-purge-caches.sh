#!/usr/bin/env bash
set -euo pipefail

# The pip/npm/tools/gh cache directories are backed by named Docker volumes
# (see devcontainer.json's "mounts") so they persist across container
# rebuilds. Docker creates a fresh volume mount as root-owned, so make sure
# the container's non-root user can actually write to it before anything
# else runs.
sudo mkdir -p "${HOME}/.cache/pip" "${HOME}/.npm" "${HOME}/.cache/devcontainer-tools" "${HOME}/.local/share/gh"
sudo chown -R "$(id -u):$(id -g)" "${HOME}/.cache/pip" "${HOME}/.npm" "${HOME}/.cache/devcontainer-tools" "${HOME}/.local/share/gh"

# Lives in the gh cache volume, but outside the "extensions" subdirectory
# purged below - unlike the pip/npm/tools caches, which get wiped wholesale
# by their own purge commands (pip cache purge, npm cache clean, rm -rf),
# this spot in the gh volume is never touched by the purge itself, so the
# marker survives its own purge instead of being deleted along with it.
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

echo "Cache is unpurged or older than ${max_age_days} days - purging pip/npm/tools/gh caches..."
pip cache purge || true
npm cache clean --force || true
rm -rf "${HOME}/.cache/devcontainer-tools"/*
rm -rf "${HOME}/.local/share/gh/extensions"/*

touch "$marker"
