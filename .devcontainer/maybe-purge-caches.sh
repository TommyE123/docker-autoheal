#!/usr/bin/env bash
set -euo pipefail

# The pip/npm/tools/gh cache directories are backed by named Docker volumes
# (see devcontainer.json's "mounts") so they persist across container
# rebuilds. Docker creates a fresh volume mount as root-owned, so make sure
# the container's non-root user can actually write to it before anything
# else runs.
#
# The chown targets are the whole ~/.cache and ~/.local trees, not just the
# specific pip/tools/gh subdirectories: Dev Container features run as root
# during image build, and can leave these parent directories root-owned even
# though they're created under the vscode user's home. That breaks anything
# writing a new file directly under them - pip's user-site fallback
# (~/.local/lib/...), install-tools.sh's install target (~/.local/bin), and
# arbitrary per-tool cache files tools create on first run (e.g. semgrep's
# own ~/.cache/semgrep_version) - not just the specific cache subdirectories
# below.
sudo mkdir -p "${HOME}/.cache/pip" "${HOME}/.npm" "${HOME}/.cache/devcontainer-tools" "${HOME}/.local/share/gh"
sudo chown -R "$(id -u):$(id -g)" "${HOME}/.cache" "${HOME}/.npm" "${HOME}/.local"

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
