# Budget-aware admission using a DBOS decision queue, revision 12

Status: proposed alternative to `durable-execution-admission-budget.md` revision 6;
not implemented. Earlier reviews are in
`docs/reviews/durable-execution-admission-queue-design-{1,2,3,4,5,6,7,8,9,10,11}.md`; request a fresh
independent design review before choosing it. WP1 owns the engine changes; WP2 must satisfy the existing idempotent `WorkerPool`
contract. No `contract.py` edit is proposed.

## Problem and choice

WP1 must stop admitting new cases when the batch bound, target, deadline or
STOP_ADMISSION requires it, without delaying an immediate replacement workflow
behind diagnosis. A balance read races ledger reservations. The six reviews of
the first proposal identified a growing custom barrier/fairness protocol. This
alternative uses a DBOS queue with `global_concurrency=1` to order admission
probes and terminal ADMIT and SEAL decisions. It keeps one recorded fence for an
uncertain queue holder, rather than a set of overlapping barriers and a custom
fairness scheduler.

This intentionally serializes SEAL with ADMIT and admission probes. Already
admitted WRITER, STRESS, GATES and diagnosis steps still use their normal global
model slots and may run concurrently. A slow or unreachable terminal attempt can
delay admissions and other terminal attempts. Actual SEAL duration has not been
measured here; compare a two-case run and the existing 20-kill exam before choosing
this tradeoff. It is no guarantee of higher throughput.

## Workflows and ordering

- The batch is a durable, non-blocking actor. It creates an eligible replacement
  workflow immediately in `pending_admission`, with no keys, worker, grant or
  paid model call. `max_cases_started` counts admission decisions; pending
  workflows have unique case IDs and are reported separately. At most
  `min(target_sealed, max_cases_started)` initial candidates plus one replacement
  per admitted case are created. A processed target, deadline, STOP_ADMISSION or
  case limit ends ineligible pending workflows as `not_admitted`.
- The batch registers `decision-<batch>` with global concurrency 1. An admission
  probe or terminal ADMIT/SEAL is one queued workflow on it. The batch may enqueue
  work, but **never calls `get_result` on this queue inside its event loop**. The
  queued workflow reports a result by message and waits for the batch's recorded
  acknowledgement before releasing the queue. All queue jobs use the same default
  priority. DBOS 3.4 orders dequeues by priority and creation time; equal-time jobs
  may be reordered. No promise depends on tie order, and a finite queued job cannot
  be overtaken indefinitely by retries enqueued at later times.
- The batch selects pending replacements before pending originals, then the lowest
  creation ordinal in each class, and maintains at most one queued admission probe
  per batch. A WAIT candidate becomes eligible again only on a real settlement,
  bound raise, predecessor release or bounded poll. On dequeue the probe asks the batch for
  authorization, because target, stop, or case limit could have changed since
  enqueue. The batch responds while continuing its own event loop. Only an
  authorized probe reserves the real first ADMIT key, then records `now_step`.
  A deadline or sub-minimum BATCH grant is zero-settled; WAIT uses a new key after
  a real settlement, bound raise or bounded poll, and its own zero settlement never
  wakes itself. Positive sub-minimum NOTHING remains allowed; zero case money stops
  admission without a worker. An admitted grant is counted before the queue
  workflow receives its acknowledgement. A recorded pre-deadline clock decision
  is grandfathered across crash/recovery, even if execution occurs later.
- A successful probe sends the batch `{kind: probe_result, op, case, attempt,
  grant}`. The batch records the case as admitted, the full held key and grant,
  then sends `{kind: prepare, case, attempt, key, grant}` to its pending case with
  a deterministic send idempotency key. It acknowledges the probe only after that
  send is recorded. The case ignores duplicate permits, checks that the case,
  attempt and key agree, and cannot prepare or dispatch before this message. It
  reuses the held key and grant; it never reuses a WAIT or EXPIRED key. If a crash
  occurs after reserve, clock, probe result, batch count, permit send or acknowledgement,
  recorded steps and the same send key reconstruct that sequence. An ambiguous
  handoff retains the hold. A recorded clock decision precedes any zero-settlement,
  so a backward clock step cannot change a replayed WAIT/EXPIRED decision.
- ADMIT and SEAL are enqueued only when their worker is prepared. The terminal
  workflow then takes one global model-step slot. The authoritative release read
  happens in that model child **after both slots are held**, immediately before
  dispatch. ADMIT reads the latest registry **inside** the serialized decision queue. On success it sends the
  updated registry to the batch, which records it before acknowledging the
  terminal decision. For SEAL, the terminal workflow compares current plumbing
  and bench with the versions that passed GATES, regardless of which version was
  prepared, including when preparation had already selected the newer release. A
  mismatch starts no worker, releases the unused grant, reports nonterminal and
  asks the case to rerun GATES. Other steps similarly read latest plumbing at their
  final model-slot dispatch boundary; a stale lease returns without dispatch so
  preparation can retry outside model slots.
- The terminal workflow takes the recorded pre-attempt counters and the result,
  then derives the same post-result counters the case currently uses: increment
  infra for non-pause INFRA_ERROR except late batch-deadline stops; increment
  free/spent provider limits according to paid usage; increment late-deadline stops
  after the batch deadline. It records `now_step` only for `infra:deadline`, then
  calls `decide` with those post-result counters, the grant and spec. It returns the
  updated counters so the case does not count the same result twice. The workflow
  reports STOP_ADMISSION, a successful authenticated SEAL, or a nonterminal
  outcome to the batch. The batch updates stop, target, registry and sealed cases
  before it acknowledges. A second already-admitted case can seal after target;
  every authenticated seal is retained exactly once. The case receives the
  terminal workflow output and performs sleeps or retries after the queue is free.
  The 96 free-limit and late-batch-deadline rules still apply.

## Crash fence and reconciliation

A queue slot can be released by an ERROR or cancellation, not just a clean return.
Before an authorized probe reserves, or an ADMIT/SEAL dispatch begins, the queue
holder sends a uniquely keyed `open` to the batch and waits for acknowledgement.
The batch records at most one terminal fence, identified by attempt/probe key and
workflow ID. If that workflow dies before its acknowledged result, the batch keeps
the fence. A later queued probe or terminal attempt must ask the batch before it
can reserve or dispatch; it is refused or waits while an older unresolved fence
exists. The event loop continues processing operator and case messages. A clean
holder's result is applied, fence closed, then acknowledged. The batch records
each applied decision by operation ID as part of its replayed state. A duplicate
or recovered result for an already-applied operation can redeliver its case
response, but must never reapply its registry, stop, target or seal decision and
must never close a different fence. No new
admission or terminal work is permitted on an unknown result.

On each bounded batch poll and after recovery, the batch independently monitors
all admitted cases (including before preparation starts), the first-ADMIT preparation
token holder, the terminal-fence holder, and any active reconcilers. ERROR/CANCELLED
or a missing expected case, holder or child starts or attaches to one reconciliation
workflow for that case, even when neither token exists. PENDING/ENQUEUED holders
remain attached, not duplicated. The batch records a per-case reaper generation and
uses a deterministic ID derived from case ID and generation, so duplicate detection
cannot create competing reapers. A reaper deliberately creates no nested workflows
and retries transient reads/cancels in durable steps. Its intended settlement
(choice, key and exact usage or lost) is recorded before the ledger side effect and
is reused unchanged on replay or in any later generation. On ERROR, after proving
its synchronous operation and any children are quiescent, the actor may start the
next generation. A CANCELLED status alone does not prove an in-flight synchronous
operation stopped: until it can be proved quiescent, retain the hold and tokens and
report a content-free error; do not start an overlapping reaper or guess a settlement.
This preserves correctness even when automatic progress is impossible. The reconciler
identifies probe, first-ADMIT preparation, decision and nested model children by
recorded DBOS parent/child IDs and `list_workflow_steps`. A synchronous reservation
or model step may continue after cancellation, so cancellation status alone never
establishes quiescence. The model child writes an `attempt_context` event containing
only the StepInput record, grant, exact lease and attempt key before it can call
`attempt_step`. A missing context proves no dispatch only if no queued/running child
can still produce it; otherwise retain the fence and hold. A probe with recorded
reserve and clock results reconstructs WAIT, EXPIRED or ADMITTED, replays the
idempotent settlement if needed, and redelivers the same keyed result/permit. If
reserve committed but its result was not recorded, once the old synchronous call is
proven quiescent the reconciler repeats the same idempotent reserve to recover the
original grant. If reserve is recorded but no clock decision is recorded, it records
a new `now_step` only after the original holder cannot still record one, then applies
the normal deadline/grant decision. A WAIT or EXPIRED zero-settlement can occur
only after a recorded clock decision; replay uses that same decision, even after a
backward clock step, and never delivers the settled key. If a reserve or clock call
could still be in flight and cannot be fenced, retain the hold and quarantine it.
A queued/running model child is attached to and awaited; cancellation is requested
only as part of reconciliation and is never itself taken as proof of termination.
Once an exact lease is known, poll/cancel it without starting another attempt. If
no worker execution can still occur, a confirmed unstarted grant can be
zero-settled. Before settlement the reaper records the `no_dispatch` decision and
the exact key; replay repeats that same zero-settlement idempotently. It reconciles
any acquired lease and does not clear the preparation token until release or
confirmed absence. The batch then closes the matching fence and the case receives
an operation-keyed `no_dispatch` response rather than a nonexistent `StepResult`.
The case continues the same step with the next attempt number and a fresh ledger
key; a settled key is never reused. An initial ADMIT remains counted as admitted,
including after its deadline, and does not repeat the admission probe. A new
BATCH-limited grant can make the already-admitted case wait for the bound. A
retried SEAL rechecks the current releases against passing GATES before dispatch.
Test child failure before dispatch and crashes before/after zero settlement, with
and without an acquired lease; the case progresses only after quiescence and never
reuses a settled key. A recorded ordinary result is authenticated and its usage is settled
idempotently. **Every** unknown-usage result, whether recorded or synthesized,
keeps the grant and fence: poll/cancel the exact recorded lease and key without
starting a new attempt until an authenticated DONE, confirmed tombstone, or proven
worker death. Only then settle its actual usage or lost, close the fence, or retry.
An unreachable live worker remains quarantined rather than retried on a guess.
Before closing an ADMIT fence for a dispatched attempt, the reconciler recovers the recorded pre-attempt
inputs, grant, authenticated result, relevant clock and post-result counters, and
derives or recovers exactly the same terminal action as the normal path. It applies
STOP_ADMISSION or the authenticated updated registry to the batch before closing
the fence. A non-OK ADMIT does not carry a registry: retain the existing registry
for that result. If the required action or successful-ADMIT registry cannot be
established, retain the fence. A proven `no_dispatch` follows the separately
recorded zero-settlement transition above and does not require a nonexistent result.

The case catches a failed terminal-child result and waits on a deterministic,
idempotently keyed reconciliation response. After applying the batch decision,
the reconciler sends the authenticated `StepResult` (including its snapshot),
the derived action and post-result counters; the case acknowledges and continues
from that result without rerunning ADMIT or incrementing counters twice. Before it
can start a subsequent step, the case records an acknowledgement event at a stable
case-owned key derived from the operation and attempt. Every reaper generation can
read that event, including after a previous reaper failed; an acknowledgement is not
addressed only to a particular generation. A generation that observes the recorded
acknowledgement completes without waiting for a duplicate response or another ack.
For both a recovered result and `no_dispatch`, test generation 1 failing after the
case records acknowledgement but before that reaper observes it; generation 2 must
complete and the case's subsequent work and batch termination must progress. The case
accepts a response only for its currently awaited operation and attempt, records
which result it applied, and ignores later duplicates even across reaper generations.
Replay redelivers the same response until acknowledged. Test an already-applied
ADMIT A whose holder fails after the batch acknowledgement, then a successful
ADMIT B and delayed A recovery: B's registry remains current. Deliver A's response
again while the case waits for a later attempt and prove it is ignored. If the case itself is terminal
and cannot consume it, the batch retains the authenticated result and registry,
reports the case as `engine_error`, and safely reconciles its worker and grant;
it neither invents a continuation nor reruns the paid step. This exceptional
fallback can require operator intervention. Test a terminal child failing after
settlement but before reporting: the still-running case must consume the recovered
result and continue, and ADMIT must run once. Also test the terminal-case fallback
and a non-OK ADMIT that leaves the existing registry unchanged.
Test a holder failing after settlement but before reporting, for both a threshold
STOP (no later probe) and a successful ADMIT (the next ADMIT reads its registry).
For a recovered successful SEAL, the reconciler sends the authenticated archive,
`hard` and case ID to the batch and waits for the batch's durable acknowledgement
that the seal and target count were recorded **before** closing the fence. A probe
cannot reserve while that fence is open; after acknowledgement it sees the new
target. Duplicate recovery messages count the seal once. Test a holder failing
between settlement and reporting at target one, with a queued probe: it must not
reserve and is refused after the seal is recorded. The seal is reported as `sealed`
with a separate cleanup error if cleanup fails; other failed cases are
`engine_error`. The reconciler does not occupy a global model slot.

## Capacity and replacement

A stopped case publishes its result/escalation and requests its replacement before
waiting. The batch creates the pending replacement immediately, joining request and
confirmed predecessor-release messages by predecessor case ID in either order.
These facts are durable and idempotent; the case's `done` message repeats its
replacement-request and release facts, and any sealed result and attempt key. A
`done` received before `line_stopped` therefore cannot hide a replacement. Batch
termination requires all admitted and pending cases, cleanup and reconciliation to
be terminal, all readable control messages drained, and every fence resolved. The
predecessor releases its worker before any unbounded wait; a durable cleanup workflow
continues after transient failure. The original diagnosis cannot reserve ahead of
its replacement: it waits until the replacement has its first grant and a usable
worker, or that replacement is ruled out by a processed stop, target, deadline or
case limit. Other cases and operator messages keep running.

Worker preparation occurs outside the decision queue and the global model queue.
A per-batch first-ADMIT preparation queue with concurrency 1 is held from the start
of preparation until that first ADMIT terminal workflow completes. Before calling
`acquire`, its holder sends the batch a keyed preparation-token request and waits
for acknowledgement; the batch retains the single token until that first terminal
result is resolved or the acquired lease is confirmed released. If DBOS marks the
preparation holder ERROR or CANCELLED, its queue slot may reopen, but the next holder
cannot acquire until the token's deterministic reconciliation workflow resolves
its child/lease and the batch clears the token. Before `acquire`, the holder records
the case ID, attempt key, and requested plumbing and bench versions, so the reaper
can recover even if the acquisition's output was never recorded. If that call may
still run, retain the token and grant. Only after proving the call quiescent may the
reaper repeat that exact idempotent acquisition to recover, adopt or release the
lease. A provider error or negative inventory alone does not prove absence; a
confirmed terminal no-worker result is recorded as a predecessor-release fact.
Test a successful acquisition committed before its step output, a still-running
acquisition that cannot be repeated, and an unresolved provider outcome. Thus at most one first-ADMIT worker
is prepared or queued per batch even after failure. A case with the only worker can
still run SEAL on the decision queue and release capacity. Preparation for other
steps is independent of the held first-ADMIT token; individual attempts use a
separate bounded preparation queue and sleep outside it when necessary. For WP2's generic `infra:worker_create_failed` and
`infra:worker_create_unknown`, record the fixed INFRA_ERROR reason and keep the
same grant and attempt key while retrying with durable exponential backoff (30 to
900 seconds), without consuming the ADMIT infra allowance or a model slot. These
reasons may also mean persistent configuration failure; the public operator view
shows `waiting_for_worker` and the reason rather than scoring the case.

**WP2 dependency:** its current code clears an uncertain creation intent after an
inventory miss and can issue a new nonce while an earlier VM appears late. The
queue design relies on the frozen `WorkerPool.acquire` idempotence guarantee, which
WP2 has not established. WP2's review must fix or prove this path, including a late
create after a subsequent inventory miss and restart, before the integrated system is
considered safe for real Boat work. The implementation must never assume a negative
inventory proves an outstanding create cannot still complete.

## Implementation and tests

The first increment is test-only and disabled by an immutable internal `queue_v2`
boolean in the recorded batch job, not an environment read inside a workflow.
Intermediate V1 batches run only in disposable test databases; no production V2
generation may run them. Once the V2 phases pass, V2 is the only path for new
production batches, and the old V1 functions can be deleted from the final release.
Future compatible workflow changes, including independently recovered child
workflows, use `DBOS.patch`; a batch-only patch does not repair old child histories.
This is one operator launch path, not a user-facing mode switch.

### Earlier WP1 draft databases and the deployment boundary

The unreviewed WP1 draft and current fixes have incompatible recorded operations:
an interrupted `7d09dae` fake-worker journal restarted under `77f1e6f` ended in
`engine_error`, as documented in
`docs/reports/durable-execution-wp1-replay-compatibility.md`. Prior draft journals
are incompatible and must not be opened with this code. They may exist; this design
does not assume otherwise. The WP1 package has **no supported persistent-database
or production launch path**. `Engine.launch` accepts an arbitrary URL and does not
currently refuse old journals. Do not claim it automatically protects them.

All wave-1 executions use freshly created disposable test databases, reused only
for restart/replay within the same test and compatible code. The V1 path is only
for migration tests and no V1 workflow may enter the later V2 production database
if V1 support is removed. Same-generation replay, including the 20-kill exam, remains
required. Future compatible releases must use `DBOS.patch` for changed workflows,
including independently recovered children, while retaining the same application
version and database for the lifetime of the production generation.

An independent review (`docs/reviews/durable-execution-wp1-bootstrap-scope-design-1.md`)
accepted deferring a deployment guard to WP8 for this un-deployed package. The
previous proposed marker and schema-validation protocol and its unresolved findings
remain in queue reviews 3–8; they are not implemented or claimed fixed.

**WP8 rollout gate, still open:** before any production DBOS, ledger, key-service or
other database-mutating seam is constructed, the supported initial production path
must provision a genuinely new dedicated database, verify it is empty of all user
objects and partial application schemas, bind all seams to it, and establish exclusive
control against older engines and other writers. It must fail closed on uncertainty,
leave any old or unknown database unchanged, and record and verify the new database's
identity on subsequent starts. This is a first-generation launch requirement, not a
request for a new database on each reboot. WP8 must design and independently review
the actual initialization and restart mechanism, including lost ledger/key/journal
state, then verify it against disposable PostgreSQL and old-journal fixtures before
production use. An operator instruction or application-version change alone is not
a sufficient guard.

Files and checkpoints:

1. `factory/durable/engine.py`: add V2 pending workflows, keyed message records and
   predecessor-fact join; `factory/durable/report.py`: whitelist `pending_admission`,
   `waiting_for_worker`, `not_admitted` and a validated boolean `cleanup_error` on
   a known seal. `tests/factory/test_durable_report.py` verifies a sealed archive
   remains counted as sealed with cleanup error, while an unverified stale card is
   `engine_error`. `tests/factory/test_durable_engine.py` exercises V2 only under
   the recorded switch, including `done` before request, release before request,
   duplicates and equal-time messages. V1 remains default and its tests pass.
2. `factory/durable/engine.py`: add asynchronous decision queue workflows and
   singleton terminal fence. `tests/factory/test_durable_admission_queue.py` checks
   actor responsiveness, no `get_result` in the batch loop, queued probe vs terminal
   ordering, terminal FIFO/ties, STOP_ADMISSION, target grandfathering, two seals
   with one after target, 96th free limit, max-infra threshold, late deadline, and
   release changes before preparation, in the decision queue and while waiting for
   the model slot. Test failure before/after open/result/ack and unknown fences.
3. `engine.py` and `tests/factory/test_durable_admission_recovery.py`: add the
   keyed grant handoff, recorded clock and preparation token. Test zero case money,
   positive sub-minimum NOTHING, tied BATCH, WAIT and EXPIRED settlement replay with
   a backward clock step and bound raise, fresh retry keys, ADMITTED replay past
   deadline, duplicate permits, no released key reused, preparation ERROR/CANCELLED
   after lease and after terminal enqueue, and the three-case one-worker cycle.
4. `engine.py`, `executor.py` and recovery tests: implement deterministic nonblocking
   reconciliation and durable worker cleanup using the explicit states above. Test
   a cancelled queued child, cancellation of an executing synchronous step, unknown
   dispatch, a recorded `engine:executor_raised` while its worker is live followed
   by late DONE, proven death, missing context, and successful SEAL followed by failed
   release. Test reaper ERROR/CANCELLED at each monitor point, before preparation
   creation, and after token claim, lease acquisition and terminal enqueue. Test a
   recorded grant without a clock, an unrecorded committed reserve, and a still-live
   synchronous reserve. No later reaper may choose a conflicting settlement. Verify no model slot is held while waiting for capacity or an
   operator. Add fixed `infra:worker_create_failed` and `infra:worker_create_unknown`
   to WP4's `PUBLISHED_REASONS` through a distinct worker-pool allowlist, and test their grammar and public
   rendering in `tests/factory/test_durable_classify.py`; no provider text is published.
5. Enable V2 for new batches; run all touched tests, the 20-kill mid-term and the
   ENGINEERING full suite on the exact head, then a fresh goldfish diff review.
   After WP2, WP5a and WP6/WP7 are independently reviewed and merged in the user's
   specified order, run an independent cross-package integration test against the
   combined implementations. That test is a final merged-tree and real-use gate,
   not a prerequisite that reverses WP1's package-review order.

Internal messages contain only IDs, reason codes, enum values, numbers and encrypted
Refs: `replacement_request(case, action)`, `worker_released(case)`,
`done(case, status, replacement_action, worker_released, seal)`,
`open/close(op, holder, role, result)`, `probe_result(op, case, attempt, grant)`,
`prepare(case, attempt, key, grant)`, and `prep_claim/prep_release(op, holder)`.
Each send key is derived from `(batch, operation key, sender role, message kind,
phase, destination)`, because DBOS deduplicates by key and destination, not topic
or kind. Request, result, acknowledgement and token-release keys must all differ;
retries of the same phase reuse its key, while a genuinely new attempt uses a new
one. Reaper-control messages may include the generation; a recovered response's
delivery key is instead stable across generations for the same operation, attempt,
phase and destination. Test delivery of distinct phases and suppression of an
exact duplicate. The batch joins facts by predecessor or operation key and never
assumes FIFO delivery. No plaintext or raw
provider exception enters DBOS events.

The old V1 path is test-only during the migration and is removed from the final
new-generation production launch. WP8 must prevent old draft databases from being
selected before initialization; WP1 alone does not enforce that boundary. The queue
serializes SEAL with ADMIT; actual production SEAL timing
and the incremental implementation/review effort are not measured, so the parent
schedule estimate may increase. Tests use fakes and real DBOS 3.4 SQLite, with no
real paid calls. Targets Murphy rows 18 and 51; closes none without the real final
exam artifacts.
