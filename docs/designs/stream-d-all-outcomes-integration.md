# Fresh-batch diagnosis routes: integrated exam

Prove that a fresh case can finish every diagnosis route without bypassing the
package, admitting an extra writer, or losing its completed work. The existing
exams prove individual pieces; they do not join first-entry capture, real diagnosis,
writer admission, package completion and the next decision in one test.

## Scope and dependency

Base: land15 a169a40 plus the authorized lane-1 opt-in branch bc3c8a7, merged at
84a5649. Use job_config.diagnosis_enabled(c) from the current installed batch
manifest, never a global flag or a patched enabled predicate. This increment adds
an offline integration exam and updates item 7's evidence; no production routing,
allowance, scoring or activation change is intended. If the exam finds a production
defect, record it and include a concrete fix in the reviewed scope before claiming
completion. Retired/pre-schema cases never resume and get no new adapter.

## One test, explicit scenario table

Add tests/factory/test_stream_d_all_outcomes.py with one unittest method,
test_fresh_batch_all_outcomes, using named subtests and a fresh fixture per branch.
Mutually exclusive retirements cannot happen on one case; each branch starts a
new current-schema case, not a restored retired case. A shared lifecycle fixture
joins the same production calls for every branch. Do not call existing test
methods or simply aggregate their pass results.

The lifecycle driver follows the runner's sequence: job_config.install;
an authored initial completed ordinary stress receipt (specified below);
run.run_gates ordinary observation; stop handling plus run.finalize_accounting;
restore_ledger.install; diagnosis_dispatch.dispatch(comparison_route=True);
if returned ID is exactly int 0, real admit_extension; then real
extension_package.run. False (factory-bug ordinary resume) is not int 0. On
BudgetError/PauseRequested it sets stopped=True and uses main's exact branches:
FactoryBugHeldWait -> terminal_stop=factory_bug_held plus factory_bug_wait_reason;
provider_wait or cancelled with router_waits -> real write_provider_wait;
otherwise terminal_stop is paused for PauseRequested, else str(error), and
exhaustion_occurred ORs isinstance(error, BudgetError). Apply pause_terminal for
PauseRequested and main's budget_exhausted stress_review adjustment. Any other
Exception (including InfrastructureExhausted) sets error=type name and stopped;
terminal_stop is infrastructure_exhausted for InfrastructureExhausted, otherwise
runner_error:<type>; only InfrastructureExhausted ORs exhaustion_occurred. Every
path calls real finalize_accounting. Each subtest asserts its exact expected stop,
so an unexpected exception is a failure, not an accepted synthetic exhaustion. The fixture calls these real functions;
it does not replace main or add a production launcher. This is an offline route
integration exam, not VM boot, Linux containment, encryption or live qualification.
Branches that retire before package admission assert that package/writer calls
never occur; forcing a retired case into a package would be the wrong route.

Never stub dispatch/apply/admit_extension, entry/subsequent_entry, propose/admit/
complete, package.run, terminal producers/verifiers, comparison/progress, history,
limits, restore/install readers or diagnosis validation. Wrapping these functions
with call spies is allowed. No manually generated entry/outcome snapshots,
completed history rows, decisions or factory-bug resume admissions.

### Fixture and substitution boundary

Reuse saved practice case bytes and the 5813be ledger in
RuntimeTests (tests/factory/test_stream_d_runtime.py) and
InputTests (tests/factory/test_stream_d_inputs.py);
copy the setup helpers rather than inherit their test methods. The new fixture
has a new case identity and no inherited diagnosis, extension or factory-bug
history. Saved usage is a labelled accounting input, not old resume authority.
Use that InputTests' real worker-layout/restore installation and DispatchTests' actual
diagnosis task helper/validator (tests/factory/test_stream_d_dispatch.py) with
unprivileged OS substitutes. Use ConfigTests' (tests/factory/test_job_config.py)
manifest/config delivery construction: real batch manifest, worker/release hashes,
job_config.deliver and install. Include diagnosis_policy={schema:1, enabled:true}
in the pinned manifest. Before the enabled run, a separate disabled manifest must
leave dispatch at diagnosis_pending with zero diagnosis/writer calls. Card/env
policy flags grant no authority. No policy reader is patched.

Only external boundaries are authored: model CLI answers, router leases from the
offline router, UID/chown/pilot transport, checkpoint encryption/upload ACK, Docker
setup and gate answers lacking saved executables, plus the clock/runtime-revision
controls named in the table. The only authored initial receipt is the ordinary
pre-gate stress pass: use EntryTests.stress in tests/factory/test_stream_d_entry.py
as a shape reference, round=builder_rounds, report round-N.json, complete=True,
blocking=[], real run.attack_binding, review_attempt UUID and real report/binding
hashes, phase validated, next_phase gates. The fixture represents a fresh case's
completed initial writer/stress transport, not a retired checkpoint; it makes no
claim to test initial build(). Extension writer/stress always run through real
write_and_attack and pending_call. Diagnosis answers are written to
the real task's result.json, then validated/persisted by dispatch. Writer/stress
answers use ModelRuntime's _invoke transport seam and real pending_call,
reservations, complete_writer and stress receipts. Use the real public_progress
publisher with temporary SEALED. Gate substitution is explicit per branch:

| Branch family | Real science and authored controls |
| --- | --- |
| Partial/progress/capture recovery, extension cap, factory-bug comparison return/cap, irrelevant edit | Replace case.json with artifacts.REAL['suffix-case']['files']['case.json'] from invalid-runs-real.json.gz as EntryTests.saved_execution_controls does. G1 is an authored pass (never claim real G1 here). Real run.g4 uses execution('plain'); initial rejecting G5 uses execution('plain'), repaired G5 uses execution('reference'), both from the saved checkpoint transport. All other gates are authored pass/fail controls, including G3 and the named late frontier. |
| G1 rejected writer | Saved practice tree, actual run.g1, with args.source deliberately differing from case.json source as the existing real G1 rejection exam. Assert that exact diagnostic. Later gates are forbidden. |
| Early G5 / saved-cheat rejected writer | Suffix-case tree, authored G1/G15/G3 passes, real G4 plain and G5 plain rejection; saved-cheat variant uses the saved reference sample and actual verdicts with labelled guard transport. |
| Public match | Practice tree; authored gate/setup controls, real loop_freshness/retrieval/confirmation over invalid-runs-http.json.gz and authored fetch/reviewer answers, as PublicMatchTests. No real G5-pass claim. |
| Blocking/request-only stress, ordinary factory bug, malformed/not-converging/deadline and negative-proof branches | Practice tree with authored gate/setup controls unless an earlier row specifies a real check. Actual stress receipt validators and dispatch/package/terminal functions remain real. No fabricated retained snapshot. |

Use the real public_progress publisher with temporary SEALED. Saved-cheat rejection uses real saved reference execution/verdicts as in
EarlyWriterTests. No model/network/worker is launched.

Use real checkpoint-card serialization and restore_ledger.install at every new
exhaustion. Same- and cross-batch money transitions use installed current configs;
release/transport envelopes are authored, their validation is real. Cross-batch
manifest carry_from follows only the manifest/envelope shape of ResumeTests.transition
in tests/factory/test_stream_d_held.py. Do not copy its fabricated config_sha256
or its manual history write. Deliver the new config with its actual SHA, publish
restore-scorecard.json and restore-accounting.json through restore_ledger.install,
then call job_config.install to produce job-money-history from authenticated bytes.
Do not patch resume_factory_bug or install readers.

### Required branches and assertions

| Branch | Actual path and observable result |
| --- | --- |
| Partial entry, progress and completed replay | Ordinary stress pass and real G4 pass, budget_exhausted at G5's budget_boundary before invoke: no close marker, no G5 pass/fail label, and finalize_accounting must produce pending diagnosis_state. Close-to-passing diagnosis -> entry prefix -> reserved writer -> stress -> real G5 repaired result -> authored G16 failure. Completed package outcome advances the frontier; next diagnosis admits extension 2. Replay of each completed package uses the same records, no writer/stress/evaluator or extra reservation. |
| Capture recovery | Repeat that initial traversal with one-shot post-rename G1 sync failure; verification succeeds. Entry/dispatch/admission still use real proof; each gate executes once. |
| Unchanged and irrelevant edit | The second writer leaves the exact tree unchanged: terminal proof, next close-to-passing -> retired_no_progress before another reservation. A separate writer changing BUILD-NOTES.md only retains the same failing frontier under fixed gate controls and likewise retires; no progress is inferred from editing files. |
| Rejected writer | Separate G1, early G5 and saved-cheat controls through write_and_attack and package.run produce real retained rejection proof. Finalize -> queued diagnosis -> close-to-passing -> retired_no_progress. Replay never reruns the rejecting check; saved cheats are never scored as G6. |
| Confirmed public match | Real saved HTTP confirmation during package stress produces public-match proof, extension_incomplete, then retired_no_progress on close-to-passing. No gates after confirmation. |
| Blocking stress and request-only | Real category receipt producer with labelled blocking output completes a failed-stress package and next close-to-passing retires_no_progress. A separate reviewer-request-only answer without freshness metadata takes retired_stress_request_only directly. |
| Ordinary factory bug | Fresh case with no extension history: real exhaustion/finalization -> factory_bug diagnosis -> same-batch hold. Install fixed release/new batch, real dispatch returns exactly False, resume count 1, diagnosis_state cleared. The driver returns the ordinary-route sentinel without calling admit/package/writer. Assert those calls are forbidden. Ordinary build/validate_and_repair after this boundary remains covered by their existing tests, not claimed here. |
| Factory bug hold and return | After a completed progressing package, change one pinned scientific dependency to force current comparison. Use the existing synchronous IPC transport from ComparisonTests, with two authored InvalidInfra child-start failures inside real Evaluator/gate_attempt. Finalize -> real factory_bug diagnosis -> hold. Same-owner replay stays held with no new admission. Install fixed release/cross-batch config, then real dispatch restores extension-resume target; real entry/comparison/package continues without ordinary build. Count one durable resume and unchanged prior snapshot bytes. |
| Factory bug cap | Repeat the real hold/new-owner admission sequence three times; the fourth distinct finding takes retired_factory_bug_limit before model/package work. Do not seed the admissions file or lower the cap. A changed authored runtime_revision at each fixed release permits the existing infra journal's normal new-runtime retry. |
| Extension cap | Five genuinely admitted/completed progressing packages, with successive authored late-stage frontiers G16, G8, G9, G6, G13. A sixth close-to-passing reaches retired_extension_limit before entry/writer or reservation. Never synthesize history or lower LIMIT. |
| Not converging | Validated authored diagnosis -> retired_not_converging, zero writer/package admission. Replay is model-free and preserves decision bytes. |
| Malformed diagnosis | Invalid external answers on all real selected routes, including the existing schema-repair attempt, -> retired_diagnosis_malformed. Replay makes no further diagnosis or writer call. No journal is seeded. |
| Batch deadline | After a durable close-to-passing decision, advance the authored clock past the authenticated deadline before resume install: real job_config.install -> job_authority.read raises retired_batch_bound before dispatch, writer reservation or package. Assert the label at install. Never change the allowance or forge expired authority. |

Current-schema retired labels are exactly retired_not_converging,
retired_no_progress, retired_extension_limit, retired_factory_bug_limit,
retired_diagnosis_malformed, retired_stress_request_only and retired_batch_bound.
Assert the executed label set equals this explicit set. retired_import_estimate
and retired_import_history_unknown are excluded by the founder's retire-only
pre-schema decision; ttl_retired is an ordinary worker lifecycle stop, not a
diagnosis retired_* outcome. No fresh-case retirement is silently omitted.

For every terminal branch, replay from the saved card through real dispatch (and
package only when it returns an existing extension ID), checking stable history,
decision/proof bytes, operation IDs, resume counts and ledger reservations. Assert
no active reservation leaks and no duplicate exhaustion. For progress branches,
assert extension ID increments once and progress uses retained real snapshots.
For rejected/unchanged/public outcomes forbid Evaluator and writer_request on the
next retirement. For factory-bug return forbid ordinary build/validate_and_repair.
Use the existing comparison synchronous IPC transport, never mock compare or
Evaluator itself; process isolation remains for the founder's real pilot.

## Missing proof and completion claim

Include negative branches for a permanently missing record with a known card
score, corrupt support, and a budget interruption during G2 freshness mutation.
They must stay extension_comparison_pending, with no writer reservation or reroll.
These are evidence refusals, not fake scores or successful recoveries. Record
their remaining operational limitation explicitly in the final report; do not
claim those cases automatically recover or close Murphy rows. Partial missing
suffix and intact-record ACK recovery above are the supported fresh-case recoveries.

## Cost, phasing and review

No new spend or production mechanism; delete no existing tests or weaken their
assertions. One test/docs implementation commit, then full-suite evidence and pass
record. Midterm: the new integration file plus affected entry/dispatch fixtures.
Final: detached plain lockf /tmp/unbug-suite.lock, uv run --with numpy --with scipy
python -B tests/run.py, unique log/JSON record, 7200 seconds after lock acquisition;
then fresh diff review. Time the single integration method independently first:
expected 10–20 minutes, target at most 1200 seconds. Record its actual runtime;
combine with the prior 2828.8-second full-suite runtime when assessing the 7200s
budget. If the midterm exceeds 1200 seconds, report the timing before queuing the
suite; do not drop branches or weaken assertions to shorten it. At most two rounds each for design and diff, with any
round-2 blocker sent to parent in three lines. No push or main changes.

Estimate 4–6 engineering hours plus queue/reviews. Main risk is a harness that
bypasses the route it claims to test; real boundary spies, forbidden-call guards,
immutable byte checks and unsynthesized history prevent that. This integrates
item 7's covered current-schema routes; it does not activate any real batch or
claim Linux/VM/live qualification. Supports Murphy 9/13 and new-stream-d-current-comparison-1, closes none. The latter
remains open because this exam drives the real routing functions with an in-process
lifecycle driver and synthetic comparison IPC, not main plus archive restore in a
new worker process. It proves the target/decision chain but does not claim that
remaining worker-lifecycle qualification; name this limitation in the report.
The founder's
three-case real pilot follows only the parent's acceptance of this increment.
