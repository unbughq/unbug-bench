#!/bin/sh
# Host: <founder identity> | factory/launch.sh N --source port|hunt|plant [--ttl-hours 8] [--max-spend 3]
# <founder identity> | factory/launch.sh --resume-launch ID (or --resume-launches)
# [--stall-minutes 20] [run.py options]. TTL 8 h: real cases took 5-6 h on 2026-10-17 (writing ~2 h + serial gates).
# Boat transient stops restart in place at most three times inside the original TTL/spend cap.
# Every stop is collected and verified first; failed gates and budget caps never restart.
# Collect sealed results, then delete every created VM on success, error, INT or TERM.
# FACTORY_SECRETS: keys pushed by bin/push-secrets (default: every key in the bundle).
# BOAT_CMD overrides boat with an executable; BOAT_POLL_SECONDS shortens test polls.
# Read whole before running: editing this file while a launcher runs must not change what it executes.
{
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
if [ "${UNBUG_CONTROL_PID:-}" != "$$" ]; then
  exec python3 "$here/control_resume.py" "$@"
fi
n=${1:?usage: launch.sh N --source port|hunt|plant [...]}; shift
case $n in *[!0-9]*|'') echo "N must be a positive integer" >&2; exit 1 ;; esac
[ "$n" -gt 0 ] || exit 1
qualified_release=""
batch_release=""; batch_sha=""; checkpoint_sha=""
founder_ruling_sha=""
admission_root=$root
ttl_hours=8; max_spend=3; args=""; purpose=case; label=factory; restore=""; audit_g11=no; continue_review=no; reuse_worker=""; sealed_audit=""
# Factory servers: most cores per euro first (cx53 16c, cx43 8c when in stock), then cpx42 8c, then cpx32 4c.
# Bench parallelism follows the cores (run.py: one bench run per 2 cores); checks ~3x faster on 8 cores (2026-10-17).
HCLOUD_PLACES=${HCLOUD_PLACES:-cx53@fsn1 cx53@nbg1 cx53@hel1 cx43@fsn1 cx43@nbg1 cx43@hel1 cpx42@fsn1 cpx42@nbg1 cpx42@hel1 cpx32@fsn1 cpx32@nbg1 cpx32@hel1}; export HCLOUD_PLACES
. "$root/bin/boat-launch-guards.sh"
while [ $# -gt 0 ]; do
  case $1 in
    --founder-ruling-sha256) [ $# -ge 2 ] || exit 1; founder_ruling_sha=$2; shift 2 ;;
    --admission-root) [ $# -ge 2 ] && [ -d "$2/sealed" ] || { echo "missing authoritative admission root" >&2; exit 1; }; admission_root=$2; shift 2 ;;
    --qualified-release) [ $# -ge 2 ] && [ -n "$2" ] || { echo "missing qualified release directory" >&2; exit 1; }; qualified_release=$2; shift 2 ;;
    --batch-release) [ $# -ge 2 ] || exit 1; batch_release=$2; qualified_release=$2; shift 2 ;;
    --batch-sha256) [ $# -ge 2 ] || exit 1; batch_sha=$2; shift 2 ;;
    --checkpoint-sha256) [ $# -ge 2 ] || exit 1; checkpoint_sha=$2; shift 2 ;;
    --audit-fairness|--rehearse-only) sealed_audit=$1; args="$args $(quote "$1")"; shift ;;
    --audit-g11) audit_g11=yes; args="$args '--audit-g11'"; shift ;;
    --restore-review) [ $# -ge 2 ] || { echo "missing value for $1" >&2; exit 1; }; restore=$2; continue_review=yes; audit_g11=yes; args="$args '--continue-g11-review'"; shift 2 ;;
    --reuse-review-worker) [ $# -ge 2 ] || { echo "missing value for $1" >&2; exit 1; }; reuse_worker=$2; shift 2 ;;
    --restore) [ $# -ge 2 ] || { echo "missing value for $1" >&2; exit 1; }; restore=$2; shift 2 ;;
    --case-budget|--rounds)
      [ $# -ge 2 ] || { echo "missing value for $1" >&2; exit 1; }
      args="$args $(quote "$1") $(quote "$2")"; shift 2 ;;
    --ttl-hours|--max-spend|--stall-minutes)
      [ $# -ge 2 ] || { echo "missing value for $1" >&2; exit 1; }
      case $1 in
        --ttl-hours) ttl_hours=$2 ;;
        --max-spend) max_spend=$2 ;;
        --stall-minutes) BOAT_STALL_MINUTES=$2 ;;
      esac
      shift 2 ;;
    *) args="$args $(quote "$1")"; shift ;;
  esac
done
if [ -n "$batch_release" ]; then
  [ "$n" -eq 1 ] || { echo "batch jobs require N=1" >&2; exit 1; }
  python3 -B "$here/batch.py" verify --root "$root" --release "$batch_release" --sha256 "$batch_sha"
  args="$args --batch-release-sha256 $(quote "$batch_sha")"
elif [ -n "$batch_sha" ]; then
  echo "batch digest requires a batch release" >&2; exit 1
fi
if [ -n "$founder_ruling_sha" ] && [ -z "$restore" ]; then
  echo "founder ruling requires a restore" >&2; exit 1
fi
if [ -n "$sealed_audit" ]; then
  [ -n "$restore" ] && [ "$audit_g11" = no ] && [ -z "$reuse_worker" ] || { echo "sealed audit requires a fresh restore" >&2; exit 1; }
fi
if [ -n "$reuse_worker" ]; then
  [ "$continue_review" = yes ] && [ "$n" -eq 1 ] && [ "${UNBUG_CLOUD:-hetzner}" = boat ] || { echo "--reuse-review-worker requires one Boat --restore-review" >&2; exit 1; }
  case $reuse_worker in *[!A-Za-z0-9_-]*|'') echo "invalid worker id" >&2; exit 1 ;; esac
fi
# This adapter stays outside the worker runtime manifest. Its bytes are bound by
# this holder-pinned launcher; never execute an unverified deployment helper.
qualified_adapter() {
  python3 -B - "$root/bin/qualified-release.py" "$@" <<'PYCODE'
import hashlib, json, pathlib, sys
path = pathlib.Path(sys.argv[1])
if path.is_symlink(): raise SystemExit('symlink release adapter')
code = path.read_bytes()
pins = path.parent.parent / 'factory/launcher-sha256.json'
if pins.is_symlink() or not pins.is_file():
    raise SystemExit('missing helper hashes; review launcher fingerprint')
expected = json.loads(pins.read_text())['bin/qualified-release.py']
if hashlib.sha256(code).hexdigest() != expected:
    raise SystemExit('qualified release adapter changed; review launcher fingerprint')
sys.argv = [str(path), *sys.argv[2:]]
exec(compile(code, str(path), 'exec'), {'__name__': '__main__', '__file__': str(path), 'QUALIFIED_ADAPTER_BYTES': code})
PYCODE
}
# Bound transitively by the holder's launcher fingerprint, outside frozen runtime.
qualified_readiness() {
  python3 -B - "$root/tools/boat_readiness.py" "$root/bin/boat-call" "$id" "${BOAT_TYPE:-default}" "$ttl_seconds" "$readiness_mono" "$readiness_wall" "$margin" "${spend_file%.json}-$id.readiness.json" <<'PYCODE'
import hashlib, pathlib, sys
import json
path = pathlib.Path(sys.argv[1])
if path.is_symlink(): raise SystemExit('symlink readiness helper')
code = path.read_bytes()
pins = path.parent.parent / 'factory/launcher-sha256.json'
if pins.is_symlink() or not pins.is_file():
    raise SystemExit('missing helper hashes; review launcher fingerprint')
if hashlib.sha256(code).hexdigest() != json.loads(pins.read_text())['tools/boat_readiness.py']:
    raise SystemExit('readiness helper changed; review launcher fingerprint')
sys.argv = [str(path), *sys.argv[2:]]
exec(compile(code, str(path), 'exec'), {'__name__': '__main__', '__file__': str(path)})
PYCODE
}

if [ -n "$qualified_release" ] && [ -n "$reuse_worker" ]; then
  echo "qualified source installation requires a fresh worker" >&2; exit 1
fi
collect_vm() { "$here/collect.sh" "$1"; }
factory_ttl_retire() {
  [ -n "${FACTORY_TTL_CONTINUATION:-}" ] || return 0
  [ -z "$sealed_audit" ] && [ "$audit_g11" = no ] || return 1
  python3 "$here/ttl_continuation.py" retire --root "$root" --worker "$1" --job-json "$FACTORY_TTL_CONTINUATION" >/dev/null || return 1
  touch "$state/$1.ttl-continuation"
}
factory_ttl_retired() {
  [ -f "$state/$1.ttl-continuation" ] || return 0
  python3 "$here/ttl_continuation.py" retired --root "$root" --worker "$1" >/dev/null
}
# Keys from bin/setup-secrets, decrypted in memory with the founder identity on stdin; never sent
# to a factory VM (it would open sealed cases). Fails here, before any VM exists.
secrets_file=${UNBUG_SECRETS_FILE:-$HOME/.config/unbug-bench/secrets.age}
[ ! -t 0 ] || { echo "pipe the founder age identity on stdin (it decrypts $secrets_file in memory)" >&2; exit 1; }
identity=$(cat)  # in memory only: opens credentials and the small wrapped case key
secrets_b64=$(printf '%s\n' "$identity" | age -d -i /dev/stdin "$secrets_file" | base64) || true
[ -n "$secrets_b64" ] || { echo "could not decrypt $secrets_file (run bin/setup-secrets?)" >&2; exit 1; }
codex_login_gate() {
  printf '%s' "$secrets_b64" | base64 -d | python3 -B "$here/codex_login.py" --ttl-hours "${1:-$ttl_hours}"
}
# Before restores, guard ownership or any paid worker operation. Recheck each
# creation too: provisioning a large batch consumes part of the safe lifetime.
if [ "${UNBUG_RESUME_LAUNCH:-}" != 1 ]; then
  codex_login_gate
fi
# 2026-10-20: R2 keys stay on this host; VMs only get pre-signed links for single objects.
held_secrets_b64=$secrets_b64
held_secret_labels=$(printf '%s' "$held_secrets_b64" | base64 -d | tar -tf - | sed '/^\._/d' | tr '\n' ' ')
r2_env=$(printf '%s' "$secrets_b64" | base64 -d | tar -xOf - r2-env 2>/dev/null) || r2_env=""
r2_sign() { [ -n "$r2_env" ] && (set -a; eval "$r2_env"; exec "$root/bin/r2-presign" "$@"); }
restore_casekey() {
  if [ -f "$1" ] && [ ! -L "$1" ]; then printf '%s\n' "$1"
  elif [ -n "$2" ]; then echo 'wrapped case key required for batch restore; no VM created' >&2; return 1
  fi
}
restore_transfer_timeout() {
  python3 - "$1" "${BOAT_RESTORE_TIMEOUT_SECONDS:-1200}" <<'PYCODE'
import os, sys
# At least 20 minutes by default; budget a conservative 256 KiB/s for large archives.
size = os.stat(sys.argv[1]).st_size
print(max(int(sys.argv[2]), 2 + (size + 262143) // 262144))
PYCODE
}
restore_ciphertext() {
  fallback_reason='no R2 object on the selected card'
  if [ -n "$r2_object" ]; then
    fallback_reason='R2 signing unavailable'
    if url=$(r2_sign GET "$r2_object" "$((restore_timeout + 300))"); then
      echo "$id: restore ciphertext download from R2 (timeout ${restore_timeout}s)" >&2
      if BOAT_COMMAND_TIMEOUT_SECONDS=$restore_timeout boat ssh "$id" "set -e; umask 077; curl -fsS --retry 3 -o ~/restore.age '$url'; test \"\$(sha256sum < ~/restore.age | cut -c1-64)\" = $r2_sha" >/dev/null; then
        echo "$id: restore ciphertext downloaded and verified from R2" >&2
        return 0
      fi
      fallback_reason='R2 download or checksum verification failed'
    fi
  fi
  echo "$id: restore ciphertext local upload: $fallback_reason (timeout ${restore_timeout}s)" >&2
  BOAT_COMMAND_TIMEOUT_SECONDS=$restore_timeout boat --stdin ssh "$id" 'umask 077; cat > ~/restore.age' < "$ckpt" >/dev/null
}
# --restore CASE_ID resumes a case from sealed/CASE_ID.checkpoint.tar.gz.age, or from its final
# CASE_ID.tar.gz.age after a failed gate. Batch plaintext stays on workers;
# legacy unwrapped archives keep their prior streaming path until VM migration.
if [ -n "$restore" ] && [ "${UNBUG_RESUME_LAUNCH:-}" != 1 ]; then
  founder_recipient=$(sed -n 's/^FOUNDER_RECIPIENT = "\(age1[a-z0-9]*\)".*/\1/p' "$here/run.py")
  restore_recipient=$(printf '%s\n' "$identity" | age-keygen -y 2>/dev/null) || restore_recipient=""
  [ -n "$founder_recipient" ] && [ "$restore_recipient" = "$founder_recipient" ] || {
    echo "founder identity required to restore a checkpoint onto a new worker; run the restore from the Mac" >&2; exit 1;
  }
  [ "$n" -eq 1 ] || { echo "--restore resumes exactly one case (N=1)" >&2; exit 1; }
  case $restore in case-*) ;; *) echo "--restore takes a case id (case-...)" >&2; exit 1 ;; esac
  case $restore in *[!A-Za-z0-9-]*|case-) echo "invalid case id" >&2; exit 1 ;; esac
  ckpt=$root/sealed/$restore.checkpoint.tar.gz.age; card=$root/sealed/$restore.scorecard.json
  final=$root/sealed/$restore.tar.gz.age
  # The newer archive wins: a case that failed a gate after its last pause has an old checkpoint (2026-10-18).
  { [ -f "$ckpt" ] && ! [ "$final" -nt "$ckpt" ]; } || ckpt=$final
  if [ "$continue_review" = yes ]; then
    card=$root/sealed/g11-review-$restore.scorecard.json
    ckpt=$root/sealed/g11-review-$restore.tar.gz.age
    # Verify the encrypted audit before spending on a VM. Never open it on this host.
    python3 - "$card" "$ckpt" "$restore" <<'PYCODE'
import hashlib, json, pathlib, sys
card = json.loads(pathlib.Path(sys.argv[1]).read_text())
h = hashlib.sha256()
with open(sys.argv[2], 'rb') as file:
    for chunk in iter(lambda: file.read(1024 * 1024), b''): h.update(chunk)
if (card.get('case') != sys.argv[3] or card.get('kind') != 'g11-independent-review' or
        card.get('status') != 'stopped' or card.get('inputs_unchanged') is not True or h.hexdigest() != card.get('sha256')):
    sys.exit('no verified stopped review; no VM created')
PYCODE
    python3 - "$card" <<'PYCODE'
import json, sys
if json.load(open(sys.argv[1])).get('digest_version') != 2:
    sys.exit('old audit digest generations are retired; no VM created')
PYCODE
  fi
  [ -f "$ckpt" ] && [ -f "$card" ] || { echo "no sealed archive or $card for $restore" >&2; exit 1; }
  casekey=$root/sealed/$restore.casekey.age
  if [ "$continue_review" = yes ]; then casekey=$root/sealed/g11-review-$restore.casekey.age; fi
  casekey=$(restore_casekey "$casekey" "$batch_release")
  if [ -n "$casekey" ]; then
    cp "$casekey" "$UNBUG_LAUNCH_STATE/restore-casekey.age"
    casekey=$UNBUG_LAUNCH_STATE/restore-casekey.age
  fi
  # Freeze public metadata once; collection can publish a newer card while the
  # worker is preparing. The launch lock owns this per-launch snapshot.
  cp "$card" "$UNBUG_LAUNCH_STATE/restore-input-scorecard.json"
  card=$UNBUG_LAUNCH_STATE/restore-input-scorecard.json

  if [ "$audit_g11" = no ] && [ -z "$sealed_audit" ]; then
    PYTHONPATH="$here" python3 - "$card" "$args" <<'PYCODE'
import json, pathlib, shlex, sys
from restart import raised_limits
card = json.loads(pathlib.Path(sys.argv[1]).read_text())
args = shlex.split(sys.argv[2])
def option(name, default):
    value = default
    for i, item in enumerate(args):
        if item == name: value = args[i + 1]
        elif item.startswith(name + '='): value = item.split('=', 1)[1]
    return value
explicit = lambda name: any(v == name or v.startswith(name + '=') for v in args)
raised_limits(card, float(option('--case-budget', 50)), int(option('--rounds', 8)),
              explicit_budget=explicit('--case-budget'), explicit_rounds=explicit('--rounds'))
PYCODE
  fi
  if [ -n "${founder_ruling_sha:-}" ]; then
    [ "$audit_g11" = no ] && [ -z "$sealed_audit" ] || exit 1
    cp "$root/founder-ruling.json" "$UNBUG_LAUNCH_STATE/founder-ruling.json"
    python3 - "$UNBUG_LAUNCH_STATE/founder-ruling.json" "$founder_ruling_sha" <<'PYCODE'
import hashlib, pathlib, re, sys
if not re.fullmatch('[0-9a-f]{64}', sys.argv[2]) or hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest() != sys.argv[2]:
    sys.exit('founder ruling hash mismatch; no VM created')
PYCODE
  fi
  if [ -n "$sealed_audit" ]; then
    ckpt=$final
    PYTHONPATH="$here" python3 - "$card" "$ckpt" "$restore" <<'PYCODE'
import hashlib, json, pathlib, sys
from sealed_audit import verify_source
card = verify_source(json.loads(pathlib.Path(sys.argv[1]).read_text()), sys.argv[3])
with open(sys.argv[2], "rb") as stream:
    actual = hashlib.file_digest(stream, "sha256").hexdigest()
if actual != card["sha256"]:
    raise SystemExit("sealed source digest mismatch; no VM created")
PYCODE
  fi
  # A public card may postdate its embedded copy, but must still identify the
  # exact ciphertext selected for restore. Never spend on a mismatched pair.
  cp "$ckpt" "$UNBUG_LAUNCH_STATE/restore-input.tar.gz.age"
  ckpt=$UNBUG_LAUNCH_STATE/restore-input.tar.gz.age
  python3 - "$card" "$ckpt" "$restore" "${checkpoint_sha:-}" <<'PYCODE'
import hashlib, json, sys
with open(sys.argv[1]) as stream: card = json.load(stream)
with open(sys.argv[2], 'rb') as stream: actual = hashlib.file_digest(stream, 'sha256').hexdigest()
if card.get('case') != sys.argv[3] or card.get('sha256') != actual:
    sys.exit('restore card/archive generation mismatch; no VM created')
if sys.argv[4] and actual != sys.argv[4]:
    sys.exit('requested checkpoint generation changed; no VM created')
PYCODE
  purpose=$(python3 - "$card" "$restore" "$audit_g11" <<'PYCODE'
import json, sys
slot = json.load(open(sys.argv[1])).get("rotation_slot")
prefix = f"slot {slot} — " if type(slot) is int else ""
print(prefix + ("G11 review — " if sys.argv[3] == "yes" else "repair — ") + sys.argv[2].rsplit("-", 1)[-1])
PYCODE
  )
  # The trusted fingerprint is taken from the fresh VM before the restore: nothing has run on it yet, and the
  # bench-env image may have been rebuilt since the case started (a recorded one would then refuse the resume).
  bench_sha=
fi
[ -n "$restore" ] || unset identity
# Push every key in the bundle; these four are required (MiMo and GLM on the OpenCode Go key, Muse Contributor on OpenRouter since Go dropped it on 2026-10-17).
# 2026-10-23: a bundle written by macOS tar carries AppleDouble ._ entries; they are metadata, not keys.
secrets=${FACTORY_SECRETS:-$(printf '%s' "$secrets_b64" | base64 -d | tar -tf - | sed '/^\._/d' | tr '\n' ' ')}
opencode_secret=${OPENCODE_SECRET_NAME:-opencode-go-key}
case $opencode_secret in opencode-go-key|opencode-go-key-2) ;; *) echo "unapproved OpenCode account label" >&2; exit 1 ;; esac
# 2026-10-20: one factory Claude account per launch; only its token goes to the VM (never the exam's claude-token-2).
claude_secret=${CLAUDE_SECRET_NAME:-claude-token}
case $claude_secret in claude-token|claude-factory-token-2|claude-factory-token-3) ;; *) echo "unapproved Claude account label" >&2; exit 1 ;; esac
kept=""; for s in $secrets; do case $s in opencode-go-key|opencode-go-key-2) [ "$s" = "$opencode_secret" ] || continue ;; r2-env) continue ;; claude-token|claude-token-2|claude-factory-token-*) [ "$s" = "$claude_secret" ] || continue ;; esac; kept="$kept $s"; done; secrets=$kept
secrets_b64=$(printf '%s' "$secrets_b64" | base64 -d | python3 -c 'import io, sys, tarfile
keep, src, out = set(sys.argv[1:]), tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read())), io.BytesIO()
with tarfile.open(fileobj=out, mode="w") as t: [t.addfile(m, src.extractfile(m)) for m in src.getmembers() if m.name in keep]
sys.stdout.buffer.write(out.getvalue())' $secrets | base64) || { echo "could not select secrets" >&2; exit 1; }
for need in "$claude_secret" codex-auth.json "$opencode_secret" openrouter-key; do
  case " $secrets " in *" $need "*) ;; *) echo "$secrets_file lacks $need (run bin/setup-secrets)" >&2; exit 1 ;; esac
done
# On the VM: drop boat relay settings, load each pushed key (codex keeps its own file).
vm_creds="unset ANTHROPIC_BASE_URL OPENCODE_API_KEY_BASE_URL OPENAI_BASE_URL OPENAI_API_KEY; export OPENCODE_DISABLE_AUTOUPDATE=1 OPENCODE_SECRET_NAME=$opencode_secret CLAUDE_SECRET_NAME=$claude_secret"
if [ -n "${FACTORY_ACCOUNT_POLICY:-}" ]; then
  initial_accounts=$(python3 "$here/account_handoff.py" exports --state "$UNBUG_LAUNCH_STATE/initial.accounts.json")
  vm_creds="$vm_creds; $initial_accounts"
fi
for s in $secrets; do
  case $s in
    statements-key) ;; # runner reads the private key file directly, never through the environment
    claude-token|claude-factory-token-2|claude-factory-token-3) vm_creds="$vm_creds; export CLAUDE_CODE_OAUTH_TOKEN=\$(cat /dev/shm/secrets/$s)" ;;
    openrouter-key) vm_creds="$vm_creds; export OPENROUTER_API_KEY=\$(cat /dev/shm/secrets/openrouter-key)" ;;
    opencode-go-key|opencode-go-key-2)
      if [ "$s" = "$opencode_secret" ]; then vm_creds="$vm_creds; export OPENCODE_API_KEY=\$(cat /dev/shm/secrets/$opencode_secret)"; fi ;;
    codex-auth.json) vm_creds="$vm_creds; cp /dev/shm/secrets/codex-auth.json ~/.codex/auth.json; : > ~/.codex/config.toml" ;;
    *) echo "unknown secret $s" >&2; exit 1 ;;
  esac
done
# One bench run per 2 cores, decided on the VM (cx53 16c -> 8, cpx42 8c -> 4, cpx32 4c -> 2), unless given.
case " $args " in *" '--bench-workers'"*|*" --bench-workers"*|*" '--probe'"*|*" --probe"*) workers_arg="" ;;
  *) workers_arg='--bench-workers $(( $(nproc) / 2 < 1 ? 1 : $(nproc) / 2 ))' ;; esac
if [ -n "$reuse_worker" ] && [ "${UNBUG_RESUME_LAUNCH:-}" != 1 ]; then
  # Reuse an interrupted upload only: keep the provider's existing absolute expiry.
  ttl_hours=$(boat list --json | python3 -c '
import datetime, json, math, sys
worker, case, requested, vm_type = sys.argv[1:]
matches = [v for v in json.load(sys.stdin)["sandboxes"] if v.get("id") == worker]
if len(matches) != 1: sys.exit("reuse worker missing or ambiguous")
v = matches[0]
if (v.get("state", v.get("status")) not in ("idle", "running") or
        v.get("type") != vm_type or not v.get("name", "").endswith(case.rsplit("-", 1)[-1])):
    sys.exit("reuse worker metadata does not match this review")
left = datetime.datetime.fromisoformat(v["archiveAfter"].replace("Z", "+00:00")).timestamp() - datetime.datetime.now(datetime.timezone.utc).timestamp()
hours = min(float(requested), left / 3600)
if not math.isfinite(hours) or hours < 1: sys.exit("reuse worker has less than one hour left")
print(hours)
' "$reuse_worker" "$restore" "$ttl_hours" "${BOAT_TYPE:-default}")
fi
guard_init
if [ "${UNBUG_RESUME_LAUNCH:-}" != 1 ]; then
admission_snapshot=""
selection_snapshot=""
if [ -z "$restore" ] && [ "$audit_g11" = no ] && [ -z "$sealed_audit" ]; then
  case " $args " in *--dry-run*) ;; *)
    # Advisory history arrives before the first writer call. It grants no admission.
    case " $secrets " in *" statements-key "*) ;; *) echo "selection requires statements-key; no VM created" >&2; exit 1 ;; esac
    selection_snapshot=$(PYTHONPATH="$here" python3 - "$admission_root" "$state/selection-board" <<'PYCODE'
import pathlib, sys
from registry import Registry
destination = pathlib.Path(sys.argv[2])
Registry(pathlib.Path(sys.argv[1]) / 'sealed/statement-registry').export_board(destination)
print(destination)
PYCODE
    )
  ;; esac
fi
if [ -n "$restore" ] && [ "$audit_g11" = no ] && [ -z "$sealed_audit" ]; then
  # Collected candidate handoffs need their coordinator reservation before any VM
  # is created. Only public cards/hashes and encrypted statements are read here.
  admission_snapshot=$(PYTHONPATH="$here" python3 - "$root" "$restore" "$ckpt" "$state/admission" <<'PYCODE'
import sys
from statement_round import prepare_restore
snapshot = prepare_restore(*sys.argv[1:])
print(snapshot or '')
PYCODE
  )
  if [ -n "$admission_snapshot" ]; then
    case " $secrets " in *" statements-key "*) ;; *) echo "candidate restore requires statements-key; no VM created" >&2; exit 1 ;; esac
  fi
fi
if [ -n "$reuse_worker" ]; then
  # Check before taking lifecycle ownership: never collect/delete another live run.
  # The lock also prevents a second recovery from overwriting this one's restore.
  reuse_check=$(cat <<'PYCODE'
import json, pathlib, subprocess, sys
card = json.load(sys.stdin); home = pathlib.Path.home(); case = card['case']
if (home / 'sealed/DONE').exists(): sys.exit('reuse worker already finished')
if subprocess.run(['pgrep', '-f', '^python3 [^ ]*/factory/(run|runner_supervisor)[.]py( |$)'], stdout=subprocess.DEVNULL).returncode != 1:
    sys.exit('reuse worker runner is active or uncertain')
if subprocess.run(['pgrep', '-f', '(^|/)(opencode|claude|codex)( |$)'], stdout=subprocess.DEVNULL).returncode != 1:
    sys.exit('reuse worker model process is active or uncertain')
if subprocess.run(['pgrep', '-f', '(^|/)tar -x.*f -|^python3( -B)? [^ ]*/case_permissions[.]py( |$)'], stdout=subprocess.DEVNULL).returncode != 1:
    sys.exit('reuse worker restore extractor is active or uncertain')
if any(p.name != case for p in (home / 'work').glob('case-*')):
    sys.exit('reuse worker contains another case')
ledger = home / 'sealed' / (case + '.continuation-budget.json')
audit = home / 'work' / case / 'g11-audit'
if ledger.exists() or ledger.is_symlink() or audit.exists() or audit.is_symlink():
    sys.exit('reuse worker already has review work or usage; refusing to overwrite it')
if card['continuation_budget'].get('active'): sys.exit('saved audit ledger is active')
sys.path.insert(0, str(home / 'factory'))
import run
if run.bench_manifest() != card.get('review_bench_sha256'):
    sys.exit('reuse worker bench fingerprint changed')
(home / 'sealed/.factory-review-restore.lock').mkdir()
PYCODE
  )
  # Public metadata only; the founder key stays in the existing stdin decrypt pipe.
  cat "$card" | boat --stdin ssh "$reuse_worker" "OPENCODE_DISABLE_AUTOUPDATE=1 python3 -c $(quote "$reuse_check")" >/dev/null
  id=$reuse_worker
  printf '%s\n' "$id" > "$state/ids"
  date +%s > "$state/$id.started"
fi
bundle="$state/factory.tgz"
# Freeze a public release manifest alongside the exact runner bundle. Source edits
# during capture fail qualification instead of silently mixing worker versions.
if [ -n "$batch_release" ]; then
  python3 -B "$here/batch.py" prepare --root "$root" --release "$batch_release" --sha256 "$batch_sha" --output "$bundle"
elif [ -n "$qualified_release" ]; then
  qualified_adapter prepare --release "$qualified_release" --output "$bundle"
else
  python3 "$here/worker_release.py" --root "$root" --stamp "$state/worker-release-manifest.json"
  PYTHONPATH="$here" python3 -B - "$root" "$state/worker-release-manifest.json" "$bundle" <<'PYCODE'
from pathlib import Path
import sys
from launch_manifest import worker_upload
worker_upload(*(Path(p) for p in sys.argv[1:]))
PYCODE
fi
PYTHONPATH="$here" python3 -B - "$root" "$bundle" <<'PYCODE'
from pathlib import Path
import sys
from launch_manifest import verify_worker_runtime
verify_worker_runtime(*(Path(p) for p in sys.argv[1:]))
PYCODE
fi
probe_python=$(cat <<'PYCODE'
import glob, os, time
home = os.path.expanduser("~")
import json
status = home + "/sealed/runner-status.json"
if os.path.isfile(home + "/sealed/DONE"):
    print("DONE")
elif os.path.isfile(status) and (lambda s: s.get('reason') == 'startup_failed' or s.get('phase') in ('finished', 'stopped'))(json.load(open(status))):
    print("STARTUP_FAILED")
else:
    paths = [home + "/.boat-launch-start"] + glob.glob(home + "/sealed/*.continuation-budget.json")
    # Gates and strategy runs write bench evidence under ~/unbug-bench/results, not ~/work.
    for top in ("/work", "/unbug-bench/results"):
        for directory, dirs, files in os.walk(home + top):
            paths.extend([directory] + [os.path.join(directory, f) for f in files])
    latest = 0
    for path in paths:
        try: latest = max(latest, os.stat(path).st_mtime)
        except FileNotFoundError: pass
    print(max(0, int(time.time() - latest)))
PYCODE
)
opencode_pin=$(cat <<'SHCODE'
set -eu
export OPENCODE_DISABLE_AUTOUPDATE=1
cli=/usr/local/bin/opencode
if [ ! -x "$cli" ] || [ "$("$cli" --version)" != 1.19.0 ]; then
  sudo env OPENCODE_DISABLE_AUTOUPDATE=1 npm install -g --force --prefix /usr/local --no-audit --no-fund opencode-ai@1.19.0
fi
[ "$("$cli" --version)" = 1.19.0 ]
codex_cli=/usr/local/bin/codex
if [ ! -x "$codex_cli" ] || [ "$("$codex_cli" --version)" != 'codex-cli 0.162.1' ]; then
  sudo npm install -g --force --prefix /usr/local --no-audit --no-fund @openai/codex@0.162.1
fi
[ "$("$codex_cli" --version)" = 'codex-cli 0.162.1' ]
SHCODE
)
factory_auto_resume() {
  # Batch continuation is an explicit launch of its collected checkpoint until
  # the standing coordinator stop rules are approved and implemented.
  [ -z "${batch_release:-}" ] || return 1
  [ -z "$sealed_audit" ] || return 1
  [ "${UNBUG_CLOUD:-hetzner}" = boat ] || return 1
  resume_id=$1
  [ ! -f "$state/$resume_id.keep" ] || return 1
  now=$(date +%s)
  remaining=$((retire_at - now + $(cat "$state/$resume_id.started")))
  [ "$remaining" -gt 60 ] || return 1
  # Monitoring/collection remains possible with an old login; new model work does not.
  codex_login_gate "$(python3 -c 'import sys; print(int(sys.argv[1]) / 3600)' "$remaining")" || return 1
  # A detached resume may still be checking its checkpoint while old DONE exists.
  # Its lock owns that transition; polling must not collect/resume it again.
  restart_lock=$(boat ssh "$resume_id" 'if test -d ~/sealed/.factory-restart.lock; then echo locked; else echo unlocked; fi') || { touch "$state/$resume_id.keep"; return 1; }
  case $restart_lock in
    locked)
      [ "${UNBUG_RESUME_LAUNCH:-}" = 1 ] && [ ! -f "$state/$resume_id.restart-attempted" ] || return 0 ;;
    unlocked) ;;
    *) touch "$state/$resume_id.keep"; return 1 ;;
  esac
  if [ -f "$state/$resume_id.retry-at" ] && [ "$now" -lt "$(cat "$state/$resume_id.retry-at")" ]; then return 0; fi
  # The collector validates the ciphertext before any resume. A failed collection keeps
  # the normal guard's collect-before-delete path; it never authorizes another model call.
  if [ ! -f "$state/$resume_id.collected" ]; then
    collect_vm "$resume_id" || return 1
    touch "$state/$resume_id.collected" || return 1
  fi
  resume_case=$(boat ssh "$resume_id" 'cat ~/sealed/DONE') || return 1
  case $resume_case in case-*[!A-Za-z0-9-]*|'') return 1 ;; case-*) ;; *) return 1 ;; esac
  attempts=0
  [ ! -f "$state/$resume_id.autoresumes" ] || attempts=$(cat "$state/$resume_id.autoresumes")
  plan_status=0
  admission_guard=""; admission_proof=""; admission_trap=""
  checkpoint_generation=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$root/sealed/$resume_case.scorecard.json") || return 1
  if [ -f "$state/$resume_id.restart-attempted" ]; then
    if [ "$checkpoint_generation" != "$(cat "$state/$resume_id.restart-attempted")" ]; then
      rm -f "$state/$resume_id.restart-attempted" "$state/$resume_id.restart-acknowledged"
    elif [ -f "$state/$resume_id.restart-acknowledged" ]; then
      rm -f "$state/$resume_id.collected"; return 0
    else touch "$state/$resume_id.keep"; return 1; fi
  fi
  admission_stop=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("terminal_stop", ""))' "$root/sealed/$resume_case.scorecard.json") || return 1
  if [ "$admission_stop" = admission_registry_unavailable ]; then
    handoffs=0
    [ ! -f "$state/$resume_id.admission-handoffs" ] || handoffs=$(cat "$state/$resume_id.admission-handoffs")
    generation=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "$root/sealed/$resume_case.scorecard.json") || return 1
    case $generation in *[!0-9a-f]*|'') touch "$state/$resume_id.keep"; return 1 ;; esac
    # Reserve before transport. An uncertain swap/start must never be retried.
    admission_proof=$state/$resume_id.admission-$generation.json
    if [ -f "$state/$resume_id.admission-$generation.reserved" ] && [ -z "${UNBUG_LAUNCH_STATE:-}" ]; then
      touch "$state/$resume_id.keep"; return 1
    fi
    if [ ! -f "$admission_proof" ]; then
      # Journaled attempts reclaim their token; an unjournaled attempt stays uncertain.
      if [ -f "$state/$resume_id.admission-$generation.attempted" ] && [ ! -f "$admission_proof.pending" ]; then
        touch "$state/$resume_id.keep"; return 1
      fi
      touch "$state/$resume_id.admission-$generation.reserved" || return 1
      if ! python3 "$here/statement_round.py" --same-worker-handoff --root "$root" --history-root "$admission_root" \
          --worker "$resume_id" --case "$resume_case" --remaining "$remaining" --args="$args" \
          --handoffs "$handoffs" --proof "$admission_proof"; then
        touch "$state/$resume_id.keep"
        echo "$resume_id: KEEPING VM: admission handoff refused or uncertain; checkpoint retained" >&2
        return 1
      fi
    fi
    handoffs=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["handoffs"])' "$admission_proof") || return 1
    echo $((handoffs + 1)) > "$state/$resume_id.admission-handoffs" || { touch "$state/$resume_id.keep"; return 1; }
    admission_guard=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["resume_guard"])' "$admission_proof") || { touch "$state/$resume_id.keep"; return 1; }
    admission_trap=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["resume_trap"])' "$admission_proof") || { touch "$state/$resume_id.keep"; return 1; }
    # Snapshot transfer consumes the original TTL; never extend its deadline.
    now=$(date +%s)
    remaining=$((retire_at - now + $(cat "$state/$resume_id.started")))
    restart_plan=$(python3 "$here/restart.py" "$root/sealed/$resume_case.scorecard.json" "$attempts" "$remaining" "$args" "$admission_proof") || plan_status=$?
    if [ "$plan_status" -ne 0 ]; then touch "$state/$resume_id.keep"; fi
  elif [ -n "${FACTORY_ACCOUNT_POLICY:-}" ] && [ "${admission_stop#provider_limit:}" != "$admission_stop" ]; then
    restart_plan=$(printf '%s' "$held_secret_labels" | python3 "$here/account_handoff.py" plan \
      --card "$root/sealed/$resume_case.scorecard.json" --state "$state/$resume_id.accounts.json" \
      --retries "$attempts" --remaining "$remaining" --args="$args") || plan_status=$?
  else
    restart_plan=$(python3 "$here/restart.py" "$root/sealed/$resume_case.scorecard.json" "$attempts" "$remaining" "$args") || plan_status=$?
  fi
  if [ "$plan_status" -eq 2 ]; then
    touch "$state/$resume_id.keep"
    echo "$resume_id: KEEPING VM: checkpoint verification is uncertain; original TTL remains the backstop" >&2
  fi
  [ "$plan_status" -eq 0 ] || return 1
  # Retry deadlines stay in this launch's state; no new VM, TTL extension,
  # raised ceiling, or replacement usage ledger is involved.
  set -- $restart_plan
  resume_case=$1; delay=$2; original_seed=$3
  if [ -z "$admission_proof" ] && [ ! -f "$state/$resume_id.retry-at" ]; then
    echo $((now + delay)) > "$state/$resume_id.retry-at" || return 1
    echo "$resume_id: transient stop; retry $((attempts + 1))/3 in $delay seconds" >&2
  fi
  if [ -z "$admission_proof" ]; then
    [ "$now" -ge "$(cat "$state/$resume_id.retry-at")" ] || return 0
    echo $((attempts + 1)) > "$state/$resume_id.autoresumes" || return 1  # reserve before an uncertain remote call
  fi
  printf '%s\n' "$checkpoint_generation" > "$state/$resume_id.restart-attempted" || return 1
  rm -f "$state/$resume_id.retry-at" || return 1
  resume_creds=$vm_creds
  if [ -n "${FACTORY_ACCOUNT_POLICY:-}" ] && [ "${admission_stop#provider_limit:}" != "$admission_stop" ]; then
    if ! printf '%s' "$held_secrets_b64" | base64 -d | python3 "$here/account_handoff.py" apply \
        --card "$root/sealed/$resume_case.scorecard.json" --state "$state/$resume_id.accounts.json" --worker "$resume_id"; then
      touch "$state/$resume_id.keep"; return 1
    fi
  fi
  if [ -n "${FACTORY_ACCOUNT_POLICY:-}" ]; then
    account_creds=$(python3 "$here/account_handoff.py" exports --state "$state/$resume_id.accounts.json") || { touch "$state/$resume_id.keep"; return 1; }
    resume_creds="$vm_creds; $account_creds"
  fi
  sha=$(cat "$state/$resume_id.bench-sha") || return 1
  # The next call may mutate work even when its transport reports failure. Its old
  # archive can no longer authorize deleting this VM.
  rm -f "$state/$resume_id.collected" || return 1
  if ! boat exec "$resume_id" --detach -- sh -c "set -eu
if [ -z \"$admission_proof\" ]; then
mkdir ~/sealed/.factory-restart.lock
trap 'rmdir ~/sealed/.factory-restart.lock' 0
fi
if pgrep -f '^python3 .*factory/(run|runner_supervisor)[.]py' >/dev/null; then echo 'runner already running' >&2; exit 1; fi
$admission_guard
test -d ~/work/$resume_case/case
test -f ~/sealed/$resume_case.continuation-budget.json
export OPENCODE_DISABLE_AUTOUPDATE=1
test \"\$(/usr/local/bin/opencode --version)\" = 1.19.0
$resume_creds
rm -f ~/sealed/DONE
touch ~/.boat-launch-start
$admission_trap
FACTORY_DEFER_WIPE=1 FACTORY_OPENCODE_BIN=/usr/local/bin/opencode FACTORY_RUNNER_SECONDS=$remaining FACTORY_RUNNER_GRACE_SECONDS=$((margin / 2 < 720 ? margin / 2 : 720)) python3 ~/factory/runner_supervisor.py -- python3 ~/factory/run.py $args $workers_arg --resume $resume_case --resume-bench-sha $sha --seed $original_seed > ~/sealed/scorecard.stdout 2>/dev/null < /dev/null" >/dev/null; then
    touch "$state/$resume_id.keep"
    echo "$resume_id: KEEPING VM: detached restart outcome is uncertain; reconcile before deletion" >&2
    collect_vm "$resume_id" || true
    return 1
  fi
  touch "$state/$resume_id.restart-acknowledged"
  echo "$resume_id: resumed $resume_case in place (transient retries $attempts/3; separate admission handoffs; original ceilings and TTL)" >&2
  return 0
}
batch_status=0
if [ "${UNBUG_RESUME_LAUNCH:-}" = 1 ]; then
  guard_ids > "$state/all-ids"
  cp "$state/all-ids" "$state/ids"
  guard_wait || batch_status=1
  exit "$batch_status"
fi
while [ "$serial" -lt "$n" ]; do
  if ! codex_login_gate; then batch_status=1; break; fi
  if [ -n "$qualified_release" ]; then
    readiness_mono=$(python3 -c 'import time; print(time.monotonic())')
    readiness_wall=$(python3 -c 'import time; print(time.time())')
  fi
  if [ -n "$reuse_worker" ]; then serial=$((serial + 1)); else
    if ! guard_new; then
      batch_status=1
      if [ -n "$id" ]; then
        date +%s > "$state/$id.started"
        guard_retire "$id" || true
        touch "$state/$id.retired"
      fi
      continue
    fi
  fi
  # Standalone subshell: conditional subshells disable errexit in POSIX shells.
  set +e
  (
  trap - 0 INT TERM
  set -e
  if [ -n "$qualified_release" ]; then qualified_readiness; fi
  # Reuse the restore stream instead of a separate SCP transport.
  # Verify the complete public bundle before unpacking or sending credentials.
  bundle_sha=$(python3 -c 'import hashlib,sys; print(hashlib.file_digest(open(sys.argv[1], "rb"), "sha256").hexdigest())' "$bundle")
  boat --stdin ssh "$id" "set -eu; umask 077; cat > ~/factory.tgz; printf '%s  %s\\n' '$bundle_sha' \"\$HOME/factory.tgz\" | sha256sum -c -" < "$bundle" >/dev/null || { echo "$id: public source upload/checksum failed before credentials" >&2; exit 1; }
  boat ssh "$id" "tar -xzf ~/factory.tgz -C ~ && rm ~/factory.tgz" >/dev/null
  if [ -n "$qualified_release" ]; then
    boat ssh "$id" 'python3 -B ~/qualified-release/deploy.py install --release ~/qualified-release' > "$state/$id.source-install.json" || { echo "$id: full source installation failed before credentials" >&2; exit 1; }
  fi
  # Fork hydration can replace the baked CLI. Re-pin before keys or case data arrive;
  # v2 omits the usage event the budget guard needs. Keep updates off for the worker too.
  ( BOAT_COMMAND_TIMEOUT_SECONDS=${BOAT_PIN_TIMEOUT_SECONDS:-300} boat ssh "$id" "$opencode_pin" ) ||
    { sleep 1; BOAT_COMMAND_TIMEOUT_SECONDS=${BOAT_PIN_TIMEOUT_SECONDS:-300} boat ssh "$id" "$opencode_pin"; } || { echo "$id: could not pin agent CLIs (OpenCode 1.19.0, Codex 0.162.1)" >&2; exit 1; }
  if [ -n "$qualified_release" ]; then
    boat ssh "$id" 'python3 -B ~/qualified-release/deploy.py verify --release ~/qualified-release' > "$state/$id.source-preimport.json" || { echo "$id: full source verification failed before credentials" >&2; exit 1; }
  fi
  # Fresh images may lack Medusa. Build before read-only qualification or keys.
  ( BOAT_COMMAND_TIMEOUT_SECONDS=${BOAT_IMAGE_TIMEOUT_SECONDS:-1800} boat ssh "$id" 'cd ~/unbug-bench; docker image inspect unbug-bench-medusa:latest >/dev/null 2>&1 || { docker compose -f projects/medusa/compose.yaml pull postgres redis && docker compose -f projects/medusa/compose.yaml build medusa; }' ) || { echo "$id: Medusa image preparation failed before credentials" >&2; exit 1; }
  # Qualification is read-only: no model calls or credentials. Driver defaults
  # match the existing pin block; selected Claude is checked by run.py before use.
  boat ssh "$id" 'OPENCODE_DISABLE_AUTOUPDATE=1 python3 -B ~/factory/worker_release.py --manifest ~/worker-release-manifest.json --root ~/unbug-bench --factory-root ~/factory --drivers opencode,codex' > "$state/$id.worker-release.json" ||
    { sleep 1; boat ssh "$id" 'OPENCODE_DISABLE_AUTOUPDATE=1 python3 -B ~/factory/worker_release.py --manifest ~/worker-release-manifest.json --root ~/unbug-bench --factory-root ~/factory --drivers opencode,codex' > "$state/$id.worker-release.json"; } || { echo "$id: worker release qualification failed" >&2; exit 1; }
  if [ -n "$qualified_release" ]; then
    boat ssh "$id" 'python3 -B ~/qualified-release/deploy.py verify --release ~/qualified-release' > "$state/$id.source-verify.json" || { echo "$id: full source verification failed before credentials" >&2; exit 1; }
  fi
  # Snapshot the clean VM before keys or case data arrive, once for every launch.
  # Automatic resumes reuse this trusted fingerprint rather than trusting mutable work.
  bench_sha=$(boat ssh "$id" "cd ~/factory && OPENCODE_DISABLE_AUTOUPDATE=1 python3 -B -c 'import run; print(run.bench_manifest())'")
  case $bench_sha in *[!0-9a-f]*|'') echo "$id: no bench fingerprint" >&2; exit 1 ;; esac
  [ "${#bench_sha}" -eq 64 ] || { echo "$id: invalid bench fingerprint" >&2; exit 1; }
  if [ -n "$reuse_worker" ]; then
    saved_sha=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["review_bench_sha256"])' "$card")
    [ "$bench_sha" = "$saved_sha" ] || { echo "$id: reused bench fingerprint changed" >&2; exit 1; }
  fi
  printf '%s\n' "$bench_sha" > "$state/$id.bench-sha"
  statements_snapshot=${admission_snapshot:-$selection_snapshot}
  if [ -n "$statements_snapshot" ]; then
    PYTHONPATH="$here" python3 - "$root/bin/boat-call" "$id" "$statements_snapshot" <<'PYCODE'
import sys
from statement_round import install
install(*sys.argv[1:], provider='boat')
PYCODE
  else
    boat ssh "$id" "mkdir -p ~/statements" >/dev/null
    for statement in "$root"/sealed/*.statement.age; do
      [ -f "$statement" ] || continue
      boat scp "$statement" "$id:/home/user/statements/$(basename "$statement")" >/dev/null
    done
  fi
  # Real keys, not boat's paid relay (off since 2026-10-16): files only, read on the VM.
  printf '%s' "$secrets_b64" | "$root/bin/push-secrets" "$id" $secrets
  if [ -n "$restore" ]; then
    args="$args --resume $(quote "$restore") --resume-bench-sha $(quote "$bench_sha")"
    restore_to='~/work'; restored_case='case'
    if [ "$continue_review" = yes ]; then restore_to="~/work/$restore"; restored_case='g11-audit/case'; fi
    # R2 sends ciphertext directly to the worker. Local transport has the same
    # size-scaled bound; never use boat-call's 120-second default for an archive.
    r2_sha=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "$card")
    restore_timeout=$(restore_transfer_timeout "$ckpt")
    if [ -n "$casekey" ]; then
      r2_object=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("r2_object") or "")' "$card")
      restore_ciphertext
      printf '%s\n' "$identity" | age -d -i /dev/stdin "$casekey" |
        BOAT_COMMAND_TIMEOUT_SECONDS=$restore_timeout boat --stdin ssh "$id" "set -e; umask 077; trap 'rm -f ~/restore.age /dev/shm/casekey' EXIT; cat > /dev/shm/casekey; chmod 600 /dev/shm/casekey
          test \"\$(sha256sum < ~/restore.age | cut -c1-64)\" = $r2_sha
          age -d -i /dev/shm/casekey ~/restore.age | python3 -B ~/factory/case_permissions.py --extract-to $restore_to --case-tree ~/work/$restore/$restored_case" >/dev/null
    else
      # Compatibility only: stream B migrates these legacy case keys on the VM.
      echo "$id: restore via legacy plaintext stream: no wrapped case key (timeout ${restore_timeout}s)" >&2
      printf '%s\n' "$identity" | age -d -i /dev/stdin "$ckpt" |
        BOAT_COMMAND_TIMEOUT_SECONDS=$restore_timeout boat --stdin ssh "$id" "python3 -B ~/factory/case_permissions.py --extract-to $restore_to --case-tree ~/work/$restore/$restored_case" >/dev/null
    fi
    if [ "$audit_g11" = no ] && [ -z "$sealed_audit" ]; then
      # Import only after the worker compares accounting with retained metadata.
      # Full public-card labels can postdate the archived scorecard. They do not
      # prove a ledger delta or grant any new attempt/gate allowance.
      ruling_args=""
      if [ -n "$founder_ruling_sha" ]; then
        cat "$state/founder-ruling.json" | boat --stdin ssh "$id" "cat > ~/founder-ruling.json" >/dev/null
        ruling_args="--founder-ruling /home/user/founder-ruling.json --founder-ruling-sha256 '$founder_ruling_sha'"
      fi
      release_args=""; [ -z "$batch_sha" ] || release_args="--release-sha256 '$batch_sha'"
      cat "$card" | boat --stdin ssh "$id" "python3 -B ~/factory/restore_ledger.py --case '$restore' --generation '$r2_sha' $ruling_args $release_args" > "$state/$id.restore-accounting.json" || {
        echo "$id: restored accounting refused; no runner started" >&2; exit 1;
      }
    else
      # Independent audit copies retain their separate accounting contract.
      python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["continuation_budget"]))' "$card" |
        boat --stdin ssh "$id" "mkdir -p ~/sealed && cat > ~/sealed/$restore.continuation-budget.json" >/dev/null
    fi
    if [ -n "$sealed_audit" ]; then
      cat "$card" | boat --stdin ssh "$id" "cat > ~/sealed/$restore.source-scorecard.json" >/dev/null
    fi
    boat ssh "$id" "test -d ~/work/$restore/$restored_case" || { echo "$id: checkpoint restore failed" >&2; exit 1; }
    echo "restored $restore on $id" >&2
    unset identity
  fi
  # Pre-signed upload links for this VM's sealed archives (7 days, the SigV4 maximum); run.py uploads after sealing.
  if put_ckpt=$(r2_sign PUT "vm/$id/checkpoint.tar.gz.age" 604800) && put_final=$(r2_sign PUT "vm/$id/final.tar.gz.age" 604800); then
    python3 -c 'import json,sys; print(json.dumps({"prefix": "vm/" + sys.argv[1], "checkpoint": sys.argv[2], "final": sys.argv[3]}))' "$id" "$put_ckpt" "$put_final" |
      boat --stdin ssh "$id" "umask 077; cat > ~/.factory-r2" >/dev/null || echo "$id: R2 links not stored; archives stay host-collected only" >&2
  fi
  remaining=$((retire_at - $(date +%s) + $(cat "$state/$id.started")))
  [ "$remaining" -gt 0 ] || exit 1
  review_lock_exit=""
  if [ -n "$reuse_worker" ]; then review_lock_exit="set -eu; trap 'rmdir ~/sealed/.factory-review-restore.lock' 0;"; fi
  boat exec "$id" --detach -- sh -c "$review_lock_exit mkdir -p ~/sealed ~/.codex && touch ~/.boat-launch-start && $vm_creds && FACTORY_DEFER_WIPE=1 FACTORY_OPENCODE_BIN=/usr/local/bin/opencode FACTORY_CODEX_BIN=/usr/local/bin/codex FACTORY_RUNNER_SECONDS=$remaining FACTORY_RUNNER_GRACE_SECONDS=$((margin / 2 < 720 ? margin / 2 : 720)) python3 ~/factory/runner_supervisor.py -- python3 ~/factory/run.py $args $workers_arg > ~/sealed/scorecard.stdout 2>/dev/null < /dev/null" >/dev/null
  echo "started $id" >&2
  )
  setup_status=$?
  set -e
  [ -z "$restore" ] || unset identity
  printf '%s\n' "$setup_status" > "$state/$id.setup-status"
  if [ "$setup_status" -ne 0 ]; then
    batch_status=1
    echo "$id: setup failed; retiring this worker while peers continue" >&2
    guard_retire "$id" || true
    touch "$state/$id.retired"
  fi
  guard_wait once || batch_status=1
done
guard_wait || batch_status=1
exit "$batch_status"
exit
}
