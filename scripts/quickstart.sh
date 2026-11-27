#!/usr/bin/env bash
# Runs the README quick start end to end on the synthetic demo, offline, in dry mode.
#
# Usage: bash scripts/quickstart.sh [FOLDER]
#
# FOLDER is the demo workspace to create. It must be new or empty. Without it, the
# script makes a new temporary folder, so your own ./workspace is never touched.
# The script uses `getmeajob` from PATH, or the program named in $GETMEAJOB.
# The apply step needs the browser extra: pip install -e ".[browser]" and
# playwright install chromium.
set -euo pipefail

GMJ="${GETMEAJOB:-getmeajob}"
if ! command -v "$GMJ" >/dev/null 2>&1; then
  echo "error: cannot find the getmeajob command ($GMJ)." >&2
  echo "hint: activate the virtual environment, or set GETMEAJOB=/path/to/getmeajob." >&2
  exit 2
fi

made_tmp=""
if [ "$#" -ge 1 ] && [ -n "$1" ]; then
  home="$1"
else
  tmp_base="${TMPDIR:-/tmp}"
  made_tmp="$(mktemp -d "${tmp_base%/}/getmeajob-demo.XXXXXX")"
  home="$made_tmp/workspace"
fi
if [ -e "$home" ] && [ -n "$(ls -A "$home" 2>/dev/null)" ]; then
  echo "error: $home is not empty, so the demo will not use it." >&2
  echo "hint: give a new folder, or run the script with no argument to use a temporary one." >&2
  exit 2
fi

todo="$home/answers-todo.yaml"
steps=11
n=0

step() {
  n=$((n + 1))
  printf '\n== %d/%d  %s\n' "$n" "$steps" "$1"
}

run() {
  printf '$ getmeajob %s\n' "$*"
  "$GMJ" --home "$home" "$@"
}

echo "Demo workspace: $home"

step "Create the demo workspace (synthetic candidate, recorded board replies)"
run init --demo

step "Read the four demo job boards"
run source

step "Score the jobs against the demo preferences"
run rank

step "Plan the form answers"
run plan

step "Write the questions only the candidate can answer to a file"
run plan unknowns --stub "$todo"

step "Save the demo's fixed synthetic answers to those questions into answers.yaml"
run plan answer "$home/quickstart-answers.yaml"

step "Plan again: both demo forms should be ready"
run plan

step "Review every answer that would be sent"
run plan review

step "Fill both mock forms in Chromium without submitting"
dry="$(run apply --mode dry)"
printf '%s\n' "$dry"
if ! printf '%s\n' "$dry" | grep -q "2 dry_ok"; then
  echo "error: the dry run did not fill both demo forms." >&2
  echo "hint: install the browser it drives: playwright install chromium" >&2
  exit 1
fi

step "Write the Excel and Markdown trackers"
run report

step "Show the one-screen summary"
run status

printf '\nDone. Nothing was sent anywhere.\n'
echo "Excel tracker:    $home/exports/tracker.xlsx"
echo "Markdown tracker: $home/exports/tracker.md"
echo "Screenshots:      $home/shots/"
if [ -n "$made_tmp" ]; then
  echo "Delete the demo when you are done: rm -r \"$made_tmp\""
fi
