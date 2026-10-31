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

## Review 2 corrections (binding; supersede conflicting prose above)

### Exact identity and owner joins (B1, M3)

Receipt reservation elements have exactly lease_id, invocation_id, operation_id,
call_name, parent_call_name (null when absent). Each must byte-equal the named
frozen ledger row's same fields, using row.get('parent_call_name') for old rows.
The map key must equal row.lease_id. Scope case equals c.case_id; ledger path must
be c.ledger; stage/hash are captured by the code scope before the first call and
never taken from a model. Ledger row identity is NOT a money-owner certificate.
State settled is required for classification, not for retaining a failure's
identity: an estimated operation is eligible but its amount remains pending.

Add money_owner to each failure/replay receipt, equal to a deep copy of
job_authority.for_case's validated current c.job_money dictionary (the exact
nine-field channel). Do not infer it from a reservation. Retain the existing
batch_id/job_id/source_generation as repeated fields and require equality to
money_owner.batch/job/source_generation; require money_owner.case == receipt.case.
The producer obtains it only from current RAM-authorized for_case, never a card.

Freeze job-money.json and job-money-history.json with diagnosis input in addition
to the failure/replay directories. _write_input_tree's names tuple names all four
explicitly. Freeze only after ordinary verified install/authentication and
reconciliation as today. For eligible(evidence_root,case), verify each receipt's
money_owner equals either frozen work/job-money.json or a transition.old/new
in frozen work/job-money-history.json. The latter is the exact authenticated
transition history already validated by job_config.install, not a new source of
money authority. Require job_authority.read(value,value) shape validation and
same case for every candidate, and receipt release equality to the corresponding
current/frozen release when current; historical receipt releases remain private
producer evidence authenticated by the encrypted checkpoint, not fix authority.
No new transition-chain implementation. A foreign dictionary or reservation
mismatch refuses diagnosis input; matching an old owner grants no current spend.
Existing inputs with no producer records need no newly frozen money files.

resume_scope calls diagnosis._resume_bindings(c) for the current chain; it does
not duplicate that helper's transition rules. An attribution link requires the
last durable factory-bug-resumes entry, matching its full case/batch/job/reservation/
source/release tuple against an element of that chain. Its held finding and
held release must authenticate via _read_factory_bug_finding using the old bound
owner. No history entry means no replay link. A same-batch held marker cannot
acquire one. The caller need not have executed resume_factory_bug in this process:
a later same-owner checkpoint can continue the durable admission, but the exact
on-disk entry and chain proof are mandatory. Copy resume_id/replay_of from those
proofs. No attributes supplied by a caller or model substitute for them.

### Immutable input and finding compatibility (B2, M5)

Remove the exact eligible_operation_ids != [] / failure_receipts != [] guard in
_read_factory_bug_finding. Recompute both from eligible(evidence_root,case) and
require exact equality with the finding. evidence_root is always the retained
finding's inputs directory: read only work/factory-failures there, using
_input_bytes no-follow regular reads and existing manifest/hash validation.
Never consult mutable c.work/factory-failures for a completed finding. failure_receipts
is a sorted list of exactly {path,sha256}, paths relative to inputs. Include only
records contributing validated operations. Absent/empty directories or valid
zero-reservation records yield []/[] and preserve old empty findings byte-for-byte.
Malformed nonempty records refuse, never manufacture eligibility. No historical
record may gain operations on replay; a preexisting empty finding with newly
nonempty valid input proof refuses differing evidence instead of being upgraded.
The fresh producer name has never shipped; no historical attribution is guessed.

### Three durable phases and settlement order (M1)

1. Hold: write history then immutable finding; classify settled eligible operations
   with both resume fields null; publish completed held card last.
2. B resume: after its ordinary input/chain validation, append the admission to
   factory-bug-resumes.json durably. This existing append is the counter commit
   point. Never clear the held card before attribution succeeds.
3. Inside resume_factory_bug, immediately after the append-or-reuse block and
   before constructing admitted_card, prepare model_runtime dispatch and take its
   lock; assert no active_model_calls, run budget.reconcile_reservations, then
   classify(c,finding,admission). This is quiescent because archive_pilot_state has
   already joined old work. No new lease or model call. In one reclassification
   ledger transaction, add newly settled eligible operations and replace a null
   pair with the admission UUID/digest. Existing equal pair is idempotent; different
   non-null pair is waste_attribution_mismatch. Both-null may legitimately lag a
   committed history after a crash: replay performs phase 3 again using that same
   admission. Mixed-null refuses. Only then clear held/infrastructure state using
   B's existing atomic scorecard write and return True to dispatch's ordinary path.

If any selected operation remains estimated/pending, classify may publish the
settled subset and admitted pair but raises money_wait before card clearing. No
new resume debit on retry. Filesystem failure keeps B's factory_bug_resume_io_wait
handling; a semantic attribution mismatch must preserve held markers and raise
its specific BudgetError rather than be converted to a scored result. Add tests
at all three durability boundaries, including history committed / ledger null and
ledger admitted / held scorecard lagging. No claim that resume runs outside
_dispatch: B's hook is inside _dispatch before its ordinary reconciliation.

### Ledger update predicate (M2, M4)

V2 immutable identity is exactly schema_version, kind, id, finding_id,
diagnosis_sha256. Reclassifier compares these fields exactly. operation_ids may
only be a superset; event_ids must equal the current settled reservation union
for that superset, with all rows settled and estimated_gap_usd == 0. Neither
unknown nor estimated rows enter a waste record. classify recomputes eligibility
from immutable failed proof and validates each additional replay proof against
the durable resume link before supplying additions. It also rechecks ledger rows.
Pending selected operations remain in the immutable finding, never dropped from
its eligible set. An existing classified operation must never disappear when
another operation settles. Other waste records may share no operation or event.
The accountant still refuses waste_operations_pending for a supplied unsettled
row; the classifier only submits the eligible settled subset.

_settle_leaf explicitly branches on waste.schema_version: 1 keeps existing
float-compatible historical refresh; 2 refreshes the event union and assigns
format(usd(_waste_amount(events, ids)), '.9f'), never float. Unknown versions
refuse. Preserve immutable v2 identity and paired resume fields. All mutation is
inside the existing ledger transaction and validates aggregate case_spending;
no total increase/decrease comes from reclassification. Actual late provider
charges can increase total normally, but only their ordinary/waste allocation
changes here. Add zero-price, sub-nanodollar and late-growth tests to shared ledger
coverage controls, not a separate rounding implementation.

### Thread and failure scope clarification (N1–N3)

InfrastructureExhausted is an InvalidInfra subclass and qualifies when it escapes
an actual attempt scope. Gate retry exhaustion raised before invoking check has
no new scope and no duplicate receipt. Stress scope wraps only stress_categories;
if that function does not raise InvalidInfra for a path, no cost qualifies there.
Do not turn incomplete report/CLI exceptions into InvalidInfra just to attribute
cost. The producer is causal evidence, not a new validity classifier.

Owner HTTP-thread calls must share the tester's current attempt. At construction
of the model-backed owner responder, capture a context copy and run each request's
model invocation under its own copied context. Do not run one Context concurrently.
The shared attempt object is locked, so tester and owner lease bindings accumulate
once and parent_call_name remains part of the receipt join. This extends the
explicit context propagation beyond G10 submit; it does not change owner pricing,
model selection, gates or exam policy. Standalone exam responders without an
active factory attempt remain unaffected. Test two concurrent tester/owner pairs
and unrelated foreground calls with distinct operations and expected sets.

## Review 5 corrections (binding; supersede conflicting prose above)

### One proof and immutable findings (M1)

An InvalidInfra on a replay-linked attempt publishes only its schema-2 replay
receipt, never a schema-1 failure record for that attempt. Its reservations grow
the original finding's v2 waste record keyed by finding_id, never the immutable
finding itself. Scope-exit classification finishes before any subsequent hold's
persist_factory_bug call. That later hold legitimately has an empty eligible set
for the replay attempt; it cannot claim those operations again. Test replay →
InvalidInfra → exactly one proof, one waste record, no overlap, empty second
finding, unchanged total spending and no immutable finding rewrite.

### Never-final usage is an explicit held terminal (M2)

Choose the conservative held terminal, not synthetic final usage. Reconciliation
of a missing receipt does not make an estimate final and must not be described as
a future automatic recovery guarantee. After B's append-or-reuse admission,
classify settled operations as specified, then raise money_wait once for that
dispatch if any selected operation remains non-final. Preserve factory_bug_held,
the immutable finding and durable admission; do not clear the card or start paid
work. The dispatcher returns its ordinary checkpoint refusal and does not loop
internally. B's scheduler must not resubmit the same unchanged wait automatically:
the checkpoint remains held until a final receipt or an explicit operator/new-batch
action changes the inputs. A new batch alone does not finalize usage or bypass
the pending-proof check. This is an open lifecycle limitation, not row closure or
a claim to complete automatic recovery. The existing open attribution row remains
open until the integrated exam also covers that terminal.

Test a permanently absent receipt with repeated reconciliation: one money_wait
per explicit dispatch, no automatic retry loop, one durable admission/resume debit,
no new scientific calls, held markers unchanged, no unsettled waste operations.
A subsequent final receipt may allow the same admission to complete normally.

### Owner-call drain and active-call guard (M3)

For factory attempt scopes only, owner_server tracks admitted request threads
under a lock. On scope teardown, first stop accepting new requests and set its
existing cancellation event; then wait for admitted requests to finish, using one
30-second monotonic deadline for the whole drain. Register a request before its
thread starts and remove it in finally. Drain must cover both normal and exception
exits. Existing standalone exam behavior remains unchanged.

A successful drain precedes freezing any attempt proof. If the deadline expires,
mark the attempt unpublishable permanently and raise InvalidInfra for incomplete
owner cleanup. Publish neither schema-1 nor schema-2 partial proof. Late
reservations cannot enter another attempt: request context retains the original
closed attempt, which refuses additions without altering any frozen record.
They remain ordinary unless a later independent complete proof establishes
eligibility; never fabricate such a proof from a before/after ledger diff.
This limitation is conservative and does not close the attribution row.
No active call is forcibly finalized. Existing runtime cleanup/reconciliation
must handle it through its normal infrastructure path.

Replace the phase-3 bare assert with the existing explicit guard:
if active_model_calls is nonempty, raise BudgetError(
'usage_reconciliation_while_active') before reconciliation or ledger mutation.

Tests: owner invocation finishes after gate evaluation but within drain → receipt
contains it once; owner invocation exceeds drain → InvalidInfra, no partial proof,
late completion cannot mutate receipts or leak into another attempt, active-call
guard refuses reconciliation, no ordinary/waste double count. Use an injected
clock/deadline in offline controls rather than waiting 30 seconds per test.

### Concrete compatibility sites and B preconditions (N1–N3)

budget._spending's factory-bug branch must accept schema 2 under the same exact
identity, event-union and nine-decimal string validation as the reclassifier.
Unknown versions refuse. Updating _settle_leaf alone is insufficient.

B's resume_factory_bug returns True; _dispatch consumes it and returns False.
run.main then continues ordinary work because only integer extension IDs select
the extension route. Preserve this existing return contract exactly.

job_authority.read(value, value) enforces a live batch deadline, including for
historical owners. Cross-batch eligibility therefore requires all predecessor
owners used by B's _resume_bindings chain to remain within their deadlines.
An expired predecessor raises the existing retired_batch_bound refusal; it grants
neither attribution nor resume authority. Historical encrypted receipts remain
private evidence but do not override that precondition. Removing that inherited
limit requires a separate B-owned design; this producer does not duplicate or
relax B's chain validator.
