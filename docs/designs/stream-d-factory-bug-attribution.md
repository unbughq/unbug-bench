# Factory-bug cost attribution

## Problem, objective and boundary

A factory error must not spend the case's ordinary writing allowance. Today the
held finding has no code-linked operations, so all inference remains ordinary
spend. Track this as new-stream-d-outcome-routes-1. Classify proven failed work
and its admitted replay as infrastructure waste while preserving total spend.
Use budget.reclassify_factory_bug, not a second ledger or spend allowance.

This follows stream-d-outcome-routes.md. It depends on the reviewed B carry-over
branch (9ddb70e at design time) for diagnosis.resume_factory_bug, lifetime history,
verified money transition chain and at most three resumes. Merge that branch
before implementation; resolve only the diagnosis dispatcher join by preserving
both B's resume-before-dispatch hook and D's fresh extension routing. No edit to
B's holder policy, manifest, counters or transfer service. One implementation,
full-suite and fresh-review cycle; offline $0. Midterm: concurrent attempt
attribution and unknown settlement. Final: hold, cross-batch resume, late receipts
and replay over real saved case/ledger artifacts. Activation remains disabled.

This is a proposed addendum to interfaces.md §8 and stream-d.md's held lifecycle.
Those currently require empty eligible sets and v2 records bound to a resume.
The addendum permits classification at hold, before any resume exists. No security
property or ENGINEERING §4 rule changes. Old checkpoints without producer evidence
remain ineligible: historical costs cannot be reconstructed from model prose.

## Producer: one code-owned execution attempt

Add factory/factory_waste.py with a ContextVar carrying an attempt object. An
attempt is scoped to one ordinary gate evaluation in GatePipeline.check, after
cache lookup and before self.evaluate, and includes the invalid-infra returned
classification check. CaseProblem becomes ordinary substantive failure as today.
An exception escaping the scope is eligible only if isinstance(InvalidInfra),
not BudgetError, cancellation, pause or arbitrary Exception. The existing gate
retry policy remains untouched. Each actual retry creates its own attempt UUID.
No attempt is created for cache/early reuse. Failure before calls creates no
eligible operation and no charge.

The context object holds case, stage, semantic case hash, current source binding,
operation reservation identities and a lock. It is private runtime state, never
loaded from a scorecard. ModelRuntime._call records each admitted reservation in
the current scope immediately after reserve_invocation; this covers fallback
leases and already-reserved calls idempotently. The join validates ledger path
and case identity against the scope. No ambient whole-ledger before/after diff.

G10 calibrator executor submissions explicitly propagate copy_context().run,
one new copied context per submission. G10's overlapping gate itself opens its
own scope in its own thread, so unrelated foreground gate charges cannot enter
it. G5 worker threads make no model calls; they need no cost propagation.
Nested scope defaults to innermost attempt. No thread-local c attributes or
process-global active gate. Include a concurrent G10/foreground test.

Stress uses the same scope around stress_categories in run.py, with stage stress
and current semantic hash. Only an escaping InvalidInfra produces failure proof.
Incomplete model output, provider/money waits and scientific blocking findings
never become eligible. Writer work outside an invalid-infra gate/stress attempt
has no attribution; do not infer it from a later bug diagnosis. This is deliberate
conservative causal evidence, not a claim to repair historical unknown costs.

A completed failed attempt publishes one private immutable record under
work/factory-failures/<attempt UUID>.json, after all owned child calls have joined:
{schema_version:1, attempt_id, case, stage, case_sha256, batch_id, job_id,
source_generation, batch_release_sha256, classification:"invalid-infra",
error_type, reservations:[{lease_id, invocation_id, operation_id, call_name}]}.
Sort reservations by lease_id; no duplicate lease/operation invocation binding.
Use registry.atomic_json plus directory fsync. Empty reservations may be retained
for diagnostic evidence but grant no charge. Record no model prose as authority.
If publication fails, propagate infrastructure; do not publish a scored failure.

The receipt binds immutable reservation identity, not mutable event sums. Input
freezing already includes ledger and usage-receipts; add factory-failures to the
selected diagnosis input tree. Validate each reservation against that frozen
ledger and its receipt path at normalization, preserving missing/estimated usage
as pending cost, not a fabricated event or a scientific verdict.

## Diagnosis eligibility and immutable finding

factory_waste.eligible(evidence_root, case) reads only the frozen input tree and
returns operation IDs plus exact path/hash proof references for valid failure
records. Require strict schema, UUIDs/digests, allowed GATES/stress stage, matching
case and known reservation identities, and the record's owner matching the
reservation's bound owner. Refuse unsafe/malformed retained evidence; old inputs
without the directory return empty. Input validation remains private.

validate_result normalizes affected_operations to its sorted intersection with
this eligible set. A model may narrow, never enlarge it. Preserve original raw
answer before normalization as diagnosis_dispatch already does. The retained
finding keeps its existing schema and exact fields, but eligible_operation_ids
and failure_receipts now contain the code-derived set/proof references rather
than unconditional empty lists. _read_factory_bug_finding recomputes those values
from the immutable input tree and revalidates the normalized diagnosis. Old empty
findings remain byte-equivalent when their old frozen inputs lack this producer.
No change to public factory_bug's content-free shape.

persist_factory_bug publishes history and immutable finding first, then invokes
factory_waste.classify(c, finding, resume=None), then completed card. If writing
waste fails, replay uses the same finding and retries accounting before card
completion; no second diagnosis. restore_factory_bug does the same idempotently.
No eligible selected operations means no record and the normal hold.

## Existing ledger, v2 hold and late growth

Implement the previously proposed v2 waste schema in budget's shared valuation
and reclassifier. Exact fields remain {schema_version:2, kind:"factory_bug", id,
finding_id, diagnosis_sha256, resume_id, resume_binding_sha256, operation_ids,
event_ids, infrastructure_waste_usd}. At hold, resume_id and resume_binding_sha256
are both null. At a validated B admission they both become the real UUID/hash.
Mixed null/non-null refuses. V1 remains decode-only historical evidence. V2
amounts are exact nine-decimal strings. IDs are sorted unique; id is
factory-bug:<finding_id>. Empty operation sets emit no record; a nonempty set of
zero-cost settled operations permits empty event_ids and zero amount.

Classify only operations whose reservations all have state settled and zero
estimated gap. Their event IDs must equal the exact union of settled reservation
events; amounts use budget.event_charge and usd, never public rounded totals.
Unsettled/estimated selected operations remain pending attribution, retained in
the immutable finding; hold still completes without pretending their amount is
known. The classify helper retries on hold replay after reconciliation.

A v2 update may only grow operation_ids with independently validated eligible
operations or code-linked resumed attempts, grow event_ids consistently with
settled reservations, and change the paired resume fields from null to their
single admitted value. It never drops or rewrites attribution identity. Reject
overlap with another waste record. reclassify_factory_bug validates the complete
result through case_spending in the same ledger transaction. Preserve totals
before/after; a classification only moves amount from ordinary breakdown to
waste. Extend _settle_leaf to preserve string v2 amounts while refreshing events
for already-classified operations. Late receipt growth must not append another
record or create cumulative money headroom. V1 behavior stays unchanged.

Before B clears a held card on resume, after its durable history admission, call
classify(c, finding, admission). It binds the paired resume fields and refuses
money_wait if any selected operation remains estimated/unsettled. No paid work
starts while its attribution is uncertain. Admission replay is already idempotent
on finding_id, so that wait consumes no second resume. Do not move the hook before
history: the real resume UUID/hash must exist first. Same-batch holds do not admit.

## Code-linked replay work

After a validated B admission, the case can resume ordinary work. An attempt
scope may inherit a replay link only through factory_waste.resume_scope(c,stage,
case_sha256): validate latest factory-bug-resumes history and the current owner
against B's existing _resume_bindings chain; authenticate its finding/input proof;
require stage and semantic case hash equal an eligible failed attempt. Gate code
may change with the new authenticated release, but changed case bytes or another
stage do not inherit attribution. No user/model fix credential or free-form IDs.

Successful or invalid resumed attempts publish the same attempt receipt with a
separate exact replay_of list of original attempt IDs and resume_id. This uses a
second strict receipt schema (schema_version:2) in factory-replays/<attempt>.json;
all original failure fields except classification/error_type are present, plus
replay_of/resume_id and outcome:"completed"|"invalid-infra". A provider wait,
cancel or crash before completion produces no replay attribution; its cost stays
conservative until an actual bound receipt exists. Replaying a saved gate invokes
no new attempt and adds no operations. Resumed attempts remain linked across
same-owner waits through B's authenticated transition chain, not a mutable card
flag. After the scope exits and child calls join, classify adds newly settled
operations to the same finding record. Snapshot/input freezing retains these
private receipts. No whole-run or unrelated writer spend is labelled waste.

## Tests, deletions and rows

Add tests/factory/test_factory_waste.py using saved practice bytes, 5813be ledger
and actual reservation/settlement APIs. Authored failures and model results are
labelled controls. Test concurrent attempt isolation, G10 context propagation,
fallback leases, successful/scientific/provider/money/cancel non-attribution,
unsafe/tampered/foreign-owner proofs, empty historic inputs, model narrowing and
attempt-proof mutation refusing immutable finding replay. Test hold publication
kill before/after waste: same finding, one record, unchanged total and no new
model call. Verify zero-cost operations and raw Decimal sums.

Test estimated operation is held without fake charge, B admission waits before
work, late settlement permits replay with one resume debit, and further receipt
growth preserves nine-decimal strings and total. Reuse B's real bind/install
fixture for three admissions and fourth refusal; no duplicate B implementation.
Test resume receipt linkage, changed case/stage refusing attribution, successful
replay spend added exactly once, and cross-finding overlap refused. Existing v1
waste/usage coverage/reconciled decrease suites remain mandatory.

Delete the unconditional empty-set normalization and v1-only factory-bug writer
assumption. No new ledger or launch path. Supports row 9 and
new-stream-d-outcome-routes-1. Close the latter only if real saved monetary events
through the new code-linked lifecycle prove ordinary headroom and batch total;
otherwise retain open and state the missing proof. Full suite to unique committed
log, then fresh diff review; no self-verification of blocker fixes.
