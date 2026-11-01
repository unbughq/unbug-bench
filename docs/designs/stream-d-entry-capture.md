# Stream D: first-extension entry receipts

## Problem, scope and payoff

Keep proof of what already ran so diagnosis can request the first extra writer
round without paying to run the same checks again.

Lane 1's proposed consumer calls `extension_package.entry(c, runner)` before
admitting a writer. Today no producer exists. A scorecard's gate booleans are not
scientific receipts, so inventing an entry from them would permit unsupported
extensions. Preserve evidence at the ordinary gate boundary, then return an entry
without running a writer, gate, model or checkpoint again.

This is one deliberately smaller increment of package increment 2. It implements
first-extension entry capture. Isolated current-version comparison and subsequent
extension admission follow next; rejected/unchanged writer and confirmed-public-
match terminal outcomes follow those. The package checkbox remains open.
`diagnosis_dispatch.py` belongs to lane 1 and is not changed. Its proposed entry
signature is preserved. Activation stays false. No section 4/security changes,
workers, cloud calls, secrets or paid calls are part of implementation or tests.
Supports Murphy 9/13 and closes no rows.

## One receipt implementation, two owners

Generalize the existing `extension_package.Records` constructor to accept either
an admitted row (unchanged public constructor use), or keyword-only
`observation_id` and `round_number` for an ordinary traversal. Exactly one owner
is required. The ordinary ID is a runner-created UUID, not an extension ID or
writer operation. Ordinary roots are `c.work/entry-records/<observation_id>/`;
package roots remain unchanged. Set internal `operation_id`, `round_number`,
`completed` and `root` once in the constructor; load/save refer to these rather
than reaching through the row. The existing record key `writer_operation_id`
is null for ordinary records, explicitly meaning no admitted writer reservation.
A package record still binds its real admitted operation. `Records.row` remains
available to package orchestration. Ordinary records are never passed to
`extensions.writer_receipt`, `admit`, or package `run`.

All record invariants remain: exact schema/digest, semantic case hash,
post-invoke scientific version, private support bytes/hash checks, card/context
projection and pending-shape refusal. This deletes duplication rather than adding
a second evidence collector or format. Existing package replay behavior is
unchanged. Ordinary capture uses observational observe_gate, specified below; it never
replays or restores a previous result. Package capture behavior is unchanged.

## Ordinary traversal capture

`run.run_gates` is the only wiring seam. Only when the exact activation/mode predicate below holds, call a new
`extension_package.observe(c, runner, pipeline)` wrapper. Excluded modes keep
the old pipeline behavior without capture overhead. Package
callbacks continue to take precedence. No `main` or dispatcher changes.

At entry to observe, create a new UUID root and atomically publish
`entry-records/current.json` with exact schema 1, observation_id, round_number
(the current nonnegative integer builder_rounds), semantic case hash. Publishing the pointer first invalidates an older traversal
as the current entry even if this one crashes before its first record. Never
reuse a prior traversal's stage records. On restart the normal runner may run its
normal gate/cache paths; this increment adds no new execution or retry policy.
The wrapper sets serial overlap only for this activated capture traversal, as the
existing package does, because parallel G10 can mutate card/context and evidence
while another record snapshots them. Preserve the ordinary after_gate callback,
checkpointing, budget checks and early-probe policy. Per-stage capture includes
an early/cache reused result's actual scientific projection/support as today.

Before invoking the pipeline, attempt to capture stress from the retained
ordinary handoff, not the public card. Use `late_recovery.gate_marker(c)` to
validate completed, clean stress and any retained freshness clearance. Require a
non-null marker, the exact current semantic attack binding (the same execution-
only seed/workers/concurrency normalization currently used by package stress),
no unfinished diagnostics, and a valid parsed/cleared report. Save a stress pass
with that real report and proof using Records.save. Missing/inapplicable old
proof means no stress record; it does not stop or change an ordinary traversal.
Catch only expected evidence-refusal errors (ValueError, missing file/invalid
JSON and BudgetError labels for evidence mismatch); unexpected errors propagate.
Do not suppress money/provider/cancel errors or mutate attack-state. Do not mark
stress fail from missing evidence. Restrict the pre-existing inventory baseline
to its current digests when saving stress, so unchanged old gate-details/bench
results are not attributed to stress; the explicit stress evidence roots remain.

The ordinary pipeline then runs with this traversal's capture hook. Infrastructure
failures leave missing/pending entry evidence and keep existing ordinary stop
labels. It never completes extension history or queues diagnosis itself.

## Entry producer and refusal contract

`entry(c, runner)` first verifies job authority and `extensions.read(c)`. If any
history exists, raise `extension_comparison_pending`: the follow-on comparison
increment owns selecting/reconstructing its current outcome. This explicit
refusal prevents the new first-entry path bypassing a prior extension's progress.
No dispatcher change is needed, and lane 1 retains its existing held boundary.

For no history, read current.json using the existing safe JSON reader. Validate
its exact keys/types, UUID, round, and current semantic case binding; never take
a path from the file. Resolve the UUID beneath entry-records. Load every required
stage through Records.load in pipeline order, restoring G3 effective workers
before checking G3 or later versions exactly as package replay does. Pin the
current scientific vector after that restoration; drift or missing
proof raises `extension_comparison_pending` rather than relabelling old scores.
A real gate failure is terminal and makes later stages unreached. A missing record
before that failure is pending. A stress pass is required. No scorecard result
or generic gate-cache file alone is sufficient.

Use unchanged `extension_compare.snapshot` as the sole snapshot producer with a
read-only adapter over those records. Its output proof paths remain in c.work,
so ordinary `extensions.propose`/`verify_proposal` can validate them. The input is
`Workspace(c.case, c.work, runner.BENCH, c.args, c.models, c.card, c.seed,
factory_slot, case_id)` and source_generation comes from authenticated job
identity. Return only a snapshot with no pending stage and stress pass, else
raise `extension_comparison_pending`. Do not admit, reserve, mutate case, consume
an extension ID, touch history or invoke evaluation. Snapshot writes only its
existing comparison-receipts/support outputs. Unchanged repeated calls produce
the same result on the same execution context. The existing snapshot producer
checks full case/config/version stability and supporting bytes before return.

## Tests and cost

Use saved public practice case/HTTP/checkpoint fixtures and real admission
helpers. Author only external execution/model outputs, clearly labelled.
1. Real ordinary pipeline with G1 and saved G4/G5 evaluations captures a passing
   prefix and a scientific failure; entry returns the exact prefix/failure and
   can feed propose/verify_proposal without another evaluation.
2. Validated saved stress handoff (including freshness-clearance fixture) earns
   stress pass. Missing/tampered/unfinished/stale stress leaves entry pending and
   does not change ordinary gate execution or its stop.
3. Kill before first record, after record rename, and after final failure: pointer
   identifies only this traversal; partial entry refuses, completed prefix replays
   without model/gate calls. An earlier complete traversal cannot cover the gap.
4. Missing/tampered/symlink support, changed semantic case, current version drift,
   malformed pointer and a changed source generation refuse or rebind only the
   authenticated lineage as appropriate. No snapshot is fabricated.
5. Existing extension history refuses before any capture/evaluation/snapshot;
   legacy/dry/rehearsal/package paths preserve behavior, and ordinary activation
   is still false. Tests never edit diagnosis_dispatch.py.
6. Existing package replay tests, full prescribed suite with unique committed
   log/result, then fresh diff review. Lane 1's known dispatcher semantic fix is
   imported only after the parent merges it; do not weaken its test locally.

Midterm exam is the real artifact capture -> entry -> proposal test. Final exam
is the full suite plus fresh review. One design/review/implementation cycle;
no live spend or qualification claim. Main risks are stale proof and changing
ordinary scheduling: explicit binding, pointer replacement, no previous-traversal
replay, and serial capture tests address those. Remaining item 7 obligations stay
listed in stream-d.md; no package-complete claim.

## Binding review-1 amendments (supersede conflicting text above)

B1: ordinary capture uses a new `Records.observe_gate(c, stage, invoke)`, not
package `capture`. Invoke is called once outside capture error handling. Exceptions
from invoke therefore retain the pipeline's existing retry/interruption behavior.
After it returns, a pending-shaped result is returned unchanged without saving.
Before/after inventory and serialization/save failures are observational: catch
BudgetError, InvalidInfra, OSError, ValueError, KeyError and TypeError only around
capture-side operations, never around invoke. Return the original tuple unchanged.
No package refusal or invalid-infra exception is injected into ordinary scoring.
If saving failed after rename, attempt to remove that stage directory;
ignore cleanup OSError because the traversal remains ineligible and its root
is removed when the next pointer is published. Entry requires an explicit successful traversal close marker described
below, so no failed capture can authorize an entry. Ordinary capture does not
load/replay a record on an in-process retry and never restores card/context.
The unchanged package capture keeps its existing replay-on-retry behavior.

The wrapper writes `entry-records/<uuid>/closed.json` only after pipeline.run
returns normally and every invoked stage produced a valid saved result. The file
contains schema_version 1, observation_id and the final semantic case hash.
Any pending-shaped result or capture-side failure suppresses this file; pipeline
return and ordinary validate_and_repair still see the original gate tuple/card.
A close-marker write failure occurs outside gate retry and cannot rerun a gate.
Infrastructure/budget/provider/cancel interruption never writes closed.json.
Entry requires and validates this marker before snapshot. This intentionally
holds incomplete captures; it does not reinterpret them as scientific failure.
Initial pointer/root publication occurs before any gate invocation; its I/O errors
propagate outside gate_attempt rather than causing a paid retry. No older pointer
is used by entry after a successfully published new traversal.

B2: exact eligibility is `batch_service.DIAGNOSIS_ENABLED is True` AND
`model_runtime.factory_job(c)` AND neither args.dry_run, args.rehearse_only nor
args.audit_fairness AND no c.audit_source or c.audit_gates attribute AND both
explicit replay_gate and around_gate are None. Read flags via getattr(default
False). `observe` verifies `job_authority.for_case(c)` before writing a pointer.
When disabled or excluded, do not create entry-records, inventory/hash evidence,
change overlap_reason, or call any capture helper. Enabled ordinary capture is
serial; retaining the full projection safely costs throughput only when the
consumer is enabled. Tests cover every exclusion independently and unchanged
overlap callback identity when disabled. This does not enable diagnosis.

M1: after atomic pointer publication, remove only superseded UUID-named direct
children of entry-records, never arbitrary paths from disk metadata. Use
`diagnosis._uuid4` to recognize names, refuse symlink roots, and preserve current
UUID/current.json. Deletion failures propagate before gate execution (no paid
retry). This bounds normal retained roots to one; an interrupted deletion is
retried at the next traversal. No extension-snapshots or package records are
removed.

M2: entry uses a shallow copied context with deep copied args/card/models when
loading records and building the Workspace. G3 worker restoration affects only
that copy, never the caller. For a failure before G3 there is no G3 restoration;
the unused suffix is versioned using the current requested workers. Reached G1
and G2 versions do not depend on workers. Missing G3 after a passing G2 remains
pending, never silently unreached. Pin versions after a preliminary G3 load only
if a valid G3 record exists; otherwise do not invent its runtime preparation.

M3: explicitly deferred held cases are budget exhaustion midway through gates,
and exhaustion during stress before gates are traversed. Both return
extension_comparison_pending, not retired_no_progress. This is a conservative
first-entry subset, not lane 1's eventual failed-stress retirement contract.
Lane 1's retirement remains waiting for the terminal-outcomes producer; no
consumer code change is requested. Add these obligations to stream-d.md and test
that neither a proposal nor retirement is produced from these partial inputs.

M4/M5: validate attack-state with extensions._writer_json before gate_marker.
Require integer positive round == pointer round == c.card['builder_rounds'],
report exactly `round-<round>.json`, matching semantic attack binding, and
`attack_diagnostic_unfinished(c, round)` false. Stress capture catches
(BudgetError, InvalidInfra, OSError, ValueError, KeyError, TypeError) arising from
this read-only proof/copy work and leaves stress missing, with no new exception
from stress validation. There is no model/budget call in that region. Ordinary
mark_gates retains its existing validation behavior outside the wrapper.

Pointer reader is extensions._writer_json; UUID validator is diagnosis._uuid4.
Map malformed/missing pointer, marker and stage-record proof refusals to
extension_comparison_pending at entry (BudgetError evidence labels plus OSError,
ValueError, KeyError, TypeError); do not catch job-authority/history errors.
Pointer round must exactly equal the caller card's builder_rounds. Records are
not tied to source_generation: always stamp the authenticated current generation,
and test that exact rebind with unchanged case/evidence. No vague alternative.

M6: fixture plan uses tests/factory/fixtures/invalid-runs-practice.json.gz (SHA-
checked practice files), invalid-runs-real.json.gz plain/reference checkpoint
records and suffix-case metadata, invalid-runs-http.json.gz response bytes, and
the real 5813be public-card ledger already used in test_stream_d_execution.py.
The integration control uses real GatePipeline/run_gates; real G1 evaluates the
practice contract in its own test (its current diagnostics may fail). In the
prefix integration G1/G2/G3 pass outputs are explicitly authored orchestration
controls; G3 records effective workers without Docker. G4/G5 call real gates
with checkpoint transport replaced by saved plain/reference executions. Choose
G5's authored false outcome only in the crash/control test; use a saved real
rejection in the evidence test. Later stages are unreachable, not fabricated
passes. A separate real fairness.breadth/G16 test supplies an inconclusive
independent-review answer at its external model boundary; it asserts one review,
unchanged returned tuple, validate_and_repair returning and an entry fail receipt
with review_inconclusive in its detail. A separate authored error-shaped result
asserts unchanged ordinary behavior and entry pending.
Stress/clearance uses real completed receipt/hash validation and the existing
saved HTTP+authored confirmation boundary fixtures, never a public boolean.

Nits: early reused G3 case/inputs-only proof is accepted, as G3 setup happened in
this process and it has no scored scientific failure. Entry repeatability is
same-slot/context only; cross-slot interrupted admission needs the follow-on
retained-entry integration, not a promise of byte-identical execution metadata.
extensions.read may refresh the public history projection; entry uses the copied
context to keep even that effect off the caller. Goal in plain words: keep proof
of what already ran so diagnosis can request the first extra writer round without
paying to run the same checks again.


## Binding review-2 decisions

Keep extension_compare._pending unchanged: `(False, review_inconclusive=True)`
is a scored failure; no new capture-only rule. A result containing `error` or
`execution_valid=False` is pending. The real inconclusive test uses G16 breadth
(not G17 diagnose). Lane 1 owns subsequent writer feedback, not this producer.

Add args.late_gate_rehearsal to the exact exclusion predicate and test it after
c.audit_gates has been removed. skip_build gate-only continuation remains eligible.
The test file is `tests/factory/test_stream_d_entry.py`; use the prior execution
fixture helpers without inheriting unrelated test methods.

Track saved status per invoked stage, replacing that status on every attempt.
Close only if each last attempt saved successfully and c.stopped is false and
c.card has no infrastructure_gate. Entry requires pointer.case_sha256 ==
closed.case_sha256 == runner.case_hash(copied_context), and both marker IDs match.
Map extension_compare._Changed to extension_comparison_pending. G3 failure proof
without a positive bench_workers_effective is accepted as an entry hold, not a
scored extension failure. Hoist the existing scientific attack-binding
normalization from stress() to a module helper reused by ordinary observation;
its semantics do not change.

A symlinked entry-records root or UUID child is refused as
extension_snapshot_changed during initial publication/cleanup; entry maps such
proof refusal to extension_comparison_pending. Safe path validation must include
all parents inside c.work, not merely the final pointer file.

Activation obligation: serial G10 changes throughput and must be measured before
enabling diagnosis. A retained historical card reports 144.4 G10 minutes out of
148.1 gate minutes with overlap; this is context, not an estimate of the added
serial cost. No live timing experiment is authorized here. Record the unmeasured
serial-vs-overlap cost alongside remaining item-7/item-8 activation obligations.

## Implementation clarifications after PASS

Pointer exact keys: {schema_version, observation_id, round_number, case_sha256}.
Close marker exact keys: {schema_version, observation_id, case_sha256}.
Entry maps only BudgetError labels extension_reservation_mismatch,
extension_snapshot_changed, extension_comparison_pending inside its proof-reading
try; job authority/history validation is outside. G16 integration runs real
validate_and_repair with authored pass controls for preceding stages (including
G3 effective worker metadata), a valid stress receipt, and real G16 breadth at
its external review boundary. Assert both Records.load('G16') and entry() fail
receipts, exactly one review, and no writer repair.

A tampered symlink entry-records root may stop the enabled ordinary traversal
before any gate; this is an accepted evidence-integrity refusal, tested without
retry. Before snapshot in a history-free entry(), remove only comparison-receipts
and comparison-support scratch outputs after verifying neither is a symlink.
They have no admitted history owner (history was checked empty); rebuilding them
bounds copies from repeated diagnosis. Never remove extension-snapshots. G3
without positive effective workers is pending even when its raw result failed.
