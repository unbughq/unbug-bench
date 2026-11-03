# Drain authenticated diagnosis resume requests

## Objective

Automatically resume an exhausted pilot case after its collected checkpoint has
been authenticated and queued. The holder will consume the existing resume
request through its existing reservation and dispatch machinery; the resumed
worker settles and diagnoses under its existing cumulative money owner.

Baseline: lane-1 2550ccb (land18 is being merged by the parent). The preceding
increment's design and passing review are
`stream-d-collected-diagnosis-planning.md` and
`stream-d-collected-diagnosis-planning-diff-2.md`. Merge factory-simplify when
the parent says land18 has landed. No real pilot or spend is authorized here.

This increment drains **resume rows**, not replacement rows. The proposed pilot
has replacement policy disabled. To preserve the documented priority of
replacement requests without inventing their consumer, in a batch whose
authenticated replacement_policy is enabled this increment drains settlement
resumes only and leaves known-total diagnosis resumes queued. Supporting those
diagnosis resumes requires the separately reviewed replacement consumer and
priority integration. This is an explicit scope limit, not a new general
scheduler. Diagnosis opt-in and the existing holder activation both remain
required. No manifest is changed. B owns pilot admission, lifecycle limits,
cleanup and Boat settlement.

## Existing flow and change

The holder tick already runs reconcile, plan_collections, schedule_waits,
orphaned and unpublished. Add `batch_holder.drain_resumes` with action None
immediately after plan_collections and before schedule_waits. It reserves work;
it returns [] and never spawns a child itself. Existing reconcile discovers a
pending operation on the next tick, and existing key_holder spawning and
holder.dispatch perform the sole launch path. Existing provider waits keep their
own path.

`drain_resumes(policy, root, home)`:
1. Require holder.active via enabled(), authenticate money.manifest, and return
   [] immediately if its diagnosis_policy is absent or false. Malformed policy
   follows the existing manifest refusal. Never read policy from a public card.
2. Under one `money.locked`, load _operations and service._load. Copy
   `service.ordered_queue(journal)` and ops, then release the lock. Never hold
   this lock while calling reserve, which takes it again.
3. Iterate the sorted rows. Process only kind=resume. Settlement comes before
   exhaustion and FIFO applies within each; skip replacement rows. When
   replacement_policy.enabled is true, skip reason=exhaustion and still process
   reason=settlement. This prevents an unimplemented replacement dispatcher
   from being overtaken; it intentionally defers diagnosis for that configuration.
   For each row compute `operation_id(policy, row.job, row.source_generation)`.
   If it already exists in the snapshot in **any** state, skip it, including
   failed/uncertain operations; reconcile, not the queue, owns existing work.
4. Call `reserve(policy, root, home, row.job, row.source_generation,
   queued_resume=row)` outside the scan lock. Catch OSError, ValueError,
   KeyError, TypeError and AttributeError per row and continue to later rows.
   Use a separate process-local _RESUME_RETRY_AFTER dict keyed by
   (str(home.resolve()), manifest_sha256, job, source_generation). On refusal
   wait 60 seconds of time.monotonic() before retry; clear on success or when
   the operation is already present. This bounds repeated snapshot hashing;
   restart clears the delay. It never grants authority or deletes queue rows.
   A bad row cannot block later eligible rows. Existing holder-wide incidents,
   money limits and concurrency checks can of course block all applicable rows.

The queue remains immutable history with dense sequence numbers. No consumed
flag, extra ledger, second launch path, operation counter, amount or schema is
added. UUID5 operation_id over batch, job, source generation and release is the
durable replay identity. `reserve` persists authority and an operation before
reconcile/dispatch, as it already does.

## Revalidate at the money boundary

A scan snapshot is advisory. Add keyword-only `queued_resume=None` to
holder.reserve and pass it to _admit, preserving all existing calls when absent.
The value is an exact row for lookup, not an authorization flag. Inside reserve's
existing money lock, before any authority mutation, _admit:

- Load the current journal using service._load once for both existing _lineage
  validation and the queued check. For a supplied row require a dict exactly
  equal to the current journal row under
  `resume/<case>/<source_generation>`; require its kind/job/owner_job/case/
  source_generation to match the resolved requested owner. Reject a missing,
  changed or non-resume row. Require authenticated diagnosis policy enabled;
  refuse reason=exhaustion when authenticated replacement policy is enabled.
- Keep the existing batch deadline, global incidents, cumulative aggregate,
  per-job overrun, capacity, already-live-worker, source chain and same-owner
  checks. When an operation ID already exists, keep existing reserve replay:
  repair the journal, return the same operation, and grant nothing new. A racing
  duplicate never creates or dispatches a second operation.
- For a genuinely new operation, obtain (ACK, entry, card) through the existing
  _source at its existing location before money.advance_locked. This checks the
  current pointer, R2-publication outbox ACK, exact frozen generation, producing
  operation and retirement proof, money authority and immutable card. Require
  the producing operation's incident to be None. For imported sources use the
  existing batch_transfer.source branch and its proof; this increment's planner
  does not itself create imported-only queue rows.
- Refuse if the corresponding legacy-retirement marker exists or is a symlink,
  or if card.diagnosis_state is not a dict. This preserves retire_legacy's rule:
  a legacy exhaustion without a recorded diagnosis state cannot acquire a new
  diagnosis resume even if somebody forges a syntactically valid queue row.
- Recompute facts with the existing pure `service._project(card, diagnosis)`
  and require exact equality with the authenticated source entry's stored facts.
  Recompute the reason from that same card and require it to equal the queue
  reason. Extract the existing two-line reason predicate into
  `service._resume_reason(facts, unknown)`, where unknown is
  `batch_accounting.card_total(card) is None`:
  return settlement if unknown, else exhaustion, when pending_projection is
  present OR exhaustion and unknown are true; otherwise return None.
  _enqueue calls the same helper, leaving replacement derivation and queue
  semantics unchanged. No stop-label policy or model prose becomes authority.

The source validation and any money.advance_locked mutation use the **same**
lock and current immutable card. Thus tampered facts, a stale queue/pointer,
lost ACK, a failed prior owner or changed source cannot create a reservation.
The existing _post rechecks source, current authority, config, budget and
deadline again at dispatch. A queue row does not authorize model work on its
own; the normal worker retains its own job authority and diagnosis guards.

For a null-total exhausted card the existing same-revision covered settlement
rule applies. A held factory-bug card with unknown total may have an existing
settlement row: this is settlement only; the worker's existing same-batch hold
and model-work guard remain in force. The three factory-bug resumes and any
later-batch fix remain B/D's existing lifecycle, not this scanner's counter.
B's pilot lifecycle/creation limit still must land before a live pilot.

## Interruption, ordering and scope

| Situation | Result |
|---|---|
| Replayed tick, holder restart, lost reserve reply, existing pending/launched/failed operation | One deterministic operation; no second creator; existing reconcile/dispatch owns it |
| Crash after money advance, before config or reservations.json | Queue remains; later retry resumes the same persisted authority/source, writes one operation |
| Crash after reservations.json but before journal mirror | Existing reconcile/_save repairs the mirror; queue sees the same operation ID and skips |
| Missing ACK/outbox/pointer/retirement, changed card/config, source superseded | Refuse without a new authority or operation |
| Tampered facts, reason, removed/changed queue row, or legacy retirement | Refuse before advancing money |
| Capacity, per-job overrun, expired deadline, uncovered/null money or batch incident | Existing reserve fails closed; other independently eligible rows continue |
| Diagnosis policy absent/false, holder disabled, export marker | No queue-driven reservation |
| Replacement enabled | Settlement resumes drain; diagnosis resumes stay queued for replacement priority integration |

Existing pending reservations are not preempted: reconcile runs before new
queue admission. Within the new scan settlement rows are examined first and
the first eligible row takes available capacity. A blocked row does not block a
later eligible row. Queue/replay durability is the current journal + money +
reservations files, never a new cursor. Test the scan-to-reserve interleaving,
including a row removed between the two reads. Duplicate scans may race; reserve
serializes them and returns the same ID. The process-local retry map has one
entry per refused generation per holder process (small for the three-case pilot).

## Tests and evidence

Add `tests/factory/test_batch_resume_queue.py`. Reuse methods from
`test_batch_holder.HolderTests` with the `locals().update` non-test-method
pattern used by WaitSchedulingTests, not class inheritance or duplicate tests.
Use its saved card, opaque retained ciphertext and saved creation event, plus
authored batch, retirement and transport controls. Create a real pending state
by calling `diagnosis.record_exhaustion` on an authored exhausted variant,
then use the real plan_collections, diagnosis projection, collect, ACK,
retirement, reserve and reconcile. Clearly label authored inputs and controls;
no live worker, paid model, cloud call or real outcome is claimed.

- Main exam: real tick plans and drains the enabled replacement-off fixture;
  assert exact queued key, unchanged cumulative bound, same reservation_id,
  correct source and revision, one pending operation, then next tick requests
  one existing dispatch child. Feed that ID to HolderTests.preflight, which
  executes real holder.dispatch with only identity/credential labels, Boat and
  Popen as authored doubles. Assert the restored case and source, durable
  dispatch_started, exactly one creator and no second creator on replay.
- Null-total settlement: use HolderTests.accountant().unknown() and its real
  covered ledger; assert same revision, same held commitment and settlement
  priority. Two-job test queues a known exhaustion first and unknown settlement
  second, then proves the settlement reserves first with capacity one. Separate
  test proves a refused row does not block a valid later row.
- Negative matrix: off policy/holder, replacement-enabled known exhaustion,
  missing ACK/pointer/outbox/retirement, changed current generation or card,
  legacy marker, forged/replaced/removed queue row, forged facts/reason, sealed
  and retired cards, budget incident/overrun, full capacity, expired deadline,
  export. Assert no money/operation grant, no spawn, and unchanged queue bytes.
- Interruption matrix: crash at config, reservations.json, journal.json and
  lost reply; retry with original UUID5 and authority, one operation and no
  duplicate dispatch. Cover two concurrent drains and the same existing
  failed/uncertain identity. Check lock depth <=1 before taking the real lock.
- Modify PlanningTests.tick in test_batch_planning.py to patch the new
  drain_resumes scan to [] while testing the **planner in isolation**; keep its
  reserve/dispatch/spawn assertions. The new integration file exercises both
  scans together without that patch. Recheck the touched holder tick tests.
  No API double qualifies the real diagnosis projection in the main exam.

Run only touched test files while working. After integration with land18, run
one full `uv run --with numpy --with scipy python -B tests/run.py` without
lockf, commit its unique log/record, and obtain a fresh diff review. At most two
design and two diff rounds. No Murphy row is closed: row 9 and
new-stream-d-current-comparison-1 require a retained real diagnosis lifecycle
and later integration; these offline controls do not prove those rows.

## Cost, payoff and risks

Offline development: $0. A live diagnosis resume uses only the batch's already
authenticated cumulative commitment; there is no new spend allowance. One
small implementation/review cycle. Payoff: an opted-in pilot can move a
collected exhaustion into the ordinary worker route automatically once B's
pilot admission and lifecycle controls are complete.

The policy-enabled replacement limitation deliberately keeps diagnosis rows
queued until priority handling is built. Imported-only generations are outside
the preceding planner's reach. Bad evidence or permanently unknown receipts can
remain queued; 60-second retries avoid a hot loop but do not cure evidence.
Historical queue rows are never deleted and are not themselves permissions.

