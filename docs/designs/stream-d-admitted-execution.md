# Stream D item 7: execute one admitted writer and stress round

## Objective and impact

A case judged close to passing should get exactly one more writer round and its
stress review. Restarting that work must continue it without selecting another
case, writing twice, or paying to repeat a finished review. This increment makes
already admitted work executable through the ordinary launcher. It stops before
final gates and outcome comparison, which the next increment supplies.

Cost: $0 inference; tests are offline. Size: one large implementation, full-suite
and review cycle. The existing diagnosis activation flag stays false. Item 8
qualification is still required before live activation. No section 4 change.

## Exact routing seam

Extend apply(c, parent, manifest, result, *, resume=False). Only replay calls it
with resume=True; invoke and other callers retain the unconditional stop. After
existing verification and state publication, close_to_passing with active history
must match row.exhaustion_id == manifest.exhaustion_id, or refuse with
diagnosis_input_invalid. Recover writer_receipt as today. If resume=True and
DIAGNOSIS_ENABLED is True, return the integer extension_id; otherwise stop as
today. replay propagates the integer; _dispatch immediately returns it, releasing
the reconciliation lock. No model invocation occurs in this routing step.

main initializes extension_id=None, captures dispatch's return, and accepts only
an integer (False still means no diagnosis). When present, refuse dry_run,
rehearse_only, audit_fairness, late_gate_rehearsal, statement_only, skip_build,
audit_source or salvaged_from with extension_execution_mode_invalid before any
setup/model call. Skip raised_limits and restore_gate_crash for this route: they
are ordinary repair policies. The normal Compose, pick_models and driver checks
still run. Replace build(c) with write_and_attack(c, prev, extension_id=identity)
then raise BudgetError('extension_comparison_pending') unconditionally on return.
No validate_and_repair, audit branch or successful candidate seal is reached.

write_and_attack gains optional keyword-only extension_id=None. With an identity,
require modern authenticated job authority and exact active history identity.
Call writer_receipt again, then read the current attack receipt. Strip failed_gate
and failed_detail from a copy of prev: the admitted writer intent already carries
input_problems. Guard the entire existing selection/prototype block with
extension_id is None, including the complete calculation and statement admission
updates. For admitted work set complete=False only for the later skip_writer
heuristic; the verified receipt determines actual writer recovery. Missing or
invalid case files cannot call prototype, statement_precheck or reselect_candidate.

## One round, retained intent and recovery

The admitted intent must have integer round_limit == row.round. Enforce this in
retain_writer and writer_receipt; no production intent exists yet, so no migration
or allowance repair. Update authored fixture intents accordingly. Same-round
stress receipts must also have exact round and round_limit matching active history.
The parser and loop ceiling use the history round independently of args.rounds;
never mutate args.rounds. Unknown actors/phases or missing receipts refuse.

Pending admitted writer replay copies resume_unit rather than merging generated
round_limit/release fields over it. Only mutable fields already permitted by
extensions._WRITER_MUTABLE may change. This preservation change is limited to
admitted writers. Ordinary pending-writer merging stays unchanged. Whenever the
shared modern writer validation path updates binding, update binding_sha256 in
the same atomic receipt publication; this consistency fix covers ordinary writers
also. Completed output is validated without another writer call. Validated failed
output ends the round. No path permits round+1 or a final repair.

Same-round stress follows the existing category receipt/report validation and
unfinished-work machinery, with prev's old failed_gate removed. None from
writer_receipt does not grant a pass. Existing writer/stress budget checks and
invocation reservations remain in force. Early G1/early_checks validation remains;
early_review (G8/G9) is skipped for admitted execution at every call site.
loop_freshness remains allowed: public-match confirmation is necessary before
stress can be considered complete, and uses existing durable freshness machinery.

## Finished-round checkpoint and no reroll

A successful admitted stress round atomically marks its existing attack receipt
phase=validated, next_phase=extension_comparison after loop_freshness and unfinished
diagnostic checks. Then set stress_review completed and return. The receipt marker,
not the separately published card, is the durable completion signal. Preserve the
normal report authentication fields. This uses an existing phase field, not a new
file or schema. A failed round uses the existing exhausted=True and stop_reason
publication. On re-entry, after history/receipt identity validation but before
freshness, early checks, stress or writer calls, next_phase=extension_comparison
or exhausted=True stops with extension_comparison_pending or the retained
stress_review_unresolved:rounds_exhausted or budget_exhausted label respectively. These markers authorize only
a stop, never a pass or future gate reuse. Changed/malformed terminal evidence
refuses rather than reruns. No elapsed time or code drift can reopen a finished
round here. Outcome evidence qualification remains the next increment.

A kill before terminal publication may resume validation/freshness under existing
batch authority. A kill after publication cannot repeat paid work, even if the
card lags. Pending provider waits, transport failures and pauses retain their
ordinary labels (provider_wait, infrastructure_exhausted or runner_error:<type>,
paused); never relabel them as scientific failure. Money refusal stays the original
BudgetError. No new money authority, model call allowance or spend ledger.

## Deletions and risks

Remove the unconditional stopped return for qualified admitted replay, the ordinary
round clamp for it, and overwriting its immutable writer intent on replay. Reuse
the existing loop rather than duplicate writer/stress machinery. Main risks are
public labels reaching execution, an extra writer, skipping pending stress after
a gate failure, and repeating completed work. The checks below target each.

## Tests, records and Murphy rows

Use saved practice-case files and the collected 5813be ledger from existing tests;
run real admission, intent/history publication and checkpoint routing. Model
answers, job/release controls and gate results are authored substitutes, not live
qualification. Extend dispatch/admission tests and add execution cases as needed.
Test enabled/disabled replay, mismatch between decision and row, corrupted decision,
missing/stale authority, and refusal of each nonordinary launcher mode.

Test pending round above ordinary cap, missing case files with prototype/reselection
forbidden, completed/validated writer with zero reruns, immutable fields across
interruption, binding/hash agreement, invalid round_limit, and pending stress from
a failed-gate origin. Test writer validation failure ends the round without stress.
Test two resumes after success and two after exhaustion, with zero model, freshness
or gate calls and identical stop labels, including a lagging scorecard after the
terminal receipt write. Exercise provider wait and infrastructure interruption
through the real admission/receipt machinery. Main success must stop before build,
gate repair and candidate sealing. Ordinary recovery suites remain unchanged.

Run uv run --with numpy --with scipy python -B tests/run.py to a unique log and
commit docs/reviews/stream-d-admitted-execution-suite-1.md with its path and result.
Retain every design/diff review verbatim; fresh review must verify blocker fixes.
Supports Murphy row 9, closes none. Remaining checklist: full gate/outcome package,
all diagnosis outcome execution, qualified legacy deletion, then item 8 integrated
and live qualification. Review-1 findings are accepted, not rejected.


## Review 2 implementation clarifications

main passes its original prev_card checkpoint to write_and_attack. For admitted
work skip_writer=False without evaluating G1. The terminal receipt check is at
function entry immediately after active history and writer_receipt validation,
before the old selection block and before any heuristic. All three success sites
(pre-loop retained stress, freshness-cleared recovery, and in-loop stress) publish
next_phase=extension_comparison. The card label alone never proves execution.
The budget_exhausted terminal marker is defensive; ordinary modern money refusal
propagates without marking exhaustion. Target tests are
 tests/factory/test_stream_d_dispatch.py, tests/factory/test_stream_d_admission.py,
and tests/factory/test_stream_d_execution.py.

| Stop class | Replay policy |
| --- | --- |
| interrupted_review, missing_or_malformed_report | Existing modern stress retries are intended, bounded by batch money/deadline; no additional writer. |
| unchanged_repair, writer_output_changed, case_changed_during_review, invalid_recovery_receipt | Evidence refusal; never turn the refusal into a new writer round. |
| unfinished_validation, unfinished_diagnostic, stress_validation_exhausted | Existing category/freshness machinery decides resumable infrastructure work; cannot authorize a pass or extra writer. |
| freshness_public_match | Preserve G2 failure evidence; the next package/outcome increment owns its final disposition. |
| freshness_unresolved | Existing retained confirmation and retry rules apply under batch authority. |

Existing ordinary freshness/category suites cover these semantics unchanged;
new execution tests check retry admission cannot cross the one-writer ceiling.


## Diff-review clarification: freshness recovery and audit setup

This increment preserves binding-keyed freshness-verdict.json recovery. It does
not preserve the secondary scorecard-only loop_freshness.verdict_path through
apply, because that key is not in CARRY. A kill after reviewer completion but
before the binding receipt write can therefore cost one extra reviewer call,
charged under the same batch bound. The next full-package increment must carry
that fallback as part of freshness integration. This is a narrower recovery
guarantee, not permission to reroll a completed admitted round.

Audit prepare may copy an audit workspace before dispatch refuses the mode; the
refusal precedes Compose, model selection and model work, not that earlier local
copy. The required provider-wait and infrastructure-interruption loop tests are
now explicit in test_stream_d_execution.py. The exception-type assertion for
InfrastructureExhausted checks the exact type main maps to infrastructure_exhausted.
