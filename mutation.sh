#!/usr/bin/env bash
# Run mutation testing from a clean state (see docs/developer/mutation-testing.md).
#
# Usage:
#   ./mutation.sh                 full run over the whole mutation target
#   UPDATE_MUTATION_BADGE=1 ./mutation.sh
#                                 full run that also rewrites the tracked
#                                 .github/badges/mutation.json (done only by
#                                 .github/workflows/update-mutation-results.yml)
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

# A focused run scores only part of the target, so only a full run may update the
# README badge data, and only when asked to: ordinary runs (local and pull request)
# leave the tracked file alone. `mutmut badge` writes it; json.tool only re-indents
# it to the repository's JSON style (Prettier).
if [ "$#" -eq 0 ] && [ "${UPDATE_MUTATION_BADGE:-}" = "1" ]; then
  mutmut export-cicd-stats
  mutmut badge --label Mutation --output mutants/mutation-badge.json
  mkdir -p .github/badges
  python -m json.tool --indent 2 mutants/mutation-badge.json .github/badges/mutation.json
fi
