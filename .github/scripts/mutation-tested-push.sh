#!/usr/bin/env bash
# Exit 0 only if every non-badge commit in the pushed range BEFORE..AFTER came
# from a merged pull request whose head commit already has a successful
# "Mutation Testing" pull request run; exit 1 otherwise (including every case it cannot prove).
# Squash merges create a new SHA on main, so the pull request is looked up from
# the commit (not matched by SHA) and its head SHA is used to find the run.
# Needs GH_TOKEN and GITHUB_REPOSITORY. Used by update-mutation-results.yml.
set -euo pipefail

before=${1:?before sha}
after=${2:?after sha}
repo=${GITHUB_REPOSITORY:?}
workflow=mutation-testing.yml

if [[ $before =~ ^0+$ ]] || ! git cat-file -e "$before^{commit}" 2>/dev/null; then
  commits=$after
else
  commits=$(git rev-list "$before..$after")
fi

# Every commit in the push must be covered, so an untested later commit cannot
# ride along with a tested one. Badge-only commits (this workflow's own output)
# are exempt: their pull requests never run mutation testing.
subject='^mutation: update mutation score badge( \(#[0-9]+\))?$'
tested=0
for sha in $commits; do
  if git log -1 --format=%s "$sha" | grep -Eq "$subject" &&
    [ "$(git diff-tree --no-commit-id --name-only -r -m --root "$sha")" = ".github/badges/mutation.json" ]; then
    continue
  fi
  ok=0
  heads=$(gh api "repos/$repo/commits/$sha/pulls" \
    --jq ".[] | select(.merged_at != null and .merge_commit_sha == \"$sha\") | .head.sha") || exit 1
  for head in $heads; do
    count=$(gh api "repos/$repo/actions/workflows/$workflow/runs?head_sha=$head&event=pull_request&status=success" \
      --jq '[.workflow_runs[] | select(.conclusion == "success")] | length') || exit 1
    if [ "${count:-0}" -gt 0 ]; then
      ok=1
      break
    fi
  done
  [ "$ok" = 1 ] || continue
  tested=1
done
[ "$tested" = 1 ]
