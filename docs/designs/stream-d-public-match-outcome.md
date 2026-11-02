# Confirmed public-match extension outcome

## Objective and boundary

Finish an admitted extension when independent retained evidence proves the case's
bug is publicly available. Replaying that result must read proof, not repeat the
writer, stress test, retrieval or reviewer. This is lane 1 slice 1 of the table in
be567f9:docs/designs/stream-d-freshness-only-writer.md. Diagnosis remains disabled.
No new model allowance, scoring rule, launch path, snapshot schema or activation.

Baseline: factory-simplify 3a50896 includes comparison 6599e95. Merge land8
(184e81c, unchanged-writer outcome) via newest factory-simplify before integration;
its completed_route/run hooks and extensions.complete(evidence_root=...) are the
consumer seam. Do not edit its unchanged-writer predicates. Lane 2 keeps
freshness-only continuation, rejected writer and partial/legacy entry work.
Blocking stress with unfinished diagnostics and post-extension factory-bug return
are later separate lane 1 increments. The old terminal-outcomes draft is not this
slice's authority. Supports rows 9/13; closes no Murphy rows.

## Existing decision, new private proof

run.loop_freshness already calls confirm_hits, checks runner retrieval against the
independent answer and sets G2 fail before freshness_public_match. Retain a small
sidecar immediately before that existing stop for factory jobs only, without a
new review: attacks/round-N.match.json (report.with_suffix('.match.json')). Fields:
schema_version=1, source_sha256, case_sha256 (semantic), case_tree_sha256 (full
extensions.tree digest), rows (exact rows passed to confirm_hits), verdict_path,
confirmation (the existing freshness-verdict.json object). Only publish when
confirmation.verdict_path equals c.freshness_verdict_path. Missing proof leaves
the original stop and history open; never fabricate it from a public scorecard.
No receipt, report or freshness row is rewritten. Filesystem failure remains
infrastructure. Ordinary verdict/clearance behavior stays unchanged.

Factor late_recovery.cleared_stress's retained proof checks into
freshness_proof(c, attack, report, proof): returns (snapshot, blocked). Preserve
its current retrieval load/digest, source report SHA, verdict path regex,
review-completed exact binding/digest, verdict hits, search_binding plus
confirmation_contract=2, semantic case hash and checked_freshness_verdict checks.
The shared helper does not require an exclusion: cleared_stress keeps its exact
zero blocked/zero confirmed condition and resolved-report comparison afterward.
New confirmed_match requires nonempty rows, confirmed_hits>0 and
len(blocked)==confirmed_hits, the full-tree digest and exact sidecar schema.
No date expiry rerolls a completed proof. Unsafe paths/symlinks refuse through
no-follow regular-file reads and existing retrieval validation. Same-family
review cannot create proof through confirm_hits; the terminal validator also
checks the receipt's reviewer family differs from builder and attacker families.

## Terminal producer and replay

Add factory/extension_public_match.py with complete(c,r,row)->bool,
verified(c,r,row)->bool and stop(c,row). Helpers import package Records/workspace
inside functions to avoid import cycles. Reserve terminal proof name
extension-terminal/<extension_id>-public-match.json, disjoint from unchanged
writer proof. Complete only on a verified current attack-state receipt:
actor stress_tester; phase completed or validated; review_pending false;
round == round_limit == row.round; report == round-N.json; review_completed
attempt/binding/report hash exact; scientific_binding(receipt.binding) equals
scientific_binding(r.attack_binding(c)). Require real parseable report and the
new confirmed-match proof. This rule never declares stress complete or passed:
public-match G2 evidence is sufficient regardless of unperformed stress checks.
No new writer round or stress diagnostic is permitted by this producer.

Before calling write_and_attack, package.run attempts complete when the sidecar
exists (to recover publication interrupted after confirmation). Catch only
freshness_public_match from write_and_attack and try complete again; success
calls stop; absent/incomplete proof preserves freshness_public_match with history
open. Malformed/tampered available proof refuses extension_snapshot_changed.
Other stops propagate unchanged. Existing unchanged-writer hooks retain priority.
After completion, completed_route/run first call verified; replay calls stop
without entering writer/stress/gate code, including after scientific-version
changes. Proof validity uses retained outcome versions, never re-scores them.
Comparison/admission at a later diagnosis still owns current-version policy.

Complete uses a private temporary workspace and the retained candidate case.
Copy exact attack receipt/report/match sidecar/confirmation plus the referenced
verdict, review-completed marker and retrieval tree under public-match-proof/.
Validate before copying and again on the copied bytes. No arbitrary work tree
copy. Produce G2=False via Records.save using those exact validated facts and
support; no evaluator runs. The existing case/config/version checks still apply.

Extend extension_compare.snapshot with keyword-only observations=None. Default
behavior stays byte-for-byte semantically unchanged. With a trusted observations
mapping, iterate every stage but call _save only for listed observations, using
its existing support, binding and validation logic; other stages are unreached,
not pending or pass. Malformed/pending observed evidence refuses instead of
publishing a terminal snapshot. Do not short-circuit at an unreached stress slot.
Use this mode with only G2 fail and actual confirmed-match detail. All other stages
are deliberately unreached in this conservative terminal observation (do not
infer earlier passes from the card). Same snapshot fields/statuses as today.

Retain terminal metadata through G2 support with exact fields schema_version=1,
kind=public_match, extension_id, writer_operation_id, round, entry_sha256,
case_tree_sha256 and receipt. Outcome.evidence binds every copied proof. Publish
through extensions.complete(...,evidence_root=tempwork); it already retains
immutable case/evidence before the history write. No alternate history writer.
verified checks _verify_case for entry/outcome, metadata identity, exact expected
observed-stage shape (G2 fail only), comparison._load for G2 against the retained
case and its own stored version, and revalidates confirmed_match on copied proof.
It never trusts only the marker, raw model answer or live mutable work files.
A changed/missing retained byte refuses extension_snapshot_changed. Never fall
through into paid work when a public-match marker exists but is invalid.

stop restores only witnessed result: clear stale scientific gate projections and
infrastructure markers; gates={'G2':'fail'}, failed_gate='G2', failed_detail and
loop_freshness copied from authenticated detail, stress_review.status='not_run'
with reason='confirmed_public_match'. Raise existing extension_incomplete.
Main's existing accounting/checkpoint/finalize route queues one next diagnosis;
replay keeps the completed history and diagnosis identity. No new stop label.

## Exams, cost and delivery

Use tests/factory/test_stream_d_public_match.py with saved practice/5813be ledger
and real admitted history/receipt APIs. Reuse saved invalid-runs-http.json.gz exact
body bytes, freshness_retrieval validators and real loop_freshness/confirm_hits.
Only HTTP transport and independent same_bug answer are authored controls.
Midterm: original match, stopped-after-proof restart, and immutable completed
replay twice with writer/stress/gates/fetch/reviewer functions forbidden.
Final: kill between outcome case/evidence and history, lagging card, version drift,
partial/missing completion marker, retrieval/body/verdict/case/report/receipt
mutation and symlinks; unresolved/excluded/provider/money/cancel leave history
open. Old clearance tests and ordinary freshness semantics still pass. Verify G2
fail, no invented stress/other gate pass, one extension ID, stable total/counters,
checkpoint seal and one diagnosis ID via actual finalize_accounting/main seam.

Offline inference cost $0; runtime uses already admitted batch money, no extra
calls. Main risk is accepting partial reviewer output or mislabelling unfinished
stress; exact completion/retrieval checks and conservative G2-only observations
address both. One increment, estimated 3–5 h including one suite/reviews, excluding
outages. At most two design and two diff review rounds. Full suite to a unique
committed log; wait for completion, then fresh diff review. Merge newest
factory-simplify before handback; revalidate affected paths on that merged tree.
No workers, paid calls or secrets. No Murphy row closure or all-item-7 claim.
