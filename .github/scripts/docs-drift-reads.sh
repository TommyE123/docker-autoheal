#!/usr/bin/env bash
# Appends the Documentation Drift Detection read plan to its prompt. Run from the checkout root
# by a pre-agent step in .github/workflows/docs-drift.md, before the engine reads the prompt file.
#
# Each week has one focus area (the last digit of the ISO week number, modulo 5), defined in
# .github/scripts/docs-drift-areas.sh: a set of documentation files and the app source that
# implements what they describe. The plan lists those files as the exact "cat -n" commands the
# agent runs, in three parts, one per turn. The week number goes to the later steps of the job
# through GITHUB_ENV, and .github/scripts/docs-drift-coverage.sh rebuilds the same list from it,
# so the check does not depend on any file the agent could write. Part 1 is small because it goes out with the baseline calls; a reply with
# about 40 tool calls has come back cut off. A file whose cat -n output is over 30,000 characters
# is read in parts of 600 lines, and every command's output must stay under Gemini CLI's
# 40,000-character tool-output cut. The agent runs the commands as written, so a path with
# anything but letters, digits, dots, dashes, underscores and slashes is refused, and so is a
# mapped file that no longer exists (rename it in the area table). Any problem fails the step
# loudly rather than leaving the agent without a plan.
# Optional environment: PROMPT_FILE (the prompt to append to), WEEK (an ISO week number,
# instead of today's; the workflow passes its optional "area" dispatch input here, 0 to 4, and
# an empty value means today's week), FIRST_PART (calls in part 1), GITHUB_ENV (set by GitHub Actions).
set -euo pipefail

prompt_file=${PROMPT_FILE:-/tmp/gh-aw/aw-prompts/prompt.txt}
first_part=${FIRST_PART:-8}
split_chars=30000
part_lines=600
cut_limit=40000

if [[ ! -f "$prompt_file" ]]; then
  echo "::error::Prompt file $prompt_file not found; cannot append the read plan" >&2
  exit 1
fi

area_name="" files=() # set by docs_drift_area
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/docs-drift-areas.sh"
week=${WEEK:-$(date -u +%V)}
docs_drift_area "$week"

# Prints the cat -n output size of lines $2 to $3 of file $1.
part_size() { cat -n "$1" | sed -n "$2,$3p" | wc -c; }

# One command per line, in the order the agent reads them.
commands=()
for f in "${files[@]}"; do
  if [[ ! $f =~ ^[A-Za-z0-9_./-]+$ ]]; then
    echo "::error::Unsafe path '$f'; only letters, digits and ._/- are allowed" >&2
    exit 1
  fi
  lines=$(wc -l <"$f")
  [[ -n $(tail -c 1 "$f") ]] && lines=$((lines + 1))
  if (($(part_size "$f" 1 "$lines") <= split_chars)); then
    parts=("1 $lines cat -n $f")
  else
    parts=("1 $part_lines cat -n $f | head -n $part_lines")
    start=$((part_lines + 1))
    while ((start + part_lines <= lines)); do
      end=$((start + part_lines - 1))
      parts+=("$start $end cat -n $f | head -n $end | tail -n +$start")
      start=$((end + 1))
    done
    ((start <= lines)) && parts+=("$start $lines cat -n $f | tail -n +$start")
  fi
  for p in "${parts[@]}"; do
    read -r from to command <<<"$p"
    size=$(part_size "$f" "$from" "$to")
    if ((size >= cut_limit)); then
      echo "::error::'$command' prints $size characters, over the $cut_limit-character cut" >&2
      exit 1
    fi
    commands+=("$command")
  done
done

# The post-step rebuilds the same list from this week number.
[[ -n ${GITHUB_ENV:-} ]] && echo "DOCS_DRIFT_WEEK=$((10#$week))" >>"$GITHUB_ENV"

total=${#commands[@]}
((first_part > total)) && first_part=$total
rest=$((total - first_part))
second_part=$(((rest + 1) / 2))

{
  echo
  echo "===== READS START ====="
  echo "Focus area this week: $area_name (ISO week $((10#$week)))."
  echo "${#files[@]} files, read with these $total commands. Run each command as its own call,"
  echo "exactly as written. The file names come from the checkout."
  for i in "${!commands[@]}"; do
    if ((i == 0)); then
      echo
      echo "Part 1 (turn 1, with the baseline calls):"
    elif ((i == first_part)); then
      echo
      echo "Part 2 (turn 2):"
    elif ((i == first_part + second_part)); then
      echo
      echo "Part 3 (turn 3):"
    fi
    echo "${commands[$i]}"
  done
  echo "===== READS END ====="
} >>"$prompt_file"

echo "Focus area '$area_name': appended a read plan for ${#files[@]} files in $total commands ($first_part, $second_part, $((rest - second_part)))."
