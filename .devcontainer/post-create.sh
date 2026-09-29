#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

bash .devcontainer/prepare-caches.sh

python -m pip install -r requirements-dev.txt -r .devcontainer/requirements-tools.txt
npm ci --no-audit --prefix frontend
npm ci --ignore-scripts --no-audit --prefix .devcontainer

bash .devcontainer/install-tools.sh

# Needs a token, so expected to fail outside Codespaces; never fatal.
gh extension upgrade gh-aw ||
  gh extension install github/gh-aw ||
  echo "Warning: gh-aw extension install failed (expected without a GITHUB_TOKEN outside Codespaces)"
