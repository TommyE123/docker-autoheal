#!/usr/bin/env bash
# Run mutation testing from a clean state (see docs/developer/mutation-testing.md).
#
# Usage:
#   ./mutation.sh                 full run over the whole mutation target
#   ./mutation.sh "<mutant-glob>" focused run, e.g. "app.monitor.matching*"
#
# mutants/ is deleted first because mutmut keeps cached verdicts that are not
# invalidated when tests are added or edited.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

rm -rf mutants
mutmut run "$@"
# Hide mutants a focused run did not select; grep exits 1 when nothing is left.
mutmut results | grep -v ': not checked$' || true
