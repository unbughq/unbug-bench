# Code-linked factory-bug cost attribution

## Objective, scope and dependencies

When code proves a factory failure consumed model work, move its settled cost
from ordinary case spending to infrastructure waste without changing total
spending or granting money. Resume only after B authenticates a later batch and
the selected cost is settled. The diagnosis model cannot grant cost attribution.

This replaces the prior accumulated revisions, not their review records.
Baseline is stream D consumer commit 3a99fee plus B's t3/batch-carry-over
resume_factory_bug and _resume_bindings (merge B before implementing its hook).
Lane 2 owns extension entry/comparison. This change does not implement that seam
or B's counter. At most three factory-bug resumes remains exclusively B-owned.

Owner: D lane 1. Murphy row new-stream-d-outcome-routes-1 and row 9 stay open.
No closure is promised by this design: complete causal proof is deliberately
required, and never-final usage and expired predecessor bindings can remain held.
No historical unproved spend is guessed. This advances but does not complete
ENGINEERING section 3's automatic recovery property.

Offline implementation/tests cost $0. Production work uses B's existing
cumulative money commitment; reclassification is not new spending authority.
Timeline: one design/review cycle, producer and accountant implementation, tests
and full suite, then independent diff review. Payoff: known factory failures stop
consuming ordinary case headroom. Risks: incomplete causal evidence, threaded
owner calls, immutable finding compatibility, crash ordering and late receipts.

## Attempt evidence producer

Add factory/factory_waste.py. A ContextVar holds an innermost attempt object:
attempt UUID, c.case_id, stage (GATES or stress), semantic case hash, authenticated
release, current source binding, validated money owner, reservation map and lock.
Capture all identity before calls; do not read it from a model or mutable card.
GatePipeline.check opens one scope after cache lookup around actual evaluation
and invalid-infra result checking. Scientific CaseProblem remains substantive.
Only escaping InvalidInfra (including InfrastructureExhausted) qualifies.
Retry/cache shortcuts outside actual evaluation make no new attempt.
Stress scope wraps only stress_categories, with the same rule; incomplete output,
BudgetError, provider/money wait, cancellation and arbitrary exceptions do not
become attribution evidence. Writer work outside these scopes is ordinary.

Immediately after budget.reserve_invocation succeeds in ModelRuntime._call,
record the reservation in the current scope; cover fallback leases and reuse
idempotently. The ledger must be c.ledger. Each element has exactly lease_id,
invocation_id, operation_id, call_name, parent_call_name (null when absent).
The map key equals row.lease_id, and all five fields equal the ledger row
(row.get('parent_call_name') for historical rows). No ledger before/after diff.

G10 executor submissions use one copy_context per submitted call. Owner requests
also run their model invocation in a distinct copy of the constructor's context.
Never concurrently enter one Context. Shared attempt mutations use its lock.
G5 worker threads make no model calls and need no propagation.

A completed InvalidInfra attempt with no replay link publishes exactly one
schema-1 immutable receipt at work/factory-failures/<attempt UUID>.json:
schema_version, attempt_id, case, stage, case_sha256, batch_id, job_id,
source_generation, batch_release_sha256, money_owner, classification
('invalid-infra'), error_type, reservations. money_owner is a deep copy of the
nine-field channel from job_authority.for_case, never a card. Its case/batch/job/
source must match repeated receipt fields. Sort reservation elements by lease_id.
Use registry.atomic_json plus directory fsync, owner-private permissions and
strict no-follow reads. Publication failure is infrastructure, not a case result.
Empty reservation receipts grant no cost.

An authenticated replay-linked attempt instead publishes only schema 2 under
factory-replays/<attempt UUID>.json. Same identity/reservation fields, omit
classification/error_type; add replay_of (sorted original attempt UUIDs),
resume_id and outcome ('completed' or 'invalid-infra'). An InvalidInfra replay
never also publishes schema 1. Provider wait, cancel, crash or incomplete drain
publishes neither. Evidence is causal, never a new validity classifier.

## Per-call owner drain (B4, M4-a)

Keep the existing per-calibrator-call owner_server endpoint; do not move it to
gate lifetime. Drain in owner_server.finally before that context returns.
For factory attempts only, subclass ThreadingHTTPServer to register request
threads in process_request under a lock before starting them, remove in finally,
and notify a condition. Closing sets a protected accepting flag false before
shutdown; no later process_request may start. shutdown and server thread join
finish before snapshotting the registry. Use one 30-second monotonic deadline
for shutdown and all request joins; implement shutdown in a tracked helper so
even shutdown cannot block the caller indefinitely. A deadline failure means
the attempt is permanently unpublishable. Never freeze a partial proof.
Existing standalone exam responder behavior stays unchanged.

Set the existing cancel event at closing. Request model work retains its own
copied attempt context. If it finishes before the drain deadline, its reservations
are included once. If it outlives the deadline, leave its reservations ordinary;
the scope object carries an unpublishable flag checked at publication. The
reservation hook may still accumulate into that discarded object; it does not
refuse a lease or alter pricing, and no late reservation enters another scope.
There is no new budget-level closed-attempt admission guard.

Exception precedence: an error already escaping the with body wins unchanged,
including BudgetError and CaseProblem. Drain timeout marks unpublishable and
attaches a private cleanup diagnostic, without masking that error. With no body
error, raise InvalidInfra for incomplete owner cleanup. It still produces no
proof because the attempt is unpublishable. Scope exit classification and proof
freezing occur only after every per-call owner context has drained successfully.
Test late owner completion relative to the calibrator call, not relative to gate
exit. Never forcibly settle active calls.

## Frozen eligibility and immutable findings (B1, M1-a)

_write_input_tree explicitly includes factory-failures, factory-replays,
job-money.json and job-money-history.json in its names tuple. Keep ordinary
verified install/authentication and quiescent reconciliation before freezing.
Use retained inputs only, _input_bytes no-follow regular reads, manifest hashes
and exact schema validation; never consult mutable work for finding eligibility.

eligible(evidence_root, case, finding_id) derives code-owned candidate operations
and sorted {path,sha256} proof references from valid schema-1 receipts. Match
all five reservation identity fields to frozen ledger rows. money_owner must
equal frozen work/job-money.json or old/new of the already authenticated frozen
job-money-history transition chain. Use job_authority.read(value,value), same
case and the authenticated current/frozen release when current. Historical
releases are private evidence, not fix authority. Expired predecessor owners
raise retired_batch_bound, as B's _resume_bindings already does; this design
does not relax deadlines or implement another transition validator.

Exclude operations owned by another finding's valid v2 waste record in the
frozen ledger; do not exclude this finding_id's own record. Also exclude v1 or
other waste-owned operations so records never overlap. Validate waste records
through the shared accountant validator before using their ownership.
Include proof references only for receipts contributing remaining operations.
No candidates means no new waste record and a successful hold, not an error.
This makes two sequential or same-batch holds disjoint. Prior unclassified
pending cost cannot move to another finding through a resume: phase 3 keeps
that case held until it settles. Recompute on the original finding's own frozen
tree, never on a later snapshot or live ledger, preserving its exact stored set.

validate_result changes diagnosis.py's forced affected_operations=[] to the
sorted intersection of model suggestions with eligible operations. This is
narrative only. classify always uses finding.eligible_operation_ids, independent
of model narrowing. Remove the exact []/[] guard in _read_factory_bug_finding;
recompute eligible(..., finding.finding_id) and require exact equality.
Finding schema stays unchanged. Old absent/empty producer directories return
[]/[] without requiring new money files. Malformed nonempty evidence refuses.
Existing empty finding plus nonempty recomputed proof refuses, never upgrades.
Findings and their retained input trees are immutable.

## Shared accountant and live settlement (B3, M2-a, M3-a)

Extend budget.reclassify_factory_bug, _spending and _settle_leaf; no second ledger.
V1 decoding and refresh remain historical behavior. Introduce one internal
factory-bug record validator used by both _spending and reclassify_factory_bug,
not two shape/amount implementations. Unknown versions or malformed v2 records
raise invalid_waste_attribution; v1 keeps its historical invalid/unpriced behavior.

V2 exact fields: schema_version=2, kind='factory_bug', id='factory-bug:'+finding_id,
finding_id, diagnosis_sha256, resume_id, resume_binding_sha256, operation_ids,
event_ids, infrastructure_waste_usd. UUIDs/digests validated. Paired resume fields
are both null at hold or both the actual B UUID/digest at admission.
operation_ids is nonempty sorted unique; event_ids sorted unique and may be empty
only when every related reservation is settled with zero charge. All reservations
for every included operation must be settled with estimated_gap_usd zero.
Events equal the exact union of those rows' events. Amount is an exact
nine-decimal string equal to format(usd(_waste_amount(events, ids)), '.9f').
Use budget.event_charge/Decimal, never rounded card amounts. V2 has no fix_commit
or fix_attribution_sha256 checks. Refuse cross-record operation/event overlap.

reclassify_factory_bug's existing-record branch becomes version-aware:
v1 retains its current identity equality and historical behavior; v2 compares
only schema_version, kind, id, finding_id, diagnosis_sha256 as immutable identity.
Require operation_ids superset growth, event union consistent with live rows and
a single null→actual resume-pair transition (same pair replay is idempotent).
Replacing a nonnull pair or shrinking operations raises waste_attribution_mismatch.
Replace the validated v2 record in the same ledger transaction and rerun
case_spending there. Classification preserves total; only ordinary/waste split
changes. _settle_leaf v2 refresh preserves exact string amount and paired identity;
v1 float-compatible refresh stays unchanged.

classify authenticates frozen operation identities, then looks up those exact
identities in the LIVE ledger for current settlement, rechecking owner joins.
Frozen eligibility never changes when late live usage arrives. A later explicit
dispatch reconciles live receipts and calls classify again for the same finding
and admission, so estimates can become settled without rewriting the finding.
Only the settled subset enters the record; pending selection remains in the
finding. Empty settled subset creates no record, including an empty finding.
Additional authenticated replay proofs can grow the original v2 waste record.
Replay scope-exit classification happens before a later hold persists a finding.
The later hold freezes that ledger and excludes already-owned operations.

## B resume hook and held refusal (B2, B5)

Merge B's carry-over branch first. Change resume_factory_bug(c) to
resume_factory_bug(c, r), updating its single _dispatch caller. No new resume
counter, history path or launch path. After B validates finding/owner chain and
durably appends OR reuses its admission, and before constructing admitted_card:
prepare_dispatch; acquire model_dispatch_lock; if active_model_calls is nonempty,
raise BudgetError('usage_reconciliation_while_active'). Read live ledger and
refuse ledger.active before settlement. Call r.resume_provider_wait(c) with the
unchanged held card/checkpoint and current authenticated owner; it retains its
normal identity validation and may reject a foreign wait. Then reconcile live
reservations, re-read ledger and refuse any active or remaining pending row as
usage_reconciliation_pending. The post-reconcile pending guard matches B's
ordinary path; do not reject reconcilable orphan pending rows prematurely.
Then classify(c,finding,admission). Any selected estimated row raises money_wait
after publishing the settled subset. No new lease/model work here.

Define diagnosis.FactoryBugHeldWait(BudgetError), carrying reason only. Wrap
phase-3 BudgetErrors (including invalid_provider_wait, active/pending guards,
invalid_waste_attribution and waste_attribution_mismatch) in this exception.
Preserve held card and diagnosis markers. Existing B filesystem errors after
validated admission also become FactoryBugHeldWait('factory_bug_resume_io_wait').
Other B validation/retirement semantics stay B-owned and unchanged.

run.main's BudgetError handler checks FactoryBugHeldWait FIRST, before provider
wait handling or its generic terminal assignment: c.stopped=True, status stopped,
terminal_stop factory_bug_held, factory_bug_wait_reason=error.reason; do not set
exhaustion_occurred. Keep completed factory-bug state and finding reference.
Finalize and seal checkpoint through the existing stopped path. No scored seal.
No dispatcher return is used for held refusal. Success clears wait_reason along
with B's existing held fields, writes admitted_card atomically, returns True;
_dispatch then returns False and main continues ordinary work. Existing append
is the only debit commit: all interrupted attempts reuse the same admission.
Never clear held card until phase 3 succeeds.

Never-final usage remains an explicit held terminal. Reconciliation does not
invent finality. One refusal per explicit dispatch; no internal retry loop.
batch_holder.schedule_waits already selects provider_wait only, so factory_bug_held
does not require a new scheduler policy. A final receipt may unblock the same
admission. Operator/new-batch action alone cannot bypass proof or synthesize
usage. This limitation stays open in the Murphy register.

## Authenticated replay link

resume_scope uses B's existing _resume_bindings, last durable resume entry and
_read_factory_bug_finding against its held owner/release to authenticate the
exact full case/batch/job/reservation/source/release tuple. Same-batch markers
or caller attributes grant no link. Require stage and semantic case hash equal
an eligible failed attempt; code release may differ after authenticated fix.
No history means ordinary work. Same-owner checkpoint waits may reuse the durable
link. A replay's schema-2 proof names original attempt IDs and actual resume UUID.
Classify reads immutable failed proof and authenticated replay proof, then live
settlement; it never modifies finding eligibility. No whole-run writer allowance.

## Exams, deletions and delivery

Delete the []/[] invariant, v1-only factory-bug valuation assumption and v2 identity
comparison that would prohibit growth. Retain B authority and existing checkpoint
sealing. Keep run.py changes limited to the exception handling seam and stress
scope/context integrations; keep accounting in budget, evidence in factory_waste.

Midterm: tests/factory/test_factory_waste.py uses saved practice cards, 5813be
ledger bytes and actual reserve/settle APIs; authored faults are labelled controls.
Cover concurrent G10/foreground/tester/owner isolation, fallback/reused leases,
five-field tamper/foreign-owner rejection, no-follow unsafe proof, legacy empty
findings, immutable recompute and model narrowing granting no monetary authority.

Final: two sequential holds and two same-batch holds (one replay InvalidInfra),
one replay proof, no overlapping costs, correct empty second finding; unsettled
then final live receipt, never-final held terminal and one debit; zero-cost events,
nine-decimal strings/subnanodollar boundaries, v2 growth and late refresh; kills
before/after history, ledger and scorecard writes; held refusal through actual
main preserving terminal/markers for every phase-3 BudgetError; ledger active/
remaining pending/provider-wait identity checks; per-call owner completion inside
drain and timeout with body-error precedence, no partial proof or double count.

Integrated exam after B/lane2 merge: hold, later-batch resume, stage replay, new
hold, three-resume retirement; extension limits/progress and all outcomes through
B checkpoint/money adapters. Real artifact proofs are required before any row
closure. Run full required suite to unique committed log, wait for result, then
fresh independent diff review. Never self-verify a blocking fix.

## Pre-implementation clarification (review 9 MIN-1–MIN-3)

factory_waste._attempt is ContextVar('factory_waste_attempt', default=None).
attempt(c, stage, case_sha256) is a contextmanager, yielding the private Attempt
object and resetting its ContextVar token in finally. It captures resume_scope's
validated link on entry; on exit, successful complete replay attempts and escaping
InvalidInfra attempts publish according to the rules above. record_reservation(c,
row) is called by ModelRuntime immediately after admission. current_attempt()
returns the current private object or None for owner-server integration.
Attempt.unpublishable is a locked boolean; mark_unpublishable(reason) sets it and
retains a private cleanup diagnostic. classify(c, finding, admission=None) has
the accountant behavior above. eligible(evidence_root,case,finding_id) and
resume_scope(c,stage,case_sha256) have the signatures specified above.

The exact phase-3 BudgetError wrap vocabulary is money_wait,
invalid_provider_wait, usage_reconciliation_while_active,
usage_reconciliation_pending, invalid_waste_attribution and
waste_attribution_mismatch. FactoryBugHeldWait.reason and the card's
factory_bug_wait_reason preserve that exact label. Post-admission filesystem
failure adds factory_bug_resume_io_wait. Pre-admission validation, expired-chain
retired_batch_bound and B retirement semantics stay outside this mapping.
Unexpected BudgetErrors retain their existing semantics; do not silently expand
the vocabulary.
