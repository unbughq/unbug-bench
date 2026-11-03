# Recover the first extension entry from an interrupted recorded traversal

## Problem and bounded increment

Keep the checks a case already finished when its run was interrupted.
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
attribution. Supports Murphy 9/13, closes none. Parent approved implementation before land12 on 2026-11-03: this branch already contains the same rejected-writer work; land12 only merges it.

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

For every retained record, require the support/case mapping to cover exactly its
on-disk case copy, then compare that tree with the live tree excluding only
freshness.jsonl. G2 legitimately rewrites that derived evidence during traversal,
so stress/G1 may retain an earlier freshness file. Require the live freshness.jsonl
hash (including absence) equals the copy in the last retained record AND each
retained G2/G8/G9 record, which consume freshness during execution (G2 does not
include that file in scientific_version). Stress is not
required to match the later live freshness file: its completed report/clearance
has its own historical evidence bound in the stress record; we never re-evaluate
stress against newly appended search rows. Its other case files must match.
When stress is the only retained record, it is also the last record, so its
freshness copy MUST match live; the stress exception applies only when later
records exist.
A stop during G2 topup before G2's record is saved stays held if freshness changed:
the last retained record still has the earlier file. A change after the stop also
refuses. No repair, refresh, retrieval or model work runs in entry construction.

The scientific prefix is contiguous. Walk in runner order, preserving valid
records until the first failure or missing record. A scored fail ends the prefix;
all later stages are unreached. At a prevalidated missing record, retain only
the verified prefix and return that stage and every later one as unreached,
using the existing snapshot normalization described below.

A hole must not discard a score known to the retained evidence. Inspect the preserved checkpoint card
(c.checkpoint_card if present, otherwise the live card) and any on-disk records at
and beyond the missing stage. If any later record exists, or card.gates marks the
missing/later stage pass or fail, refuse extension_comparison_pending. These are
missing-proof cases, not an unexecuted suffix. A stale infrastructure_gate marker
or gate marked 'invalid-infra' does not claim a scientific result and may be
unreached. Only 'pass' and 'fail' labels at/after the hole refuse.
No gate_results or failed_detail text is converted into evidence. When a record
itself is present it must validate; never skip a corrupt record as a missing one.
An actual retained failure may have carried old downstream card fields; the
ordinary pipeline stops there, so only records beyond that failure are conflicts,
not old card labels. If capture failed and the last published card predates the
result, the result is unavailable and is treated as unreached. This does not claim
it passed or failed: the next round must get beyond that frontier under the existing
progress rule. Conversely, stale pass/fail card labels may conservatively hold a
new partial traversal; resolving that missing-proof case is legacy reconstruction,
not permission to drop a known score here.

## Snapshot construction without a second scoring implementation

Leave comparison.snapshot and its API unchanged. entry prevalidates the prefix
and identifies at most one missing-record boundary. Pin versions explicitly with
comparison._versions(workspace(owner, r)) after the G3 preload. If G3 has no record,
unreached later stages use the current requested worker count, with no setup.
Invoke snapshot with Records.evidence and those pinned versions. At the known
hole Records.evidence returns None; snapshot creates one pending row then leaves
the rest unreached. Require that this is the sole pending row, at exactly the
prevalidated hole, with null binding/evidence hashes; then change only its status
to unreached and call extensions.validate_snapshot again. Never normalize a
pending-shaped existing record, InvalidInfra or any other malformed evidence.
With no hole, require there are no pending rows and leave the snapshot unchanged.
No change to _pending, _save, receipts, versions or generic progress.

A missing first gate after stress produces frontier 1; a pass prefix ends at the
missing gate; a recorded failure remains fail with the ordinary bound receipt.
No later pass is fabricated and no G3 setup runs. Complete-observation entries
produce the same snapshot as before, including a legitimate G2 freshness topup.
All-pass snapshots remain subject to existing propose checks; no new admission rule.

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
2. Same at a real infrastructure-crash boundary with gate status 'invalid-infra'
   and infrastructure_gate.exhausted True; no scientific fail is invented. First-entry
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
6. An authored G2 control appends a labelled freshness row during real pipeline
   traversal; both closed and interrupted later captures produce entries. Appending
   another row after stop refuses. A G2 control that appends then raises money_wait
   before its record is saved stays held. No HTTP/model call is needed for this
   derived-evidence mutation control; existing G1/G4/G5 use real saved artifacts.
7. Exact existing-test updates:
   - test_malformed_pointer_close_and_missing_g3_hold: deleting closed.json now
     produces the same snapshot. Malformed close/pointer and a missing G3 with later
     records still assert ^extension_comparison_pending$.
   - test_infrastructure_has_no_close_marker: stress pass, frontier 1, remaining
     stages unreached instead of pending; retain the invalid-infra marker assertion.
   - test_new_pointer_prevents_old_traversal_filling_interruption: reset gates before
     each fresh traversal. G1 interruption yields frontier 1; G4 interruption yields
     stress/G1–G3 observed, frontier at G4. Old traversal roots cannot fill the hole.
     Add a separate stale-card pass/fail test that asserts the conservative hold.
   - Legacy/no-pointer, failed-stress, malformed-history and corrupted proof retain
     exact ^extension_comparison_pending$ refusals where currently mapped by entry.
     Subsequent-entry, attribution, retry and route assertions remain unchanged.

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
