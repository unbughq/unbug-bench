#!/bin/sh
# Host: <founder identity> | factory/restore-cases.sh CASE_ID... [launch.sh options]
# Resumes every listed case in parallel (one VM each) via `launch.sh 1 --restore`, taking its source and
# rotation slot from sealed/CASE_ID.scorecard.json. The identity is read once and held in memory, never
# in argv, env or files. Logs: results/factory/restore-CASE_ID.HHMMSS.log.
# Read whole before running: editing this file while a launcher runs must not change what it executes.
{
set -eu
here=$(cd "$(dirname "$0")" && pwd)
launch=${RESTORE_LAUNCH:-$here/launch.sh}  # tests pass a fake
[ $# -gt 0 ] || { echo "usage: restore-cases.sh CASE_ID... [launch.sh options]" >&2; exit 1; }
[ ! -t 0 ] || { echo "pipe the age identity on stdin" >&2; exit 1; }
cases=""; while [ $# -gt 0 ]; do case $1 in case-*) cases="$cases $1"; shift ;; *) break ;; esac; done
identity=$(cat)
logs=$here/../results/factory; mkdir -p "$logs"
pids=""
# Background jobs ignore SIGINT in sh, so forward INT/TERM as TERM: each launch.sh collects before deleting.
trap 'kill -TERM $pids 2>/dev/null; wait; exit 130' INT TERM
for c in $cases; do
  card=$here/../sealed/$c.scorecard.json
  meta=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["source"], d["rotation_slot"])' "$card") ||
    { echo "$c: no readable $card" >&2; exit 1; }
  source=${meta% *}; slot=${meta#* }
  printf '%s\n' "$identity" | "$launch" 1 --restore "$c" --source "$source" --rotation-slot "$slot" "$@" \
    > "$logs/restore-$c.$(date +%H%M%S).log" 2>&1 &
  pids="$pids $!"; echo "$c (slot $slot) started" >&2
done
status=0
for p in $pids; do wait "$p" || status=1; done
exit $status
exit
}
