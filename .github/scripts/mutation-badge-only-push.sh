#!/usr/bin/env bash
# Exit 0 if the pushed range BEFORE..AFTER holds only automated mutation badge
# update commits (and nothing else), so the mutation run can be skipped; exit 1
# otherwise. A push mixing those commits with any other change must still run.
# Used by .github/workflows/update-mutation-results.yml.
set -euo pipefail

before=${1:?before sha}
after=${2:?after sha}
badge=.github/badges/mutation.json
subject='^mutation: update mutation score badge( \(#[0-9]+\))?$'

# New branch, force push or unknown history: cannot prove it is badge-only.
[[ $before =~ ^0+$ ]] && exit 1
git cat-file -e "$before^{commit}" 2>/dev/null || exit 1
git cat-file -e "$after^{commit}" 2>/dev/null || exit 1

commits=$(git rev-list "$before..$after")
[ -n "$commits" ] || exit 1

# Every commit must be a mutation badge commit that touches only the badge file.
for sha in $commits; do
  git log -1 --format=%s "$sha" | grep -Eq "$subject" || exit 1
  [ "$(git diff-tree --no-commit-id --name-only -r -m --root "$sha")" = "$badge" ] || exit 1
done

[ "$(git diff --name-only "$before" "$after")" = "$badge" ]
