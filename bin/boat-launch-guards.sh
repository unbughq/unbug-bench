# Shared POSIX host guards. Source after setting root, label, n, ttl_hours, max_spend.
# Hetzner by default (bin/hcloud-boat, about half boat's price); UNBUG_CLOUD=boat uses boat.
# An explicit BOAT_CMD (tests) wins. Exported so collect.sh, push-secrets and boat-spend follow.
[ "${UNBUG_CLOUD:-hetzner}" = boat ] || { BOAT_CMD=${BOAT_CMD:-$root/bin/hcloud-boat}; export BOAT_CMD; }
boat() { "$root/bin/boat-call" "$@"; }
quote() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }
# Each worker retires in its own background task (Murphy row 16): simultaneous
# retirements never queue behind one another. Entries are id:pid:token.
guard_retiring=""; guard_deferred=""; guard_exiting=0; gr_signal=""; guard_task_counter=0
guard_task_epoch=$(date +%s)
guard_signal_traps() {
  trap 'exit 130' INT
  trap 'exit 143' TERM
}

guard_init() {
  state=${UNBUG_LAUNCH_STATE:-$(mktemp -d "${TMPDIR:-/tmp}/boat-launch.XXXXXX")}
  bundle=""; spend_file=""; serial=0
  if [ "${UNBUG_RESUME_LAUNCH:-}" = 1 ]; then
    . "$state/monitor.sh"
  else
    : > "$state/ids"
  fi
  trap 'guard_exit $?' 0
  guard_signal_traps
  [ "${UNBUG_RESUME_LAUNCH:-}" != 1 ] || return 0
  poll=${BOAT_POLL_SECONDS:-120}
  stall_minutes=${BOAT_STALL_MINUTES:-45}  # matches the runner's own silence limit
  unreachable=${BOAT_UNREACHABLE_SECONDS:-600}
  stall_seconds=$(python3 - "$poll" "$stall_minutes" "$unreachable" "${BOAT_COMMAND_TIMEOUT_SECONDS:-120}" <<'PY'
import math, sys
values = [float(x) for x in sys.argv[1:]]
if not all(math.isfinite(x) and x > 0 for x in values):
    sys.exit("poll, stall, unreachable and command timeout must be positive finite numbers")
print(max(1, math.ceil(values[1] * 60)))
PY
  )
  unreachable=$(python3 -c 'import math,sys; print(max(1,math.ceil(float(sys.argv[1]))))' "$unreachable")
  spend_file="$root/results/spend/$(date -u +%Y%m%dT%H%M%SZ)-$$-$label.json"
  if [ -n "${UNBUG_LAUNCH_STATE:-}" ]; then
    ttl_seconds=$("$root/bin/boat-spend" --check "$n" "$ttl_hours" "$max_spend" "$spend_file" "$state")
  else
    ttl_seconds=$("$root/bin/boat-spend" --check "$n" "$ttl_hours" "$max_spend" "$spend_file")
  fi
  # Collect before boat's own TTL: --no-snapshots VMs are erased when it fires.
  margin=${BOAT_TTL_MARGIN_SECONDS:-1800}  # room for checkpoint collection before expiry
  margin=$(python3 - "$margin" "$ttl_seconds" <<'PYCODE'
import sys
raw, ttl = sys.argv[1], int(sys.argv[2])
if not raw.isascii() or not raw.isdigit() or int(raw) <= 0 or ttl <= 1:
    sys.exit("TTL margin must be a positive integer; TTL must exceed one second")
value = int(raw)
print(value if value < ttl else max(1, ttl // 4))
PYCODE
  )
  retire_at=$((ttl_seconds - margin))
  if [ -n "${UNBUG_LAUNCH_STATE:-}" ]; then
    for variable in spend_file ttl_seconds retire_at margin poll stall_minutes stall_seconds unreachable; do
      eval 'value=$'"$variable"
      printf '%s=%s\n' "$variable" "$(quote "$value")"
    done > "$state/monitor.sh.tmp"
    mv "$state/monitor.sh.tmp" "$state/monitor.sh"
  fi
}

# Print IDs, or durably merge them before resolving known creation markers.
guard_ids() {
  python3 -B "$root/factory/boat_lifecycle.py" ids "$state" "${1:-print}"
}

guard_new() {
  serial=$((serial + 1))
  id=""; new_status=0
  # Write uncertainty before the provider can see a request. Never replay a serial.
  python3 - "$state" "$serial" <<'PYINTENT' || return 1
import os, pathlib, sys
state = pathlib.Path(sys.argv[1]); response = state / ('new.' + sys.argv[2])
try:
    if os.path.lexists(response): raise FileExistsError()
    with response.with_name(response.name + '.pending').open('x') as marker:
        marker.flush(); os.fsync(marker.fileno())
    directory = os.open(state, os.O_RDONLY)
    try: os.fsync(directory)
    finally: os.close(directory)
except OSError:
    sys.exit('creation intent unavailable; no request submitted')
PYINTENT
  # BOAT_TYPE (small|default|large|xlarge) picks the boat size; boat-spend prices the cap with it.
  # A fresh VM can take minutes before SSH answers (cpx42 from the 2026-10-17 image: >110 s).
  ( BOAT_COMMAND_TIMEOUT_SECONDS=${BOAT_NEW_TIMEOUT_SECONDS:-300} boat new --from bench-env ${BOAT_TYPE:+--type "$BOAT_TYPE"} --no-env --no-monitoring --no-snapshots --ttl "$ttl_seconds" --json ) > "$state/new.$serial" || new_status=$?
  id=$(python3 - "$state/new.$serial" <<'PY'
import json, pathlib, re, sys
for line in pathlib.Path(sys.argv[1]).read_text().splitlines():
    try: event = json.loads(line)
    except ValueError: continue
    if (isinstance(event, dict) and event.get("event") == "created" and
            isinstance(event.get("id"), str) and re.fullmatch(r"[A-Za-z0-9_-]+", event["id"])):
        print(event["id"]); break
PY
  )
  [ -z "${EXAM_STATUS_FILE:-}" ] || printf '%s\n' "$id" > "$EXAM_STATUS_FILE"
  if [ -z "$id" ]; then
    echo "boat creation outcome unknown; pending reconciliation (no duplicate launch)" >&2
    return 1
  fi
  guard_ids resolve || return 1
  [ "$new_status" -eq 0 ] || { echo "boat new stopped; cleaning up the reported VM" >&2; return 1; }
  # BOAT_CMD replaces all boat activity, including the direct-API naming helper.
  if [ -z "${BOAT_CMD:-}" ]; then "$root/bin/boat-name" "$id" "$label: $purpose" || true; fi
  date +%s > "$state/$id.started"
}

# Boat deletion is asynchronous: inventory absence is only an orphan check.
guard_delete_receipt() {
  python3 -B "$root/factory/boat_lifecycle.py" delete "$root" "$spend_file" "$retire_id" "$state/ids"
}

guard_retire() {
  retire_id=$1
  retire_status=0
  # A safety deletion cannot make missing collection successful, including replay.
  if [ -e "$state/$retire_id.retiring.json" ] && [ ! -f "$state/$retire_id.collected" ]; then
    retire_status=1
  fi
  [ ! -f "$state/$retire_id.deleted" ] || return "$retire_status"
  [ ! -f "$state/$retire_id.keep" ] || { echo "$retire_id: KEEPING VM: checkpoint not verified" >&2; return 1; }
  # Pending detached startup can expose the previous DONE; retire only a fresh collection.
  if [ -f "$state/$retire_id.restart-attempted" ] && [ ! -f "$state/$retire_id.deletion-attempted" ] && [ ! -e "$state/$retire_id.retiring.json" ]; then
    rm -f "$state/$retire_id.collected"
  fi
  if [ ! -f "$state/$retire_id.collected" ] && [ ! -e "$state/$retire_id.retiring.json" ]; then
    # Never delete a VM whose results did not arrive intact (2026-10-17: a cut-off scp lost a case).
    tries=0
    until collect_vm "$retire_id"; do
      tries=$((tries + 1))
      if [ "$tries" -ge 3 ]; then
        echo "collect failed for $retire_id 3 times; KEEPING it running (expires label is the backstop):" \
             "run factory/collect.sh $retire_id, then bin/hcloud-boat delete $retire_id --yes" >&2
        return 1
      fi
      sleep "${BOAT_COLLECT_RETRY_SECONDS:-30}"
    done
    touch "$state/$retire_id.collected"
  fi
  # A resumable case keeps its VM until its paid hour ends (factory/resume-in-place.sh continues it there).
  if [ "${BOAT_CMD:-}" = "$root/bin/hcloud-boat" ] && [ "$label" = factory ] && [ ! -f "$state/$retire_id.ttl-continuation" ] && "$root/bin/hcloud-park" "$retire_id"; then
    touch "$state/$retire_id.deleted" "$state/$retire_id.parked"; return "$retire_status"
  fi
  # A failed/unknown Boat request is never submitted again by the exit trap.
  if [ "${UNBUG_CLOUD:-hetzner}" = boat ] && [ "${BOAT_CMD:-}" != "$root/bin/hcloud-boat" ]; then
    guard_delete_receipt || return 1
  else
    boat delete "$retire_id" --yes >/dev/null || {
      echo "WARNING: DELETE FAILED for $retire_id; TTL remains the backstop" >&2
      return 1
    }
  fi
  touch "$state/$retire_id.deleted"
  if [ "$label" = factory ] && command -v factory_ttl_retired >/dev/null 2>&1; then
    factory_ttl_retired "$retire_id" || { echo "$retire_id: TTL deletion evidence not recorded; continuation blocked" >&2; retire_status=1; }
  fi
  echo "deleted $retire_id" >&2
  return "$retire_status"
}

guard_retire_running() {
  case " $guard_retiring " in *" $1:"*) return 0 ;; esac
  return 1
}

guard_retire_owned_pid() {
  case " $guard_retiring " in *":$1:"*) return 0 ;; esac
  return 1
}

# Start <id>'s retirement (kind retire|ttl) as its own task; the poll loop never
# waits on it. Its status is a token-named file, so a stale or orphan one is never read.
guard_retire_start() {
  gr_id=$1; gr_kind=$2
  guard_task_counter=$((guard_task_counter + 1))
  gr_token=$guard_task_epoch.$$.$guard_task_counter
  gr_exit=$state/$gr_id.retirement-exit.$gr_token
  # Before the fork: this glob must never remove the new task's own status.
  rm -f "$state/$gr_id".retirement-exit.*
  gr_signal=""
  # Defer INT/TERM until the task is recorded, so guard_exit joins it, never kills it.
  if [ "$guard_exiting" != 1 ]; then trap 'gr_signal=130' INT; trap 'gr_signal=143' TERM; fi
  (
    trap - 0
    gr_s=0
    case $gr_kind in
      ttl)
        if [ "$label" = factory ] && command -v factory_ttl_retire >/dev/null 2>&1; then
          factory_ttl_retire "$gr_id" || echo "$gr_id: TTL attestation failed; collection remains a manual pause" >&2
        fi
        guard_retire "$gr_id" || gr_s=$? ;;
      *) guard_retire "$gr_id" || gr_s=$? ;;
    esac
    printf '%s\n' "$gr_s" > "$gr_exit.tmp" && mv "$gr_exit.tmp" "$gr_exit"
  ) &
  guard_retiring="$guard_retiring $gr_id:$!:$gr_token"
  if [ "$guard_exiting" != 1 ]; then
    guard_signal_traps
    [ -z "$gr_signal" ] || exit "$gr_signal"
  fi
}

# Reap finished tasks (every task with "block"); 1 if a reaped retirement failed.
# A task that ended without a status (killed, shell error, full disk) is a failed
# retirement: marked retired, never re-classified; the exit pass retries it.
guard_retire_reap() {
  gr_block=${1:-}; gr_failed=0; gr_left=""
  for gr_entry in $guard_retiring; do
    gr_id=${gr_entry%%:*}; gr_rest=${gr_entry#*:}
    gr_pid=${gr_rest%%:*}; gr_token=${gr_rest#*:}
    gr_exit=$state/$gr_id.retirement-exit.$gr_token
    if [ "$gr_block" != block ] && [ ! -f "$gr_exit" ] && kill -0 "$gr_pid" 2>/dev/null; then
      gr_left="$gr_left $gr_entry"; continue
    fi
    wait "$gr_pid" 2>/dev/null || :
    gr_s=$(cat "$gr_exit" 2>/dev/null || :)
    case $gr_s in
      0) ;;
      ''|*[!0-9]*) echo "$gr_id: retirement task ended without a status; treated as a failed retirement" >&2; gr_failed=1 ;;
      *) gr_failed=1 ;;
    esac
    rm -f "$gr_exit"
    touch "$state/$gr_id.retired"
  done
  guard_retiring=$gr_left
  return "$gr_failed"
}

guard_retirements_active() {
  case $guard_retiring in *[!\ ]*) return 0 ;; esac
  return 1
}

guard_cleanup_error() {
  guard_cleanup_failed=true
  [ "$exit_code" -ne 0 ] || exit_code=1
}

guard_exit() {
  exit_code=$1
  guard_primary_exit_code=$1
  guard_cleanup_failed=false
  trap - 0
  trap '' INT TERM
  set +e
  # The shell job table also covers a signal between starting a probe and recording its PID.
  # Recorded retirement tasks are joined instead: killing one would orphan its collect.sh.
  for probe_pid in $(jobs -p); do
    guard_retire_owned_pid "$probe_pid" && continue
    kill -TERM "$probe_pid" 2>/dev/null
    wait "$probe_pid" 2>/dev/null
  done
  guard_exiting=1
  # Logged only: the exit pass below decides cleanup, as it did for an
  # interrupted foreground retirement.
  guard_retire_reap block || echo "an in-flight retirement failed; the exit pass retries it" >&2
  guard_ids_failed=0
  guard_ids resolve || { guard_ids_failed=1; guard_cleanup_error; }
  for exit_id in $(cat "$state/ids"); do guard_retire_start "$exit_id" retire; done
  guard_retire_reap block || guard_cleanup_error
  if [ -s "$state/ids" ]; then
    if boat list --json > "$state/list.json"; then
      python3 - "$state/ids" "$state/list.json" "$state" <<'PY'
import json, pathlib, sys
ids = set(pathlib.Path(sys.argv[1]).read_text().split())
parked = {i for i in ids if (pathlib.Path(sys.argv[3]) / f"{i}.parked").exists()}
for i in sorted(parked): print(f"{i}: parked until its paid hour ends (factory/resume-in-place.sh {i}); not an orphan", file=sys.stderr)
ids -= parked
def walk(value):
    if isinstance(value, dict):
        if value.get("id") in ids and value.get("status", value.get("state", "")).lower() not in ("deleted", "stopped", "destroyed", "terminated"):
            print(f"!!! ORPHAN: {value['id']} STILL ALIVE — DELETE IT NOW !!!", file=sys.stderr)
            return True
        return any([walk(v) for v in value.values()])
    return any([walk(v) for v in value]) if isinstance(value, list) else False
sys.exit(1 if walk(json.loads(pathlib.Path(sys.argv[2]).read_text())) else 0)
PY
      [ "$?" -eq 0 ] || { echo "!!! ORPHAN CHECK: verify deletion of this launch's VMs !!!" >&2; guard_cleanup_error; }
    else
      echo "!!! ORPHAN CHECK FAILED: verify these VMs are deleted: $(cat "$state/ids") !!!" >&2
      guard_cleanup_error
    fi
  fi
  unfinished=$guard_ids_failed
  for creation in "$state"/new.*.pending; do
    if [ -e "$creation" ] || [ -L "$creation" ]; then unfinished=1; fi
  done
  for exit_id in $(cat "$state/ids"); do
    [ -f "$state/$exit_id.deleted" ] || unfinished=1
  done
  if [ -n "$spend_file" ] && [ -f "$spend_file" ] && [ "$unfinished" -eq 0 ]; then
    if [ ! -f "$state/spend-finished" ]; then
      if "$root/bin/boat-spend" --finish "$spend_file" "$exit_code" "$state/ids"; then
        touch "$state/spend-finished"
      else guard_cleanup_error; fi
    fi
  fi
  [ -z "$bundle" ] || rm -f "$bundle"
  if [ -n "${UNBUG_LAUNCH_STATE:-}" ]; then
    printf '{"primary_exit_code":%s,"cleanup_failed":%s}\n' "$guard_primary_exit_code" "$guard_cleanup_failed" > "$state/cleanup-status.json"
    if [ "$unfinished" -eq 0 ] && [ -f "$state/spend-finished" ]; then touch "$state/complete"; fi
  elif [ "$unfinished" -eq 0 ] && [ "$guard_cleanup_failed" = false ]; then
    rm -rf "$state"
  else
    echo "unfinished launch evidence retained: $state" >&2
  fi
  exit "$exit_code"
}

guard_wait() {
  wait_status=0
  wait_once=${1:-}
  # Probe together so one unreachable VM cannot delay the rest of the batch.
  probe="python3 -c $(quote "$probe_python")"
  while :; do
    guard_retire_reap || wait_status=1
    pending=0
    for wait_id in $(cat "$state/ids"); do
      # An in-flight retirement owns its worker until it is reaped.
      if guard_retire_running "$wait_id"; then pending=1; continue; fi
      [ ! -f "$state/$wait_id.retired" ] || continue
      [ ! -f "$state/$wait_id.deleted" ] || { touch "$state/$wait_id.retired"; continue; }
      # A recorded deletion operation is reconciled through the receipt path, not SSH.
      if [ -f "$state/$wait_id.deletion-attempted" ]; then
        guard_retire_start "$wait_id" retire; pending=1; continue
      fi
      pending=1
      rm -f "$state/$wait_id.ok"
      "$root/bin/boat-call" ssh "$wait_id" "$probe" > "$state/$wait_id.reply" &
      echo "$!" > "$state/$wait_id.pid"
    done
    [ "$pending" -ne 0 ] || guard_retirements_active || return "$wait_status"
    for wait_id in $(cat "$state/ids"); do
      [ -f "$state/$wait_id.pid" ] || continue
      if wait "$(cat "$state/$wait_id.pid")"; then touch "$state/$wait_id.ok"; fi
      rm -f "$state/$wait_id.pid"
    done
    pending=0
    guard_deferred=""
    for wait_id in $(cat "$state/ids"); do
      if guard_retire_running "$wait_id"; then pending=1; continue; fi
      [ ! -f "$state/$wait_id.retired" ] || continue
      retire_kind=retire
      if [ -f "$state/$wait_id.ok" ]; then
        reply=$(cat "$state/$wait_id.reply")
        case $reply in
          STARTUP_FAILED)
            echo "$wait_id: runner startup failed; collecting operational exit receipt" >&2
            wait_status=1
            guard_retire_start "$wait_id" retire; pending=1; continue ;;
          DONE)
            # Factory-only hook: retain the original TTL/spend envelope and restart in place.
            # Exams and Hetzner keep their existing retirement paths. It stays inline (its
            # stop semantics need the launcher trap), after every due peer's task started.
            if [ "$label" = factory ] && command -v factory_auto_resume >/dev/null 2>&1; then
              guard_deferred="$guard_deferred $wait_id"; pending=1; continue
            fi
            guard_retire_start "$wait_id" retire; pending=1; continue ;;
          *[!0-9]*|'') reply="" ;;
        esac
      else reply=""; fi
      now=$(date +%s)
      if [ -n "$reply" ]; then
        rm -f "$state/$wait_id.failed"
        if [ "$reply" -ge "$stall_seconds" ]; then
          echo "$wait_id STALLED: no progress for $stall_minutes min" >&2
        elif [ $((now - $(cat "$state/$wait_id.started"))) -lt "$retire_at" ]; then pending=1; continue
        else
          echo "$wait_id: TTL margin reached; collecting before boat erases it" >&2
          retire_kind=ttl  # its task attests first (factory_ttl_retire), then collects
        fi
      else
        [ -f "$state/$wait_id.failed" ] || echo "$now" > "$state/$wait_id.failed"
        if [ $((now - $(cat "$state/$wait_id.failed"))) -lt "$unreachable" ] &&
           [ $((now - $(cat "$state/$wait_id.started"))) -lt "$retire_at" ]; then pending=1; continue; fi
        echo "$wait_id UNREACHABLE: failed polls for $unreachable seconds (or TTL margin reached)" >&2
      fi
      wait_status=1
      guard_retire_start "$wait_id" "$retire_kind"; pending=1
    done
    # Phase 2: inline auto-resume never delays a peer due in this pass.
    for wait_id in $guard_deferred; do
      factory_auto_resume "$wait_id" || guard_retire_start "$wait_id" retire
    done
    guard_deferred=""
    [ "$wait_once" != once ] || return "$wait_status"
    [ "$pending" -ne 0 ] || guard_retirements_active || return "$wait_status"
    sleep "$poll" & wait $!
  done
}
