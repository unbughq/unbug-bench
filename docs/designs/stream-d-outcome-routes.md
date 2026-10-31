# Stream D lane 1: diagnosis outcome routes

## Objective, cost and sequence

Connect validated diagnosis decisions to the existing hold/retire paths and the
single writer/stress/gate extension package. Code, not the diagnosis model,
enforces lifetime counts, scientific progress and B's cumulative money authority.
Payoff: an exhausted case continues without a human allowance. Risk: duplicate
writer admission, stale scientific evidence, or a lost checkpoint debit.

Offline tests cost $0 inference. Production calls reserve only against B's
existing cumulative commitment and deadline; no new money or fixed extension
allowance. This routing slice is one implementation/full-suite/fresh-review cycle.
Midterm exam: interrupted first admission and authenticated decision replay.
Final routing exam: main routing, checkpoint and full suite. Integrated item-7
exam additionally requires lane 2 entry/comparison and B carry-over, then the
factory-bug attribution design described below. No activation or §4 change.

## Baseline and ownership

Lane 2 commit 40822e7 is merged here by dc13368. It already supplies positive-ID
routing (including completed_route), extension_package.run, main's build bypass
and validate_and_repair bypass. These are dependencies, not lane-1 additions.
The merge retained both lanes' design records. Later reviewed lane-2 fixes merge
before the integrated exam. Lane 1 owns the additions below, not whole files.

Entry/comparison remains a lane-2 prerequisite: its current design explicitly
leaves it unfinished. This is a proposed consumer contract, not a unilateral
claim that lane 2 has delivered or accepted it:
`extension_package.entry(c, runner) -> snapshot`. It must produce current-version
scientific entry evidence over the current candidate. For later extensions it
must verify/reconstruct the prior entry/outcome at the same current version in
isolated roots and retain the pair through extensions.retain_comparison. Return
that selected outcome with current authenticated source_generation. No model
answer or public scorecard is a substitute for scientific proof. Incomplete
proof raises extension_comparison_pending. Lane 2 may revise this seam in its
reviewed entry design before integration; lane 1 then updates its consumer.

If entry is absent, first admission raises extension_comparison_pending before
lease/reservation/history/case mutation. Do not fabricate a snapshot or implement
a second evaluator. This slice is reviewable and testable against a substituted
package boundary, but not complete item 7. Tests say this explicitly.

B's t3/batch-carry-over owns new-batch-service-4, later-batch bind/install and
three lifetime factory-bug resume admissions. Merge its reviewed code before the
integrated hold/resume/limit exam. No new counter, resume path or fix signal here.

## Validated decision routing

apply retains its immutable-decision boundary and publishes completed diagnosis
before returning. Enabled fresh and replayed close_to_passing follow this table:

| Private history last row | Result |
| --- | --- |
| No row | Return integer 0: admission required. |
| Active, same exhaustion | Existing positive-ID path and writer_receipt validation. |
| Active, other exhaustion | diagnosis_input_invalid, no work. |
| Completed, same exhaustion | Existing completed_route validation and positive ID. |
| Completed, other exhaustion | Return 0: another admission must prove progress. |

DIAGNOSIS_ENABLED false keeps the existing stop with no admission. Positive-ID
proof validation remains lane 2's code; remove only the resume-only restriction
on returning a valid route. Propagate apply's result at replay, _dispatch's
valid-journal branch, and invoke's validated-result branch (return exits its
while loop). invoke's finally removes the pilot and restores operation/exclusions
before main performs extension setup. No writer executes under dispatch's
reconciliation lock.

main's sole new routing branch is immediately before its existing package call:
if extension_id == 0, call diagnosis_dispatch.admit_extension(c, runner, prev_card)
and replace extension_id with its strictly positive returned ID. Existing mode
refusals and Compose/model/driver setup still precede this. package.run never
receives 0. No new diagnosis_outcomes module. Existing positive-ID paths,
build/repair bypass and final seal remain as merged from lane 2.

## Shared writer request and exact fresh intent

Extract run.writer_feedback(c, previous): the existing failed_gate block verbatim
returns None when absent, otherwise the existing formatted failed_detail list
plus up to 8000 bytes from gate-details/<gate>.json when present. Both ordinary
write_and_attack and first-extension admission call it. The source is the
verified checkpoint card, never diagnosis prose. Stress findings are not used
for first admission: extensions.propose requires stress pass (stream-d.md's
first-extension rule), so a substantive failed stress snapshot retires with
retired_no_progress. Pending stress is pending, not failure.

Extract run.writer_request(c, n, round_limit, report, problems,
release_rereviews, release_review_attempts, before_repair, repair_requested).
It returns (fresh receipt, prompt), using the current ordinary construction.
Use it for ordinary modern fresh writer work and first extension admission.
Pending writer continuation retains its existing frozen receipt and reconstructs
its prompt from retained fields; do not regenerate immutable intent. Legacy
(nonmodern) construction stays unchanged. No shared helper changes loop policy.

| Field | First extension source |
| --- | --- |
| round, round_limit | proposal.round, exactly equal; no args.rounds mutation |
| binding | attack_binding(c), after entry/propose and before pending_call |
| report | round-<round>.json |
| repair_pending | True |
| release_rereviews, release_review_attempts | [] for this new logical writer; prior immutable receipt remains in history |
| actor | writer |
| before_repair_sha256 | case_hash(c), after entry/propose |
| repair_requested | bool(report or problems), with report None |
| findings_report | None; do not feed an old passed stress report as a defect |
| input_problems | writer_feedback(c, previous), or None |
| next_phase, output_sha256 | G1, None |

Ordinary helper callers pass their existing local n/round_limit/report/problems,
release histories, before_repair and repair_requested, preserving all values.
Prompt is exactly prompt('builder', run_context(c, round=n,
attack_report=str(report) if report else None, precheck_problems=problems)).
Admission-owned phase/schema/operation/lease/invocation/extension IDs are absent
from the fresh receipt; pending_call alone adds them.

## Admission, progress and crash order

admit_extension first authenticates job_authority.for_case and validates completed
close_to_passing state and private history. Active history refuses new admission.
Five entries retire before entry or any model call. It then calls entry and
extensions.propose; no_progress/regression retires, unknown/version mismatch
stays pending. Entry and propose precede writer-request capture. Call the existing
pending_call(..., extension_proposal=proposal) with complete_writer callback.
Use on_admitted=late_recovery.invalidate, after durable intent/history/receipt and
reservation. Callback and loop invalidation are idempotent already.

On positive-ID writer entry, after extensions.writer_receipt authenticates or
restores the intent, call invalidate if actor=writer and phase=pending. This
closes the history-before-callback window; invalidation occurs before any paid
writer resume. Completed writer requires no rerun and proceeds to validation.
After pending_call returns, require active row ID matches proposal and return it;
main calls package.run, which consumes completed writer and executes stress/gates.
The preexisting ordinary writer loop also invalidates before writer invocation.
Admission does not clear terminal_stop; lane 2's stress-pass path clears it.

All BudgetError/provider/infrastructure stops flow through main's accounting and
checkpoint seal. There is no direct B publisher or second ledger. A reservation
without admission may be conservatively charged, but cannot consume an extension.
No reset of counts, diagnosis origin or cumulative usage on wait/restart.

## Hold, retirement and required attribution follow-up

Factory bug persists the immutable private finding/history and completed state,
then factory_bug_held; same-batch replay invokes nothing. not_converging yields
retired_not_converging. Limit/progress refusal yields retired_extension_limit or
retired_no_progress; completed diagnoses do not requeue. B's later-batch import
owns the at-most-three counter and retired_factory_bug_limit refusal.

This slice's factory-bug scope is hold + retire only, attribution open. Existing
interfaces §8 requires empty eligible sets. Until a code-linked invalid-infra
operation producer exists, factory-bug cost incorrectly remains ordinary spend
and reduces the resumed case's ordinary headroom, even though cumulative batch
spend is preserved. Track new-stream-d-outcome-routes-1, owner D lane 1, required
next design stream-d-factory-bug-attribution.md. That producer must feed existing
budget.reclassify_factory_bug, never a second accounting path, and bind B's durable
resume record. Historical/model-supplied operation IDs cannot grant attribution.
No claim of complete item 7 or row closure until this follow-up and integration.

## Executable tests and exit criteria

Add tests/factory/test_stream_d_outcomes.py; reuse the saved practice-case bytes
and 5813be ledger harness from test_stream_d_execution/admission. Tests use real
pending_call/reservations/history and substituted CLI/package entry evidence.
They are consumer tests, not scientific qualification. Existing suites retain
proof of ordinary behavior, immutable history, progress/version comparisons and
held-state validation.

| Kill/refusal point | Restart route and assertions |
| --- | --- |
| Before reservation (provider wait or money_wait) | 0 route; no new ID, intent, callback or writer; preserve label and ledger total. |
| After reservation before admit, process death | 0 route; no ID; reconcile twice books full orphan maximum exactly once. No guessed zero refund. |
| After admit before on_admitted, process death | Positive ID; writer_receipt repairs lagging attack-state, pending entry invalidates stale gate-continuation before writer; one ID and same operation. |
| Mid-writer | Positive ID, same round/operation and immutable request; no ID increment; usage cumulative. |
| After complete_writer before package.run | Positive ID; completed writer validates with no second writer; package receives positive ID once. |

Additional tests: actual dispatch fresh/journal replay returns identically; invoke
cleanup executes before returned route; disabled activation starts nothing; all
three outcomes preserve totals and completed projection. Five entries refuse
before entry; no progress and regression retire; pending/mismatched versions do
not admit. Missing entry refuses specifically extension_comparison_pending.
Tampered current RAM job-money/source binding refuses money_wait before entry or
writer. Actual run.main with that refusal invokes existing checkpoint seal with
checkpoint=True, sets money_wait and never candidate-seals or executes a package.
Same main harness proves 0 conversion and completed writer handoff, and existing
nonordinary mode refusal still occurs before setup or new model calls.

After lane 2 and B merge, extend this test file's integrated exam to real entry /
package and B's ordinary bind/install, asserting fourth resume refuses
retired_factory_bug_limit and replay never debits twice. This integrated test is
not promised against this slice's base.

Run uv run --with numpy --with scipy python -B tests/run.py to a unique committed
log/record, wait for exit, then fresh diff review. Fresh goldfish verifies blocker
fixes; no self-dismissal. Supports rows 9/13; closes none in this consumer slice.
Deletes the fresh-decision unconditional stop and duplicate writer construction.
