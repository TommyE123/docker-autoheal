#!/usr/bin/env bash
set -euo pipefail

# Fresh volume mounts and Dev Container features both leave directories
# root-owned, so chown the whole ~/.cache and ~/.local trees rather than only
# the volume mount points - pip's user-site fallback and per-tool cache files
# land directly under the parents.
sudo mkdir -p "${HOME}/.cache" "${HOME}/.local/share/gh"
sudo chown -R "$(id -u):$(id -g)" "${HOME}/.cache" "${HOME}/.local"
