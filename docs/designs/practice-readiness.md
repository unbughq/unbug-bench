# Offline practice readiness

Base 070a332 includes the shared paid cap and reviewed admission clamps.
Readiness is for the $25 plumbing run in practice-run.md, not $100 item 8.
No workers/cloud/provider calls/secrets/pushes in this increment. At most two
fresh design-review rounds; a blocker after round 2 returns to the parent.

## Classification of the old preflight
| Old blocker | OFFLINE work now | LIVE evidence only |
|---|---|---|
| B cleanup/cost/legacy/controller | Practice-only independent watchdog using existing ID and deletion receipt functions; one-worker policy; never release unknown infrastructure | Provider cost/multiplicity contract, b275 debt reconciliation, deployed timer survives holder restart, actual deletion/charges |
| B2 input/S/role binding | Fresh empty input, S=0, explicit new role bindings and namespace checks; remove demand for nonexistent legacy checkpoint | Empty namespace on actual VM/common storage and actual authenticated publication/ACK |
| A maxima/paid cap/probe | Use already bounded roles and merged shared cap; delete separate cent-probe requirement, reserve its cent unused; no unbounded Codex route | Linux profile feasibility, account2 usage and deployed credit reader |
| E cancellation/escaped pipes/timing | Existing reviewed process/gate cancellation code; add cleanup/fault command tests | Actual VM gate wall, cancellation/late output and deletion timing |
| D/B outcome/clamp/carry | Existing clamp code; queued-child creation is OFFLINE item8 work outside this plumbing increment | Wider item8 outcome/carry qualification is outside this one-worker practice; retain explicit separate acceptance hold |
| Account identity/fallback | Pin initial2/[2,1], existing genuine-rate-only router rule | Privately authenticate distinct provider account identities and usage; natural fallback only if observed |
| Final policy/pins | Replace frozen-message preflight with current offline checks; one pin command after reviewed merge, independent of lane2 | Installed exact hashes, R2 access and service configuration |

## Implementation contract (revision 2)

The objective is to run one disposable worker without depending on the Mac,
prove which Claude account did its work, and retain verified publication/deletion
records within $25. Success is passing offline tests/review with only the listed
live entry checks and live observations left for this plumbing run.

### Exact new manifest
Add factory/batches/b-plumbing-practice.json with the literal object below.
The old factory/batches/b-practice-20261031.json remains frozen historical input;
no generated policy references it. Slot1 is required by batch.bind syntax but
EVERY role is explicitly overridden, including easy calibrator and reviewer1.
No new rotation table or model-family rule is introduced.

```json
{
  "schema": 1,
  "id": "b-plumbing-practice",
  "batch_deadline": "2026-11-07T00:00:00Z",
  "money_limit_usd": "19.990000000",
  "max_concurrency": 1,
  "target_slots": 1,
  "restore_recipient": "age1ae6f86fkvfnlv525ne9n4rj49texw9r9sh5h5udj23da0ptnnuksuxm6ch",
  "replacement_policy": {
    "schema": 1,
    "enabled": false
  },
  "practice_admission": {
    "schema": 1,
    "jobs": {
      "practice": {
        "baseline_usd": "0.000000000",
        "incremental_usd": "19.990000000"
      }
    }
  },
  "jobs": {
    "practice": {
      "mode": "batch",
      "case": "case-b-plumbing-practice-practice",
      "requested_total_usd": "19.990000000",
      "claude_accounts": [
        2,
        1
      ],
      "initial_accounts": {
        "claude": 2
      },
      "opencode_accounts": [],
      "args": [
        "1",
        "--source",
        "port",
        "--rotation-slot",
        "1",
        "--builder",
        "openrouter/minimax/minimax-m3.1-flash",
        "--attacker",
        "openrouter/deepseek/deepseek-v4.1-flash",
        "--reviewer1",
        "openrouter/xiaomi/mimo-v2.6-pro",
        "--strong-calibrator",
        "claude/claude-opus-4-5-20251101:compact",
        "--easy-calibrator",
        "openrouter/minimax/minimax-m3.1-flash",
        "--ttl-hours",
        "1",
        "--max-spend",
        "5"
      ]
    }
  }
}
```

### Activation, without changing ordinary gates
Add factory/practice.py: matches(record) checks equality to the literal contract
above (including recipient); active(policy,root) returns False unless the
UNBUG_PRACTICE_BATCH environment value is b-plumbing-practice, then loads
batch_money.manifest(policy,root) and requires matches(record). Authentication
means existing release SHA + manifest SHA + id binding, NOT a digital signature.
A malformed practice request refuses; unrelated ids return False without changing
legacy behavior. No recursion: manifest/check_manifest never calls active.

batch_holder.active(policy,root) = HOLDER_ENABLED or practice.active(policy,root).
Change enabled() to enabled(policy,root) at every holder entry; main loads policy first. In batch.bind use
active only at its three existing flag checks (carry/derived refusal, checkpoint
source selection, imported expected release), keeping the branches otherwise
identical. In key_holder use active at batch_tick, batch_request and serve's
canonical-policy-path check. Legacy fallback remains exactly as before for other
ids; for this practice id when inactive, batch_request must raise request_refused
rather than fall through to legacy launch. Also refuse the practice id in legacy
batch_money.authorize, already excluded by practice_admission.

Install only at live step2 a drop-in for unbug-key-holder.service:
[Service] Environment=UNBUG_PRACTICE_BATCH=b-plumbing-practice
The holder inherits it to dispatch/publish/resume children; add this one variable
to control_resume.ENVIRONMENT and dispatch's explicit launcher environment so
bind/source checks in controller children see the same gate. No worker needs it.
Both constants remain False, no environment/service is changed by offline tools.
Tests cover unset, matching and wrong ids plus existing legacy/HOLDER_ENABLED
behavior. Never claim enabled schema2 publication while legacy launch is used.

### Independent cleanup and shared deletion proof
Extract the existing heredoc implementations, preserving semantics, into
factory/boat_lifecycle.py: ids(state, mode='print') and
 delete_receipt(root, spend_file, worker, ids_path, timeout=60).
Shell guard_ids and guard_delete_receipt become thin Python CLI calls. Retain
normal guard_retire's collect-before-delete behavior. The deletion function takes
LOCK_EX on state/<worker>.deletion.lock (O_NOFOLLOW, regular file) for the whole
read/check/request/poll/write transaction. Both shell controller and watchdog
use it; an existing completed receipt is validated and returned without POST.
Existing attempted-without-request refuses with retained uncertainty; not-found
is NOT completion. No new delete POST on uncertain or repeated attempts.

Add factory/practice_cleanup.py --operation UUID. It requires UNBUG_CLOUD=boat,
canonical control-home policy, release authentication and practice.matches; it
uses the existing operation journal to bind launch_id. Parent-approved after round 2:
normal collection starts at worker start + 1800 seconds; deletion is worker start
+ 1800 run-cap + 900 collection-grace seconds, strictly before start + 3600 TTL.
Admission refuses incompatible timing; dispatch requires at least one TTL left
before the batch deadline. No reservation timestamp substitutes for worker start.
Missing worker start retains uncertainty; never invent a timestamp. Before touching provider output it compares launch.json with
op.launch. Read spend_file from the one shlex-decoded assignment in regular
monitor.sh (never source/eval); require a path under root/results/spend. Missing
monitor before creation is expected. Resolve IDs through the shared helper.

The watcher publishes atomic batches/<batch>/cleanup/<operation>.ready.json with
exact keys schema:1, operation_id, launch_id, timing (run_seconds, grace_seconds,
ttl_seconds), policy_sha256 (key_holder.policy_digest of the entire policy), pid. This avoids precreating the launch directory
owned exclusively by control_resume. Status lives beside readiness.
It then polls every 5 seconds. No delete before deadline; at deadline call the
shared deletion function for every positively bound ID, independently of collection.
Unknown creation or deletion stays an incident in <operation>.status.json (schema1,
operation_id, deadline (epoch seconds or null before known start),
state:waiting|deleting|complete|uncertain|not_dispatched, workers:[IDs]);
never emit complete unless dispatch occurred, no new.N.pending remains, all IDs
have validated completed receipts, and complete inventory confirms absence.
After timeout or not-found retain holds and keep polling/reconciling; never fake
retirement or stop the watcher due to a controller complete marker alone.
Service restart recomputes the SAME deadline from the durable worker .started file, not now.

Install this template at live step2 as /etc/systemd/system/unbug-practice-cleanup@.service:
```ini
[Unit]
Description=Cleanup for one disposable practice operation
After=network-online.target
[Service]
Type=simple
User=user
Group=user
WorkingDirectory=/home/user/unbug-bench
Environment=HOME=/home/user UNBUG_CLOUD=boat UNBUG_PRACTICE_BATCH=b-plumbing-practice
Environment=PATH=/usr/local/bin:/usr/bin:/bin
UMask=0077
LimitCORE=0
ExecStart=/usr/bin/python3 -B /home/user/unbug-bench/factory/practice_cleanup.py --operation %i
Restart=on-failure
RestartSec=5
```
Parent/operator installs via existing service deployment; no sudo policy is added.
After launch returns pending OP, operator runs
`sudo systemctl start unbug-practice-cleanup@OP.service`.
Before boat-call list and again inside the second money lock before
dispatch_started=True, practice
requires unit-file SHA equal to the pinned template and bounded `systemctl show`
ActiveState=active, SubState=running, ExecMainPID equal ready.pid; ready's op,
launch, timing and policy hash must match; at least one TTL must remain. Missing
arming returns TEMPFAIL so the existing holder retries, never creates. No dependency
on holder PID and no automatic stop when holder stops. Reject non-Boat mode.
Pin new helper files in launch_manifest HOST_FILES and control_resume closure.
Provider early expiry/not-found retains uncertainty; live evidence must resolve it.

### One publication fault
Add tools/practice-fault.py --policy PATH --operation UUID: authenticate the active
practice policy, validate the op, and under batch lock atomically create
launch/publication-fault.json with schema1, operation_id, state:armed. Refuse if
marker already exists or op.output_generation is set. In batch_holder.collect,
after writing outbox pending and before leaving that lock for transport, change
armed to consumed atomically and raise ValueError('publication_failed'). This
is a transient exception, NOT an immediate terminal op incident. No transport,
ACK, current pointer or money update occurred. Normal unpublished/publish_replay
retries the same generation. record_child counts only failed publish child exits;
a first one is failures=1 with incident=None; success resets failures=0. Existing
RETRY_LIMIT=5 is unchanged. Tests assert this exact path and that rearming refuses.

### Pin and preflight outputs
Retire docs/practice/b3/preflight.py as historical: add a header/README pointer,
keep its old behavior and frozen pins for audit. tools/practice-preflight.py is
the current command. It accepts optional --bundle PATH and emits exact keys:
{schema:1, source_commit:SHA, launch_ready:false,
 offline:[{id,status:pass|fail,reason:FIXED_LABEL}],
 live:[{id,status:unproved,ceiling_usd:NINE_DECIMAL_STRING}]}.
Offline IDs: manifest,roles,activation,cleanup,fault,pins. No free-form provider
errors. Exit1 if any offline fail; else3 (live unproved). Without bundle pins
is fail/unpinned; the pin tool supplies the bundle for its final check.

`tools/pin-practice.py --output /ABS/NEW` requires clean HEAD=factory-simplify,
the reviewed readiness files, a future manifest deadline, and all other offline
checks passing. It uses existing batch.build/verify, never checks out/merges.
Output contains release/ (six existing build files), policy.json (normal policy
schema with root=/home/user/unbug-bench and immutable VM release directory),
preflight.json, and pins.json with exact keys schema:1, source_commit, source_tree,
batch_id, deadline, launch_ready:false, manifest_sha256, trusted_code_sha256,
batch_release_sha256, files:{relative_path:SHA256}, routes:{role:{route,max_usd,
max_input_tokens,max_output_tokens,price_source}}, cleanup_unit_sha256,
activation_dropin_sha256. files covers six release files, policy, generated
unit/drop-in bytes and the two host tools (practice-fault.py and qualify-batch-inputs.py); route fields come from route_maximum. Re-run preflight using
the bundle, verify all hashes and non-null maxima. Output path must not exist;
failed partial output is retained marked incomplete, never reused as valid pins.
Cut against available reviewed/merged head, independent of lane2; item8 pins later.

## Deletions and separate scope
Remove duplicated embedded ID/deletion implementations by extraction, remove the
cent-probe and legacy-checkpoint requirements from this practice's current plan.
Do NOT add queued-child staging: diagnosis/replacement are disabled here. That
code gap remains OFFLINE item8 work, explicitly outside this plumbing acceptance;
no claim that this run fixes or qualifies it. The old manifest/b3 pins stay inert.

## Verification and scope
Offline tests use retained cards/ciphertexts and existing collection fixtures;
authored systemd/provider transports are labeled. Test exact roles via real select_models with route_maximum non-null and no
Codex; wrong/expired manifests, authenticated
activation scope, watchdog before creation, late created event, unknown creation,
controller death, normal collection < watchdog deletion < provider TTL, deletion lock/replay and wrong deletion target. Test pin/preflight
without invoking providers, including stale/dirty/mismatched heads and deadline.
Required full suite unique source-bound log plus fresh diff review covers this
design AND practice-run.md. No Murphy closures until live artifacts exist.
Cost now $0 case/cloud; timeline one offline implementation and review cycle.

Rows touched: 6 (publication), 17 (infrastructure holds), 27 (generation integrity),
28 (dispatch), 35 (checkpoint loss), 51 (restart), new-batch-auth-inputs-1 (empty
namespace). None closes offline. new-batch-service-4 remains item8, unchanged.
No new live failure was observed, so no new incident row is invented.
The likely first result is a $0 abort: exceptional provider cost/multiplicity
bounds and old-launch debt are not established. Perform those entry checks before
any deployment mutation or worker. Offline infrastructure code only pays off if
they pass; a successful worker cannot prove a universal provider guarantee.

Implementation detail: readiness is outside the launch directory to preserve
control_resume exclusive creation. A failed operation with dispatch_started=false
terminates its watcher as not_dispatched; it is never called deletion completion.
The generated holder drop-in also sets UNBUG_CLOUD=boat. Tests are in
tests/factory/test_practice_readiness.py; role resolution and temporal ordering
are real pure-code exams; systemd/cloud responses and pin containers are authored
contract fixtures. Existing isolation/launch tests cover shared deletion behavior.

Packaging correction from the full suite: keep control/ and tools/ out of the
worker archive so qualified-release retains its existing owned-root boundary.
The pin bundle carries the cleanup unit and two host tools separately. Live
deployment installs the unit both in /etc/systemd/system and the pinned source
location under root/control, and the tools under root/tools. All are hashed.
Staged test layouts include the extracted lifecycle helper. Frozen October VM
evidence is validated against its historical environment labels; no evidence is
rewritten to claim that the new activation label was observed then.
