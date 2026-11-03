# Recover the first extension entry from an interrupted recorded traversal

## Problem and bounded increment

A case stopped by budget or infrastructure can retain useful completed checks,
but today a missing closed.json makes first-entry admission wait forever. Use the
completed records without rerunning them and preserve the interruption as an
unreached frontier. This is the smallest part of partial/legacy reconstruction:
recorded traversals with a valid pointer and completed stress proof. Legacy runs
without entry records need separate evidence adapters and stay explicitly open;
do not invent results from scorecard labels or turn missing evidence into a fail.
Final all-outcomes integration is a separate increment.

No new evaluation, model call, worker, allowance, retry or progress rule. No change
to activation, scientific versions, subsequent-entry comparison or factory-bug
attribution. Supports Murphy 9/13, closes none. Merge land12 before implementation.

## Replace the close-marker prerequisite, retain evidence validation

In extension_package.entry, keep authority/history handling and the copied context.
Require current.json's existing exact schema, UUID4, round == builder_rounds and
case_hash equality. If closed.json exists or is a symlink, validate it exactly as
today; malformed, mismatched or symlink markers refuse. Its absence alone no
longer refuses. No pointer or malformed pointer keeps the existing legacy hold.

The records are the authority for pass/fail. For each stage in extensions.stages(),
use Records.load on the copied context. Preserve the G3 pre-load before pinning
versions (worker-count dependency selection); this does not mutate live args.
Require the stress record exists, is a non-pending pass, and passes normal version,
identity, support and case validation. Missing/failed stress stays held in this
increment. No ordinary stress failure or freshness result is inferred here.

For each existing record require the retained support/case file map equals the
live full extensions.tree(case), including freshness.jsonl. Require support hashes
cover exactly that tree: compare the support mapping under support/case/ as well
as the on-disk tree. This closes the gap left by case_hash ignoring freshness.
Do not treat a changed freshness row as the same observed input. No repair,
refresh, retrieval, or model work is allowed during entry construction.

The scientific prefix is contiguous. Walk in runner order, preserving valid
records until the first failure or missing record. A scored fail ends the prefix;
all later stages are unreached. At a missing record, do not call _save with a
malformed result and do not generate a pending scientific result. Instead retain
only the verified prefix and set that stage and every later one unreached.

A hole is safe only when no score is lost. Inspect the preserved checkpoint card
(c.checkpoint_card if present, otherwise the live card) and any on-disk records at
and beyond the missing stage. If any later record exists, or card.gates marks the
missing/later stage pass or fail, refuse extension_comparison_pending. These are
missing-proof cases, not an unexecuted suffix. A stale infrastructure_gate marker
or gate marked crashed does not claim a scientific result and may be unreached.
No gate_results or failed_detail text is converted into evidence. When a record
itself is present it must validate; never skip a corrupt record as a missing one.
An actual retained failure may have carried old downstream card fields; the
ordinary pipeline stops there, so only records beyond that failure are conflicts,
not old card labels. This does not discard a completed result from this traversal.

## Snapshot construction without a second scoring implementation

Reuse comparison.snapshot and Records.evidence for the observed prefix. Add an
optional keyword-only reached_stages to comparison.snapshot, default None. When
provided it must be a prefix of extensions.stages(), and only those stages may
call evaluate/_save. Every later row is constructed as unreached by the existing
row initializer; stop traversal at the prefix boundary. The default path remains
byte-for-byte equivalent in behavior for packages/comparisons. Do not change
_pending, _save, receipt schema, versions or generic progress.

entry pre-validates/selects the prefix, then invokes snapshot with reached_stages
and the pinned versions. A missing first gate after stress produces frontier 1;
a recorded pass prefix produces its first missing gate as frontier; a recorded
failure remains fail with the ordinary bound comparison receipt. No later pass
is fabricated and no new G3 setup runs. Require no pending rows in the result.
Existing complete-observation entries still use the same path and produce the
same snapshot as before. All-pass snapshots remain valid inputs to the existing
propose checks; this slice adds no special admission rule.

Only clear/rewrite comparison-receipts and comparison-support after input proof
validation, using existing safe_directory. Never modify entry-records, live case,
attack-state, gate caches, closed.json, args, models or card on the caller. Snapshot
source_generation is the current authenticated authority, as before. Repeated
entry on the same slot yields the same receipt bytes; another slot changes execution
provenance as today (admission has its existing evidence equality checks).
Existing evidence errors retain the entry layer's extension_comparison_pending
mapping. Failed evidence is never rerun. Legacy reconstruction must replace these
remaining missing-proof holds in its separate reviewed increment.

## Tests, cost and delivery

Extend tests/factory/test_stream_d_entry.py using its real practice case, real
G1/G4/G5 and saved checkpoint transports; G2/G3/G6+ controls stay labelled as in
that file. Reuse the real ordinary pipeline observation path, not hand-generated
Records as proof. Tests:

1. Interrupt after a real recorded G4 pass but before G5 starts with BudgetError;
   closed.json absent, pointer/records durable. Entry returns stress/G1 through G4
   observed, G5 onward unreached. Forbid every evaluator, money boundary, setup,
   checkpoint/model/HTTP call during entry; assert caller fields/bytes unchanged.
2. Same at a real infrastructure-crash boundary with gate status crashed and a
   valid infrastructure marker; no scientific fail is invented. First-entry
   proposal succeeds under real authenticated close-to-passing diagnosis and
   preserves frontier, with no writer until admission's existing pending_call.
3. Completed observation entry before and after removal of closed.json yields
   exactly the same snapshot (same slot/generation); real G5 failure stays fail.
4. Missing record with a card pass/fail at that stage, a later retained record,
   malformed/mismatched/symlink close marker, bad pointer, changed round, corrupted
   record/support and freshness-only case drift each stays pending without calls.
   Dot-prefixed Records staging leftovers are ignored.
5. Reduced G3 workers 1/resume requested2 uses real scientific_version and keeps
   live args2. No G3 record/no G3 score may leave the suffix unreached after stress;
   a present malformed G3 record refuses. No implicit worker setup.
6. comparison.snapshot default behavior unchanged; reached_stages validation rejects
   a gap, wrong order or unknown stage. Prefix boundary never calls evaluate beyond
   the prefix, preserves failure stopping and keeps normal receipt validation.
7. Existing full capture, legacy/no-pointer, failed-stress and malformed-history
   tests retain their hold assertions. Only partial-capture expectations change.
   Subsequent-entry, attribution, retry and route tests remain unchanged.

Midterm is the real interrupted-prefix entry with evaluator calls forbidden.
Final is the focused exams, full locked suite and fresh diff review. Full suite:
`lockf -t 7000 /tmp/unbug-suite.lock uv run --with numpy --with scipy python -B tests/run.py`,
with an outer 7200000ms execution timeout, unique committed log and JSON record.
Max two review rounds per design/diff; round-2 blockers go to parent in three lines.
Name passing-record commits with pass or approval. Hand back after a passing diff.

Estimated 2–3h plus lock/provider queues; local file hashing only, no new model
spend. The benefit is admission after a genuinely interrupted traversal without
throwing away its completed checks. Risks are silently discarding a score and
binding a pass to changed freshness; explicit hole/card and full-tree checks plus
negative exams cover them. Remaining legacy evidence reconstruction is estimated
4–7h, then all-outcomes integration 4–6h, before the founder's three-case pilot.
