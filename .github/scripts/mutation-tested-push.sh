#!/usr/bin/env bash
# Exit 0 if a commit in the pushed range BEFORE..AFTER came from a merged pull
# request whose head commit already has a successful "Mutation Testing" pull
# request run; exit 1 otherwise (including every case it cannot prove).
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

for sha in $commits; do
  heads=$(gh api "repos/$repo/commits/$sha/pulls" \
    --jq ".[] | select(.merged_at != null and .merge_commit_sha == \"$sha\") | .head.sha") || continue
  for head in $heads; do
    count=$(gh api "repos/$repo/actions/workflows/$workflow/runs?head_sha=$head&event=pull_request&status=success" \
      --jq '[.workflow_runs[] | select(.conclusion == "success")] | length') || continue
    [ "${count:-0}" -gt 0 ] && exit 0
  done
done
exit 1
