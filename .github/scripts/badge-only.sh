#!/usr/bin/env bash
# Writes badge-only=true|false to $GITHUB_OUTPUT. "true" only for a pull_request event whose
# changed files are all .github/badges/mutation.json; any other event, any other file, an
# empty list or an API error gives "false" so the normal checks run.
# Used by .github/workflows/badge-only-check.yml. Needs EVENT_NAME, PR, GITHUB_REPOSITORY,
# GITHUB_OUTPUT and GH_TOKEN (for `gh`).
set -euo pipefail

badge_only=false
if [ "$EVENT_NAME" = pull_request ]; then
  # filename and previous_filename: a rename must not hide the file it moved from.
  files=$(gh api --paginate "repos/$GITHUB_REPOSITORY/pulls/${PR:-}/files" \
    --jq '.[] | .filename, (.previous_filename // empty)') || files=
  # Exact comparison, not a short-reading pipeline: a grep -q that exits early can break the pipe.
  if [ "$files" = .github/badges/mutation.json ]; then
    badge_only=true
  fi
fi
echo "badge-only=$badge_only" >>"$GITHUB_OUTPUT"
