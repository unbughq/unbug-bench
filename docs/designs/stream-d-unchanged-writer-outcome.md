# Complete an extension whose writer changed nothing

An admitted extra writer round can finish without changing the case. Today the
writer loop either stops at `stress_review_unresolved:unchanged_repair` when a
repair was requested, leaving its history active, or continues into checks when
no repair was requested. Finish that round from its already retained evidence and
let the next diagnosis retire it for no progress. No stress or gate is run to
rediscover the same result.

## Scope and decision

This is the smallest terminal-outcome slice of item 7. Subsequent-entry
reconstruction and version-drift integration were completed in
`stream-d-current-comparison.md`. Rejected writer output, public-match outcomes,
partial first entry and the post-extension factory-bug return target remain open.
The older `stream-d-package-terminal-outcomes.md` is an unimplemented draft;
none of its scientific-version or progress-rule changes belong to this slice.
No activation, allowance, attribution, security or section-4 rule changes.

An unchanged writer does not produce a new scientific score. When the whole case
tree is byte-identical to the retained entry, retain those exact observations,
including its failure, as the outcome. Do not turn unperformed work into passes,
relabel stage versions, or re-evaluate failures. A terminal boundary receipt
explains why the identical observations were retained. The proof of no progress
is byte identity, independent of any subsequent scientific-version change.

## Producer and proof

Add small helpers in `factory/extension_package.py`, not a second execution loop.
At package entry, before `write_and_attack`, inspect an active row's authenticated
`extensions.writer_receipt(c)`. Also inspect it after the existing writer loop
raises exactly `stress_review_unresolved:unchanged_repair`. Only a receipt with
actor writer, phase completed, repair_pending False, next_phase G1,
type(repair_requested) is bool (either value), round and round_limit equal to the admitted row's round,
and before_repair_sha256 == output_sha256 == r.case_hash(c) qualifies.
`writer_receipt` already authenticates the immutable request, operation and lease;
it is mandatory before accepting the tuple. A pending receipt never qualifies.
The two unchanged checks in write_and_attack (completed-writer resume and fresh
writer completion) use `repair_requested or (extension is not None and
extensions.digest(extensions.tree(c.case)) == extension['entry']['case_sha256'])`
instead of repair_requested alone (still inside the case_hash equality check). Thus a pending writer completed inside the package also
stops before G1, early checks or stress. Ordinary non-extension behavior is
unchanged. All other writer/infra/provider/money/cancel results keep their route.

Require `extensions.digest(extensions.tree(c.case)) == row['entry']['case_sha256']`
and `extensions._verify_case(c, number, 'entry', row['entry'])`. This checks
freshness.jsonl too, unlike case_hash. At package entry a qualifying hash tuple
with a different full tree falls through: repair True keeps unchanged_repair,
repair False proceeds into G1/stress as today. Only after catching
`stress_review_unresolved:unchanged_repair` with repair True does this mismatch
raise `extension_snapshot_changed`; proof/tree tampering also keeps that label.

Stage a copy of the entry evidence with `_save_evidence` in a system
TemporaryDirectory outside the live work/archive tree. Add `extension-terminal/<number>.json`, schema_version 1, with exact
keys schema_version, kind (`unchanged_writer`), extension_id, writer_operation_id,
round, entry_sha256 (`extensions.digest(row['entry'])`), case_sha256, and receipt
(the authenticated completed writer receipt), written with atomic_json for
deterministic bytes on retry. Outcome is a deep copy of entry
with current authority.source_generation and the new proof path/hash in evidence;
all stage rows, versions and frontier remain identical. Extend `extensions.complete`
with optional `evidence_root`, passed only to its existing `_save_case` call, so
staging never overwrites live gate/receipt files. Its atomic case/evidence-before-
history ordering stays unchanged. Temporary staging is removed in finally.

Both fresh completion and replay project the same terminal card: clear stale
failed_gate, failed_detail and infrastructure_gate; set gates to the retained
entry pass/fail rows (excluding stress) and gate_results to an empty dict. If the
entry frontier names a failed stage, set failed_gate to that stage and failed_detail
to {unchanged_writer: True, entry_sha256: digest(entry), retained_stage: stage};
otherwise leave failed_gate absent (an unreached frontier is 'unknown' to
diagnosis and must be accepted). Refuse `extension_snapshot_changed` if entry's
frontier equals len(stages), both before completion and when reading terminal
proof; an all-pass entry cannot justify extension_incomplete. Set stress_review to {status: not_run,
reason: unchanged_writer}. No stale unchanged_repair or later-gate field survives.
The immutable entry proof carries full diagnostics; these card fields identify it.
After completing history raise existing `extension_incomplete`; normal main and
finalize_accounting queue one new exhaustion. Do not mark the case retired until
diagnosis chooses close_to_passing or not_converging through the existing routes.

## Replay and next diagnosis

A reader selects the terminal proof only by its fixed path in outcome.evidence.
Absence means ordinary package behavior. Presence requires `_verify_case` for
entry and outcome, strict proof keys/types, row/entry binding, the qualifying
receipt tuple, and equality of entry/outcome case hash, stage rows and frontier.
It checks the receipt output hash against the retained case using r.case_hash on
a shallow context with that case path. It never calls writer_receipt after the
row is complete, uses the live mutable attack-state, or reauthorizes a lease.
Exact equalities: proof extension_id, round and writer_operation_id match the
row; receipt operation_id, extension_id and round match the row; entry_sha256
is digest(row['entry']); proof case_sha256 equals entry.case_sha256.
Malformed/missing/tampered terminal proof is `extension_snapshot_changed`.

`completed_route` uses this verifier before its ordinary stress-record requirement.
`run` checks it before stress loading, rejects a changed live full case tree, then
raises `extension_incomplete` without writer/stress/gate/budget calls. Thus history
written before card publication recovers through the same dispatch route.
`subsequent_entry` uses the verifier after its existing authority, completed
diagnosis, five-extension limit, used-exhaustion and live-tree checks, but before
current_pair or evaluator construction. A verified unchanged outcome raises
`retired_no_progress`, including after version drift. This replaces only the
attempt to compare identical cases after this explicit terminal boundary; all
nonterminal comparisons and the pending-comparison guard are unchanged.
`extensions.progress`, snapshot schema and scientific_version remain unchanged.

## Tests and delivery

Extend the existing ExecutionTests fixture (saved practice case and saved 5813be
ledger; actual admission, reservation, writer receipts and main loop). The model
transport returns success without modifying files, explicitly authored as a no-op.
Use retained entry receipts from the real snapshot/Records tests rather than
inventing passes; the unchanged producer must preserve every retained byte.
Tests cover fresh completion and restart after completed writer publication,
both repair_requested values (including a previous card without failed_gate),
two terminal replays with identical terminal card fields, history-before-card
dispatch, one diagnosis queued through
finalize_accounting, and the next completed close_to_passing diagnosis retiring
without writer_request, pending_call, snapshot, compare or evaluator construction.
Repeat the latter with current versions changed: no paid re-evaluation.

Refusal tests independently corrupt receipt identity, pending/completed shape,
before/output hash, entry evidence, terminal evidence, case files and freshness
bytes. Missing entry proof never rerolls. A kill after outcome directory rename
before history write reuses identical staged bytes on retry. Capture source
generation in the outcome once; completed replay never rebuilds it. Existing
provider/money/infra/attribution/outcome-route tests keep all assertions.

Midterm: targeted retained-artifact and routing tests. Final: full required suite
with unique committed log/record, then fresh diff review. One implementation
commit plus records is expected. Main risk is confusing writer case_hash with
full-tree identity; the freshness-only mutation test proves the distinction.
Cost is engineering/test time, the already-admitted writer call, and one new
diagnosis call under existing money bounds. Keeping the ordinary diagnosis route
also lets it select factory_bug; immediate retirement would bypass that decision.
There is no new stress/gate spend or live qualification. The payoff is removing
the active-history dead end for exact full-tree identity. A writer that changes
only freshness.jsonl keeps the existing route: repair False reaches G1/stress;
repair True is the deferred evidence stop after unchanged_repair. Supports Murphy 9/13; closes no row. Package increment 2 remains open.


## Parent-approved after round 2

The parent accepted B2's full-tree extension-only stop and package-entry
fallthrough exactly as recorded above, without round 3. Add the freshness-only /
repair False / no failed_gate regression test proving G1 and stress run with no
terminal proof or snapshot refusal. N3 is resolved by the explicit unknown-stage
projection and a diagnosis acceptance test. N4 is resolved by rejecting an
all-pass entry. Round-2 review remains BLOCK as historical evidence; this parent
decision authorizes implementation and the subsequent fresh diff review.
