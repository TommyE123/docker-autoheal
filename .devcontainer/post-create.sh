#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

bash .devcontainer/prepare-caches.sh

mise trust
mise install --locked

python -m pip install -r requirements-dev.txt
npm ci --no-audit --prefix frontend
npm ci --ignore-scripts --no-audit --prefix .devcontainer
