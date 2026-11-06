#!/usr/bin/env bash
# Appends the Documentation Drift Detection read plan to its prompt. Run from the checkout root
# by a pre-agent step in .github/workflows/docs-drift.md, before the engine reads the prompt file.
#
# Each week has one focus area (the last digit of the ISO week number, modulo 5). The area is a
# set of documentation files and the app source that implements what they describe. The plan lists
# those files as the exact "cat -n" commands the agent runs, in three parts, one per turn, and
# writes the same list to a manifest that .github/scripts/docs-drift-coverage.sh checks, so the
# two cannot disagree. Part 1 is small because it goes out with the baseline calls; a reply with
# about 40 tool calls has come back cut off. A file whose cat -n output is over 30,000 characters
# is read in parts of 600 lines, and every command's output must stay under Gemini CLI's
# 40,000-character tool-output cut. The agent runs the commands as written, so a path with
# anything but letters, digits, dots, dashes, underscores and slashes is refused, and so is a
# mapped file that no longer exists (rename it in the area table below). Any problem fails the
# step loudly rather than leaving the agent without a plan.
# Optional environment: PROMPT_FILE (the prompt to append to), MANIFEST (where to record the
# plan), WEEK (an ISO week number, instead of today's), FIRST_PART (calls in part 1).
set -euo pipefail

prompt_file=${PROMPT_FILE:-/tmp/gh-aw/aw-prompts/prompt.txt}
manifest=${MANIFEST:-/tmp/gh-aw/docs-drift-plan.txt}
first_part=${FIRST_PART:-8}
split_chars=30000
part_lines=600
cut_limit=40000

if [[ ! -f "$prompt_file" ]]; then
  echo "::error::Prompt file $prompt_file not found; cannot append the read plan" >&2
  exit 1
fi

week=${WEEK:-$(date -u +%V)}
if [[ ! $week =~ ^[0-9]+$ ]]; then
  echo "::error::Week '$week' is not a number" >&2
  exit 1
fi
area=$((10#$week % 10 % 5))

# The areas together cover the user documentation, the architecture documents, the deployment
# files and every app source directory. README.md is read in every area: it makes claims about
# all of them, and the agent only judges a claim whose implementation it read. Entries ending in
# a slash are directories: their non-empty .py files, tests excluded, are all read.
case $area in
  0)
    name="Configuration and deployment"
    paths=(README.md docs/user/configuration.md docs/user/installation.md docs/user/migration.md
      docker-compose.yml Dockerfile app/main.py app/config/)
    ;;
  1)
    name="Health checks and recovery"
    paths=(README.md docs/user/health-checks.md docs/user/labels.md docs/user/maintenance-mode.md
      app/monitor/ app/docker_client/)
    ;;
  2)
    name="API, UI and architecture"
    paths=(README.md docs/user/usage.md docs/developer/architecture.md
      docs/developer/project-structure.md app/api/)
    ;;
  3)
    name="Metrics, logging and troubleshooting"
    paths=(README.md docs/user/monitoring-and-metrics.md docs/user/troubleshooting.md app/main.py
      app/config/config_manager.py app/api/routes/health.py app/api/routes/healthchecks.py)
    ;;
  4)
    name="Notifications and Uptime Kuma"
    paths=(README.md docs/user/notifications.md app/notifications/ app/uptime_kuma/
      app/monitor/uptime_kuma_monitor.py)
    ;;
esac

files=()
for p in "${paths[@]}"; do
  if [[ $p == */ ]]; then
    if [[ ! -d $p ]]; then
      echo "::error::Directory $p of focus area '$name' not found" >&2
      exit 1
    fi
    while IFS= read -r f; do files+=("$f"); done < <(find "$p" -path app/tests -prune -o -name '*.py' -size +0 -print | LC_ALL=C sort)
  elif [[ -f $p ]]; then
    files+=("$p")
  else
    echo "::error::File $p of focus area '$name' not found" >&2
    exit 1
  fi
done
if ((${#files[@]} == 0)); then
  echo "::error::No files in focus area '$name'" >&2
  exit 1
fi

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

mkdir -p "$(dirname "$manifest")"
{
  echo "AREA $name"
  printf '%s\n' "${files[@]}"
} >"$manifest"

total=${#commands[@]}
((first_part > total)) && first_part=$total
rest=$((total - first_part))
second_part=$(((rest + 1) / 2))

{
  echo
  echo "===== READS START ====="
  echo "Focus area this week: $name (ISO week $((10#$week)))."
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

echo "Focus area '$name': appended a read plan for ${#files[@]} files in $total commands ($first_part, $second_part, $((rest - second_part)))."
