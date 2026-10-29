#!/bin/sh
# Host: factory/collect.sh <sandbox-id>. Copy only sealed archives, scorecards and
# dry-run throwaway keys into ../sealed/, printing scorecards. Does not delete VMs.
# BOAT_CMD is an optional executable override; each CLI call has a bounded timeout.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
dest=$root/sealed
boat() { "$root/bin/boat-call" "$@"; }
id=${1:?usage: collect.sh <sandbox-id>}
mkdir -p "$dest"
# A case still running is asked to pause first: SIGTERM makes factory/run.py seal a checkpoint and write DONE
# (up to ~18 min), so stall, time-limit, Ctrl-C and sweeper retirements all collect resumable work.
pause_status=0
( BOAT_COMMAND_TIMEOUT_SECONDS=${COLLECT_PAUSE_SECONDS:-1200} boat ssh "$id" 'if [ ! -f ~/sealed/DONE ] && pgrep -f "^python3 .*factory/run.py" >/dev/null; then
  pkill -TERM -f "^python3 .*factory/run.py"; i=0
  while [ ! -f ~/sealed/DONE ] && [ $i -lt 105 ]; do sleep 10; i=$((i + 1)); done
  [ -f ~/sealed/DONE ] && echo "paused and checkpointed" >&2 || { echo "pause requested; no DONE after 17.5 min" >&2; exit 1; }
fi; true' ) || pause_status=1
# Supervisor diagnostics contain allowlisted public metadata, independently of case archives.
if boat ssh "$id" 'test ! -f ~/sealed/runner-status.json || cat ~/sealed/runner-status.json' | python3 -c '
import json, math, sys
raw = sys.stdin.read(16385)
if not raw.strip(): sys.exit(0)
if len(raw) > 16384: sys.exit(1)
d = json.loads(raw)
if (d.get("schema") != 1 or type(d.get("attempt")) is not int or not 1 <= d["attempt"] <= 3 or
    d.get("phase") not in ("running", "startup", "finished", "stopped") or
    d.get("reason") not in ("running", "startup_retry", "startup_failed", "finished", "cancelled", "timeout") or
    (d.get("exit_status") is not None and type(d["exit_status"]) is not int) or
    type(d.get("observed_at")) not in (int, float) or not math.isfinite(d["observed_at"])): sys.exit(1)
print(json.dumps({k:d[k] for k in ("schema", "attempt", "phase", "reason", "exit_status", "observed_at")}))
' > "$dest/$id.runner-status.json.tmp"; then
  if [ -s "$dest/$id.runner-status.json.tmp" ]; then
    mv "$dest/$id.runner-status.json.tmp" "$dest/$id.runner-status.json"
  else rm -f "$dest/$id.runner-status.json.tmp"; fi
else rm -f "$dest/$id.runner-status.json.tmp"; fi
# Empty patterns and a VM that never got as far as ~/sealed are normal (nothing to collect); a failed SSH stays an error.
# WORK = unwiped case work is still on the VM (a final seal wipes it; a stop keeps it beside its checkpoint).
files=$(boat ssh "$id" 'for d in ~/work/case-*/case ~/work/case-*/g11-audit/case; do
  if [ -d "$d" ] && [ -n "$(ls -A "$d")" ]; then
    echo WORK
    case "$d" in
      */g11-audit/case) echo "WORKCASE:g11-review-$(basename "$(dirname "$(dirname "$d")")")" ;;
      *) echo "WORKCASE:$(basename "$(dirname "$d")")" ;;
    esac
    [ -f ~/sealed/DONE ] || echo UNFINISHED
  fi
done
[ -d ~/sealed ] || exit 0; cd ~/sealed || exit 1
ls *.age *.scorecard.json *.scorecard.txt *.progress.json *.throwaway-key.txt 2>/dev/null; true') || exit 1
work=no; case " $(echo $files) " in *" WORK "*) work=yes; files=$(printf '%s\n' $files | grep -vx WORK || true) ;; esac
# An uncertain pause cannot authorize disposal, even if an older archive exists.
work_cases=$(printf '%s\n' $files | sed -n 's/^WORKCASE://p')
files=$(printf '%s\n' $files | grep -v '^WORKCASE:' || true)
status=$pause_status
case " $(echo $files) " in *" UNFINISHED "*)
  files=$(printf '%s\n' $files | grep -vx UNFINISHED || true)
  echo "$id holds case work without a completed seal; retaining worker" >&2; status=1 ;;
esac
# Never let a VM go while it holds case work that no collected archive covers (2026-10-17: two cases at G14 were
# deleted with nothing collected). The launcher then keeps the VM and says so.
if [ "$work" = yes ] && ! printf '%s\n' $files | grep -q '\.tar\.gz\.age$'; then
  echo "$id holds unsealed case work and no archive was collected" >&2; status=1
fi
for f in $files; do
  case $f in *[!A-Za-z0-9_.-]*|.*) echo "unexpected result filename" >&2; status=1; continue ;; esac
  case $f in *.statement.age|*.age|*.scorecard.json|*.scorecard.txt|*.progress.json|*.throwaway-key.txt) ;; *) status=1; continue ;; esac
  # Bounded chunks resume across retries; only SHA-verified bytes replace a local result.
  # The normal 120s Boat bound applies to each 8 MiB chunk, not a ~500 MiB archive.
  if python3 "$here/transfer.py" "$id" "$f" "$dest"; then
    case $f in *.scorecard.txt) cat "$dest/$f" || status=1 ;; esac
  else status=1; fi
done
# No absent/prefix-matched/stale archive can authorize collection or disposal.
python3 "$here/collection.py" "$dest" "$work" "$files" "$work_cases" || status=1
if [ "$status" -eq 0 ] && [ -f "$root/results/ttl-retirements/$id.json" ]; then
  # Queue only after every transfer and archive verification succeeded. Bounds or
  # attestation refusal blocks continuation, never disposal of safely sealed work.
  python3 "$here/ttl_continuation.py" collect --root "$root" --worker "$id" >/dev/null ||
    echo "$id: TTL continuation blocked; collected work retained" >&2
fi
exit "$status"
