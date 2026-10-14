#!/usr/bin/env bash
# Checks that a mutation badge file is what `mutmut badge` (see mutation.sh) writes:
# schemaVersion 1, a label, a "NN.N%" message of at most 100, and a "#rrggbb" colour.
# Used by the unit-tests job in .github/workflows/tests.yml for badge-only pull requests, so
# the required check still fails on a missing or malformed file.
# Usage: validate-badge.sh [file]   (default .github/badges/mutation.json)
set -euo pipefail

file=${1:-.github/badges/mutation.json}

if [ ! -f "$file" ]; then
  echo "::error::$file is missing." >&2
  exit 1
fi

# --slurp + length == 1: exactly one JSON value (jq -e alone only looks at the last result).
if ! jq -e --slurp '
  length == 1 and (.[0] |
    type == "object"
    and .schemaVersion == 1
    and (.label | type == "string" and length > 0)
    and (.message | type == "string" and test("^[0-9]+\\.[0-9]%$") and (rtrimstr("%") | tonumber) <= 100)
    and (.color | type == "string" and test("^#[0-9a-fA-F]{6}$")))
' "$file" >/dev/null; then
  echo "::error::$file is not valid JSON in the format mutmut badge writes (schemaVersion 1, label, message like 66.0%, colour like #adff00)." >&2
  exit 1
fi
