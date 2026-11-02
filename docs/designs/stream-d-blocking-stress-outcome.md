# Finish an extension when completed stress work finds a defect

## Objective and boundary

A completed stress call that finds a real defect must finish its extension as a
failure even when other checks remain unfinished. Interrupted work must never
become a case result. This removes a human stop without buying more work.

Lane 1 slice 2 of the remaining-item-7 table in
stream-d-freshness-only-writer.md. Baseline: accepted public-match 8b36a26 on
t3/stream-d-implementation, with factory-simplify e1087df merged. Parent accepted
slice 1 and owns its one quiet-host merge/land9 suite; do not rerun slice 1.
Parent merge/land9 accf0bc was inspected read-only: its package stress predicate
is unchanged; its package differences are the lane-2 unchanged-writer seam.
Merge latest factory-simplify before implementation/handback if it advances.

Only factory/extension_package.py::stress changes in production. No run.py,
stress_progress, evaluator, diagnosis dispatcher, money, schema, launch, retry,
activation or scientific-version mechanism change. DIAGNOSIS_ENABLED stays False.
Lane 2 retains rejected writer, freshness-only continuation, partial/legacy entry
and final integration. Factory-bug target recovery remains lane 1 slice 3.
Supports Murphy 9 and preserves row 13's completed-versus-partial evidence rule;
closes no rows and makes no live-qualification claim.

## Existing policy and the defect

stress_progress.run commits category outputs only after a successful completed
call. Its aggregate is scored when it has blocking findings, even before complete
coverage, and finish permits a completed blocker ahead of unfinished diagnostics.
Interrupted raw outputs stay partial and never enter scored aggregate findings.
stream-d.md's fixed-subcheck rule explicitly gives completed blocking findings
this precedence. extension_evaluator.stress already follows that rule.

Package stress authenticates the receipt/report and then unconditionally refuses
not-complete, unfinished_validation or attack_diagnostic_unfinished. It therefore
rejects this valid scored failure as extension_execution_pending, leaving history
open. The old draft stream-d-package-terminal-outcomes.md mentioned this policy
but is not an approved implementation spec; this document owns only this slice.

## Local change; deletion before addition

Keep Records.load/completed replay first and the existing actor, validated phase,
round/round-limit, report hash, review-attempt, binding and scientific-identity
checks. Add review_pending is False to the existing receipt refusal condition;
pending/inconsistent review state cannot authorize a score. Keep the existing
freshness clearance branch before deciding whether blocking findings remain.

After attack_report/classify and any authenticated clearance, calculate once:
findings = [item for item in result['blocking']
            if item.strip().lower() != 'review incomplete'].
This is exactly the existing writer/evaluator distinction, not a new classifier.
attack_report already moves explicit legacy 'validation unfinished:' labels to
unfinished_validation. Other case-defect prose stays blocking; do not infer an
operational failure from its wording. A model's status='scored' grants nothing.

Delete the unconditional unfinished-work refusal. Refuse
extension_execution_pending only when findings is empty AND any of these holds:
not result.complete; nonempty result.blocking (the incomplete-review sentinel);
nonempty result.unfinished_validation; attack_diagnostic_unfinished(c, round).
Set ok = not findings. The extra result.blocking condition preserves the ordinary
writer loop's refusal of 'review incomplete' alone, even if complete was asserted.

Keep BOTH downstream guards unchanged: a pass still needs
next_phase='extension_comparison'; a failure still needs receipt.exhausted=True
and stop_reason='rounds_exhausted'. Keep Records.save's _pending/InvalidInfra
check. Do not catch/translate provider, money, cancellation or InvalidInfra stops.
Do not trust or import findings from an interrupted call or partial output file.
No completed-phase-only fallback, new allowance or direct history writer.

| Authenticated remaining evidence | Result |
| --- | --- |
| Real blocking findings, exhausted validated completed call; complete False and/or unfinished validation/diagnostic claim | Existing Records.save stress failure, then normal package completion |
| No findings; complete True, blocking empty, no unfinished validation/diagnostic; next_phase correct | Existing stress pass and gate traversal |
| No findings; incomplete, sentinel-only, legacy unfinished label or unfinished diagnostic | extension_execution_pending; no outcome |
| Review pending, missing/mismatched completed marker or report hash | extension_execution_pending; no outcome |
| Scientific binding differs | Existing extension_comparison_pending |
| Malformed parsed report or missing exhaustion proof for a failure | Existing snapshot refusal; no outcome |
| Unresolved freshness, provider/money/cancel stop, InvalidInfra/explicit invalid execution detail | Existing refusal/exception; no scored outcome |

## Retention, replay and accounting

Reuse Records.save and comparison.snapshot, then extensions.complete. Detail is
the exact parsed/cleared report, retaining complete=False, unfinished_validation,
coverage and status as supplied. Never rewrite it to claim complete coverage.
Existing stress sources retain attack-state, category state/answers and partial
bytes. A diagnostic claim outside those sources is not needed to prove a failure:
the independently completed blocking finding is the score's authority, not the
claim or its unfinished status. Tests assert the claim remains unfinished.

The outcome has stress fail, frontier 0, every later stage unreached. No gate
runs; no unperformed check is a pass. Existing stress_review.status='completed'
means the scored round ended, not that every diagnostic completed. Existing
extension_incomplete finalization queues one next diagnosis. Further admission
keeps the existing current-version comparison/propose policy; do not add the
public-match route's special unconditional retirement rule to generic stress.

Completed replay uses the retained Records proof, never another writer, category,
diagnostic or gate call, and never another admission or extension ID. Existing
money/checkpoint adapters and cumulative ledger settlement stay the only paths.
Crashes after stress record or outcome-directory publication reuse those bytes.
No new receipt, snapshot, sidecar, card schema or record-valuation mechanism.

## Exams and delivery

New tests/factory/test_stream_d_blocking_stress.py. Reuse saved practice case and
5813be ledger admission from ExecutionTests/RuntimeTests without inheriting and
rerunning their test classes. Preserve the real stress_categories function before
fixture setup, restore it afterward and use the real category engine/publication
barrier, pending_call, receipts, package and snapshot/accountant paths. Author
only external CLI answers and the remote checkpoint acknowledgement, labelled as
controls; do not call these captured real stress findings.

Positive midterm: one real admitted writer changes the saved case; one category
CLI completes with a concrete authored blocker, incomplete category/subchecks
and unfinished_validation. During that completed call create the ordinary
attacker-round diagnostic claimed/status marker as unfinished. Check aggregate
status scored, complete False, real completion marker, one writer/one stress,
stress fail/all later unreached, retained category/report bytes, unfinished claim
unchanged, and budget reservations settled under B. Parameterize the complete
blocking regression and each unfinished signal without inventing a stress pass.

Negative midterm: CLI writes shaped partial blocking output then raises timeout
before completion; preserve partial bytes but leave aggregate unscored/history
open and propagate the original stop. Also cover InfrastructureExhausted,
provider/money refusal, pending review/missing or mismatched completion, malformed
report, no exhaustion proof, unresolved freshness, explicit invalid-infra result,
status=scored without actual findings, sentinel-only and legacy unfinished labels.
Existing genuine clean-pass/gate-traversal and public-match tests remain green.

Final exam: two completed replays with writer/stress/gates forbidden, no ledger or
extension-count change; kill after retained stress record and after outcome
publication/before history, then recover without model calls; lagging scorecard;
real finalize_accounting twice produces one pending diagnosis ID. No Murphy row
closure. Full suite, unique committed log/result, wait, then fresh diff review.
Every full suite uses the new shared lock exactly:
lockf -t 7000 /tmp/unbug-suite.lock uv run --with numpy --with scipy python -B tests/run.py
Single-file checks may run without the lock. Do not launch another full suite for
the already accepted public-match slice. Maximum two design and two diff rounds;
after round 2 hand back any remaining blocker in three lines.

Offline inference cost $0. Runtime is the already admitted writer/stress work,
with no extra model call or allowance. Main risk: treating partial output as a
case defect; completion/hash/pending/exhaustion negative tests guard it. Payoff:
valid failed work reaches automatic diagnosis instead of an infrastructure hold.
One small increment, estimated 2–3 hours including one serialized suite and
reviews, excluding shared-lock wait, outages and unrelated suite failures.
