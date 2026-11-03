# Capture final Boat usage before permanent deletion

## Problem and real feedback loop

On 2026-11-04 root prepared b-plumbing-practice-3 from reviewed merged e62a5c4.
All six offline and six phase-A live preflight checks passed. No deployment,
worker allocation, model call or extra allowance occurred.

Before spending, root queried the known deleted worker bx_z4wktrbn through the
pinned control-VM CLI: `bin/boat-call usage bx_z4wktrbn --json` returned exit 1,
HTTP404/sandbox-not-found twice. The same query in the only accessible organization
also returned not-found. `usage --help` confirms the command exists. The failure
is not an unsupported command or an account-balance observation.

Public evidence remains in results/infrastructure/2026-11-04-plumbing-practice3/:
preflight-final-live.json, prior-operations.json, prior-liabilities-usage.json,
deleted-usage-diagnostic.json and usage-org-scope-check.json. No raw credentials
or private case content were read into these observations.

Official sources (read 2026-11-04):
- https://docs.boat.dev/billing : per-sandbox usage is available while running
  or stopped; deleted resources contribute to aggregate deletedCost. Stopped
  time is not counted. Omit since/until for lifetime usage.
- https://docs.boat.dev/data-retention/delete : deletion is permanent and there
  is no deleted-sandbox list; deleting ends billing and erases sandbox data.
- https://docs.boat.dev/api/reference/sandboxes/get-sandbox-usage : same per-ID
  endpoint used by the pinned CLI. No alternative historical per-ID endpoint
  was identified.

Our accepted settlement design made an unsupported assumption: asking for a
per-ID receipt after deletion. Current code correctly holds on404 but therefore
cannot qualify this ordinary lifecycle. This is a plumbing bug, not case feedback.

## Change and what it removes

Reuse the existing launcher, per-worker deletion directory, boat-call, deletion
intent and cumulative ledger. Remove the assumption that new workers need a
per-ID lookup after permanent deletion. Normal order is verified collection,
fence worker mutations, complete stop, save final lifetime meter, delete with the
existing receipt protocol, then settle. This rollout enables the new protocol only
when the existing bounded practice/pilot supplies its authenticated absolute
deletion deadline. Other callers retain their existing deletion/held-accounting
behavior; no fleet readiness or general deadline fix is claimed. No second launcher, provider, ledger,
budget authority or per-case rescue.

### 1. Exact pinned stop interface (Major 1)

Read-only probes of an ALREADY stopped account-accessible sandbox established the actual
boat1.0.85 surface without starting/stopping/resuming it. Public evidence:
`stop-cli-help.json`, `all-state-stop-status-probe.json`,
`stopped-meter-real-receipts.json`, `stopped-meter-schema-receipt.json` in the
same evidence directory. bx_sk2p68qq remained stopped and was never mutated.
The compact retained fixture is docs/reports/boat-stopped-contract-20261104.json.
Its stop ID is stop_cf0b665fb2ed2957; lifetime seconds672, dollars0.00672,
running=false, since2026-10-14. These are real contract fixtures, not authored
responses; the pending/failing/superseded/forced variants below are authored.

Commands, always through pinned bin/boat-call:
- Start: `stop WORKER --json` (NEVER --force). It is a sandbox-action response
  naming WORKER; it need not itself provide a complete stop operation. Validate
  any returned id/sandbox.id against WORKER. Do not apply deletion-operation
  parsing or treat CLI exit0 as completed. The id/stop discriminator is obtained
  from the subsequent exact info lookup, not guessed from a deletion envelope.
- Observe: `info WORKER --json`. Actual envelope is {sandbox:{id,state,stop,...}};
  persist only public {sandbox:{id,state,stop}}. Require id==WORKER. CLI state
  is exactly 'stopped'; do not confuse it with REST's 'archived'. stop.id must be
  a nonempty string and stop.status one of pending/failing/completed/superseded.
- Poll exact operation: `stop WORKER --status STOP_ID --json`. Actual envelope
  is {id:WORKER,stop:{id,status,requestedAt,lastAttemptAt,error,endedAt,forced?}}.
  Require outer id and inner id match the requested identities. Required fields
  and status enum follow the retained schema. Present timestamps are timezone
  aware. requestedAt/lastAttemptAt can be null where documented, but completed
  requires endedAt present, error=null and status=='completed'. The historical
  by-ID requestedAt is retained even when info's completed stop has it null.
- Meter: `usage WORKER --json`, with NO since/until. The actual response contains
  sandboxId, sandboxType, billingMultiplier, secondsPerDollar, seconds, dollars,
  running, since, until. Require sandboxId==WORKER, running is exactly false,
  seconds is nonnegative int (not bool), dollars finite/nonnegative numeric,
  and timezone-aware since/until. Require since<=until and until>=the completed stop endedAt; captured_at
  cannot precede endedAt. Retain the exact public bytes, not a rounded
  float. Existing Decimal parsing/number validation handles money.

Completion predicate is the conjunction of same-worker info.state=='stopped',
current info.stop.id==STOP_ID, exact by-ID status=='completed' with endedAt and
no error, and stopped lifetime usage. Re-read info after usage, before committing
its proof, requiring the same completed current stop. A failing/refused stop with
running=false is NOT complete; superseded stops invalidate capture. Poll pending
or failing at2second intervals only while the common metering budget remains.

No automatic force escalation. If a provider reports forced=true for an otherwise
completed stop, retain that fact: final billing can still be accounted, but it
never proves case collection or success. The normal path requires verified
collection before retirement; deadline deletion may destroy uncollected work and
must report that failure. --no-snapshots stays unchanged; stop/meter is not a new
backup mechanism. A stop response lost before its ID is saved is recovered by
read-only info. If no usable operation is found, a repeated non-force stop is
allowed only for that exact owned worker within the original metering window
(the provider documents pending stop idempotence). Never use a synthetic stop ID.

### 2. Enforceable retirement fence (Major 2)

Use the EXISTING state/WORKER.deletion.lock inode for both paths:
- Every managed Boat command capable of changing or entering the worker obtains
  a shared lock for the whole CLI invocation and rejects a durable retiring marker.
  Integrate at bin/boat-call, inside its existing timeout scope. With validated
  UNBUG_LAUNCH_STATE, match owned IDs (including ID:scp paths) for ssh, exec, scp,
  prompt, resume, restart/reboot/resize/type-change, extend, fork, snapshot, new
  from that ID, stop and delete. read-only info/usage/list/deletion-status/stop-status
  do not mutate. Unknown commands targeting an owned ID refuse after fencing.
  Standalone provider administration outside this owned execution is not authorized
  during retirement; this is the same trusted-owner boundary as existing deletion.
- The lifecycle writes/fsyncs state/WORKER.retiring.json before waiting for its
  exclusive lock. New shared-lock entrants check the marker AFTER acquiring their
  lock and before running any version/worker command. It obtains SH with NB retries only
  inside its existing boat-call timeout (so timeout includes lock wait). Already admitted calls finish
  or are cancelled under their existing command deadlines. Capture starts only
  when all prior shared holders have drained and exclusive ownership is obtained.
- While exclusive, the lifecycle passes its actual lock FD with pass_fds to its
  own boat-call stop/status/usage/delete children. A numeric environment FD is
  not authority by itself: the wrapper fstats it against this worker's regular,
  no-symlink deletion.lock inode and verifies that the inherited FD holds EX/NB.
  This avoids reacquiring SH against its parent's EX. No boolean bypass flag.
  The provider executable need not inherit the FD: the parent retains EX.

On restart, control_resume's scan and locked launch entry detect retiring markers
and refuse application/controller resumption; batch_holder's resume discovery
also excludes them. Existing account handoff/push-secrets/worker restart calls
inherit UNBUG_LAUNCH_STATE and pass through boat-call, so the lowest command
boundary prevents a race even if a higher-level scan was stale. Hetzner parked
handoff remains unchanged. A resumed controller never erases the .collected marker
once retirement has begun; guard_retire reconciles deletion rather than collecting
again through SSH. Marker/lock identity mismatch or malformed marker fails closed.

A crash releases EX but leaves the fence. A new retirement owner can acquire the
same EX and reuse its original retirement generation. Before any not-yet-requested
deletion, revalidate current stopped info against the saved stop ID within the
original remaining metering allowance. A resume/type change invalidates a receipt;
no fresh stop generation or new capture window is silently granted after a crash.
Own managed mutations are blocked; external manual mutation is outside this run's
authority and invalidates qualification if observed. Case/model agents have no
provider credentials (--no-env); they cannot bypass the control-side fence.

### 3. Explicit timing and emergency precedence (Major 3)

Do not change the accepted 1800s run / 900s collection grace / 3600s provider TTL.
Let S be the existing durable worker started timestamp, D=S+2700 the watchdog's
nominal delete-request deadline, M=D-180 the latest metering cutoff. Collection
still gets its original grace; no preemptive stop of an uncollected worker.

Normal verified collection may start a retirement at any time. The cold marker
records /proc/sys/kernel/random/boot_id and a process-independent monotonic
meter deadline at that same boot; a process restart does not renew it. Its metering
budget is at most120s, ending no later than M. Persist these deadlines in the
retiring marker; restart cannot reset them. Same-control-VM-boot monotonic values
plus boot ID enforce this across process restart. If the boot changed or the
clock/binding is invalid, skip fresh metering and use safety deletion with held
liability. This fix does not claim to close the broader clock-skew Murphy row.

Each metering RPC uses command_timeout=min(20s,remaining-71s), where70s is the
existing boat-call cancellation bound and1s the interpreter margin; do not start
when that is nonpositive. subprocess timeout includes the same71s overhead, and
post-return monotonic checks reject late results. All lock acquisition is NB
polling against that SAME deadline (at most5s waiting for EX), never unbounded flock.
Polling sleeps consume the same deadline. A failed/timed-out stage ends metering;
no further stop/usage RPC renews the window.

The shared helper accepts an optional absolute delete_due argument, supplied by
both practice_cleanup.step and the existing guard_delete_receipt for an already
validated practice/pilot context. They derive the identical D from the existing
.started file and practice.deadlines; no independent clock origin or environment
string can extend it. If a retiring marker already exists, callers must use its
same D even if their optional argument is absent. Legacy callers with no marker
and no authenticated bounded context do not gain a new120s meter budget; their
existing delete-only path and unknown-cost holds remain. Both use the same atomic
deletion-intent implementation, not a second launch or deletion transport.

The remaining180s before D reserve the existing deletion path's60s query budget,
70s cancellation, one5s cleanup tick and metadata/receipt margin. Deletion's
absolute monotonic deadline is computed BEFORE lock acquisition; queries and
polls consume remaining time, never add another60s after waiting. The usual
controller starts delete as soon as metering commits or is abandoned.

Independent cleanup can notice a .collected worker and start its common retirement
earlier, but NEVER interrupts an uncollected worker just to meter. At D it skips
stop, metering, inventory queries and waits; it attempts the existing unique delete
request at once (within the existing5s observation tick plus1s local bookkeeping
in the controlled-clock exam). An already-overdue invocation has the same bypass.
This is one named safety attempt with at most5s for the version/API command plus
the existing70s cancellation overhead, not a renewed60s metering/delete sequence.
If the request ID is known, subsequent calls may only poll that same operation
with the same bounded read-only budget; they may not submit another DELETE.
It cannot prove an exact cost on this path, so its reservation remains held.
Provider TTL is still the backstop, not proof of a completed deletion.

If EX is busy at the safety deadline, the safety owner does NOT block behind a
meter or another cancellation. It fsyncs WORKER.metering-bypassed and enters the
SAME _delete/atomic-intent protocol without metering. That file permanently
invalidates any concurrent meter proof for settlement. The .retiring marker still
blocks new mutations, while an old in-flight call may make the outcome uncertain.
Deletion still needs exact target/operation completion; no false success from an
empty inventory. A busy lock alone never authorizes a duplicate delete.

Both normal and emergency callers arbitrate the existing WORKER.deletion-attempted
creation with exclusive-create/fsync. Exactly one may submit the provider request.
The loser only reads the persisted request/status inside its remaining budget.
If there is a preexisting attempted marker but no persisted operation ID, do NOT
submit another request: preserve the existing uncertainty and TTL backstop. The
exam asserts a timely unique attempt when no prior intent exists; it explicitly
does not promise a new RPC after a crash left the old attempt uncertain. Kernel
starvation or an unreachable provider cannot be turned into a completed receipt.

### 4. Exact durable proof and replay (Major 4)

A missing/corrupt clock/proof does not authorize an arbitrary worker deletion.
The emergency path still requires the existing exact owned ID/creation binding;
if that is unknown, preserve uncertainty and rely on the existing provider TTL.

WORKER.retiring.json is immutable schema1, with exactly:
{schema,retirement_id,worker_id,state_path,spend_path,launch_sha256,
 creation_sha256,source_generation,job_config_sha256,started_unix,
 created_at,boot_id,meter_deadline_mono,meter_deadline_utc,delete_due_utc}.
retirement_id is one UUID generated on the first exclusive-create, never renewed.
Paths are canonical absolute paths matching the bound ledger row. Creation is
this exact worker's unique real new.N response; hash its retained bytes. launch
hash covers existing launch.json; source_generation and job_config_sha256 are
parsed from its exact restore/config arguments, or null for a fresh/non-batch
launch. The retirement generation is a worker-lifecycle generation, not a case
judge verdict. Whole-worker lifetime cost is never inferred from a case answer.

Under the existing spend.deletions/WORKER directory, preserve:
- stop-request.json: original public stop response (when available), for diagnosis;
- stop-status.json: exact successful by-ID {id,stop} response bytes;
- stopped-info.json and rechecked-info.json: documented allowlisted public info
  projections containing id,state,stop, with capture command/time metadata;
- final-usage.json: exact public meter bytes (reject an unexpected secret-bearing
  response shape rather than logging arbitrary data);
- retirement-proof.json: schema1 commit record with exactly {schema,retirement_id,
  worker_id,state_path,spend_path,retiring_sha256,launch_sha256,creation_sha256,
  stop_id,stop_ended_at,source_generation,job_config_sha256,files,captured_at}.
  files maps the required four status/info/meter filenames to SHA256; request
  response is optional and outside billing authority. All timestamps are UTC-aware.

Write each raw/projection via temporary regular file -> fsync -> atomic replace
-> directory fsync. Write retirement-proof.json LAST with the same ordering. No
proof commit before all hashes/identity/status/amount predicates pass. Settlement
recomputes all required hashes/bindings, validates absence of metering-bypassed,
verifies creation/envelope authority, then the existing exact deletion request,
completion and complete inventory. Capture proof is never itself deletion proof.

Strict settlement dispatch:
- Existing schema1 with no_creation/deleted_lifetime_usage keeps its exact old
  shape/validation and permanent debit. Accepted settled rows replay without API.
- New schema2 permits ONLY basis=stopped_usage_then_deleted and nonempty workers.
  Outer keys remain {schema,state_path,settled_at,basis,workers}. Each worker has
  the existing id,deletion_operation_id,completed_at,seconds,dollars plus exactly
  retirement_id,stop_id,receipt_sha256. receipt_sha256 hashes retirement-proof.json.
  IDs unique/sorted, amounts exact Decimal, row total equals sum; retain existing
  envelope limits. Ledger-first commit/mirror-repair is unchanged.
- A new retiring marker selects new proof validation even when proof is absent or
  corrupt; NEVER fall back to querying deleted usage or authoring zero. Mixed
  incomplete/new/legacy worker evidence holds the whole unsettled row. No-creation
  remains schema1 with its existing finished/absence proof.

Crashes: before proof commit, partial files grant nothing; after proof commit but
before deletion intent, keep the fence and revalidate state within original bounds.
Once deletion-attempted is durable, never refresh/overwrite capture evidence. If
request ID was saved, resume ONLY exact deletion status polls and use retained
capture after completion. If acceptance happened but ID was NOT saved, marker
means unknown: no second delete, no guessed operation ID or settlement. After
ledger commit a crash only repairs its mirror, without refreshing provider usage
or altering the permanent debit. Malformed/foreign/stale receipt refuses; no
mutation of old evidence or later credit refund.

## Historical evidence and explicit limit

The control home has one old unbound legacy reservation: status=finished, usd=0.036,
no state_path or envelope fields, and no final actual_spend_usd. This record is
preserved. It is not zero and not newly settled. The already-deleted worker's
exact usage cannot be reconstructed from a monthly aggregate or wallet delta.
No migration/write-off, deletion of the ledger row, credit release, new control
home or new allowance is authorized by this change. Determine exact binding from
retained public spend/creation/deletion evidence; if it cannot be proved, report
the remaining owner disposition required with the specific amount and evidence.
Future cleanup correctness does not silently repair historical evidence.

## Tests, rollout and closure

Use the real stopped-info/status/meter public fixtures above, exact saved
creation/deletion evidence, and the real observed deleted-ID404 projection.
Authored transports supply pending/failing/superseded/forced states and timing;
label them explicitly. Before implementation, red regressions must cover:
1. Exact command/envelope parsing and completed+stopped+same-ID predicate; a
   failing stop with running=false, superseded stop and forced=true are distinct.
2. Mutation starts SH and blocks a fence until drained; new resume/exec/scp and
   controller restart after durable marker are refused. An inherited EX FD works;
   an invented FD/bypass variable does not. A concurrently paused controller or
   cleanup replay cannot invalidate a committed meter then get it settled.
3. Controlled-clock hung stop/usage,70s cancellation, EX contention and an already
   overdue entry bypass metering and attempt a unique delete within the stated
   tick/local bound; receipt remains unknown. Collection before D is not shortened.
4. All crash cuts around raw writes, proof commit, delete intent, provider accept,
   request-ID fsync, deletion completion and ledger/mirror commit; exact saved-ID
   poll replay versus deliberate no-ID uncertainty; never a duplicate request.
5. Wrong worker/stop/creation/generation/config, resumed info, late/negative/nonfinite
   usage, tampered bytes, metering-bypassed and incomplete inventory never settle.
6. New proof settles after verified deletion without a post-delete usage request;
   real404 is not zero; old accepted settlements/no_creation and Hetzner still work.

Run touched tests, fresh implementation diff review, one final full suite and
parent integration check. Re-pin reviewed runtime after merge; prepared e62a5c4
pins do not qualify modified runtime. No new money, worker or model roles. Real
stop/meter/delete qualification uses the already-authorized no-model smoke only
after historical liabilities, existing unlock and other prerequisites are resolved.
The other already-stopped sandbox was READ ONLY, never an extra qualification run.
Practice follows a passing smoke; no fleet. Historical$0.036 is not forgiven.

Murphy rows17/49/51 stay open: this fixes a provider-contract assumption, not case
logic. Row49 already records the observed failure before coding. Design/static
fixtures alone close no row; retain real normal-path lifecycle/settlement proof.
