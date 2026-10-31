# Stream D package completion: retained gate traversal and outcome

## Objective, scope and cost

After an extension's writer and stress round, run the normal gates once, save
finished results so restart cannot reroll them, record its outcome, and seal a
passing case. Today the launcher stops before all of this.

This is the first implementation slice of package increment 2. The increment is
NOT complete until a subsequent design and implementation supplies entry capture
and current-version comparison with isolated execution. That work remains in this
task/checklist, before diagnosis outcome routing. No claim of package completion
or Murphy closure follows this slice. Activation stays false. No security or
section 4 rule changes. No legacy allowance changes.

One large implementation/review cycle. Offline tests use no paid inference.
Production work uses existing money reservations and batch deadline; no additional
spend authority. Per-package production cost (stress/G10/G16/G17) remains the
qualification measurement described in stream-d.md. Payoff is recoverable work;
risks are stale score reuse, lost supporting bytes, and replaying a completed
scientific rejection. The tests below target those boundaries.

## Composition and ordinary traversal

Add factory/extension_package.py. main invokes run(c, runner, prev, extension_id)
at the existing admitted execution seam. Use an elif to bypass build, and guard
validate_and_repair with extension_id is None. All-pass flows into the same finally
seal. No second gate/card publisher or repair loop.

Package authenticates job_authority.for_case and extensions.read, requiring the
selected last row and diagnosis origin. Unfinished rows call write_and_attack
with the admitted ID. Catch only its validated terminal
extension_comparison_pending handoff, or scientific rounds exhaustion with a
validated complete blocking report. Other errors propagate. Writer precheck
failure without stress proof remains unresolved in this slice (explicit remaining
package work); no fabricated stress verdict. After successful stress, clear old
failed_gate/failed_detail/gates/gate_results/infrastructure_gate and stopped status
before the traversal. Preserve model accounting, admission and diagnosis context.

Call late_recovery.mark_gates and run_gates once. Add optional around_gate callback
to GatePipeline.run and run.run_gates. It wraps invoke *inside* gate_attempt.execute,
after early/check selection is defined. This intercepts early reuse, gate-cache
reuse and fresh execution, unlike wrapping evaluate (which misses caches). The
callback receives (c, gate, invoke); no ordinary caller supplies it. It returns
(ok, info). Existing retries, card fields, after_gate, infrastructure handling and
joining remain in GatePipeline.run. To avoid concurrent artifact and state capture,
the package traversal is serial: provide an optional overlap override through
run_gates/_gate_pipeline returning 'extension evidence capture'. Ordinary overlap
is untouched. This spends no extra calls and makes ordering deterministic.

The ordinary after_gate still does G5's early probe and durable checkpoint. Capture
its effects separately is unnecessary: early_probe uses its existing retained
operation and is outside the scientific gate result. Gate callback completion
precedes that checkpoint. G12 is already excluded by extensions.stages.

## One per-stage record and proof

Use extension-package/<id>/<stage>/record.json plus copied support in that same
stage directory; no separate package journal or per-stage snapshot. Record fields:
schema_version, writer_operation_id, round, case_sha256 (runner.case_hash),
scientific_version, ok, info, support (relative-path -> SHA256), card_effects,
context_effects. A digest envelope binds the JSON payload against accidental
corruption; receipt authentication is private checkpoint integrity, not a signature.
Validate exact schema, scalar types, source paths/symlinks and every copied hash
before replay. Existing extension history authenticates ID/operation/round.

Each invocation snapshots the inventory before invoking the ordinary check, then
copies all changed inventory files after it (bench files beneath stage/support/
bench; work files beneath stage/support/work). On cached/early reuse, also collect
all evidence referenced by gate-cache/<gate>.json, verifying its hashes and
accepting restored c.work/bench-results when original results were moved. Include
existing gate-details/<gate>.json, even unchanged. Copy files before atomic record
publication. A crash before the record exists leaves no scored result; ordinary
operation receipts/retries recover execution. Once record exists, any valid pass
OR fail is replayed without calling invoke, including G7/G10/G11/G17. There is no
second window between receipt and row publication: the record is the row.

For gates without file output, retain gate-details/<gate>.json containing the
actual returned info, plus input evidence: G1's case contract files, G2's
freshness.jsonl and public-search/confirmation receipts and referenced retrieval
bytes if present, G3's setup output if present plus case manifest. The returned
verdict alone is not a claim of externally verified execution: tests and receipts
retain the actual predicate inputs. A scientific failure with no extra artifact
still has its immutable input and exact diagnostic. For every gate retain its
scientific input inventory (gate_state.inputs) in support/inputs.json. Other
proof-producing gates include inventory/cache evidence and relevant work outputs:
G10/G11/G16/G17 include pilot-strong, pilot-easy, judge_breadth, fairness-* and
calibrator transcript/result trees when present. No mutable original path remains
the only proof. Copying supporting evidence never writes the case or bench.

Capture only gate-owned public card changes, excluding accounting, diagnosis,
extension_history, job_money, route receipts, terminal/status, gates/gate_results
and timings (the pipeline owns those). Explicit keys: counts, public_search,
reviewers_fairness, reviewers_realism, plain_app_broke, reference_fix,
cheats_passed, scenario_keys_match, calibrators, fake_pass, difficulty,
factory_slots_prepared. Record presence/deletion for these keys. Context effects:
statement, votes, votes_hash, pilot_passes (paths encoded as strings),
prepared_factory_slots; restore paths on replay. G1 reconstructs statement on
replay; G9 needs votes from G8, G11 needs pilots from G10. Gate-cache G16 proof
remains at its ordinary path so retain_delivery verifies its calibration identity.
Do not copy the ledger or old job authority from records.

## Case/version identity and snapshots

Gate execution may append freshness.jsonl; runner.case_hash deliberately excludes
it. Gate records bind that semantic hash. Other case changes during a gate refuse
with extension_snapshot_changed. Snapshot creation happens only AFTER traversal,
with a read-only adapter over saved records, so extension_compare.snapshot sees
unchanged full bytes including final freshness.jsonl. Preserve freshness bytes as
stage support at evaluation time rather than rewriting earlier proof.

Stress proof is the authenticated completed attack receipt, report, category
states/reports and loop-freshness proof. Its record follows the same schema;
report findings imply fail, fully completed clean report implies pass. Unfinished
coverage/freshness/diagnostic evidence cannot complete a stress record. Only
stress pass runs gates. A changed stress scientific version versus retained attack
binding cannot silently claim a current pass; stop comparison pending until the
remaining comparison slice handles it.

For this slice, a saved gate whose current scientific version differs stops with
extension_comparison_pending, retaining its old proof; never relabel or reroll it.
The next comparison slice must resolve drift before package checklist completion.
The snapshot read adapter only reads validated records and emits their supporting
paths. snapshot produces the standard comparison-receipts/support layout and
extensions.complete saves the outcome case/evidence before history. No snapshot
API change. Entry and outcome retain their own scientific versions; entry drift
does not invalidate recording the actually executed outcome.

## Completion, replay and diagnosis

Scientific failure raises existing BudgetError('extension_incomplete') only after
extensions.complete has committed. main sets exhaustion_occurred; finalize calls
record_exhaustion(new_exhaustion=True), replacing the completed originating
close_to_passing diagnosis with one pending diagnosis and a fresh exhaustion ID.
Replaying the failed package preserves that pending ID; diagnosis outcome dispatch
remains later. No new stop string or Murphy row for a new observed incident.

Crash after outcome history but before public card must remain routable. In
diagnosis_dispatch.apply, for authenticated close_to_passing replay inspect the
last history row even if completed; if its exhaustion_id matches the replayed
manifest and its package records exist, return its ID under DIAGNOSIS_ENABLED.
Do not call writer_receipt on completed rows. Package sees outcome, validates its
retained bytes, rebuilds gate/card effects through the same pipeline replay callback
(no fresh evaluations permitted), then reproduces all-pass seal or extension_incomplete.
A new pending diagnosis always wins normal dispatch, so this cannot reopen a row
for a different exhaustion. Successful replay clears carried stopped/terminal
fields; no new diagnosis is queued on all-pass.

## Validation and remaining obligations

Extend test_stream_d_execution.py with the real admitted history/ledger and saved
practice case. Keep existing loop-only tests; add package tests. Inject authored
model/bench execution only at external boundaries. Exercise real GatePipeline,
gate_state.save/load and copied proof validation for bench-results, gate-details,
and input-only evidence classes, plus a table covering each stage's artifact rule.
Run real G1 over practice artifacts and real freshness confirmation fixture.

Tests: unfinished category continuation; fail stops later gates; one traversal;
kill before/after stage record and after G10; replay pass/fail with no model reroll;
tampered/missing/symlink support refuses; stale case/version refuses; early and
cached checks are captured without invoking evaluators; invalid-infra/provider/
money leaves history open. Test G8 votes/G10 pilot/card reconstruction; outcome
history-before-card replay through dispatch; package failure finalization queues
one diagnosis and replay preserves it. All-pass reaches ordinary RunArtifacts.seal
and retained-delivery checks with saved calibration artifacts (encryption/process
boundary can be substituted). No ordinary build/repair path is called.

Midterm exam: gate record restart tests. Final exam: full launcher package replay,
ordinary seal contract and full suite. Run uv run --with numpy --with scipy python
-B tests/run.py to unique log; wait and commit the result record. Fresh diff review
must verify every blocker fix. Supports rows 9/13, closes none.

Remaining within package increment 2 after this slice: concrete isolated comparison
execution and entry capture, writer-validation/freshness-public-match outcome
coverage, and version-drift integration. Only then mark the package checklist done
and move to all diagnosis outcome routes. Lane 1 retains legacy allowance deletion.

## Round 2 binding amendments (supersede conflicting paragraphs above)

NB1: replace the closed card-effects allowlist with a deep-copy top-level diff
of every added, changed and deleted key around invoke. Exclude case_budget,
continuation_budget, job_money, route_receipts, models_used, diagnosis_state,
extension_history, factory_bug, factory_bug_resume_count, gates, gate_results,
gate_minutes, status, terminal_stop, infrastructure_gate, failed_gate, failed_detail,
resume, resume_operation, wall_minutes, error and checkpoint_error. Test fresh vs
replayed gate-owned card equality, explicitly owner_contract. Record deletions.
Keep named context effects, but encode pilot_passes work-relative and reconstruct
under current work. Capture statement only; do not separately reconstruct it.

NB2: split hook into replay_gate(c, gate) and around_gate(c, gate, invoke).
run_gate checks replay_gate BEFORE gate_attempt.execute and its retry journal.
Valid saved results produce the ordinary Outcome and continue normal card and
checkpoint handling. No record returns None; invalid records refuse. Capture stays
inside invoke. Test valid record plus journal running=true/invalid_attempts=1:
replay succeeds and the journal is byte-identical.

M1: actual evidence roots under work are strong_calibrator, easy_calibrator,
early_probe (G10); those plus g11-evidence (G11); judge_breadth and
fairness-g16-inputs (G16); strong_calibrator and fairness-g17-inputs (G17).
For calibration roots copy results.json, **/execution.json and **/guard/** only;
for fairness/g11 roots copy all regular files. Include associated review answer/
completion and calibrator transcript files under work. Never access pilot homes.

M2: never write live gate-details. record.info holds the returned diagnostic.
Copy only changed gate-details or verified reused gate-cache supporting files.
For artifact-less gates retain support/inputs.json from gate_state.inputs plus
actual case inputs; G2 additionally retains freshness/search/confirmation and
retrieval bytes. No unchanged unbound detail is attributed to the current result.

M3: clear carried failed/gate/infrastructure/status/terminal fields whenever
stress is pass, including completed-row replay which skips write_and_attack.
After run_gates, if c.stopped is true, return immediately, preserving its stop;
never snapshot or complete an infrastructure stop.

M4: completed-row replay never calls snapshot or complete. It verifies immutable
outcome with extensions.read, reconstructs ordinary traversal/card from records,
and compares replayed stage statuses/failing stage to row.outcome. Any mismatch
raises extension_outcome_changed. Test replay on another slot with snapshot and
complete forbidden. Fresh snapshot uses Workspace(c.case, c.work, runner.BENCH,
c.args, c.models, c.card, c.seed, getattr(c, 'factory_slot', 0), c.case_id), and
source_generation from job_authority.for_case(c).source_generation.

Only record result shapes accepted by extension_compare._pending; invalid shapes
raise InvalidInfra without publishing a record. The package disables optional
early_probe while retaining ordinary after_gate accounting and checkpointing:
_gate_completed gains probe=True default, package passes probe=False through an
optional run_gates after_gate callback. This avoids conflicting probe slots and
new model work during terminal replay. Normal traversal remains unchanged.
apply's completed-row existence check is validation of
extension-package/<id>/stress/record.json bound to that row, not mere existence.
Two stable implementation commits: record/replay hooks, then package/dispatch.

## Round 3 binding amendments

These supersede the prior card-diff rule. Retain a complete scientific card
projection after each invoke, not only keys changed inside invoke. Use all exclusions already listed above plus
these explicit plumbing keys: durable_checkpoint, cleanup_errors,
public_progress_error, router_waits, router_interrupted_calls, sha256, archive,
r2_object, early_gates, early_probe, roles, rotation_slot, provider_accounts,
account_handoffs, continuations, calls_delta, cost_delta. Additionally exclude case, source, seed, dry_run, models, model, kind, verdict,
build_deferred, budget_raised, rounds_raised, recovery_config, limits,
restore_adjustment, resume_rereview, salvaged_from, kept_from_previous_run,
kept_gate_source, free_model_fallback, model_transition, provider_routes,
provider_preflight, driver_qualification, audit_source, audit_inputs_sha256,
source_inputs_sha256, review_bench_sha256, digest_version, inputs_unchanged,
audit_runtime_preparation, delivery_provenance, statement_cipher_sha256,
dry_run_roundtrip, wipe, audit_calls_total, audit_cost_total, legacy_import,
builder_rounds, candidate_attempts, repairs, batch_release_sha256, job_identity.
These are the plumbing/identity keys in carry_over.FACTS/DERIVED, not an import
of those whole sets (which also contain scientific fields). bench_workers_effective
and factory_slots_prepared remain scientific gate output for reconstruction.
The record contains the projection plus absent keys observed before invoke, so
scientific deletions replay without touching excluded fields. Replay updates the
projection and applies only those recorded scientific deletions. Capturing the
post-invoke projection retains earlier G3/G4/G5/G15 card effects even when invoke
returns c.early or a verified gate cache. Context capture likewise stores the
current values of the explicit context keys, not a before/after diff. Thus G3's
prepared_factory_slots survives early reuse. No extra setup or gate invocation.
Tests must cover early-reused G4/G5 plus owner_contract, and a model-call boundary
that changes cleanup_errors and durable_checkpoint: neither key may enter the
record or overwrite the resumed process's values.

For G16/G17 add fairness-replacement-* calibration roots (results.json,
**/execution.json, **/guard/**) and transcripts/strong-calibrator-<folder>-*.jsonl
for each associated folder. Copy all referenced replacement proofs.

Completed-row replay injects a no-op budget_boundary into the same pipeline:
it spends nothing and must reproduce extension_incomplete even at the commitment
limit. Fresh/incomplete package work retains ordinary money/deadline boundaries.
Missing stage record on completed replay raises extension_outcome_changed before
invoke. Publish one completed/failed reused=True progress event on record replay.
Version/model/role drift may still stop completed replay with
extension_comparison_pending; resolving that stays in the comparison slice.

Disable optional early probe by temporarily setting args.no_early_probe=True
around traversal and restoring its prior value/presence in finally. This replaces
the proposed probe parameter/after_gate injection: no new _gate_completed API.
no_early_probe is not a scientific-version or retry-journal identity input.

## Round 4 binding amendments

G3 is setup (True or infrastructure exception), not a stochastic scientific
verdict. On every incomplete-row traversal, execute ordinary G3 setup even if its
record exists; bypass in-memory early reuse for G3 so the current machine is
prepared. Validate any existing G3 record before setup and keep its immutable
proof; setup may not replace the recorded verdict. Later saved gates still replay,
and only unfinished gates execute. Setup failures propagate as infrastructure,
never scientific rejection. The freshly executed G3 sets actual preparation state.

On completed-row replay no gate executes: restore args.bench_workers from the
recorded G3 bench_workers_effective before computing later stage versions. Add
args.bench_workers to the context projection for G3 only; other stages must not
restore preparation counts from a dead VM over fresh G3 setup. Before G3 replay
validate its semantic case/version using recorded effective workers as well.
Tests: requested workers 2 reduced to 1 by real G3 memory check, completed replay
has no false version drift; incomplete replay after G10 record invokes setup
before fresh G17/G11. This is a deliberate exception to no-invoke replay for
incomplete rows, and never invokes a model or permits extra author work.

Add calibration_interruptions, router_pending_requests and gate_continuation to
plumbing exclusions. Test newer counters survive replay unchanged. Deletions mean
scientific keys present before invoke and absent after it. On incomplete replay,
fresh G3 owns factory_slots_prepared/prepared_factory_slots, so other stage
projections must not overwrite these runtime preparation fields.

## Round 5 binding amendments

Compute every new stage record's scientific_version AFTER invoke returns.
Before validating an existing G3 record's scientific version, for BOTH incomplete
and completed rows, first validate the record's schema/digest/support and restore
args.bench_workers from its recorded bench_workers_effective (positive integer).
That is the single stored source of effective workers; remove the duplicate
args.bench_workers context field. On incomplete traversal ordinary G3 starts from
this restored count and may lower it further. Pop c.early['G3'] at package entry
(using getattr(c, 'early', {}).pop('G3', None)) to bypass early setup reuse.

Extend incomplete replay test: requested 2, effective 1, kill after G10 record,
restart requesting 2; G3 validates without false drift, reruns setup and fresh
G17/G11 use 1 worker. Also cover no G3 record yet: fresh setup lowers 2 to 1,
post-invoke record version matches completed replay with restored 1.
Fresh G3 owns bench_workers_effective as well as factory_slots_prepared and
prepared_factory_slots; later replayed projections must preserve those fresh
runtime values. Its current image ID may differ from recorded G3 info.image:
this is execution metadata, not scientific drift (MEDUSA_DEPS_IMAGE is versioned).
Keep immutable recorded proof; do not rewrite old info to the new image ID.

Exclude founder_ruling, call_cap_ruling and freshness_archive_ruling from card
projections so old gate records cannot overwrite newer founder authority.

## Passing review clarifications

Pop early G3 immediately before run_gates. Incomplete G3 replay validates and
restores recorded workers before returning None; around_gate then runs setup and
returns the retained verdict without rewriting proof. A further reduction below
the recorded worker count stops extension_comparison_pending without rewriting
any record; comparison owns this drift case. Add the recorded-2/new-1 test.

## Implementation boundary clarifications

The pre-G3 stress handoff compares attack bindings with the same execution-only
seed/bench_workers/concurrent_roles exclusions as scientific_version. Restoring a
worker count cannot turn completed stress into a scientific version change.
The capture hook also consults an existing record on an in-process retry: a
filesystem error after atomic rename must not execute the scored gate again.
Both have regression tests. G10 projection replay is exercised immediately before
the existing retained-delivery/portable exam proof test, using its artifact-backed
completed calibration receipts. These are offline mechanics, not live qualification.
