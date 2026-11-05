# Budget-aware case admission, revision 6

Status: proposed for fresh independent review. Applies to WP1. The frozen v5
`contract.py` remains unchanged. Previous reviews are in
`docs/reviews/durable-execution-admission-budget-design-{1,2,3,4,5}.md`.

## Problem and boundary

The batch starts replacements without consulting the money bound. A balance read
alone races concurrent reservations. `Ledger.reserve` serializes holds with
spending. ENGINEERING also requires a replacement to launch immediately, even if
it cannot yet make a paid call. These are reconciled by distinguishing a launched,
non-paid **pending workflow** from an **admitted case** with its first grant.

For the deadline, target and `max_cases_started`, a case starts at the recorded
admission decision, not at workflow creation. The cutoff is the last clock read of
the probe execution whose ADMITTED decision is recorded. A crash before that read
is recorded re-reads the clock; a crash after it is recorded can lead to one admitted
case whose worker or workflow continuation runs after the deadline. This is a cost
choice: DBOS records time separately from a child start, and an ordinary queued
ADMIT can already make its first paid call after the deadline. The hold is counted
against the batch bound. The one-at-a-time arbiter bounds that exposure to one
admission per crash. The parent design records this definition; `contract.py` is
not edited.

## Launch and admission

1. The batch creates a deterministic case workflow as soon as an original or an
   eligible replacement is requested. It is a pending workflow, with a public
   `pending_admission` card. Initially it has no grant, worker, keys, or paid call;
   after admission it may prepare a worker, then waits for `ADMIT_GRANTED` or
   `NOT_ADMITTED`. Each stopped case requests at most one
   replacement; the batch's durable workflow state deduplicates the request before
   child creation. A replacement is not created after a processed STOP_ADMISSION,
   reached target, deadline, or case limit.
2. Case IDs are unique, increasing, and never reused, including for pending
   workflows. `max_cases_started` counts ADMITTED decisions, while pending
   workflows are tracked separately. At most `min(target_sealed, max_cases_started)`
   initial pending requests plus one replacement request per admitted case can exist. A pending workflow
   that becomes ineligible receives `NOT_ADMITTED` and ends without a worker; it
   is reported separately from admitted cases. Pending replacements take priority
   over pending originals. When the admitted-case limit is reached, remaining
   pending workflows are ended without admission.
3. The batch is the sole arbiter and processes at most one admission probe at a
   time. A probe calls recorded `reserve_step` for that case's real first ADMIT
   key, then records `now_step`. If the clock is at or after the deadline, settle
   that unstarted key at zero and return EXPIRED. If the reserve commits but its
   result is not recorded before a crash, replay reserves the same key; the waiting
   case has not received a grant and cannot start an attempt. A recorded clock
   result is reused before settlement, so a clock that later moves backwards cannot
   change the WAIT/EXPIRED branch. An earlier `admission_open` time check is only
   a fast path; the probe's recorded clock read is authoritative.
4. A BATCH grant below `MIN_GRANT_USD_MICROS` is settled at zero and returns WAIT.
   WAIT and EXPIRED probe settlements send no `settled` wake. Retrying WAIT uses a
   new attempt number and key; a settled key is never sent to a case. A positive
   sub-minimum NOTHING grant is valid, following `decide_grant`. Zero case money
   stops admission because no ordinary ADMIT call can be paid. A successful grant
   is ADMITTED and is never zero-settled by the batch on a guess. The batch sends
   its pending case the successful attempt number; the case's attempt reuses the
   held key through idempotent `reserve`. DBOS's recorded send is replay-safe; the
   case ignores duplicate permits for the same key and cannot run without a permit.
5. The pending child is created using one `DBOS.start_workflow` operation with its
   deterministic ID. DBOS 3.4 persists that child and its parent's operation in
   one transaction (`dbos._core._init_workflow`). The batch does not wrap or retry
   `start_workflow`: DBOS retries connection failures and replay handles crashes.
   Any other exception fails the batch with the hold, if any, intact. Neither an
   uncertain child start nor a missing acknowledgement proves that no worker can
   later run.

When a case's line of work ends, it first publishes its status and asks the batch
to launch a replacement. The batch creates the eligible pending workflow at once,
then may reserve its first grant ahead of diagnosis. The predecessor releases its
worker and sends `predecessor_released` only after confirmed release or confirmed
absence. A replacement may not prepare a worker before that confirmation. Cleanup
retries durably after transient failures and resumes after process loss. If the
predecessor workflow fails during cleanup, a separate cleanup workflow continues
on its recorded lease; unknown release leaves the replacement waiting, with its
grant held and status visible. The predecessor holds no model slot during cleanup.

The batch records release confirmation by predecessor case ID even when its
`line_stopped` request has not arrived; it joins these facts in either order and
treats duplicates idempotently. A case's final `done` message repeats the immutable
replacement-request and release facts, and any terminal SEAL decision and attempt
key, so a reordered `done` cannot erase them. Batch termination requires every
child/cleanup/reconciliation to be terminal, all readable control messages drained,
and all terminal barriers resolved. Test release-before-request,
`done`-before-request, and `done`-before-SEAL-resolution, including equal timestamps
and replay.

For diagnosis, the acknowledgement that allows its own reservation is sent only
when the replacement has a confirmed worker lease and its permit, or is ruled out
by a processed stop, target, deadline or case limit. Thus diagnosis cannot take
the replacement's grant. Escalation and retirement remain visible during either
wait. Other running cases continue and can free holds. Pending replacements take
priority over pending originals; the finite admitted-case limit bounds requests.

Pending requests are reconsidered after a real attempt settlement, `BOUND_RAISED`,
predecessor release, barrier resolution, or a bounded batch poll. A failed probe's
zero-settlement never creates a wake. At each wake the batch drains a bounded number
of readable case and operator messages, makes at most one admission decision, then
returns to the message loop; it retains the recorded processing order across replay.
The linearization point for a terminal barrier is when the batch processes its
request. A probe begun before that point is ordered first, even when the request is
already queued. When the target, STOP_ADMISSION, deadline or case limit rules out a
pending request, send `NOT_ADMITTED`; it exits with `not_admitted` and no worker.
A grant already ADMITTED is grandfathered and must be delivered even if the target
is reached before execution. All authenticated seals from admitted cases are kept
exactly once. A batch remains live while an admitted case, eligible pending request,
cleanup or reconciliation remains; it finishes only after those have settled, the
control messages are drained and the terminal barriers are resolved. `report.py`
includes `pending_admission`, `waiting_for_worker` and `not_admitted` in its status
whitelist and reports unadmitted cases separately from admitted outcomes.

## Worker preparation and capacity

The first grant remains held while a pending replacement waits for a worker. An
attempt preparation workflow runs outside the global model-step queue: it reserves
or reuses the attempt's grant, and obtains the case's worker lease before enqueueing
a dispatch child. For WP2's generic `infra:worker_create_failed` and
`infra:worker_create_unknown`, record a content-free INFRA_ERROR with that original
reason, keep the same grant and attempt key, and retry acquisition after durable
bounded exponential backoff (initial 30 seconds, maximum 900 seconds). No ADMIT
infra-retry count is consumed, no new worker attempt is started, and no model slot
is held during this wait. These generic reasons also cover some persistent provider
or configuration failures: show `waiting_for_worker` and the fixed reason in the
operator view, and retain the hold until the provider succeeds or an operator
changes the state. Other PoolError reasons keep the existing fixed-code infra retry
policy. This deliberately chooses a visible wait over scoring a capacity failure as
STOP_ADMISSION; it does not assume WP2 has a capacity-specific error.

After a lease is acquired, the parent enqueues a dispatch child on the global steps
queue; ADMIT also takes the serialized admit queue. On dequeue the child reads the
latest releases before starting any worker process. If those releases cannot be
served by the prepared lease, it returns STALE without dispatch, freeing the model
slot. The parent reinstalls or reacquires outside the slot, then enqueues a new
uniquely numbered dispatch child under the same attempt and grant. A dead lease is
handled the same way before any start. Once dispatch begins, exact-lease
reconciliation and first-wins idempotency apply as specified below. A release change
cannot silently run old plumbing, and a case cannot lose its priority grant merely
because a third case acquired the provider's only free VM first.

## Terminal barriers and event ordering

Use the smaller pre-enqueue barrier recommended in review 4. Before any ADMIT or
SEAL attempt is enqueued, the case sends the batch `barrier_open` with the full
attempt idempotency key and waits for its acknowledgement. The batch records that
key before acknowledging it. For a first ADMIT the batch installs the barrier with
the admitted permit before delivering the permit. No pending case is admitted while
any terminal barrier is open. The attempt then reserves or reuses its grant, runs,
and settles in the normal way. After its outcome is decided the case sends exactly
one keyed resolution: nonterminal, STOP_ADMISSION, or SEAL with archive and hardness.
**Every** attempt resolves its own key before immediate RETRY, sleep, a bound or
replacement wait, or return. A successful SEAL's resolution is published before
potentially slow cleanup. The batch applies STOP or counts a validated SEAL before
closing the key. A resolution cannot precede installation because the attempt
cannot be enqueued before the acknowledgement. Duplicate or stale resolutions are
idempotent by full key; closed keys are retained for the life of the batch. An
unknown or contradictory resolution is quarantined, never used to close another
attempt. Acks echo the key and target the unique case workflow, so message order
among different attempts is immaterial. `settled` remains a wake for existing
waiters, not a second half needed to close a barrier.

Fairness is across barrier generations, not merely event-loop iterations. Once an
eligible pending request exists, the batch defers acknowledgements of newly requested
terminal barriers while already acknowledged barriers finish. When the open set is
empty, it permits one pending admission probe, then fairly acknowledges at least one
deferred barrier before beginning another drain generation. If that probe must WAIT,
it releases the deferred barriers and retries the candidate only on an external wake
or bounded poll. The first ADMIT of a granted case installs its own barrier before
its permit. A genuinely unresolved or quarantined barrier still blocks admission.
Test two repeatedly nonterminal overlapping SEALs and an eligible pending case: the
pending case gets a probe without overtaking an acknowledged barrier.

This conservative choice can delay pending admissions for the full duration of an
ADMIT or SEAL, including time queued for a model slot. ADMITs are already serialized;
a slow SEAL can delay an otherwise independent admission, but already-admitted cases
and operator messages continue. It replaces the more complex pre-settlement
handshake and paired messages in revision 4. Test the throughput tradeoff and do not
claim admission availability while a terminal step is outstanding.

SEAL success is recorded and sent to the batch before potentially slow worker
cleanup. The batch counts a given case's archive and hardness exactly once toward
the target, but the case is not finally done until cleanup completes. A transient
release failure is retried durably. If cleanup or the case workflow fails after a
successful SEAL, recovery uses the recorded authenticated SEAL output, counts it,
and reports the cleanup failure separately rather than losing the seal or allowing
new cases as though it never happened. Public status reflects the seal and a
content-free cleanup error; an `engine_error` overlay cannot erase a known seal.

## Failure reconciliation

An unresolved case or attempt is reconciled without blocking the batch's event
loop. Use a separate durable reconciliation workflow and poll it via events; do not
hold a model slot while it waits. Preserve the grant and, for ADMIT or SEAL, the
terminal barrier until the outcome is established. Explicit states:

- Before any attempt is enqueued, a definitively failed case with no DBOS child
  operation and no live child can settle its held first grant at zero. A pending
  or uncertain child start is not such proof; DBOS's atomic child record is checked
  by deterministic case/slot ID and by parent operation.
- For an ENQUEUED or PENDING `slot_workflow`, or nested ADMIT `attempt_workflow`,
  wait or attach; do not settle or launch a duplicate. For ERROR or CANCELLED,
  inspect `DBOS.list_workflow_steps` and nested children: cancellation status alone
  cannot prove a synchronous step or detached worker stopped.
- A recorded attempt result is authoritative only after all output refs authenticate.
  An unknown-usage code, including `engine:executor_raised` or
  `engine:executor_bad_result` synthesized by `guarded_run`, is not proof the worker
  stopped: reconcile the exact worker first, whether or not a result was recorded.
  Only after a DONE result, confirmed tombstone, or proven worker death may the
  engine settle actual usage or lost and recover the terminal decision. For a
  successful SEAL preserve its archive and `hard` value. For ADMIT reconstruct the
  case's recorded outcome and retry counters;
  if a STOP decision cannot be established, quarantine rather than reopen admission.
- If a lease was recorded but the attempt result was not, dispatch may have landed.
  Poll and cancel **on that exact lease and attempt key**, without calling start;
  accept a late DONE result with authenticated outputs, or a confirmed tombstone,
  or proof the worker is gone. Settle actual usage or lost as appropriate only after
  that proof. A bounded reconciliation pass reports `unknown` and retries later;
  an unreachable live worker leaves the hold and terminal barrier quarantined.
- If neither lease nor attempt execution can have occurred, settle zero only when
  DBOS's recorded child/step state also proves no running or queued operation can
  subsequently dispatch. If any observation is ambiguous, retain the hold and
  report a content-free `engine_error`; do not reopen admission on an unresolved
  terminal outcome. The batch can still service other existing cases and operators.

## Incremental implementation and verification

1. Add pending workflows, unique IDs, permit handling and no-money waiting behind
   a disabled feature switch; the old path remains the only runnable path until
   steps 2–4 are all in place and verified. Tests in
   `tests/factory/test_durable_engine.py` cover an immediate replacement workflow
   when another case holds all money, raising the bound, a single-worker pool,
   stop/target/deadline and case-limit cancellation, original vs replacement
   priority, zero case money, positive sub-minimum NOTHING, and tied sub-minimum
   BATCH. Confirm no worker or paid call occurs before its first grant, except the
   explicit worker-preparation stage after ADMITTED.
2. Move the first reservation to the batch probe. In
   `tests/factory/test_durable_admission_recovery.py`, fault-inject before/after
   reserve, clock, WAIT and EXPIRED zero-settlement, decision recording, permit send,
   and child start. Include a backwards clock step and bound raise; assert that a
   failed probe retries with a new key and no released grant is reused. After a
   recorded ADMITTED decision and recovery past the deadline, assert one reserve
   row, one child start operation, the same hold until ADMIT settles, no new
   replacement/extension, and no duplicate worker execution. Stall after a
   pre-deadline clock read until after the deadline to exercise the decision boundary.
3. Add the pre-enqueue keyed barrier/ack protocol and terminal recording. Test a
   probe already in progress, queued barriers alongside bound/settled messages,
   overlapping nonterminal SEALs with fair admission, reordered and same-timestamp
   release/request/done messages, duplicates and stale keys, an immediate
   retry followed by success, and kills after acknowledgement, ledger settlement,
   settlement-step recording and outcome reporting. A SEAL reaching target or
   ADMIT stopping admission prevents later probes; a probe already in progress is
   ordered first. An already-admitted case keeps its grant and may later seal even
   after the target, with every seal counted exactly once.
4. Add the nonblocking reconciliation states, report status changes and durable
   cleanup retry. Test a delayed and transiently failing predecessor release in a
   one-worker pool, including a third case acquiring capacity before the replacement,
   bounded-backoff retries with the same held key, no occupied model slot, crash
   recovery and escalation visibility. Inject
   failures before enqueue, while queued, after lease, during uncertain dispatch,
   after a recorded result, and during worker release after successful SEAL. Assert
   holds are zero-settled only with proof, unknown usage settles lost only after
   worker death/tombstone, a live unknown attempt retains its hold, no duplicate
   attempt runs, successful seals remain counted, and the batch can service operator
   messages while a reconciliation is quarantined.
5. Enable the new path only after phases 1–4 pass; remove the old unguarded path.
   Run the existing 20-kill mid-term, every touched test file, the full suite required
   by ENGINEERING, and a fresh goldfish diff review. No individual test closes a
   Murphy row without real final-exam artifacts.

This replaces the unguarded `start_case` admission path and moves worker preparation
outside the model queue; `settled` remains a wake and terminal decisions use the
pre-enqueue barrier. It adds one first-attempt
reservation and messages per admission,
with no paid calls by itself. Pending replacements can hold future grant priority;
long external outages retain uncertain holds and can prevent new admissions. No
real-infrastructure costs are incurred by the tests. Implementation and replay
checks are not yet timed; they may extend the parent design's final-exam estimate.
Targets Murphy rows 18 and 51; closes neither in this package.
