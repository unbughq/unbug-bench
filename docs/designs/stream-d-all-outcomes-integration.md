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
run.run_gates ordinary observation; stop handling plus run.finalize_accounting;
restore_ledger.install; diagnosis_dispatch.dispatch(comparison_route=True);
if returned ID is exactly int 0, real admit_extension; then real
extension_package.run. False (factory-bug ordinary resume) is not int 0. On
BudgetError it sets the same stopped/terminal_stop/exhaustion_occurred fields
as main and calls finalize_accounting. The fixture calls these real functions;
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

Reuse saved practice case bytes and the 5813be ledger in RuntimeTests/InputTests;
copy the setup helpers rather than inherit their test methods. The new fixture
has a new case identity and no inherited diagnosis, extension or factory-bug
history. Saved usage is a labelled accounting input, not old resume authority.
Use InputTests' real worker-layout/restore installation and DispatchTests' actual
diagnosis task helper/validator with unprivileged OS substitutes. Use ConfigTests'
manifest/config delivery construction: real batch manifest, worker/release hashes,
job_config.deliver and install. Include diagnosis_policy={schema:1, enabled:true}
in the pinned manifest. Before the enabled run, a separate disabled manifest must
leave dispatch at diagnosis_pending with zero diagnosis/writer calls. Card/env
policy flags grant no authority. No policy reader is patched.

Only external boundaries are authored: model CLI answers, router leases from the
offline router, UID/chown/pilot transport, checkpoint encryption/upload ACK, Docker
setup and gate answers lacking saved executables. Diagnosis answers are written to
the real task's result.json, then validated/persisted by dispatch. Writer/stress
answers use ModelRuntime's _invoke transport seam and real pending_call,
reservations, complete_writer and stress receipts. Use the real public_progress
publisher with temporary SEALED. G1 uses the practice contract; G4/G5 use
invalid-runs-real.json.gz via the existing saved checkpoint transport and actual
run.g4/run.g5. Other pass/fail controls are named as authored, including G3 setup
and G16 onward. Public-match uses invalid-runs-http.json.gz, the real retrieval and
confirmation validators, and authored fetch/reviewer answers as in PublicMatchTests.
Saved-cheat rejection uses real saved reference execution/verdicts as in
EarlyWriterTests. No model/network/worker is launched.

Use real checkpoint-card serialization and restore_ledger.install at every new
exhaustion. Same- and cross-batch money transitions use installed current configs;
release/transport envelopes are authored, their validation is real. Cross-batch
manifest carry_from and job-money-history follow ResumeTests.transition's shape,
but go through job_config.install rather than patching resume_factory_bug.

### Required branches and assertions

| Branch | Actual path and observable result |
| --- | --- |
| Partial entry, progress and completed replay | Ordinary stress pass and real G4 pass, money_wait at G5: no close marker. Close-to-passing diagnosis -> entry prefix -> reserved writer -> stress -> real G5 repaired result -> authored G16 failure. Completed package outcome advances the frontier; next diagnosis admits extension 2. Replay of each completed package uses the same records, no writer/stress/evaluator or extra reservation. |
| Capture recovery | Repeat that initial traversal with one-shot post-rename G1 sync failure; verification succeeds. Entry/dispatch/admission still use real proof; each gate executes once. |
| Unchanged and irrelevant edit | The second writer leaves the exact tree unchanged: terminal proof, next close-to-passing -> retired_no_progress before another reservation. A separate writer changing BUILD-NOTES.md only retains the same failing frontier under fixed gate controls and likewise retires; no progress is inferred from editing files. |
| Rejected writer | Separate G1, early G5 and saved-cheat controls through write_and_attack and package.run produce real retained rejection proof. Finalize -> queued diagnosis -> close-to-passing -> retired_no_progress. Replay never reruns the rejecting check; saved cheats are never scored as G6. |
| Confirmed public match | Real saved HTTP confirmation during package stress produces public-match proof, extension_incomplete, then retired_no_progress on close-to-passing. No gates after confirmation. |
| Blocking stress and request-only | Real category receipt producer with labelled blocking output completes a failed-stress package and next close-to-passing retires_no_progress. A separate reviewer-request-only answer without freshness metadata takes retired_stress_request_only directly. |
| Factory bug hold and return | After a completed progressing package, change one pinned scientific dependency to force current comparison. Use the existing synchronous IPC transport from ComparisonTests, with two authored InvalidInfra child-start failures inside real Evaluator/gate_attempt. Finalize -> real factory_bug diagnosis -> hold. Same-owner replay stays held with no new admission. Install fixed release/cross-batch config, then real dispatch restores extension-resume target; real entry/comparison/package continues without ordinary build. Count one durable resume and unchanged prior snapshot bytes. |
| Factory bug cap | Repeat the real hold/new-owner admission sequence three times; the fourth distinct finding takes retired_factory_bug_limit before model/package work. Do not seed the admissions file or lower the cap. A changed authored runtime_revision at each fixed release permits the existing infra journal's normal new-runtime retry. |
| Extension cap | Five genuinely admitted/completed progressing packages, with successive authored late-stage frontiers G16, G8, G9, G6, G13. A sixth close-to-passing reaches retired_extension_limit before entry/writer or reservation. Never synthesize history or lower LIMIT. |
| Not converging | Validated authored diagnosis -> retired_not_converging, zero writer/package admission. Replay is model-free and preserves decision bytes. |
| Malformed diagnosis | Invalid external answers on all real selected routes, including the existing schema-repair attempt, -> retired_diagnosis_malformed. Replay makes no further diagnosis or writer call. No journal is seeded. |
| Batch deadline | After a durable close-to-passing decision, advance the authored clock past the authenticated deadline: retired_batch_bound before writer reservation/package. Never change the allowance or forge expired authority. |

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
then fresh diff review. At most two rounds each for design and diff, with any
round-2 blocker sent to parent in three lines. No push or main changes.

Estimate 4–6 engineering hours plus queue/reviews. Main risk is a harness that
bypasses the route it claims to test; real boundary spies, forbidden-call guards,
immutable byte checks and unsynthesized history prevent that. This integrates
item 7's covered current-schema routes; it does not activate any real batch or
claim Linux/VM/live qualification. Supports Murphy 9/13, closes none. The founder's
three-case real pilot follows only the parent's acceptance of this increment.
