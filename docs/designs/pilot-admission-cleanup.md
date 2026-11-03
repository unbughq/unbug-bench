# Admit and clean up the three-case pilot

## Objective and boundary

Run three new cases one at a time and remove each rented worker on time, even if
the program launching cases stops.

Allow the control VM to admit three fresh cases in sequence, and keep independent
cleanup armed for every worker even if the holder stops. Never launch a fourth
case or exceed six possible worker creations. This is offline plumbing, not
approval to run or spend. Baseline: land13 `7dbdc58`, branch t3/pilot-admission.
The pilot plan is `abc11ef:docs/designs/pilot-run.md`.

Today only practice.EXPECTED plus UNBUG_PRACTICE_BATCH activates the holder.
Cleanup's paths and lock name use that practice batch, and its systemd instance
must be armed manually for each operation. Reusing those bindings for three new
jobs would either refuse or mix ownership. General activation remains off.

B owns Boat settlement (2c174ba/0292abc on t3/batch-service-control-vm) and the
practice startup repair (design revision bef877d). Read those changes; do not
merge them into this branch or edit boat_lifecycle, boat-spend, guards, money,
accounting, settlement or ledger schemas. Specifically leave cleanup.step and B's
bound_spend/settle additions untouched. Diagnosis scheduling/activation, route
headroom, final manifest/pin bundle, startup repair and live qualification stay
with their owners. This increment alone does not make the pilot launch-ready.
No Murphy row closes; supports rows 17/49/51 without claiming live evidence.

## Authenticated opt-in and manifest

Add factory/pilot.py, a small admission policy module. A pilot batch ID must begin
`b-real-pilot`, matching the bounded-role and legacy-authorizer checks, and cannot be a practice ID. Its manifest must have a `pilot_admission`
object with exactly: schema=1, starts_at (UTC), max_lifecycles=6,
max_lifecycles_per_case=2, infrastructure_limit_usd (positive nine-place USD).
The ordinary manifest owns money_limit_usd and each job's requested_total_usd;
none of their numeric values is hard-coded. Their sum must not exceed the model
money_limit_usd. Infrastructure is a separate manifest ceiling, not list-price
model money. No proposal ($20/$60/$65/$5) becomes authorization here.

Require exactly three ordinary jobs, max_concurrency=1, target_slots=3, explicit
replacement_policy={schema:1,enabled:false}, no practice_admission or carry_from,
and distinct canonical case IDs. Use existing money.check_manifest and
money.manifest verification; do not add another loader. Require each args list to
start with '1', and exactly one separate '--ttl-hours','1' and '--max-spend',VALUE
whose Decimal value equals infrastructure_limit_usd. Reject equals-form or
duplicate occurrences of these two flags, dry-run and alternative worker/reuse/
continuation modes. Ordinary batch.bind keeps owning the rest of argument safety.
All six lifecycle attempts therefore pass the same infrastructure ceiling to
B's cumulative Boat admission. Earlier practice costs/holds remain in the same
home-wide ledger and cannot be reset by a pilot manifest. With B merged, the
effective infrastructure ceiling is the minimum of all historical reservation
caps and the new manifest cap, less all settled home-wide charges including
practice; unknown liabilities block admission. A larger new cap never replenishes
that headroom. Fixed lifecycle values remain explicit approval data in the
manifest, while the monetary values remain entirely parameterized.

Activation requires UNBUG_PILOT_PIN equal to the exact string
`<batch-id>:<manifest-sha256>:<release-sha256>` from the current policy, plus full
manifest/release authentication and the shape checks above. No switch is written
by this increment. Missing/wrong pin returns inactive; malformed matching pinned
input refuses. pilot.active does not expire by clock: cleanup must remain alive
after admission closes. pilot.managed(policy) recognizes the reserved ID prefix
even without a pin so inactive pilot requests cannot fall through to legacy APIs.

batch_holder.active checks pilot activation in addition to unchanged practice
activation and the existing test/global flag. A managed pilot always needs its
pin even when HOLDER_ENABLED is set; that flag must not bypass pilot validation.
key_holder.batch_request and batch.bind explicitly refuse inactive managed pilot
policies, as practice's request path already does. Active requests still enter
the existing reserve/dispatch/bind route. Add the public pin to control_resume's
environment allowlist and copy the authenticated pin into dispatch's environment.
Host trust inventory includes pilot.py and the new cleanup unit. No second
launch API, no worker-side activation or diagnosis constant toggle.
Because policy_load calls bind for every job, a missing/wrong pilot pin prevents
both key-holder and cleanup startup. This is intentional fail-closed behavior,
not merely an inactive background scan. Current practice pins become stale when
trusted code changes and must be regenerated with B's planned re-pin.

## Durable bounds using existing operations

The starts_at/batch_deadline interval must be positive and at most six hours.
Admission is allowed only at or after starts_at and with strictly more than one
hour remaining before batch_deadline. Check again before dispatch through armed;
a queued reservation cannot launch after the window closes.
Reuse practice.admission(record) for the existing remaining-TTL check and
practice.deadlines(0) for timing validation, adding only the pilot starts_at and
six-hour interval constraints. Translate the timing refusal to pilot_window_closed.

Under the existing batch money lock, pilot admission examines the validated
operations dictionary. For a new operation identity, refuse if six operations
already exist or two already belong to that job. Existing identity replay is
idempotent and consumes no extra slot. Count reservations, including failed or
uncertain ones, conservatively; never reclaim a possible creation based on a
missing worker ID. At most one worker is requested by each operation. No new
counter file, operation fields or ledger mutation. Refuse malformed histories
that already exceed either bound even on replay/dispatch. The ordinary source
ACK, retirement, accounting, concurrency and empty-input checks remain intact.
Three independent initial jobs and one successor per job exhaust six slots.
Provider-wait resumes count too; there is no exception for another reason.
Exact order inside _admit: validate the pilot manifest/window and validate that
existing history is within bounds; compute the existing operation identity;
apply the new-operation cap checks only if that identity is absent; then execute
the unchanged existing-identity return and ordinary admission checks. Replay
after the window closes refuses new launch authority while lookup still reports
the retained operation. Dispatch's armed checks also validate history bounds.

Errors use fixed labels: `pilot_lifecycle_limit` for a new operation beyond the
bound and `pilot_window_closed` for admission outside the window (MoneyWait, no
creation); invalid policy/history is request_refused. They cannot manufacture
a retirement or free a money hold. No further operation may be admitted to
work around a spent slot. Existing state is retained for the pilot outcome report.
For a reserved, never-dispatched operation after its window closes, the batch
cleanup status is state=window_closed (schema/operation_id/deadline/workers retain
the ordinary shape). This is an outcome-report label, not a deletion receipt,
money release or journal state mutation. The cleanup loop can remember it as
terminal because the frozen window cannot reopen; dispatch still refuses it.

## Cleanup owner and B interface

Keep factory/practice_cleanup.py and its single step implementation. Generalize
location(home,op) to `home/batches/op.authority.batch/cleanup/operation_id`; normal
callers have already validated op through the holder. For practice this is the
same path. Preserve ready's PID, policy digest, operation and launch identity.
The policy digest already binds batch/release/manifest. Preserve all start-time,
monitor, deletion-receipt and full-inventory validation in step.

Keep the old practice unit/--operation path unchanged. Add one
control/unbug-pilot-cleanup.service copying the practice unit exactly except its
Description, ExecStart (same module with bare --batch) and removal of the practice
activation environment value. Preserve HOME, UNBUG_CLOUD=boat, PATH, User/Group,
WorkingDirectory, UMask, LimitCORE, Restart and RestartSec. Add
EnvironmentFile=/home/user/.unbug-control/pilot.env and an [Install] section with
WantedBy=multi-user.target, so deployment can enable cleanup across reboot.
pilot.env contains the exact UNBUG_PILOT_PIN for the approved deployment. The
deployment owner supplies a key-holder systemd drop-in with the same
EnvironmentFile path, and enables/starts cleanup before the holder. No secrets
belong in this file. There is no per-worker unit-start command or added sudo
permission. Final manifest/pin/drop-in installation remains a deployment dependency.

--batch is a bare store_true flag, mutually exclusive with --operation, and
requires pilot.active.
Each five-second iteration reads the full validated operations under the existing
batch lock, then releases it before any cloud/subprocess work. It writes each
operation's ready marker with its own PID before observing ANY step, then writes
each status to that operation's path. Order observations: dispatched operations
without retirement first, then other nonterminal dispatched operations, then
never-dispatched operations, then retained terminal operations to revalidate.
Use the retained status only to order work, never as fresh deletion proof.
Remember complete/not_dispatched/window_closed operations in memory to avoid
repeated provider polling; after restart revalidate each once. This prevents
old terminal operations' inventory/settlement queries from delaying a live
worker's deletion after restart.
Stay alive when empty or when all current operations finish, so a later admitted
successor is armed automatically. Never stop cleanup merely because the admission
deadline passed. Freeze policy, release and pin from the first dispatch until
every dispatched operation is terminal. A changed policy makes _operations
refuse the old journal on restart, so breaking that freeze leaves only Boat TTL;
redeployment is permitted only after cleanup completes. Cleanup continues for
every known admitted operation; malformed
operation state refuses and is not treated as absent or complete.

armed chooses the pilot batch unit or the unchanged practice instance. For pilot
it validates activation, admission window, installed unit digest and systemd
ActiveState/SubState/ExecMainPID, then requires the exact per-operation ready
record. Both existing dispatch armed checks remain. A not-yet-observed operation
returns cleanup-not-armed and retries normally without starting a worker. The
second check immediately precedes durable dispatch_started. Per-worker timing
stays start+1800 collection < start+2700 deletion < start+3600 TTL. batch_deadline
bounds admission, not guaranteed VM deletion: preparation plus provider creation
latency (boat new can take 300 seconds) precede the durable worker-start record.
VM lifetime may extend to dispatch + preparation/creation latency + 3600 seconds.
Strict live absolute deletion-window qualification therefore remains a deployment
dependency; this increment does not claim it from a pre-dispatch clock check.

At BOTH armed call sites, the pilot also reads the validated operations and
requires every OTHER dispatch_started operation to have a regular cleanup status
at location(home,other).with_suffix('.status.json'), schema=1, matching
operation_id, and state complete or not_dispatched. Missing/malformed status,
settlement_pending, waiting, deleting or uncertain raises MoneyWait('cleanup not
settled'). The first read is a preflight observation; the authoritative second
check runs under the caller's batch money lock immediately before dispatch_started.
armed does not acquire that lock recursively. No cloud call or ledger inspection
is introduced by this check. A successor remains pending and dispatch returns
TEMPFAIL until the predecessor is settled; no durable dispatch or shell guard is
entered early. Reservation slots remain conservatively counted as before.

B's existing step/settle interface is preserved: it uses location(home,op), and
state remains settlement_pending until --settle succeeds. Our batch loop treats
only complete/not_dispatched as terminal for dispatched operations, so all
settlement retries continue. The pre-dispatch cleanup-status check is the
interface: with B merged, complete means settled. The existing shell guard still
owns final admission against the same Boat ledger. Integration/activation must
wait for B's settlement merge and live usage qualification, and ALL prior rows
in the home's boat-reservations.json must be settled before the first pilot job.
The batch-local check cannot establish that home-wide prerequisite. On this
baseline complete means the existing deletion proof only; do not claim cumulative
settlement without B. This branch must not be independently deployed as a pilot.

## Deletion, tests, risks and delivery

Delete the cleanup location/main-lock dependency on practice.BATCH. Reuse the
holder journal and cleanup step rather than adding another batch supervisor or
ledger. Production edits: pilot.py, small admission/dispatch hooks in
batch_holder.py, inactive-policy guards in key_holder.py/batch.py, cleanup owner
selection/main loop, control_resume environment allowlist, launch_manifest and
the pilot unit. Do not edit practice.py/EXPECTED, practice unit, run.py, scheduling
or B's settlement files/functions.

New tests/factory/test_pilot_admission.py reuses retained card/ciphertext/created
event fixtures and real holder reserve/collection/reconcile paths from
test_batch_holder. Three-worker identities, policy pins, times and systemd/cloud
responses are explicit authored controls, not real pilot acceptance. Tests:

1. Default off, wrong/missing pins, altered release/manifest, old/practice IDs,
   fourth job/replacements/carry, invalid monetary values/flags and mismatched
   caps refuse before worker creation. Different valid monetary values work;
   no $20/$65 assumption. Check key-holder and direct batch.bind legacy bypasses.
   policy_load must refuse startup with a missing/wrong pin. Validate the new unit
   preserves required practice fields and has reboot enablement.
2. Three distinct jobs plus one ACKed/retired successor each through real holder
   APIs. Replays preserve identity; restart reloads the same journal. A third
   lifecycle for any case and seventh global attempt refuse. Concurrent reserves
   under the real lock cannot bypass bounds; uncertainty/failed reservations
   remain counted. Never mock the cap predicate or journal persistence.
3. Start/deadline boundaries and a reservation delayed past the last dispatch
   window refuse. Cleanup observation still runs after that deadline.
   Never-dispatched expired reservations report window_closed without changing
   their journal or claiming retirement/settlement.
4. Batch cleanup discovers all three operation paths, preserves separate ready
   and status records, and discovers successor operations in a later iteration.
   Same PID is allowed only with exact policy/launch/operation binding. Wrong PID,
   stale policy/launch, dead service and changed installed unit refuse dispatch.
   Restart re-observes terminal proof and pending settlement is never terminal.
   Write all ready markers before any observation and observe a live worker
   before terminal revalidation after restart. Successor dispatch with a previous
   settlement_pending/uncertain/missing/wrong-identity status returns TEMPFAIL,
   remains pending with dispatch_started=False and never calls the shell launcher;
   replacing it with a valid complete status allows the same operation to proceed.
5. Existing real retained deletion/creation fixtures: each worker start controls
   its own deadline; wrong/missing receipt, partial inventory and pending creation
   never become complete. Reuse step without cloud calls or settlement fabrication.
6. Remove the cap check and the ready-marker check in temporary source copies;
   their integration tests must fail. Preserve practice tests and existing launch
   manifest/recovery tests.

One offline increment, estimated one day including serialized suite/review waits,
zero live spend. Main risks: missing lifecycle paths, accidental legacy fallback,
cleanup disarmed by expiration, and collision with B's pending edits; tests and
the explicit no-step-edit boundary target those. No broad live-readiness claim.
Fresh Claude design review max two rounds; after a failing round 2 hand back in
three lines. Implement, focused tests, then exactly
`uv run --with numpy --with scipy python -B tests/run.py`
(shared TEST_SLOTS pool per current ENGINEERING.md; no lockf), retain timing failures and unchanged focused reruns, and
fresh diff review max two rounds. Hand back on pass. No merge/push/live actions.


## Authorized continuation after round 2 (2026-11-03)

The founder/root task authorizes fixing R2-B1 and implementation on the integrated
settlement baseline f9a97ea. No third design review and no repeated accepted review.
The former prohibition on B integration edits is superseded only for the cleanup
clearance and a behavior-preserving extraction of Boat's existing ledger reader.
No settlement schema, pricing, spend authority or worker proof changes.

For a failed/preflight_refused dispatched operation with worker_id=None, the pilot
may clear cleanup only when the existing home ledger is regular, parses with
Boat's existing validator, and has NO row bound to that launch state. Missing
ledger is unknown. Check the ledger under its existing shared lock; missing lock
also refuses. Any matching row (even settled) uses the existing settlement path.
Read this proof again at both armed checks; status alone cannot grant this exception.
Require the operation lock and controller lock free, launch.json equal to the
retained operation, no new.* entry (including dangling links), and empty/missing
ids. This covers pre-guard delivery/refusal without spend-finished; reconciliation
already proved the owner gone. The fenced-before-controller case is allowed only
for the empty directory _reconcile_one creates under the operation lock; a directory
with any entries and no launch binding refuses. These are proof of no creation,
never inventory absence or deletion proof. No cloud call, journal rewrite, money
release or ownership waiver. Nonblocking locks return pending and retry.

The batch observer reports this narrowly proven case as not_dispatched with
basis=preflight_no_reservation. Other failed empty launches with a bound row keep
settlement retry, and unknown evidence remains blocked. _operations history is
passed to armed at both existing checks, including the authoritative locked check.

The six-creation/two-per-case/six-hour bounds in this increment are tighter than
the later nine-creation proposal in pilot-run.md. This code supports only the
reviewed six-creation policy; activation remains OFF, with no manifest/pin/deploy.
No-replacement is a proposed section-4 exception, not approved by this code.
Root/founder must explicitly decide that exception and final pilot bounds before
activation. The Stream D resume consumer a245768 and land19 c318fa1 (187/0 suite
at /Users/bugsincode/Developer/land19-suite-20261103T194005Z.log) are root-owned
dependencies, not implementations to duplicate here. Live deleted-ID lifetime usage,
credit/top-up/containment/absolute timing proof and manifest/headroom remain open.
