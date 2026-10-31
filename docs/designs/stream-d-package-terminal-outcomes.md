# Stream D package increment 2: finish rejected writer and freshness outcomes

Status: draft only. Review attempts were unavailable; no implementation is authorized by a passing review yet.

## Problem and scope

The retained traversal slice finishes a clean stress round and its gates. A writer
that returns invalid or unchanged bytes, an early gate rejection, or a confirmed
public match can still leave extension history open forever. Finish those packages
without another writer call, invented stress pass, or converting broken execution
into writer feedback. This is the next slice of package increment 2, not diagnosis
routing. Entry capture and isolated current-version comparison still follow before
the package checklist closes. Activation remains false. No security/section 4 or
legacy-allowance change. One implementation/review cycle, offline cost zero; existing
batch money/deadline bounds govern every external call.

## Record actual early execution

The package creates its Records object before write_and_attack and installs it
as a scoped c.extension_records attribute, removed/restored in finally. Add a
small runner helper for the two post-writer G1 validation sites: ordinary callers
use g1 as before; the package calls records.capture(c, 'G1', lambda: g1(c)). This
records the actual diagnostics from the completed writer's bytes before a failed
validation can end the round. It never reruns the writer and only runs validation
where the existing loop already does so.

GatePipeline.early_checks wraps its existing invoke through c.extension_records
when present (including G15 and G3/G4/G5). It keeps gate_attempt retry ownership,
existing fail feedback, and the same ordering. A record lookup happens before the
retry journal just as in final traversal. No other early_review caller changes.
Early records belong to the same admitted writer operation, round and immutable
output. Package records cannot precede writer completion on this route. In the
final traversal G1/G15/G4/G5 may replay those records. G3 keeps its setup exception.

## Remove worker-count selection from scientific identity

Early G15 runs before G3 may reduce bench_workers. Current scientific_version
removes that setting but inputs() conditionally includes factory_pool.py based on
it, so the scientific version still changes with execution worker count. Add an
include_pool keyword to inputs/dependency_files use: full execution fingerprints
keep their current worker-sensitive inventory; scientific_version always includes
the declared factory_pool dependency when the stage's patterns contain it.
No stage gains an undeclared dependency. Stress already uses include_pool=True.
This makes scientific identity conservative and independent of worker count.
Existing scientific versions may change once for stages previously computed with
one worker. They are not relabelled; comparison handles old vectors. The active
flag remains false, so this does not roll an unqualified change into live cases.

G3 still restores recorded effective workers and prepares the current machine on
incomplete replay. A further memory reduction no longer alone means scientific
drift. Remove only the explicit old/new worker inequality refusal; retain source,
case and model checks. Fresh G3 owns runtime counts. Update the prior conservative
drift test to assert retained later passes survive a 2-to-1 reduction without a
new stochastic evaluation. Test early G15 at requested 2 then G3 at effective 1.

## Terminal outcomes without invented scores

Extend the snapshot producer with an explicit observations mode for package
completion. Default snapshot()/compare behavior is unchanged. observations is a
trusted mapping of reached stage names to (ok, detail, support paths); unobserved
stages are 'unreached'. Iterate every stage in normal order, calling the existing
_save for observed stages, with the same case/config/version/evidence validation.
Do not short-circuit on stress being unreached: G1 and early gates really execute
before stress. No observed result can be pending. Additional boundary evidence
(writer receipt and terminal reason) is copied/hashes checked through the same
support validation and retained in snapshot.evidence. This is the shared producer,
not a separately invented snapshot schema. No new snapshot fields/statuses.

The package uses observations only after one authenticated terminal boundary:
- validated writer receipt with exhausted=True, stop_reason=rounds_exhausted and
  captured G1/early scientific failure; stress stays unreached;
- completed writer with repair_requested and before_repair_sha256==output_sha256,
  authenticated through writer_receipt; unchanged_repair ends the package, with
  actual recorded early observations (normally none) and stress unreached;
- authenticated stress receipt with real blocking findings. stress_progress
  deliberately marks such a report 'scored' even if diagnostics remain unperformed.
  Preserve that existing policy: a genuine blocking defect is stress fail, not an
  infrastructure result. 'review incomplete' alone, unfinished validation alone,
  malformed report, missing completion, active categories, provider/money/cancel,
  or invalid-infra never produces a terminal outcome;
- freshness_public_match after a completed stress call: verify the retained
  review completion/retrieval/case binding using the existing clearance validator's
  shared proof checks, without calling a reviewer. Record G2 fail with the actual
  confirmed-match proof. Do not call it a stress pass: stress is unreached unless
  an independently completed clean stress record already exists.

Factor the retained freshness-proof validation in late_recovery so both clearance
and confirmed match use the same validation; only the interpretation differs.
No stale/partial/absent verdict is sufficient, and time alone never rerolls a
completed package. An unverifiable retained result remains pending/refused.

Every outcome stores actual observations only. No pass is inferred for missing
stress, G1 or later gates. extensions.complete keeps its immutable case/evidence
write-before-history ordering. Scientific terminal completion raises existing
extension_incomplete; ordinary finalization queues the next diagnosis once.
Completed terminal replay reads the immutable outcome and restores recorded
observations without invoking writer, stress, gates, or money admission. It does
not traverse absent stages or recreate receipts. Validate observed stage statuses
and immutable boundary proof, then reproduce extension_incomplete. All-pass replay
continues to use the ordinary traversal/seal contract from the first slice.

## Progress semantics for terminal unperformed stages

progress first rejects version mismatch or any pending stage exactly as today.
Then check every previously passed stage for a witnessed fail (regression).
Otherwise compare frontiers; unperformed stages in a fully terminal outcome are
not pending execution. A lower/equal frontier is no_progress. This avoids an
unreached stress slot hiding a real G1 regression, and lets unchanged-author work
retire instead of creating another writer allowance. No broken run is completed,
so this rule never turns unfinished infrastructure into no_progress feedback.
Tests distinguish pending from unreached explicitly. Admission's existing stress
pass requirement still refuses a next extension from such an outcome.

## Tests, risks and records

Use the saved practice case and ledger through actual admission, writer receipts,
early GatePipeline and snapshot validation. Author model outputs explicitly; use
real G1 validation on invalid practice-case bytes and saved bench artifacts for an
early rejection. Test unchanged writer, invalid G1, early G4/G15 rejection, complete
blocking stress, partial diagnostics with scored blocking defect, confirmed public
match, and missing/partial freshness-proof refusal. Exercise two replays, lagging
card after outcome write, and one pending diagnosis ID. Assert no extra author or
review work. Existing provider/money/infra tests must leave history open.

Test actual early-G15/G3 version stability across worker reduction; unchanged
fingerprint behavior for ordinary execution caches; source edits still change only
affected scientific versions. Test observations-mode proof tamper and missing files,
no fabricated pass, and progress regression/no_progress/pending distinctions.
Midterm: each terminal boundary and proof test. Final: launcher completion replay,
required full suite with unique committed log/result, then fresh diff review.
Supports Murphy 9/13; closes none until remaining package/diagnosis/item-8 work.
Main risk is mislabelling unfinished stress; tests use the existing classify and
stress_progress scored-vs-pending distinction rather than guessing from prose.
