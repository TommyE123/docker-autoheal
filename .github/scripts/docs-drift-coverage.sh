#!/usr/bin/env bash
# Checks that the Documentation Drift Detection agent really read every file of its read plan.
# Run from the checkout root by a post-step in .github/workflows/docs-drift.md, after gh-aw has
# written the agent output and before it is uploaded for the safe_outputs job.
#
# The Weekly Maintainer's test runs showed that an agent's own coverage claim is not trusted
# (one reported "27 of 27 app source files read" after reading 3 of 35). This script reads the
# manifest that .github/scripts/docs-drift-reads.sh wrote for this run, finds the successful
# "cat -n FILE" shell calls in the agent log, and writes the result to the step summary. Each
# call covers a line range: the whole file, "| head -n H", "| tail -n +K", or
# "| head -n H | tail -n +K". A range counts only if its output stays under Gemini CLI's
# 40,000-character tool-output cut, and a file counts only when its counted ranges cover every
# line.
# If any file was not read, a create_pull_request in the agent output is replaced by a noop, so
# no pull request is opened from an incomplete audit, and the step fails so the run shows red.
# Optional environment: AGENT_LOG, AGENT_OUTPUT, MANIFEST, GITHUB_STEP_SUMMARY.
set -euo pipefail

log=${AGENT_LOG:-/tmp/gh-aw/agent-stdio.log}
output=${AGENT_OUTPUT:-/tmp/gh-aw/agent_output.json}
summary=${GITHUB_STEP_SUMMARY:-/dev/null}
manifest=${MANIFEST:-/tmp/gh-aw/docs-drift-plan.txt}

if [[ ! -f "$manifest" ]]; then
  echo "::error::Read plan manifest $manifest not found; the read plan step did not run" >&2
  exit 1
fi

area=$(sed -n 's/^AREA //p' "$manifest")
mapfile -t sources < <(grep -v '^AREA ' "$manifest")
if ((${#sources[@]} == 0)); then
  echo "::error::Manifest $manifest lists no files" >&2
  exit 1
fi

# Successful shell commands, one per line. The log mixes plain text with stream-json lines;
# lines that do not parse as JSON are skipped.
commands=$(mktemp)
trap 'rm -f "$commands"' EXIT
if [[ -f "$log" ]]; then
  grep '^{' "$log" | jq -nrR '
    [inputs | fromjson? | objects] as $events
    | ($events | map(select(.type == "tool_result" and .status == "success") | .tool_id)) as $ok
    | $events[]
    | select(.type == "tool_use" and .tool_name == "run_shell_command")
    | select(.tool_id as $id | $ok | index($id))
    | .parameters.command // empty
    | gsub("\n"; " ")' >"$commands" || true
fi

# Gemini CLI replaces the middle of any tool result over this many characters.
cut_limit=40000

# Prints "START END" for each read of file $1 that the agent saw in full, where $2 is the
# file's line count.
ranges() {
  local f=$1 lines=$2 cmd rest start end
  while IFS= read -r cmd; do
    [[ $cmd == "cat -n $f"* ]] || continue
    rest=${cmd#"cat -n $f"}
    if [[ -z $rest ]]; then
      start=1 end=$lines
    elif [[ $rest =~ ^\ \|\ head\ -n\ ([0-9]+)$ ]]; then
      start=1 end=${BASH_REMATCH[1]}
    elif [[ $rest =~ ^\ \|\ tail\ -n\ \+([0-9]+)$ ]]; then
      start=${BASH_REMATCH[1]} end=$lines
    elif [[ $rest =~ ^\ \|\ head\ -n\ ([0-9]+)\ \|\ tail\ -n\ \+([0-9]+)$ ]]; then
      start=${BASH_REMATCH[2]} end=${BASH_REMATCH[1]}
    else
      continue
    fi
    ((start < 1)) && start=1
    ((end > lines)) && end=$lines
    ((start <= end)) || continue
    if (($(cat -n "$f" | sed -n "${start},${end}p" | wc -c) < cut_limit)); then
      echo "$start $end"
    fi
  done <"$commands"
}

# True when the ranges read for file $1 cover all of its lines.
covered() {
  local f=$1 lines next=1 start end
  lines=$(wc -l <"$f")
  # A file without a final newline still has a last line to read.
  [[ -n $(tail -c 1 "$f") ]] && lines=$((lines + 1))
  while read -r start end; do
    ((start <= next && end >= next)) && next=$((end + 1))
  done < <(ranges "$f" "$lines" | sort -n -k1,1 -k2,2)
  ((next > lines))
}

missing=()
for f in "${sources[@]}"; do
  covered "$f" || missing+=("$f")
done

total=${#sources[@]}
read_count=$((total - ${#missing[@]}))

{
  echo
  echo "## Source coverage check"
  echo
  echo "Focus area: $area. Read $read_count of $total files, counted from the agent log."
  if ((${#missing[@]})); then
    echo
    echo "Not read:"
    echo
    printf -- '- %s\n' "${missing[@]}"
  fi
} >>"$summary"

if ((${#missing[@]} == 0)); then
  echo "Source coverage complete: $total of $total files read."
  exit 0
fi

if [[ -f "$output" ]] && jq -e '.items // [] | any(.type == "create_pull_request")' "$output" >/dev/null; then
  message="INCOMPLETE AUDIT: the agent read $read_count of $total files, so its pull request was withheld."
  updated=$(mktemp)
  jq --arg message "$message" \
    '.items |= map(if .type == "create_pull_request" then {type: "noop", message: $message} else . end)' \
    "$output" >"$updated"
  mv "$updated" "$output"
  echo "Withheld the create_pull_request output: coverage incomplete." | tee -a "$summary"
fi

echo "::error::Incomplete audit: the agent read $read_count of $total files" >&2
exit 1
