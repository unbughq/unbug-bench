# Budget-aware admission using a DBOS decision queue, revision 8

Status: proposed alternative to `durable-execution-admission-budget.md` revision 6;
not implemented. Earlier reviews are in
`docs/reviews/durable-execution-admission-queue-design-{1,2,3,4,5,6,7}.md`; request a fresh
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
holder's result is applied, fence closed, then acknowledged; duplicate or stale
messages keyed to a closed operation cannot close a different fence. No new
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
zero-settled. A recorded ordinary result is authenticated and its usage is settled
idempotently. **Every** unknown-usage result, whether recorded or synthesized,
keeps the grant and fence: poll/cancel the exact recorded lease and key without
starting a new attempt until an authenticated DONE, confirmed tombstone, or proven
worker death. Only then settle its actual usage or lost, close the fence, or retry.
An unreachable live worker remains quarantined rather than retried on a guess.
Before closing an ADMIT fence, the reconciler recovers the recorded pre-attempt
inputs, grant, authenticated result, relevant clock and post-result counters, and
derives or recovers exactly the same terminal action as the normal path. It applies
STOP_ADMISSION or the authenticated updated registry to the batch before closing
the fence. If either action or registry cannot be established, retain the fence.
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
its child/lease and the batch clears the token. Thus at most one first-ADMIT worker
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

### Older WP1 draft databases and guarded bootstrap

The original unreviewed WP1 draft and current fixes share `factory-engine-1`, but
an interrupted `7d09dae` fake-worker journal restarted under `77f1e6f` returned
`engine_error`: `reserve_step` conflicted with `DBOS.getEvent`, and
`attempt_workflow` conflicted with `slot_workflow`. Evidence and limits are in
`docs/reports/durable-execution-wp1-replay-compatibility.md`. A patch at batch
entry alone cannot recover independently restarted old children.

The handoff says real infrastructure has not been exercised; it does not prove
that all development journals disappeared. No unknown journal is deleted or
migrated. All cooperating control-engine entry points use one mandatory bootstrap:

1. Before constructing DBOS **or any database-mutating seam**, inspect the intended
   dedicated system database read-only. In particular, do not construct WP6's
   `SqlLedger` or WP7's `AgeKeyService`: both currently call `create_all` in their
   constructors. `Engine` accepts an executor factory rather than a preconstructed
   database-backed executor; it does not invoke the factory before this bootstrap
   succeeds. WP8's eventual CLI uses the same bootstrap, with the identical approved
   database URL for DBOS, ledger and key service. Direct construction of database
   seams is for standalone tests/tools, not a supported control-engine launch path.
2. An absent SQLite path is checked without creating the file. An unmarked database
   with **any user table or partial schema**, whether DBOS, ledger, keys or other
   data, is refused with fixed `engine:incompatible_database`. A missing DBOS
   schema alone does not prove emptiness. Connection, permission, schema-inspection
   and unexpected-object errors fail closed without printing credentials.
3. Use the backend-specific lock and marker protocol below. Under that lock,
   reinspect before writing, then create the marker only after proving the
   dedicated database empty. The marker identifies a database generation, not a
   code release; a partial or mismatched marker fails closed. A marked restart
   accepts only the known objects and partial setup states listed below.
4. Only then construct the ledger, key service, Executor and DBOS using that same
   approved database, and launch. The application's new generation is pinned for
   the lifetime of the dedicated DB. Exclusive control of that DB is a rollout
   precondition: an old engine that ignores the marker must never concurrently
   write between inspection and launch. Old journals remain available to their old
   engine and are not claimed to resume under this release.

#### Bootstrap protocol, DBOS 3.4.0

The only supported backends are a local SQLite file and PostgreSQL. Reject an
in-memory SQLite URL, an unknown backend or a malformed URL with a fixed code.
The marker is table `unbug_engine_generation` in SQLite's main database or
PostgreSQL's `public` schema. It has exactly `singleton INTEGER PRIMARY KEY CHECK
(singleton = 1)`, `generation TEXT NOT NULL`, `app_name TEXT NOT NULL`, and
`app_version TEXT NOT NULL`, and exactly one row:
`(1, "unbug-durable-db-v2", "unbug-factory-engine", "factory-engine-2")`.
`factory-engine-2` is pinned for the lifetime of this new database. Future
compatible code releases retain the marker and use workflow patches.

For local SQLite, canonicalize the absolute database path and use an exclusive
`fcntl.flock` on `/tmp/unbug-engine-init-<uid>/<sha256(canonical-path)>.lock`;
the directory is owned by the current user with mode 0700. The fixed location and
canonical path make cooperating processes use the same lock; network filesystems
are unsupported. Hold it across reinspection, marker commit, seam construction and
DBOS.launch. If the path is absent, inspect that fact without connecting or
creating it; after acquiring the lock, check again, then create a new file with
`O_CREAT|O_EXCL` and mode 0600. Existing files are inspected via SQLite URI
`mode=ro` and `PRAGMA query_only=ON`; inspection failure, including an unreadable
WAL, fails closed. Only an empty, accepted database is reopened writable. Execute
`BEGIN IMMEDIATE`, reinspect under that transaction, create the marker table and
row, and COMMIT. A rollback or killed process leaves no committed partial marker.
After commit, release the SQL transaction before invoking the factories while
keeping the OS lock. A marked restart validates without updating the marker.

For PostgreSQL, connect to the already-existing dedicated database and take the
session-level advisory lock `pg_advisory_lock(6930772581893188690)`, the signed
first eight bytes of SHA-256 of `unbug-engine-bootstrap-v2`. PostgreSQL advisory
locks are scoped to the database; all cooperating bootstraps use the same key.
Hold that one connection and lock across read-only catalog reinspection, marker
transaction, seam construction and DBOS.launch. If the connection/lock is lost,
abort initialization and close the constructed seams; never continue on an assumed
lock. The read-only inspection checks all non-system schemas, not just `dbos`.
For an empty dedicated DB, only the built-in `public` schema may exist and it must
contain no user objects; system `pg_*` and `information_schema` are ignored. Create
the marker table and row in one PostgreSQL transaction only after that check.
The external requirement remains exclusive control over the dedicated DB: an old
engine does not honor this advisory lock and must not write concurrently.

On a marked restart, accept only this marker with exactly its specified row and
columns, the durable tables `durable_ledger_batch`, `durable_ledger_attempt` and
`durable_scope_key` in `public` (or SQLite main), and DBOS 3.4 objects. The DBOS
3.4 table names are `application_versions`, `dbos_migrations`, `notifications`,
`operation_outputs`, `queues`, `streams`, `workflow_events`,
`workflow_events_history`, `workflow_input`, `workflow_output`,
`workflow_schedules`, and `workflow_status`; in PostgreSQL they belong to the
`dbos` schema. PostgreSQL also has `dbos.event_dispatch_kv`, created by its first
migration; SQLite does not. Allow indexes and constraints belonging to these tables, and only
DBOS 3.4 PostgreSQL routines `enqueue_workflow`, `notifications_function`,
`send_message`, `streams_function`, `workflow_events_function` and triggers
`dbos_notifications_trigger`, `dbos_streams_trigger`,
`dbos_workflow_events_trigger` in `dbos`. SQLite's `sqlite_*` internal objects are
ignored. No other user tables, views, routines, triggers, or schemas are accepted.
Validate each present durable table's complete pinned WP6/WP7 definition, including
column names/types, nullability, primary and foreign keys, other constraints and
required indexes. Whenever **no DBOS object exists**, every present durable table
must be empty, even if all three tables are present: bootstrap constructors create
tables but do not write durable data before DBOS initialization. Once any DBOS
object exists, a missing ledger or scope-key table is refused before constructing a
seam, even if workflow rows have since been deleted. This prevents silently
recreating lost keys or accounting. Test marked, used SQLite and PostgreSQL
databases with one missing durable table; a marked database with populated durable
tables but no DBOS objects; and altered keys, nullability, foreign keys or indexes.
Each is refused without calling a factory or changing schema or data. **Do not accept an arbitrary subset of
DBOS tables for a recorded migration version.** A recorded version means DBOS
will skip those migrations, so required objects or columns missing at that version
would never be repaired.

For SQLite, pinned DBOS 3.4.0 initializes its system schema and migration version
in one transaction. A marked DB may have no DBOS objects yet, or the complete
version-125 DBOS schema and its expected columns, indexes and constraints; any
partial schema, a different recorded version, or a missing core object is refused
without mutation. Check in an independent normalized full-v125 SQLite schema
snapshot generated by a real pinned DBOS initialization. Test marked restart and
refusal of a missing table, column or index. A durable-table subset is allowed only
under the pre-DBOS, empty-table condition above.

For PostgreSQL, pinned DBOS 3.4.0 commits ordinary migrations separately and runs
some online-index migrations in autocommit before recording their version. Before
implementation, generate and check in a normalized schema-state fixture from a
disposable local PostgreSQL instance by applying the exact pinned migration list
one recorded version at a time. The fixture records, per nonempty migration
version, required tables, columns/types, constraints, indexes, routines and
triggers. Include the marker-only state and the `dbos` schema plus empty
`dbos_migrations` table before migration 1. For each next pending online migration,
include the exact pre-DDL and post-DDL/pre-version state: both CREATE (including
an invalid index remnant) and DROP. For example, a crash after online DROP 22 but
before its version update leaves version 21 recorded with that index absent. Pin
both fixture generation and runtime to DBOS 3.4.0 with `use_listen_notify=True`,
which determines the functions and triggers. Verify this fixture against a full initialization by DBOS itself.
On a marked restart, the catalog must match one specifically enumerated state for
the recorded version and its next pending online CREATE or DROP; DBOS then cleans
or retries that operation. A version not in the fixture, missing required object or
column, unexpected object, or unknown future version is refused. During an
incomplete initial migration, no workflow, ledger, or scope-key data may exist;
only DBOS migration metadata is allowed. At version 125 the full expected schema
must be present and online indexes valid. If `workflow_status` is nonempty, every
row must carry the marker's application and version. A marked version-125 DB
missing `operation_outputs` is always refused before constructing a mutating seam
or launching DBOS. The same check applies to missing columns and other core tables.
This state validation and the WP6/WP7 metadata checks run while holding the
backend initialization lock. Only then may DBOS resume pinned migrations.

Verify PostgreSQL fresh initialization, `event_dispatch_kv`, marked restart,
interruption after migration 1 and every recorded version, an interrupted online
index, the lock and catalog checks, and marker atomicity against a **disposable
local PostgreSQL database** before enabling this path;
no existing or remote database is modified by that verification. SQLite tests must
cover both absent files and existing read-only databases. Database URLs and raw
provider exceptions never appear in errors or logs.

A regression in `tests/factory/test_durable_wp1_upgrade.py` creates the actual
`7d09dae` fake-worker SQLite journal with a case and in-flight attempt, then checks
that bootstrap refuses it before constructing any database-backed seam or launching
DBOS and that the complete schema **and** data are unchanged. Test an old journal
without ledger/key tables, unmarked databases containing only ledger or key data,
partial markers, an absent SQLite path, inspection/connection failures, concurrent
cooperating bootstraps, and crashes on each marker transaction boundary. A fresh
marked DB must restart across the 20-kill exam. No error may print a database URL.
This verifies safe refusal, not that old journals resume under the new engine.

Files and checkpoints:

1a. Implement only the SQLite guard primitive in `factory/durable/compat.py`, with
   `tests/factory/test_durable_wp1_upgrade.py` and a checked-in normalized SQLite
   DBOS-v125 schema snapshot. It is disabled and invoked only by disposable tests;
   it is not wired into `Engine` or a production launch. It rejects PostgreSQL and
   every other backend **before** calling an executor/seam factory. Correctly refuse
   missing durable tables once any DBOS object exists, and preserve old DB schema
   and data. The existing V1 engine remains the only runnable application path.
1b. Implement the PostgreSQL guard and per-version schema-state fixture after local
   disposable-PostgreSQL verification, including online CREATE/DROP crash states.
   Only after both backend tests and fresh review may the guarded bootstrap be wired
   before every mutating seam. Adapt WP6/WP7 construction through the guarded factory
   when those branches are integrated. PostgreSQL production use remains disabled
   until this gate and the later fault-injection/integration checks pass.
1c. `factory/durable/engine.py`: add V2 pending workflows, keyed message records and
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
   to WP4's `CONTRACT_REASONS`/`PUBLISHED_REASONS` and test their grammar and public
   rendering in `tests/factory/test_durable_classify.py`; no provider text is published.
5. Enable V2 for new batches; run all touched tests, the 20-kill mid-term and the
   ENGINEERING full suite on the exact head, then a fresh goldfish diff review.
   An independent cross-package test must combine WP1 with fixed WP2, WP5a and WP6.

Internal messages contain only IDs, reason codes, enum values, numbers and encrypted
Refs: `replacement_request(case, action)`, `worker_released(case)`,
`done(case, status, replacement_action, worker_released, seal)`,
`open/close(op, holder, role, result)`, `probe_result(op, case, attempt, grant)`,
`prepare(case, attempt, key, grant)`, and `prep_claim/prep_release(op, holder)`.
Each send key is derived from `(batch, operation key, sender role, message kind,
phase, destination)`, because DBOS deduplicates by key and destination, not topic
or kind. Request, result, acknowledgement and token-release keys must all differ;
retries of the same phase reuse its key, while a genuinely new attempt or reaper
generation uses a new one. Test delivery of distinct phases and suppression of an
exact duplicate. The batch joins facts by predecessor or operation key and never
assumes FIFO delivery. No plaintext or raw
provider exception enters DBOS events.

The old unguarded V1 path is test-only during the migration and is removed from
final new-generation production launch; old draft databases are preserved and
refused before initialization, as above. The queue serializes SEAL with ADMIT; actual production SEAL timing
and the incremental implementation/review effort are not measured, so the parent
schedule estimate may increase. Tests use fakes and real DBOS 3.4 SQLite, with no
real paid calls. Targets Murphy rows 18 and 51; closes none without the real final
exam artifacts.
