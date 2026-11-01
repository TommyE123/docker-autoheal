#!/usr/bin/env bash
# Checks that the Weekly Maintainer agent really read every app source file. Run from the
# checkout root by a post-step in .github/workflows/weekly-maintainer.md, after gh-aw has
# written the agent output and before it is uploaded for the safe_outputs job.
#
# A test run reported "27 of 27 app source files read" after reading 3 of 35, so the
# agent's own coverage claim is not trusted. This script lists the same files the prompt
# tells the agent to list, finds the successful "cat -n FILE" shell calls in the agent log,
# and writes the result to the step summary. Each call covers a line range: the whole file,
# "| head -n H", "| tail -n +K", or "| head -n H | tail -n +K". A range counts only if its
# output stays under Gemini CLI's 40,000-character tool-output cut, and a file counts only
# when its counted ranges cover every line.
# If any file was not read, a create_issue in the agent output is replaced by a noop, so no
# issue is filed from an incomplete audit, and the step fails so the run shows red.
# Optional environment: AGENT_LOG, AGENT_OUTPUT, GITHUB_STEP_SUMMARY.
set -euo pipefail

log=${AGENT_LOG:-/tmp/gh-aw/agent-stdio.log}
output=${AGENT_OUTPUT:-/tmp/gh-aw/agent_output.json}
summary=${GITHUB_STEP_SUMMARY:-/dev/null}

if [[ ! -d app ]]; then
  echo "::error::Directory app not found; run this from the checkout root" >&2
  exit 1
fi

mapfile -t sources < <(find app -path app/tests -prune -o -name '*.py' -size +0 -print | LC_ALL=C sort)

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
  echo "Read $read_count of $total app source files, counted from the agent log."
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

if [[ -f "$output" ]] && jq -e '.items // [] | any(.type == "create_issue")' "$output" >/dev/null; then
  message="INCOMPLETE AUDIT: the agent read $read_count of $total app source files, so its issue was withheld."
  updated=$(mktemp)
  jq --arg message "$message" \
    '.items |= map(if .type == "create_issue" then {type: "noop", message: $message} else . end)' \
    "$output" >"$updated"
  mv "$updated" "$output"
  echo "Withheld the create_issue output: coverage incomplete." | tee -a "$summary"
fi

echo "::error::Incomplete audit: the agent read $read_count of $total app source files" >&2
exit 1
