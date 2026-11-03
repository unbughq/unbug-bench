# Authenticated collection planning (diagnosis scheduling increment 2)

## Objective and scope

After an opted-in worker's result has been collected, published, acknowledged
and retired, automatically put its diagnosis request in the existing durable
queue. Today `batch_service.plan` has no production caller.

Baseline: lane-1 3bd1027 includes factory-simplify a169a40 and the accepted
authenticated diagnosis opt-in. B's pilot plan is the read-only
`t3/batch-service-control-vm:docs/designs/pilot-run.md`, Diagnosis scheduling row.
This increment supplies the caller only. Resume queue draining is the next
increment; this change alone cannot run a diagnosis. B owns pilot activation,
admission/lifecycle limits, cleanup and Boat settlement. No tracked manifest
opts in, no global activation changes, and no live action is authorized.

## Existing path and minimum change

The existing holder tick reconciles worker retirement, schedules provider waits,
and recovers controllers/publication. Collection already persists an immutable
generation, R2 publication, current pointer, money ACK, acknowledged outbox and
the producing operation's output_generation. `_source` authenticates the pointer,
outbox, operation/ACK retirement and authority, and immutable snapshot.

Add `batch_holder.plan_collections(policy, root, home)` to that same tick,
after reconcile and before schedule_waits, with action None. It returns []:
no spawn, reserve, authority revision, new ledger, journal/schema, config or
launcher. Persist planning identity using the existing entry key
case/generation and existing resume/<case>/<generation> queue key. Existing
atomic facts+queue publication provides replay idempotence; no new cursor.

A cheap scan under the money lock reads operations and service entries. It
selects launched operations with no incident, retirement present, output
generation present, no deterministic successor operation, no existing (or symlinked)
retirements/<case>/<generation>.json marker, and that entry's facts still None. All other operations
are skipped. Missing/false authenticated diagnosis_policy returns [] before
reading operations or importing diagnosis. HOLDER activation is still required.
A candidate's scan result grants nothing.

For each candidate call the existing `service.plan` outside the scan's lock.
Add keyword-only `published_operation=None` to plan (after existing now).
Existing offline/local calls without the keyword keep their existing contract.
The production caller always passes the producing operation ID. When supplied,
plan authenticates the source *inside its own existing money lock*, before
projection, legacy retirement or journal writes. This avoids both nested flock
deadlock and a validate/unlock/commit race. The identifier is a durable lookup
key, never a caller-provided authorization bool.

Extract the existing common _post prefix into _current_operation with the
same arguments as _post. It keeps the existing export/incident/aggregate/deadline,
row-overrun/authority/source and frozen-config checks unchanged and returns op.
Both _post and the new helper call it; _post's input-source checks stay unchanged.

Implement the remaining locked validation in a private holder helper
`_planning_source(directory, record, policy, root, home, identity, case, generation)`.
It reuses `_operations`, `money.load_locked`, `_config` and `_source`; no
second snapshot/parser/retirement protocol:
1. Require holder enabled, diagnosis policy enabled and no export.json
   (including symlink).
2. Require current live batch deadline; no money incidents; aggregate(state)
   <= manifest money_limit_usd; job row not overrun. No monetary authority is
   created or increased.
3. Lookup the operation; require state launched, incident None, retirement
   present, matching case and output_generation, and authenticated frozen config.
4. Require money row authority == operation authority and last persisted source
   == operation.source_generation. Skip/refuse if the deterministic successor
   operation_id(policy, job, generation) already exists: this source has been
   consumed, including uncertain/pending/failed successors.
5. Call _source for this job/generation; its ACK/pointer/acknowledged outbox,
   retirement, authority, immutable collection and job_money checks must pass.
   Require returned entry case/generation to match plan's requested identity.

All those reads and plan's existing atomic journal write share one money lock.
The helper returns the verified card, never a grant. plan calls it BEFORE its
existing _snapshot branch and reuses that returned card for projection/enqueue;
only plain local calls use the old _snapshot site. Thus production verifies one
full snapshot per attempt, never two. Existing plain local plan remains intentionally a verifier and
metadata producer, not launch authority; no external handler exposes it.

The scanner catches OSError, ValueError, KeyError, TypeError and AttributeError
per candidate and continues, just like schedule_waits. Top-level malformed
manifest/journal failures use batch_tick's existing labelled refusal. No raw
cards, argv or credentials are logged. On per-candidate failure, store time.monotonic()+60 in module-private
_PLAN_RETRY_AFTER, keyed by (str(home.resolve()), manifest SHA, case, generation).
The cheap scan skips keys whose deadline is in the future. Retry after 60 seconds;
remove the key on success. Restart clears this process-local delay. It is never
an authorization cache and adds no durable latch. Its size is bounded by refused
generations during this holder process; the three-case pilot needs no index or
framework. Repaired proofs become eligible on the next due attempt. A bad candidate cannot block a valid peer.

## Interruption and refusal contract

| Condition | Result |
|---|---|
| Missing/false policy or holder inactive | No projection or queue write; tick keeps existing activation behavior |
| Collected but unACKed, unpublished, unretired, incident, stale pointer, wrong authority/config/snapshot | Refuse candidate, no facts/queue or money writes |
| Exported batch, deadline passed, accounting incident, aggregate over bound or job overrun | Refuse candidate without a grant or money mutation |
| Successor already exists | Skip/refuse old source, even if planning metadata was never written |
| Crash before plan's atomic journal publication | facts remains None; retry after backoff or immediately after process restart |
| Crash after publication or lost reply | facts and queue already committed together; next tick skips; no duplicate sequence |
| Crash in collection before output_generation persisted | Existing unpublished/collect replay repairs first; planning waits |
| Imported-only generation without a producing local operation | Not scanned in this increment; later local collected outputs are eligible normally |

The scan is deliberately O(number of operations), using existing local state.
The pilot has three cases; no index or general scheduler framework is needed.
Queue rows remain durable history. Subsequent reserve/dispatch must revalidate
all authority and capacity; this increment neither consumes the queue nor treats
ordered_queue as ready work.

## Tests and evidence

Add `tests/factory/test_batch_planning.py` using the existing
`test_batch_holder.HolderTests` setup and helper methods (not subclassing its
test methods), using the existing WaitSchedulingTests mechanism:
locals().update({k: v for k, v in vars(HolderTests).items()
if not k.startswith(('test_', '__'))}). Override setup after copying helpers,
call HolderTests.setUp(self), disable replacement_policy and freeze before reserve.
Use the authored API double self.answers(pending={'schema_version': 1,
'status': 'pending', 'replacement_eligible': False}) via patch.dict(sys.modules,
diagnosis=api). Known total plus this pending projection yields exactly the
resume/<case>/<generation> row and no replacement/derivation. This is a contract
projection control, not proof of real diagnosis eligibility. Replacement planning
remains existing policy-gated behavior; next increment drains only resume rows. Saved isolation card/ciphertext/deletion event plus authored batch
bindings remain honestly labelled. Use real reserve/start/output/collect/
retirement/reconcile/plan with the labelled projection control above;
no hand-authored state is claimed to qualify a live diagnosis. No cloud, decryption,
worker or model call.

Midterm: enabled policy, collected+ACKed+retired generation reaches real plan
through real key_holder.batch_tick, commits facts and the expected resume key,
never calls reserve/dispatch/spawn, and leaves money.json, operations and config
bytes unchanged. Repeated ticks/restart preserve queue, sequence and facts bytes.

Change only WaitSchedulingTests.test_tick_future_due_restart_and_single_successor
to disable diagnosis_policy and freeze BEFORE creating its wait, preserving its
provider-wait-specific no-hash assertion. Also re-check HolderTests'
test_batch_tick_never_stops_and_records_only_dispatch_exits and
test_batch_tick_survives_real_corrupt_money in the touched holder file.

Count _snapshot calls: one successful production attempt; a legacy retirement
then repeated ticks verify once total; a projection/snapshot refusal followed by
repeated ticks verifies at most once until the 60-second monotonic boundary,
then retries once. Clear the private retry map in test setup.

Negative matrix: absent/false policy; missing ACK, retirement, outbox or pointer;
wrong current pointer/authority; damaged immutable snapshot/config; accounting
incident, job overrun, expired deadline, export marker, existing successor.
Assert no projection/journal write and no monetary change. Include a two-job
case in which a corrupt candidate does not block an eligible peer.

Kill exams: fail the journal atomic write before publication and retry; simulate
lost reply after publication and retry; use existing collect publication/
retirement repair helpers to show eligibility only after all durable proofs.
An interleaving test mutates the pointer after cheap selection but before plan:
the in-lock check must refuse. Patch money.locked with a contextmanager depth counter that asserts depth <= 1
BEFORE calling the original lock. Exercise both direct plan with published_operation
and plan_collections, asserting maximum depth exactly one; no assumed suite timeout.

Only touched tests run during implementation. Merge parallel-tests 281bf20 (uncached parallel runner with exit-based grading and interruptible slot waits) before the handback full suite. Use a
function-local import of _planning_source in service.plan. Patch monotonic only
around tick calls so the global time module is not changed during setup.

Final exam is one full
`uv run --with numpy --with scipy python -B tests/run.py` at the handback code,
without lockf (parent retired the suite lock). Commit unique log and structured
record. Then fresh diff review; at most two design and two diff rounds.

## Cost, timing, payoff and limits

Offline cost $0; production planning makes no paid call. One increment, roughly
one implementation/review cycle. Payoff: opted-in exhausted collections reach
the durable diagnosis queue automatically after the same collection and money
proofs used by ordinary resumes.

Risk: legacy local plan can still write metadata without holder ACK checks; it
cannot grant work. Production always supplies published_operation, and tests
assert that wiring. Historical queue requests need revalidation by the next
increment's reserve path. Imported-only and already-consumed sources are outside
this caller's scope, not silently granted exceptions.

No Murphy row closes: row 9 requires the full production queue-to-diagnosis
cycle and retained live qualification. No row or pilot admission work is borrowed
from B. This removes the missing production caller, and adds no parallel path.

