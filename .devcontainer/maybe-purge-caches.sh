#!/usr/bin/env bash
set -euo pipefail

# The pip/npm cache directories are backed by named Docker volumes (see
# devcontainer.json's "mounts") so they persist across container rebuilds.
# Docker creates a fresh volume mount as root-owned, so make sure the
# container's non-root user can actually write to it before anything else
# runs.
sudo mkdir -p "${HOME}/.cache/pip" "${HOME}/.npm"
sudo chown -R "$(id -u):$(id -g)" "${HOME}/.cache/pip" "${HOME}/.npm"

# Lives inside the pip cache volume itself (already owned by this user,
# unlike its parent ~/.cache, which Docker creates as root when the volume
# mount point doesn't exist yet) so it persists exactly as long as the cache
# it's tracking does.
marker="${HOME}/.cache/pip/.devcontainer-cache-purge-marker"
max_age_days=7

if [[ -f "$marker" ]]; then
  last_purge_epoch="$(date -r "$marker" +%s)"
  now_epoch="$(date +%s)"
  age_days=$(((now_epoch - last_purge_epoch) / 86400))
  if ((age_days < max_age_days)); then
    exit 0
  fi
fi

echo "Cache is unpurged or older than ${max_age_days} days - purging pip/npm caches..."
pip cache purge || true
npm cache clean --force || true

touch "$marker"
