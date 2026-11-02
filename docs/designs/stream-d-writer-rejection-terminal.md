# Complete a rejected extension writer without repeating its checks

## Problem, scope and decision

A failed writer check now survives a restart, but the extension stays active
forever. Close that history from the actual rejection and let the next diagnosis
choose its normal outcome. If it asks for another extension, reject that request
as retired_no_progress without running stress or checks to rediscover the failure.
This covers retained G1, G15/G3/G4/G5 and saved-cheats observations only. Missing
legacy observations stay in the existing hold; reconstructing them is next.

The writer failed before stress, the first stage of the extension progress order.
There is no forward progress to compare. Do not fabricate stress failure, G6
failure or earlier gate passes. The terminal snapshot has every stage unreached,
frontier 0, and private rejection proof. Its version vector is copied from entry
as structural metadata for unreached stages, not a claim of execution at those
versions. Generic extensions.progress remains unchanged (it may report pending).
A verified terminal rejection is a separate, explicit no-progress decision in
subsequent_entry before current_pair/Evaluator, like unchanged/public-match
terminal handling. This replaces the execution-pending hold for proven writer
rejections, not the ordinary comparison rule for scored packages.

No activation, limits, attribution, schema or normal scientific-version changes.
No new paid validation, stress or writer calls. One subsequent diagnosis call is
allowed by the existing exhaustion route; preserving that route also permits a
factory_bug decision. Lane 1 owns its return target. Supports Murphy 9/13, closes
none. Successful writer edits (including irrelevant-edit rerolls) are outside
this failure-only decision and remain an explicit final integration obligation.

## One terminal module, existing evidence and publication

Add factory/extension_writer_rejection.py with complete(c,r,row), verified(c,r,row),
stop(c,row). Add its worker inventory entry using the existing inventory mechanism.
Keep Records as the only rejection evidence producer. Do not add callbacks or
run any check. Delete package.run's direct replay_writer_early hold branch and
replace it with complete/stop at that location. Keep writer_early's shared helper
for the existing capture path. No rewrite of writer receipts.

The selector examines only G1,G15,G3,G4,G5,saved-cheats record.json under this row's
package root, including symlinks as present. None returns False (normal route).
More than one, or a stress record alongside a candidate, refuses
extension_snapshot_changed. Other package gate directories alongside a candidate
also refuse: a rejected single round cannot have reached final gates.

Use a copied context (copied args/card) and Records.load(check_version=False) to
validate envelope, identity, case and support. The rejection is historical: never
compare it with current gate versions, and never restore its card projection.
G1 must be ok is False, non-pending under comparison._pending, and info.problems
a nonempty list of nonempty strings. Early records additionally use the exact
writer_observation feedback/positive-int bench_workers validation from the prior
slice; factor that validation into a Records helper shared by replay and terminal
selection rather than duplicating it. G3 retains load's effective-count check.
Require saved-cheats' sample == retained_case_cheats; it remains private feedback.

Bind the full case as well as case_hash: the selected record's support/case tree
must equal extensions.tree(c.case), including freshness.jsonl, with no missing or
extra file. Validate all paths with comparison._path/_writer_json; missing,
tampered or symlink proof and case drift refuse extension_snapshot_changed.
Check the same equality before and after staging. A raw old writer receipt or
feedback text without an observation is never evidence.

Before calling extensions.writer_receipt, read attack-state.json safely and require
actor writer, phase completed/validated and repair_pending False. This prevents
writer_receipt's previous-to-intent recovery write on a refusal path. Then call
writer_receipt to authenticate immutable intent, reservation and continuation.
Require operation_id/extension_id/round against row, round_limit == row.round,
output_sha256 == current case_hash, and a strict boolean repair_requested.
Completed window: next_phase G1, no true awaiting_stress/exhausted and no nonempty
validation_problems. Validated window: next_phase writer, validation_problems
exactly retained feedback, no true awaiting_stress; exhausted and stop_reason
must either both be absent or be True and rounds_exhausted. The absent pair is
the legitimate crash between validation publication and exhaustion publication.
Reject mixed or contradictory fields. No pending writer, money/provider/infra
interruption is turned into a terminal rejection.

Stage into a system TemporaryDirectory, never live gate work. Copy selected
record.json and exactly its support files preserving work-relative paths; these
include the full observed case. Write extension-terminal/<id>-writer-rejection.json
with atomic_json. Its exact keys are schema_version=1, kind=writer_rejection,
extension_id, writer_operation_id, round, entry_sha256, case_tree_sha256,
source_generation, stage, record_sha256, receipt. Bind entry_sha256 to digest(entry),
record_sha256 to the raw record envelope file, case_tree_sha256 to the complete
observed tree, and source_generation to job_authority.for_case(c).source_generation.

Build outcome with that generation/tree digest, copied entry stage names/versions
all status unreached and null binding/evidence hashes, frontier 0, and evidence
mapping every copied record/support/marker path to its actual hash. Call existing
validate_snapshot and extensions.complete(evidence_root=staging). Existing
_save_case copy/rename-before-history and immutable target verification provide
retry safety. If an outcome directory already exists while history is still open,
read its fixed marker first, derive the expected snapshot from its retained bytes
and stored generation, and run the same verified logic against a temporary row
with that outcome. Require its record and receipt to equal the authenticated
current rejection; then complete that exact snapshot. Never regenerate a marker
with a new source generation after rename. The rename-crash exam changes source
generation on resume and requires byte-identical retained outcome evidence.
Refuse an all-pass entry (frontier == len(stages)); do not invent
an outcome for a state admission should not create.

## Replay and routing

verified returns False only when the fixed terminal marker is absent from an
outcome's evidence. When present, verify entry and outcome via _verify_case, read
the retained marker, require its exact key set/type/row/entry bindings, and read
record/support from the outcome evidence root with a copied context whose case
is the retained outcome case. Records.load(check_version=False) then rechecks
all recorded paths/hashes and original writer operation/round. Use the same pure
receipt/feedback/full-tree rules as complete, without calling writer_receipt or
reading live ledger/attack-state. Rebuild the expected snapshot from these bytes
and the marker's stored generation; require exact equality to row.outcome.
Do not consult today's gate versions/models/slot, or rewrite comparisons/history.

Wire verified into completed_route before Records.load(stress), and into package.run
before the ordinary stress path. On replay require live full tree == outcome tree,
then stop. For an active row call complete before write_and_attack (after existing
unchanged/public terminals). After write_and_attack raises the existing
stress_review_unresolved:rounds_exhausted handoff, call complete again before
stress(); propagate all other original stops. The producer handles completed and
validated publication windows; there is no synthesized validation receipt.

stop clears gates/gate_results, failed_gate/failed_detail/infrastructure_gate and
stale early markers, then sets stress_review={status:not_run,reason:writer_rejection}.
For G1/G15/G3/G4/G5 set failed_gate to the actual rejecting gate and failed_detail
to retained info. For saved-cheats leave failed_gate absent ('unknown' in diagnosis),
and set failed_detail to private sample info/feedback; never label it G6. Preserve
builder_rounds and money/diagnosis fields. Raise extension_incomplete so main and
finalize_accounting queue one new exhaustion after the outcome is committed.

In subsequent_entry, after existing eligibility and live-tree checks, call verified
before current_pair or Evaluator and raise retired_no_progress. The production
comparison_route=True path in apply already routes a new exhaustion to this
producer before writer admission even if generic progress is pending. Keep the
non-opted-in pending guard and every existing route/attribution/limit assertion.
No diagnosis_dispatch change is planned. Tests must exercise real apply with
comparison_route=True and then real admit_extension to prove this seam.

## Exams and delivery

New tests/factory/test_stream_d_writer_rejection.py reuses the real admitted
practice/5813be ledger and G1 source-setting failure from test_stream_d_writer_g1,
and real G4/G5 and saved-cheat verdicts over invalid-runs-real.json.gz from
test_stream_d_writer_early. Writer/G15/G3 and checkpoint transports remain labelled
controls. No real workers, network or model calls.

- Fresh G1, real G5 and real saved-cheats failures complete history with all stages
  unreached and exact retained diagnostic/support bytes. No stress or G6 claim.
- Crash after observation before validation, after validation before exhaustion,
  after outcome rename before history, and after history before card: same proof,
  outcome and stop on replay. Forbid writer, G1, early checks, stress, gates, money
  and model calls; forbid writer_receipt on completed outcome replay.
- Valid record with repair_pending True, pending/wrong phase, wrong next_phase,
  wrong feedback, awaiting_stress True, mixed exhaustion markers or wrong operation
  refuses before evaluator calls and leaves attack-state bytes unchanged.
- Tampered/missing/symlink record/support/marker, full-tree freshness-only drift,
  extra observation, pass/pending-shaped observation, malformed early metadata and
  all-pass entry refuse. Legacy receipt with no record stays execution_pending.
- A real finalized G5 terminal and a saved-cheat terminal each go through
  finalize_accounting -> record_exhaustion -> queued_inputs -> validate_result;
  one pending diagnosis, held stage G5 or unknown respectively. Replay does not
  queue duplicate exhaustion without main's new-exhaustion flag.
- New close-to-passing: real apply(comparison_route=True) -> admit_extension ->
  subsequent_entry retires before writer_request/pending_call/current_pair/Evaluator;
  changed gate versions and slot cannot reroll the rejection. Same-exhaustion
  dispatch recovers committed history before card via completed_route.
- Existing observation tests that asserted the old package hold are updated only
  at the package boundary to expect extension_incomplete and a completed outcome;
  their capture/refusal/no-rerun assertions remain. Direct helper tests unchanged.
  Ordinary runtime, route, attribution, retry and public/blocking tests unchanged.

Midterm is retained observation -> terminal replay with forbidden evaluators.
Final is diagnosis/admission no-progress route plus the full locked suite and fresh
diff review. Merge land11 before implementation and newest factory-simplify before
handback. Max two review rounds; round-2 blockers go to parent in three lines.
One implementation commit then records/review. Estimated 3–5h plus lock/provider
queues. Benefit: rejected rounds stop holding active history. Risks: counterfeit
stage scores, wrong receipt window and paid rerolls; the all-unreached schema,
exact receipt checks and forbidden-call exams target each. Remaining lane-2 work:
partial/legacy first-entry reconstruction 6–10h, final all-outcomes integration
4–6h including successful irrelevant-edit progress checks. Lane 1 factory-bug
return remains its separate prerequisite (3–5h estimate).
