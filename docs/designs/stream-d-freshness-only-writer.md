# Continue an extension writer that added freshness evidence

## Problem and scope

A writer that only added search evidence is wrongly frozen; let it go through
normal checks.

The accepted unchanged-writer slice deliberately left a narrow hold: when a
repair-requested writer changes only freshness.jsonl, case_hash is unchanged and
write_and_attack raises unchanged_repair. The package then refuses with
extension_snapshot_changed, leaving the admitted history open. Yet G2 reads that
new evidence, so the full case is scientifically different. The no-repair variant
already continues correctly. This slice makes both variants follow the same
ordinary validation/stress/gate route without another writer call.

This closes only the explicitly deferred freshness-only writer continuation.
It is not a terminal result and invents no observations. Rejected writer, confirmed
public-match and incomplete first-entry producers remain separate. No activation,
money/round limits, attribution, schema, scientific-version or section-4 changes.
No live qualification, model calls or workers are authorized by this design.

## Change and deletion

In both write_and_attack unchanged checks (completed-writer resume and fresh
completion), retain the existing case_hash equality. Replace the second half
with an explicit conditional: for an extension use only
`extensions.digest(extensions.tree(c.case)) == extension['entry']['case_sha256']`;
otherwise use repair_requested as today. Full-tree identity remains the terminal
boundary regardless of the repair flag. Missing/symlinked/tampered retained entry
proof still refuses through existing extensions.read/writer_receipt validation.
This changes no ordinary non-extension branch and never changes a writer receipt.

At package entry, complete_unchanged already returns False for a different full
tree. Delete its after_stop keyword and the mismatch refusal guarded by that flag;
both callers use the same producer. Exact full-tree identity is required on every
terminal publication, so a different tree simply returns False in both contexts.
Keep the existing propagation of unchanged_repair if the producer returns False.
That is not an expected live path under the new rule: unchanged_receipt binds
before == output == case_hash and the extension stop requires full-tree equality.
There is no new catch, retry, or result.

The replacement supersedes only the parent-approved previous slice's deferred
repair-True freshness-only evidence stop. Freshness-only output now reaches G1,
early checks and stress for both repair flags; subsequent G2 is the existing
independent freshness evaluator. Existing invalid proof/hash/operation/lease stops
are unchanged, as are truly unchanged output and its no-progress retirement.
Stage caching and failure reuse remain governed by the existing gate machinery.
This does not fix its existing reroll limitation: freshness is omitted from most
gate inputs, and gates without pass caches still run again (including model gates).
The no-repair route and edits to BUILD-NOTES.md already have that behavior. Lane 2
rejected-writer/progress work owns preventing irrelevant edits from earning lucky
progress; this slice makes no claim to solve that existing limitation.

## Tests and delivery

Use tests/factory/test_stream_d_unchanged.py's saved practice case, real G1 entry
receipts, actual extension admission and saved 5813be ledger. Author only the
writer's appended freshness row and clean stress response, clearly labelled.
Replace the explicitly superseded test
test_freshness_only_repair_keeps_evidence_stop_and_open_history with a test that
proves the writer and stress each run once, G1/early checks are reached, no terminal
proof is published and the package reaches the ordinary stress handoff. Preserve
the no-repair variants and all genuine no-op/invalid-proof tests.

Add the repair-True completed-writer checkpoint variant, proving no second writer
and one stress call. Add the retained done-writer recovery variant (pending receipt
whose final usage was retained before complete_writer): complete_writer and the
resume check execute for real, with only writer_call_done's external completion
answer authored. Append the freshness row before resuming that pending receipt.
Expect no builder-9, one attacker-9, G1 called, outcome None, no
extension-snapshots/1/outcome directory, and the test_stress_handoff stub stop.
The existing runtime
tests for ordinary unchanged_repair stay byte-for-byte unchanged and must pass.

For G2, reuse the saved HTTP/confirmation fixture and real run.g2 test from
`test_stream_d_execution.py::test_real_g2_retains_freshness_confirmation_and_response_bytes`.
After admission refresh the saved baseline rows' timestamps to now and set hit=False
so expired evidence cannot bypass confirmation. Then append one well-formed,
current-time hit row with a unique URL
(e.g. the saved fixture URL plus a distinct query) and valid pinned app_version.
Run complete_writer on the saved repair-True receipt; assert output_sha256 ==
before_repair_sha256. Then assert complete_unchanged is False, and call
records.capture(c, 'G2', lambda: run.g2(c)). The authored fetch returns the saved
HTTP body at the requested URL; the authored reviewer answer resolves that exact
new URL as excluded (same_bug False). Use the existing fixture's old rows as
non-hit baseline controls, and assert flagged_hits == 1. Assert the new URL appears
in the reviewer's supplied rows and the retained verdict
hits and the retrieval receipts/body evidence; public-search.json carries the
flagged_hits count, not URLs, so assert that count there. This test fails if G2 ignores the
new row, even if it otherwise returns pass. Only fetch/reviewer transports are
authored; G2, retrieval, confirmation and record validators execute for real.

One short implementation commit, then the exact full suite with unique committed
log/record, then fresh diff review. Midterm: both writer completion windows and
ordinary-behavior regression tests. Final: full suite and diff review. The main
risk is accidentally loosening non-extension unchanged-repair behavior; unchanged
runtime tests cover it. Benefit: an admitted, scientifically changed candidate no
longer needs a human to clear this hold. Runtime cost is its already-authorized
stress/gate work, under existing bounds, with no additional writer allowance.
Engineering estimate: small, 1–3 hours (including the explicit G2 evidence test) including one suite and reviews, excluding
provider failures or unrelated suite failures. Supports Murphy 9/13; closes none.

## Remaining item-7 slices after this change

These are single-lane estimates including design, implementation, one full suite
and reviews. They exclude item-8 live qualification/activation, provider outages,
unrelated suite failures and parent merge time; boundaries may split at review.

| Owner | Slice | Size / estimated elapsed effort |
| --- | --- | --- |
| Lane 2 | Rejected writer outcomes: G1, early gates and saved-cheat rejection; durable observations, terminal replay and progress decision | Large, 6–10 h |
| Lane 1 | Confirmed public-match terminal outcome with retained retrieval/verdict proof and replay | Medium, 3–5 h |
| Lane 1 | Scored blocking stress outcome when remaining diagnostics are unfinished; preserve scored-versus-infrastructure policy | Small, 2–3 h |
| Lane 2 | Partial/legacy first-entry reconstruction, including budget interruption before gate closure and stress exhaustion before traversal | Large, 6–10 h |
| Lane 1 | Post-extension factory-bug resume returns to the pending package/comparison target (new-stream-d-current-comparison-1) | Medium, 3–5 h |
| Lane 2 after both lanes land | All-diagnosis-outcomes integration across hold/fix/resume, progress/retire and B lifetime limits; remove temporary comparison-route compatibility seam | Medium, 4–6 h |

Total after this slice: approximately 24–39 lane-hours, now parallelized by the
parent: lane 2 owns 16–26 h and lane 1 owns 8–13 h. Final integration waits for both.
These ranges are not additive wall-clock time under the two-lane split; this is an estimate,
not a claim that any remaining checkbox is complete. Package increment 2 and All
diagnosis outcomes remain open. The other completed entry/comparison/unchanged
writer slices are not counted again.

Factory-bug spend attribution is already covered by lane 1's
stream-d-factory-bug-attribution.md; this table does not budget it again. Replacing
an ordinary unchanged-repair writer receipt is already supplied by extension
admission's retained intent/reservation path (stream-d-outcome-routes.md).
