#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

bash .devcontainer/prepare-volumes.sh

mise trust
mise install --locked
# Only mise's tool installs grow without bound (each version bump leaves the old
# install behind); prune is a no-op when nothing is superseded.
mise prune --yes || echo "Warning: mise prune failed; superseded tool versions were kept"

python -m pip install -r requirements-dev.txt
npm ci --prefer-offline --no-audit --prefix frontend
npm ci --prefer-offline --ignore-scripts --no-audit --prefix .devcontainer
