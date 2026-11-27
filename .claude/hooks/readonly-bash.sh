#!/usr/bin/env bash
# PreToolUse hook for read-only agents: allow only read-only gh/git commands.
# Exit code 2 blocks the command and returns stderr to Claude.
set -u

block() {
  printf 'Blocked by readonly-bash hook: %s\n' "$1" >&2
  exit 2
}

command -v jq >/dev/null 2>&1 || block "jq is not installed"

cmd=$(jq -r '.tool_input.command // empty')
[[ -n "$cmd" ]] || exit 0

case "$cmd" in
*$'\n'*) block "multi-line commands are not allowed" ;;
esac

if printf '%s' "$cmd" | grep -q '[;&|<>`()$]'; then
  block "chaining, pipes, redirection and substitution are not allowed"
fi

if ! printf '%s' "$cmd" | grep -Eq '^[A-Za-z0-9 ._/:=@,%+~^-]+$'; then
  block "quotes, escapes, braces, tabs and other unusual characters are not allowed"
fi

if printf '%s' "$cmd" | grep -Eq -- '(^| )--output'; then
  block "--output writes files"
fi

if printf '%s' "$cmd" | grep -Eq '^gh (issue view|pr view|pr checks|pr list)( |$)'; then
  block "GraphQL-backed gh commands return 403 in cloud sessions; use the gh api repos/<owner>/<repo>/... forms in CLAUDE.md"
fi

allowed='^(gh (pr diff|run view|run list)|git (diff|log|show|status|rev-parse|merge-base|ls-files|blame))( |$)'
if printf '%s' "$cmd" | grep -Eq "$allowed"; then
  exit 0
fi

if printf '%s' "$cmd" | grep -Eq '^gh api ' &&
  ! printf '%s' "$cmd" | grep -Eq -- '(^| )(-X|--method|--input|-f|-F|--field|--raw-field)'; then
  exit 0
fi

block "only read-only gh and git commands are allowed: $cmd"
