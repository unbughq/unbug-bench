#!/bin/sh
# Host: <founder identity> | factory/launch-slots.sh FIRST LAST --source port|hunt|plant [launch.sh options]
# Runs `launch.sh 1 --rotation-slot S` for every slot FIRST..LAST in parallel (README "V2 rotation").
# The identity is read once and held in memory, never in argv, env or files. Logs: results/factory/.
# Read whole before running: editing this file while a launcher runs must not change what it executes.
{
set -eu
here=$(cd "$(dirname "$0")" && pwd)
first=${1:?usage: launch-slots.sh FIRST LAST --source ...}; last=${2:?usage}; shift 2
[ ! -t 0 ] || { echo "pipe the age identity on stdin" >&2; exit 1; }
identity=$(cat)
logs=$here/../results/factory; mkdir -p "$logs"
pids=""
# Background jobs ignore SIGINT in sh, so forward INT/TERM as TERM: each launch.sh deletes its VMs.
trap 'kill -TERM $pids 2>/dev/null; wait; exit 130' INT TERM
s=$first
while [ "$s" -le "$last" ]; do
  printf '%s\n' "$identity" | "$here/launch.sh" 1 "$@" --rotation-slot "$s" > "$logs/slot-$s.$(date +%H%M%S).log" 2>&1 &
  pids="$pids $!"; echo "slot $s started" >&2; s=$((s + 1))
done
status=0
for p in $pids; do wait "$p" || status=1; done
exit $status
exit
}
