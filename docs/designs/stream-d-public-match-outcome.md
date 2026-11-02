# Finish a publicly known case without another review

## Objective, scope and dependencies

When the existing independent review proves the case's bug is publicly available,
finish its admitted extension from that evidence. A checkpoint or the next
diagnosis must not buy another writer, stress test, fetch or reviewer call for
that proved result. No scoring standard, model allowance, schema, launcher or
activation change. DIAGNOSIS_ENABLED stays False. This is lane 1 slice 1 of
be567f9:docs/designs/stream-d-freshness-only-writer.md's remaining-slices table.

Baseline factory-simplify 3a50896 includes comparison 6599e95. Incoming 184e81c
(unchanged-writer outcome) is a prerequisite, merged via latest factory-simplify
before integration. Reuse its complete(evidence_root=...) and package hooks;
leave unchanged-writer predicates alone. Lane 2 keeps freshness-only continuation,
rejected writer, partial first entry and final integration. Lane 1's unfinished
blocking stress and factory-bug return slices remain separate. Supports Murphy
9/13; closes none. The old terminal-outcomes draft is not this specification.

## Observation and next-diagnosis contract (B1)

Match extension_evaluator.stress's existing policy: confirmed public match is a
scored stress FAIL with detail {confirmed_public_match:True, freshness:<info>}.
All later stages are unreached; there is no invented stress PASS or later gate
observation. stop projects the witnessed public-match reason as G2 fail on the
scorecard, as loop_freshness already does. This is a terminal observation, not
unfinished diagnostics. Do not change the separate blocking-stress policy.

Add extension_public_match.verified to subsequent_entry before comparison or
Evaluator construction. If it verifies this terminal and live full-tree identity
matches its retained outcome, refuse retired_no_progress, even after source or
scientific-version drift. A public case is conservatively retired, never made
eligible by re-scoring it. Different live case bytes refuse snapshot_changed.
The dispatcher production comparison_route=True seam already reaches entry;
keep the temporary legacy comparison_route=False behavior unchanged. Direct
propose on the terminal snapshot also refuses retired_no_progress through its
existing stress-pass requirement. Test the next real diagnosis/entry path with
Evaluator, comparison.compare, fetch, reviewer and writer forbidden.

## Capture inputs BEFORE confirmation (B3, M1–M3)

Add extension_public_match.capture(c,r,row), a contextmanager used only around
package.run's write_and_attack call. It installs/restores
c.extension_public_match_recorder. Its closure ignores calls on any context other
than the identical owning c. No ordinary run or comparison child gains a recorder.
run.loop_freshness calls that optional recorder(c,rows,report) immediately before
confirm_hits, after constructing the exact rows. No catch/decision/retry changes
inside the ordinary freshness code. This is the only new run.py hook.

The recorder writes report.with_suffix('.public-match.json') with envelope
{record:<below>,sha256:extensions.digest(record)}. It is an intent, not a score.
Record exact fields: schema_version=1, kind='public_match_request', extension_id,
writer_operation_id, round, entry_sha256, source_generation, case_sha256 (semantic),
case_tree_sha256 (full tree), receipt (whole attack-state JSON), source_sha256
(report SHA), rows (exact confirm_hits rows), versions (ordered map for every
extensions.stages()), execution (seed,slot,bench_workers,concurrent_roles,
slot_environment from comparison._execution(workspace(c,r))). It has NO card
projection, clock timestamp, new UUID or current-slot reconstruction on retry.
Hash and no-follow-check all reads. Atomic write plus directory sync.

Capture only when actor stress_tester, phase completed or validated,
review_pending False, round==round_limit==row.round, report==round-N.json, and
review_completed attempt/binding/report hash match exactly; report must parse.
Receipt.binding.case and case_id must equal current semantic case/id. The writer
operation/entry digest come from verified private history, not c.card. When these
preconditions are absent (e.g. freshness on a previous-round report before the
extension writer) record nothing; preserve the existing stop. No sidecar appears
in ordinary or isolated-comparison runs. Captured sidecars are private attacks
input on later diagnosis and stress evidence, intentionally; they grant no money.

## Exact recovery decision table (B3)

Package completion checks the current report and sidecar BEFORE writer/stress work.

| Retained state | Result |
| --- | --- |
| No request sidecar | Return False; ordinary writer/stress path owns continuation. |
| Old sidecar names a different source report, and an actual round-N-superseded-*.json has its exact source SHA | Ignore it (return False); a later recorder replaces this unscored intent for the new report. Do not delete old report/retrieval evidence. |
| Source SHA differs without that exact superseded report | Refuse extension_snapshot_changed, no paid fallback. |
| Same report but receipt/entry/case identity differs, including freshness.jsonl-only changes | Refuse extension_snapshot_changed. |
| Intact intent/receipt/case; plumbing, models, slot, seed or gate versions rolled since capture | Complete using the recorded binding/vector/execution; never compare to current attack_binding or re-review. |
| Matching completed confirmation is absent, or freshness-verdict binding is for another request | Return False; no score. Existing ordinary retry/review policy remains. |
| Matching confirmation is a valid exclusion | Return False; ordinary clearance path remains. |
| Mixed confirmed/unresolved rows and no matching complete confirmation cache | Return False; preserve freshness_public_match with history open when that stop was raised. |
| Matching confirmed cache exists but its completion marker/retrieval/body/verdict/intent is corrupt, missing or symlinked | Refuse extension_snapshot_changed; never paid fallback. |
| Matching confirmed proof is valid | Complete once and stop extension_incomplete. |

The live candidate case is c.case INCLUDING stress-appended freshness.jsonl.
Check its full tree against the intent before and after copying. An intent is
never re-created from current slot/card state if one already exists for this
same report. Retry reuses its exact bytes. Before a new recorder replaces an old
intent, apply the superseded-report rule above. No age expiry rerolls proof.

A kill after confirmation cache publication but before package completion is
recoverable: the intent predates the cache and supplies exact rows and binding.
complete reads and validates the cache directly, without calling loop_freshness
or confirm_hits. A kill before cache publication has not proved a public match;
continuation may finish the existing confirmation through its normal policy.

## One shared freshness proof validator

Factor late_recovery.cleared_stress's common validation into
freshness_proof(c, attack, report, proof) -> (snapshot,blocked). c.work and c.case
are EXPLICIT validation roots: completion supplies a copied work root and copied
candidate; replay supplies immutable retained support and outcome case. Read via
no-follow regular-file JSON/bytes under those roots. Preserve source report SHA,
semantic case hash, verdict path regex, retrieval.load/digest, review-completed
exact binding/digest, verdict hits and search_binding + confirmation_contract=2.
Use checked_freshness_verdict once on a fresh snapshot, with confirmed_hits=0.
cleared_stress keeps its existing zero-blocked/zero-confirmed condition and exact
resolved-report comparison; no ordinary clearance rule changes.

Public-match validation assembles proof from intent.rows/source/case plus the
existing freshness-verdict confirmation; require rows nonempty, confirmed_hits>0
and len(blocked)==confirmed_hits. Thus mixed unresolved rows intentionally cannot
complete this slice. Check reviewer family differs from both original builder
and attacker families in the confirmation binding. No caller/model-supplied
retrieval claim, public card or verdict file without completion suffices.

## Deterministic copy / snapshot pipeline (B2, B4)

Do NOT use Records.save or sources. Add factory/extension_public_match.py with
capture, complete(c,r,row)->bool, verified(c,r,row)->bool, stop(c,row).
Imports of package workspace happen inside helpers to avoid cycles.

complete copies live c.case into a private temporary case root. Temporary work
contains ONLY these original relative paths: attack-state.json, attacks/round-N.json,
attacks/round-N.public-match.json, freshness-verdict.json, and the referenced
g2-confirm-<digits>/verdict.json, review-completed.json and its retrieval/ tree.
Validate originals before copy and copied bytes afterward. Keep filenames rooted
identically so freshness_proof uses SimpleNamespace(work=tempwork,case=tempcase,
case_id=receipt.binding.case_id). Do not glob other confirmation directories.

Add metadata extension-terminal/<id>-public-match.json with exact fields
schema_version=1, kind='public_match', extension_id, writer_operation_id, round,
entry_sha256, case_tree_sha256, request_sha256. All are derived from the intent.
All copied files and metadata are explicit paths passed to comparison._save for
stage stress, ok=False, detail above, version=intent.versions['stress'].

Extend comparison._save with keyword-only execution=None: default remains
_execution(w); terminal passes the exact recorded execution. Validate that override
as the existing execution schema (five keys, integer seed/slot, positive integer
workers, bool concurrent_roles, slot_environment string or None). No environment
or mutable card is read to regenerate terminal evidence. _load already validates
retained execution shape and does not equate it to the new worker's slot.

A private _snapshot in the new module wraps _save: one stress fail row plus
unreached rows for remaining stages at intent.versions, frontier=0, evidence from
_save, case_sha256=digest(tree(tempcase)), source_generation=intent.source_generation.
Run extensions.validate_snapshot. It performs no evaluator/current-version call;
this is retained execution evidence under its recorded version, not a fresh test.
No generic observations mode or new snapshot fields/statuses are needed.

Call extensions.complete(c,snapshot,evidence_root=tempwork). This alone owns
case/evidence-before-history publication. Every byte is a function of retained
intent/receipt/report/retrieval/confirmation, so retry after outcome-directory
rename reconstructs the SAME snapshot/evidence despite changed slot, seed,
environment, source, or scorecard. Existing _save_case then verifies/adopts the
already-retained directory and commits history. Do not overwrite retained proof.

verified recognizes the exact metadata name under
comparison-support/stress/extension-terminal/<id>-public-match.json. If absent,
return False. If present, any invalid proof refuses extension_snapshot_changed,
never fall through to stress Records. Verify entry/outcome with _verify_case;
validate metadata identity and exact one-stress-fail/all-other-unreached shape;
comparison._load on a workspace using the immutable outcome case/evidence and
stored stress version; then freshness_proof on work root
<outcome>/evidence/comparison-support/stress (original relative names) and the
immutable <outcome>/case. Reconstruct the deterministic snapshot in temporary work
and require exact equality with row.outcome, including the evidence map. Never
consult live mutable attack/confirmation files for completed replay.

## Hook order and stopping (M4)

In completed_route, run and subsequent_entry: unchanged-writer check FIRST,
public-match verified check SECOND, existing ordinary logic THIRD. Incomplete
run tries complete(public match) before write_and_attack, then wraps that call
with capture. Catch only freshness_public_match and unchanged existing catches;
if complete succeeds stop, else re-raise the original freshness stop. A present
invalid public-match metadata marker always refuses before ordinary fallback.
No edits to diagnosis_dispatch or extensions.propose are needed.

stop uses authenticated detail, clears stale gate projections and infrastructure
markers; gates={'G2':'fail'}, failed_gate='G2', failed_detail/loop_freshness from
that detail; stress_review={'status':'completed','round':row.round,
'reason':'confirmed_public_match'}. Raise extension_incomplete. Ordinary main
accounting/checkpoint/finalization produces one next diagnosis ID; replay keeps
history/counters/total unchanged. The stress fail is exactly the evaluator's
public-match interpretation; no unperformed diagnostic is labelled pass.

## Exams, cost and delivery

New tests/factory/test_stream_d_public_match.py: saved practice/5813be ledger,
actual admission/receipts and real loop_freshness/confirm_hits/retrieval validators;
saved invalid-runs-http.json.gz body bytes. Author only HTTP and independent
same_bug response, explicitly labelled. Cover every decision-table row.
Midterm: original confirmed stop; kill after intent/before cache and after cache/
before completion; repeated completion after outcome rename/before history,
changing slot/seed/environment/card/source, exact evidence equality. Final:
completed replay twice and next diagnosis with all paid/evaluator/retrieval/gate
work forbidden, drift, corrupt/missing/symlinked bytes, excluded/mixed/incomplete
proof and other stop labels preserving history. Run existing clearance tests.
Assert one extension ID, no invented pass, stable money/counters, one next diagnosis
ID through actual finalize_accounting/main checkpoint seam. No live qualification.

Offline inference $0; runtime no additional writer/review allowance. Benefit:
proved public cases finish without a pit stop or duplicate review. Main risk is
partial reviewer output becoming a score; exact completion/retrieval and all-row
checks prevent it. One increment, estimated 3–5 h excluding outages. At most two
design/two diff review rounds; after round 2 report remaining blockers in 3 lines.
Full suite to unique committed log, wait, then fresh diff review. Before handback
merge newest factory-simplify and revalidate affected paths. No workers, paid
calls, secrets, row closure, activation or claim of all-item-7 completion.

## Round-2 implementation clarifications

Deterministic freshness detail is exactly {rows:len(intent.rows),
requested:len(dict.fromkeys(attack_report(copied_report)['freshness_review'])),
verdict_path:confirmation.verdict_path, outcome:'public_match',reason:'same_bug'}.
Use it for the receipt, failed_detail and loop_freshness. Never read the card.
Intent versions come from comparison._versions(workspace(c,r)). Terminal Workspace
has case=tempcase, work=tempwork, execution=None; execution override goes only
through _save's new keyword. Completed run checks live full-tree hash equals
row.outcome.case_sha256 before stop, as subsequent_entry does. Existing intent
for the same report is never rewritten for different rows; preserve bytes and
refuse on mismatch when capture/completion validates it.

Intent also records original c.models as models: attack.binding.models contains
only the stress chain, whereas search_binding uses the full model map. Require
confirmation.binding.models == intent.models so current model drift cannot
relabel the old reviewer family or let a stale confirmation match new inputs.
