# Retain early writer rejections, including saved cheats

## Problem and scope

Keep the check that actually rejected an extra writer round, so a restart cannot
lose it or repeat earlier paid checks to rediscover it. G1 failures are now retained.
Early G15/G3/G4/G5 and the saved-cheat sample still return only feedback strings
before write_and_attack marks the receipt validated/exhausted. This slice records
those failures at that boundary. It does not complete history or decide progress.
Terminal completion is the next increment; partial/legacy entry is separate.
No activation, allowance, attribution, snapshot schema or existing gate-version
change. No workers or live/paid calls. Supports Murphy 9/13, closes none.

## Small explicit hooks

Add optional writer_early=None to write_and_attack. Its two post-writer early_checks
sites call (writer_early or early_checks)(c); dry-run skipping stays unchanged.
The package supplies records.writer_early. Keep its existing G1
callback and public.capture context. Ordinary callers use exactly today's path.

Add optional on_rejection=None to run.early_checks and GatePipeline.early_checks.
On a gate failure, first build the existing problems list including live detail
text, clear c.early as today, then call on_rejection(c, gate, info, problems) before
returning that same list. This is AFTER gate_attempt.execute, outside its retry
journal. Saving an observation therefore cannot retry a paid gate. For saved-cheat
feedback, call on_rejection(c, 'saved-cheats', detail, problems), where detail is
{'sample': 'retained_case_cheats',
 'summary': copy of c.card['early_gates'].get('saved_cheats')}; summary may be None
when early_cheat_check returned a CaseProblem. Immediately before calling
saved_cheat_check, pop c.card.get('early_gates', {}).pop('saved_cheats', None),
so a prior round's summary cannot be mistaken for this sample's result. The returned problems are the
authoritative diagnostic in both cases. Exceptions never invoke the callback.
No success callback and no pass observation are added.

## One failure-only observation

Records.writer_early checks for existing records at G15, G3, G4, G5, saved-cheats
before calling any early check. At most one may exist; multiple records refuse
extension_snapshot_changed. These directories cannot coexist on a legitimate
rejection path: the first failure ends the only writer round. A stress record
already skips the entire writer path. A found record must be a False scientific
result with writer_observation metadata described below; a pass refuses.

If no record exists, take one inventory digest baseline and scientific-card
projection before r.early_checks. Invoke r.early_checks(c, on_rejection=save_failure).
The callback requires ok is False and not comparison._pending(ok, info), and a
nonempty list of nonempty string problems. Pending-shaped info writes no record
and leaves the existing tuple/feedback path unchanged. It checks case_hash is
unchanged, then calls existing Records.save(stage, False, annotated_info, before,
old_card). annotated_info is a copy of actual info with one reserved key:
writer_observation = {'feedback': problems, 'bench_workers': c.args.bench_workers}.
Refuse a collision with that key. bench_workers must be a positive integer.
All changed early-invocation artifacts may be retained as support, including
earlier passing checks; only the rejecting stage is claimed as an observation.
The actual info and problems returned to the caller are never modified.

Use the existing atomic record publication and case/evidence copy in Records;
do not create another record schema, manifest writer or evidence collector.
For 'saved-cheats' only, Records.version returns digest of
{'kind': 'saved-cheats', 'g6': scientific_version(c, 'G6', BENCH),
 'source': gate_state.source_inputs('early_cheat_check')}.
This conservatively binds its shared execution/judging dependencies and sample
policy without changing G6's version. In Records.save choose gate_state.inputs
for G6 for this private observation and add the kind and early_cheat_check source
to the saved inputs.json. The record remains under saved-cheats/, never G6/.
No G6 pass/fail, cache, c.early entry, comparison receipt or public stage is created.
It is private writer feedback until the next terminal producer interprets it.

## Replay and refusal

Before checking a found record's version, use a shallow context copy with copied
args and card and a temporary Records object rooted at the same admitted row.
load(stage, check_version=False) first verifies the envelope/support/case/operation
bindings, then validate writer_observation's exact two keys, positive integer
workers and nonempty feedback. Set the copy's args.bench_workers to that recorded
count and call load again with version checking. This handles G3's worker reduction
without changing any normal cache/scientific version or mutating the live args.
G3's own count requirement in Records.load remains in force. Real G3 returns True
or raises infrastructure, so normally it produces no rejection observation.

Restore the verified record using Records.restore, clear c.early, and remove
c.early_hash if present. Restore the original early_gates rejection marker:
for gate stages set {'ok': False, 'minutes': 0}, explicitly a replay marker
with no new execution time; for saved-cheats restore the
saved summary when non-None, otherwise remove that stale marker. Emit no new
progress stage and make no money, setup, G15, checkpoint or model call. Return
a deep copy of retained feedback. No pass is restored as a gate verdict. The
live worker args remain those of the current process; replay ends in the existing
writer exhaustion hold and performs no further bench execution.

Tamper/missing/symlink support and changed case refuse before any early invocation.
Version drift gives extension_comparison_pending directly, which package.run's
existing handoff converts to extension_execution_pending while actor is writer.
An already validated/exhausted legacy receipt skips callbacks and remains held;
do not infer an observation from feedback text. Before publication a crash can
retry the ordinary early path/cache; after publication it skips the whole early
path. Existing retry limits and invalid-infrastructure classification stay intact.

## Exams and delivery

New tests/factory/test_stream_d_writer_early.py reuses admitted saved practice
case/5813be ledger from test_stream_d_execution. Author G1 pass and G15/G3 controls
explicitly to reach the later checks, not as claims of real bench results.
Use actual GatePipeline.early_checks, writer loop and record validator. For real
G4/G5 use invalid-runs-real.json.gz executions and suffix-case case.json, as in
test_extension_compare; checkpoint transport returns saved plain/reference
records and writes those bytes into the ordinary results inventory. Use real G5
rejection on plain execution. For saved cheats, use real early_cheat_check,
cheat_runs and verdicts over saved reference execution; the cheat guard directory
is a labelled control selecting that saved transport, never a live worker.

Test fresh/completed/done writer capture, actual G5 diagnostic and byte retention,
authored G15 rejection, and actual saved-cheat rejection with no G6 record/cache.
Kill after save but before validated receipt: resume with G1, every early evaluator,
setup and checkpoint forbidden; feedback and record bytes match, writer once,
history open/no stress, and the writer receipt stays byte-identical at completed. Kill before publication preserves ordinary retry/cache.
Test recorded effective workers 1 with resume requesting 2 and no false drift or
live args mutation. Missing/tampered/symlink support, stage version drift, case
drift, multiple/pass-shaped records and metadata corruption refuse before work.
Exercise saved-cheat CaseProblem and invalid-infra/timeout exception differences;
no observation on exceptions or pending-shaped returns. A save OSError after a
paid authored G15 rejection must propagate without a second gate call. All-pass
early path saves nothing and reaches normal stress. Existing ordinary early-crash,
stress-loop, G1, public-match, runtime/retry tests keep their assertions.

Midterm: real G5 and saved-cheat evidence plus publication-crash replay. Final:
full suite under `lockf -t 7000 /tmp/unbug-suite.lock uv run --with numpy --with scipy
python -B tests/run.py`, unique committed record/log, fresh diff review (max two
rounds per design/diff). Merge land10 before implementation and newest
factory-simplify before handback. One implementation commit plus records/review.
Expected effort 2–3 hours excluding lock queues/provider outages. Runtime cost
is a local copy only on rejection, no new model spend. Main risks are calling the
sample G6 or replaying through paid earlier checks; explicit namespace and
forbidden-call exams cover both. The remaining rejected-writer increment consumes
these observations for terminal completion/progress; no such result is claimed here.


## Round-1 binding fixes

B2: package.run checks for a retained early rejection before entering write_and_attack,
inside its existing incomplete-row/no-stress branch. Factor the early-record lookup
and restoration above into Records.replay_writer_early(), called both here and at
the start of writer_early. It returns None if no early record exists, otherwise
returns the retained nonempty feedback after validation/restoration. Include G1
in the conflict check: any G1 record alongside an early record refuses
extension_snapshot_changed; a lone G1 remains owned by the existing G1 path.
Before restoring a found early rejection, authenticate extensions.writer_receipt(c):
it must be actor writer, phase completed or validated, repair_pending False,
output_sha256 equal to current case_hash, and the same admitted operation/round
(the existing writer_receipt validator checks the reservation and frozen fields).
A failure here refuses extension_snapshot_changed; no receipt is rewritten.
On a found rejection package.run raises extension_execution_pending immediately.
It does not enter G1, early checks, stress, or the writer loop, and does not mark
G1 pass. This is safe because the verified, unchanged-case rejection already
prevents the single admitted round from advancing; this slice publishes no
terminal score. In particular the after-publication crash retains a completed
receipt, rather than fabricating a later validated/exhausted receipt. A normal
fresh rejection still follows the ordinary validated/exhausted hold. The future
terminal producer must accept these two authenticated publication windows.
Version drift still holds: direct lookup gives extension_comparison_pending;
package entry explicitly maps only that label to extension_execution_pending to
preserve the package-visible hold. All other evidence refusals propagate.

B1 exam: seed a stale saved_cheats summary with ok True, then let real
saved_cheat_check return a CaseProblem. The retained summary is None and replay
removes any stale saved_cheats marker. No contradictory pass is retained.

M1 disposition: keep the worker count and copied-context validation. Although
scientific_version removes the numeric bench_workers setting, dependency_files
(gate_state.py:113) omits bin/factory_pool.py at one worker. G4/G5/G15/G6 depend on
MEASURE, so their version still changes between one and multiple workers. The
existing reduced-worker test must use real scientific_version, not a fixed mock.
This slice deliberately does not alter normal versions or cache fingerprints.
