#!/bin/sh
# Founder-approved future run only. No keys, holder, control VM or model providers.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
usage() {
  echo "Usage: $0 --release DIR --adapter FILE --adapter-sha256 SHA --approved-by-founder [--output DIR]"
  echo "Use a newly qualified release containing the smoke sources; old pinned releases are refused."
}
release=""; adapter=""; adapter_sha=""; approved=no
output="$root/results/infrastructure/2026-10-24-gate-smoke/live"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --approved-by-founder) approved=yes; shift ;;
    --release|--adapter|--adapter-sha256|--output)
      [ "$#" -ge 2 ] || { usage >&2; exit 2; }
      case "$1" in
        --release) release=$2 ;; --adapter) adapter=$2 ;;
        --adapter-sha256) adapter_sha=$2 ;; --output) output=$2 ;;
      esac
      shift 2 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[ "$approved" = yes ] && [ -n "$release" ] && [ -n "$adapter" ] && [ -n "$adapter_sha" ] || { usage >&2; exit 2; }
# Refuse inherited alternative clouds, profiles or launch states; this owns ONE new Boat worker.
[ -z "${BOAT_CMD:-}" ] && [ -z "${UNBUG_LAUNCH_STATE:-}" ] || { echo "clear BOAT_CMD/UNBUG_LAUNCH_STATE" >&2; exit 2; }
mkdir -p "$output"
output=$(CDPATH= cd -- "$output" && pwd)
state=$(mktemp -d "$output/run.XXXXXX")
# Verify the reviewed adapter and all changed runtime sources BEFORE allocation.
python3 -B - "$root" "$release" "$adapter" "$adapter_sha" "$state/bundle.tgz" <<'PYCODE'
import hashlib, pathlib, runpy, sys
root, release, adapter = map(pathlib.Path, sys.argv[1:4])
if adapter.is_symlink() or hashlib.sha256(adapter.read_bytes()).hexdigest() != sys.argv[4]:
    raise SystemExit('reviewed qualified adapter digest mismatch')
module = runpy.run_path(str(adapter), run_name='gate_smoke_release')
_, _, files = module['load'](release)
for name in ('factory/account_handoff.py', 'factory/restart.py', 'factory/control_resume.py', 'bin/push-secrets', 'tests/factory/test_account_handoff.py', 'tests/factory/test_control_resume.py', 'tests/factory/test_admission_handoff.py', 'tests/factory/fixtures/opencode-failover/policy.restore.json', 'tests/factory/fixtures/opencode-failover/launch.json', 'tests/factory/fixtures/opencode-failover/input-scorecard.json', 'tests/factory/fixtures/opencode-failover/launch-state.json', 'bin/gate-smoke', 'bin/bench.py', 'bin/bench_judging.py', 'bin/factory_pool.py',
             'factory/gate_pipeline.py', 'factory/case_contract.py',
             'factory/run_artifacts.py', 'factory/run.py', 'factory/case_permissions.py'):
    if files.get(name) != hashlib.sha256((root / name).read_bytes()).hexdigest():
        raise SystemExit('qualify current smoke source first: ' + name)
# 2026-10-24: the refactor moved the canary model-route line into model_runtime.py;
# the smoke calls no model. Accept that exact rewrite of the current source, nothing else.
code = (root / 'factory/model_runtime.py').read_text()
paid = 'cli_model = {"opencode/deepseek-v4.1-flash-free": "opencode-go/deepseek-v4.1-flash"}.get(model, model)'
note = ("            # 2026-10-20: OpenCode refuses its anonymous free DeepSeek from boat's shared IPs and Go lists it as unavailable;\n"
        "            # the same model on the Go plan (priced, cheap) stands in. Roles and cards keep the recorded name.\n")
routed = code.replace(paid, 'cli_model = model  # isolated one-case candidate: preserve selected free route').replace(note, '')
if files.get('factory/model_runtime.py') not in {hashlib.sha256(c.encode()).hexdigest() for c in (code, routed)}:
    raise SystemExit('qualify current smoke source first: factory/model_runtime.py')
module['prepare'](release, pathlib.Path(sys.argv[5]))
PYCODE
# Same canary envelope: 8-hour TTL, $0.50 maximum reservation. This harness has
# a separate 45-minute controller deadline and 30-minute remote test deadline.
UNBUG_CLOUD=boat; BOAT_TYPE=default; export UNBUG_CLOUD BOAT_TYPE
UNBUG_LAUNCH_STATE=$state; export UNBUG_LAUNCH_STATE
BOAT_TTL_MARGIN_SECONDS=600; export BOAT_TTL_MARGIN_SECONDS
label=gate-smoke; purpose=public-gate-smoke; n=1; ttl_hours=8; max_spend=0.50
. "$root/bin/boat-launch-guards.sh"
collect_vm() {
  # Public fixture only: a failed collection must never strand a paid test worker.
  if BOAT_COMMAND_TIMEOUT_SECONDS=60 boat ssh "$1" 'cat ~/gate-smoke/summary.json' > "$state/summary.json.tmp"; then
    if python3 -m json.tool "$state/summary.json.tmp" > "$state/summary.json"; then
      rm -f "$state/summary.json.tmp"
    fi
  fi
  if [ ! -s "$state/summary.json" ]; then
    printf '%s\n' '{"status":"FAIL","error":"remote summary missing; inspect run.log"}' > "$state/summary.json"
  fi
  BOAT_COMMAND_TIMEOUT_SECONDS=60 boat ssh "$1" 'test ! -d ~/gate-smoke || tar -czf - -C ~ gate-smoke' > "$state/worker-logs.tgz" || true
  return 0
}
guard_init
bundle="$state/bundle.tgz"
# The guard's exit trap owns deletion (with provider completion receipt) even if
# creation/upload/setup/test/collection fails or the controller receives a signal.
(
  trap 'kill "$timer" 2>/dev/null || true; exit 0' TERM INT
  sleep 2700 & timer=$!
  wait "$timer"
  kill -TERM "$$"
) >/dev/null 2>&1 &
watchdog=$!
requested_mono=$(python3 -c 'import time; print(time.monotonic())')
requested_wall=$(python3 -c 'import time; print(time.time())')
guard_new
printf '%s\n' "$id" > "$state/worker-id"
python3 "$root/tools/boat_readiness.py" "$root/bin/boat-call" "$id" "$BOAT_TYPE" \
  "$ttl_seconds" "$requested_mono" "$requested_wall" 600 "$state/readiness.json"
bundle_sha=$(shasum -a 256 "$bundle" | cut -d ' ' -f 1)
BOAT_COMMAND_TIMEOUT_SECONDS=300 boat --stdin ssh "$id" \
  "set -eu; cd ~; umask 077; cat > gate-smoke-release.tgz; printf '%s  %s\\n' '$bundle_sha' gate-smoke-release.tgz | sha256sum -c -; tar -xzf gate-smoke-release.tgz; rm gate-smoke-release.tgz" < "$bundle" > "$state/upload.log"
boat ssh "$id" 'python3 -B ~/qualified-release/deploy.py install --release ~/qualified-release' > "$state/install.json"
boat ssh "$id" 'python3 -B ~/qualified-release/deploy.py verify --release ~/qualified-release' > "$state/verify.json"
# Build the checked-in public baseline if the fresh worker has no cached image.
BOAT_COMMAND_TIMEOUT_SECONDS=1200 boat ssh "$id" \
  'set -eu; cd ~/unbug-bench; docker compose -f projects/medusa/compose.yaml pull postgres redis; docker compose -f projects/medusa/compose.yaml build medusa' > "$state/baseline-build.log" 2>&1
boat ssh "$id" "python3 -B ~/factory/worker_release.py --manifest ~/worker-release-manifest.json --root ~/unbug-bench --factory-root ~/factory --drivers ''" > "$state/worker-release.json"
# This marker is installed only on the ID returned by guard_new, never a supplied ID.
boat ssh "$id" "python3 -c 'import json,pathlib; p=pathlib.Path(\"/tmp/unbug-gate-smoke-owned.json\"); p.write_text(json.dumps({\"worker_id\":\"$id\",\"root\":str(pathlib.Path.home()/\"unbug-bench\")}))'"
status=0
BOAT_COMMAND_TIMEOUT_SECONDS=1900 boat ssh "$id" \
  "cd ~/unbug-bench && python3 -B bin/gate-smoke --run --worker-id '$id'" > "$state/run.log" 2>&1 || status=$?
collect_vm "$id"
touch "$state/$id.collected"
guard_retire "$id" || status=1
kill "$watchdog" 2>/dev/null || true
python3 - "$state/summary.json" <<'PYCODE' || status=1
import json, pathlib, sys
if json.loads(pathlib.Path(sys.argv[1]).read_text()).get('status') != 'PASS':
    raise SystemExit('gate smoke failed; see summary and captured worker logs')
PYCODE
printf 'Evidence: %s\nDeletion receipts: %s\n' "$state" "${spend_file%.json}.deletions/$id"
exit "$status"
