# Stream D: current-version comparison before another extension

## Goal and scope

Decide whether the last extension improved the case under today's gates before
reserving another writer. Run any needed checks on retained copies, keep their
proof across a crash, and never replace a scored result with another roll.

This increment completes the runner side of item 6's comparison service and the
subsequent-entry producer required by item 7. First entry is already implemented.
It includes the routing change in diagnosis_dispatch.py, expressly authorized
by the parent on 2026-11-01. Base is fe182c2 (e2c2ea8 merged into this branch).
Activation stays false. Terminal writer rejection/unchanged and confirmed-public-
match package outcomes, live qualification, and whole-item-7 completion remain
out of scope. This supports Murphy rows 9 and 13 and closes none.

Today extension_compare.compare creates separate case/work copies and can retain
a version-matched comparison, but has no runner adapter. Calling run.gN directly
would use the live BENCH/results. extension_package.entry refuses all history.
The lane-1 guard deliberately stops a new exhaustion with an unresolved pair
before admission. This change replaces that hold with an explicit comparison
route; it does not turn the hold into permission to write.

The benefit is automatic, restart-safe progress decisions. The main risks are
cross-contamination of live evidence, lost usage receipts, stochastic rerolls,
and treating an incomplete comparison as regression. Existing snapshot,
Records, retry, authority, and admission validators remain the owners of those
decisions. No new allowance, extension, resume, or retirement rule is introduced.

## 1. Replace the pending-comparison routing boundary

Add keyword comparison_route=False to apply, replay and dispatch, forwarding it
through the dispatch/replay chain. Existing callers keep the conservative hold.
The main runner opts in with dispatch(..., comparison_route=True).

Only in apply's existing completed-prior-row / different-exhaustion branch:
when comparison_route and DIAGNOSIS_ENABLED are both true, return the ordinary
0 admission route regardless of the old pair's state. Persist the same diagnosis
scorecard first. Without opt-in or activation, retain the old pair check and
extension_comparison_pending hold exactly. The 0 means proceed to the entry
producer, not permission to reserve a writer. There is no new route class and
no second compare_entry call. Same-exhaustion completed-package replay and active
extension routes are unchanged. Factory-bug and not-converging branches never
use this route. All existing limits and attribution paths remain unchanged.

After ordinary model selection and bench startup, main's existing extension_id=0
branch calls admit_extension. Its entry call is the ONLY comparison producer,
and may run checks. A pending comparison raises extension_comparison_pending
before propose, writer_request or pending_call. No catch-and-continue is added.
A resolved old pair also passes through this same entry call: stale versions
cannot evade comparison. Existing main execution-mode exclusions still apply.

This explicitly replaces the table row and Merge correction paragraph in
stream-d-outcome-routes.md (currently lines 60–73). Keep non-opted-in guard tests
unchanged. Add opt-in integration tests showing that 0 reaches the producer and
that a pending producer prohibits every writer/admission call. The history-before-
card test retains both exhaustion IDs and its existing default refusal assertion.

## 2. Subsequent entry is a verified retained outcome

Keep the first-entry implementation intact. entry(c,r) selects a new internal
subsequent_entry when verified history is nonempty. Reject active rows, reused
diagnoses and the extension limit using the existing extensions eligibility
rules before evaluation. Require the live case tree to equal the retained
latest outcome tree. Do not update the live case to make it match.

Run extension_compare.compare(c, last.extension_id, r.BENCH, evaluator) inside
the evaluator's lifetime. It still owns common-version pinning, immutable
originals, snapshot production and retain_comparison. Select the resulting pair
with extensions.comparison_pair using the current vector. Rely on compare's existing _load checks over every scored receipt on its fast
path; do not add a second receipt verifier. Return a deep copy of the selected outcome with source_generation
rebound to job_authority.for_case(c).source_generation. No other field changes.

pending -> extension_comparison_pending. no_progress or regression ->
retired_no_progress (the same decision propose enforces). progress returns the
snapshot, and extensions.propose/verify_proposal remain mandatory before the
writer reservation. Missing/tampered retained scored proof stays pending, never
gets re-evaluated. Original snapshots/history rows are never rewritten.

## 3. Scientific version versus execution layout

Leave gate_state.py, scientific_version, ordinary gate-cache fingerprints and
all existing retained versions unchanged. This plumbing release must not
invalidate a one-worker pass. Test that an existing one-worker cache record
continues to load without recomputation or a new gate invocation.

The comparison service pins versions from the owner's original args/models as
it does today. Child runtime args independently use bench_workers=1 and
concurrent_roles=False; those are execution choices, not reasons to relabel a
receipt. Extend Records with optional expected_versions=None. Only the evaluator
passes the pinned current vector. Its load/save use that vector's stage value;
ordinary entry/package Records still recompute versions exactly as today. The
adapter checks source versions before every new invocation and after receiving
its result, and compare checks both original workspaces again before publication.
Thus a copied bench or execution-worker choice cannot silently select science.

Receipt provenance must report the actual serial execution. Add optional
execution=None to Workspace and compare (keyword-only in compare). The controller
passes {'bench_workers': 1, 'concurrent_roles': False}; _workspace deep-copies it.
_execution overrides only those two existing receipt fields; seed, slot and env
remain actual. Validate the exact override keys/types and include it in
_configuration so callbacks cannot change it. With None, all callers and receipt
bytes retain their existing behavior. Do not change Workspace.args or the version
vector to obtain serial execution. No execution_args API is added.

## 4. Isolated evaluator and process boundary

Add factory/extension_evaluator.py, exposing Evaluator(c,r,number) as a context
manager and callable (Workspace,stage)->(ok,detail,proof paths). It runs only
under the already authenticated owning job; it is not a launcher or public CLI.
No new machine, model worker, service or queue is created by this increment.

One OS child per phase runs gates serially. Use multiprocessing.get_context(
'fork') and a duplex Pipe on the Linux worker. No serialised credentials or
authenticated channel file is written. Fork only with no active model calls
and threading.active_count() == 1; reject a non-quiescent fork with
InvalidInfra before starting it. The child calls os.setpgid(0,0) before any work
and acknowledges its process-group ID to the parent.
The parent retains original runner globals. In the child only:
- set run.BENCH/COMPOSE to a private copied bench;
- put that bench's bin first on sys.path and evict only bench, factory_pool and
  claims, whose globals resolve bench paths; never evict run_validity;
- set BENCH in the child environment;
- set parallel_calibrators and g10_overlap_reason to serial choices;
- preserve the original factory module objects and exception classes; assert
  run_validity.InvalidInfra is extension_compare.InvalidInfra after imports.
Subprocess checkpoint/setup tools therefore import the copied bin modules.
No parent environment or sys.modules changes.

Private sources are copied, never linked, under
c.work/comparison-runs/<extension-id>/<identity>/bench.
Extract the existing bench_manifest inclusion predicate into a pure helper in
run.py and use it unchanged both for manifest hashing and source copying. Copy
all files included by that predicate, plus the factory source tree needed by
subprocess imports (excluding __pycache__). Excluded trees are never traversed.
Any symlink in the included source set is InvalidInfra; do not preserve or follow
it. No secret/credential paths are added to the source set. Verify the source
manifest equals c.manifest0 before copying, then compute bench_manifest over the
installed copy and require equality with c.manifest0 before a gate may run.
A missing file, changed source or bad copy is InvalidInfra, never a G1 failure.
Repeat checks on an existing copy and before its first stage in each process.

Identity is extensions.digest of schema_version=1, extension_id, both original
case hashes, and the ordered current version vector. The copy is atomically
installed; never refresh over existing execution evidence. Mutable bench results
and seed IDs are private. Docker services are exclusively used sequentially by
this job and freshly set up per phase. This does not claim concurrent-container
isolation. After comparison, ordinary execution must prepare live G3 again:
clear live c.early['G3'] and preparation markers before returning from the producer;
package.run already clears early G3 immediately before traversal. Test that the
live setup runs before any following live checkpoint after private G3 reseeds
shared Docker volumes. No live seed/result file is adopted from the private copy.

Determine phase from w.work.parent.name, requiring entry or outcome, and check
w.case against original[phase].case_sha256. Equal case hashes do not collapse
the phases: their names and roots stay distinct. Each phase has durable case/work directories under that identity, separate from
the immutable Workspace inputs and from the other phase. Initial case bytes come
from Workspace.case, verified against the original snapshot digest. They are
never overwritten on resume. A phase manifest has exact keys schema_version,
identity, phase, case_sha256, observation_id (UUID4), round_number. Use safe
readers and reject symlinks. Round is the admitted row round.

The runtime context is a shallow copy of the owner with independent args, card
and models, case/work set to these phase paths, and no inherited early, votes,
pilot_passes, role_cancel, audit attributes, or live scientific cache. Keep
authenticated job configuration, ledger path and source_generation. Set
accounting_work to the owner's work path. The scientific card starts with roles,
case identity and builder_rounds; operational authorization state is copied.
Records uses the phase observation_id, retaining the existing scientific card/
context projection and support collector.

The child receives only stage requests. It replies with result or typed stop,
and can request a parent checkpoint. Parent never trusts a result without
loading its durable Records envelope and copying its verified support to
Workspace.work under evaluator-support/<stage>/... before returning proof paths.
No pickle file is accepted from disk; Pipe is an inherited private channel.
Only BudgetError, InvalidInfra and CaseProblem are translated to their existing
types; other child exceptions become a diagnostic RuntimeError, not a fail.
Unexpected child death is InvalidInfra, hence pending. No partial reply scores.
The parent uses processes.kill_tree while the child leader still exists, then
os.killpg(child.pid, SIGKILL) and join, never its own group. Cooperative child
shutdown runs pilot disposal first: stop_pilot for each pilot_homes user (which
uses sudo pkill and diagnosis_task._quiet), removes pilot walls, and disposes
homes through ordinary archive_pilot_state. Model subprocess ownership stays
with budget/processes.run and their existing finally/kill_tree paths. Parent
repeats privileged stop_pilot checks after child death, including forced death.

Before fork the parent becomes a Linux child subreaper using prctl
(PR_GET_CHILD_SUBREAPER=37, PR_SET_CHILD_SUBREAPER=36), saving the previous value
and restoring it after final cleanup. No other subprocess owner may run in the
parent during the evaluator lifetime except its synchronous checkpoint helpers.
Double-forked or detached orphans are then reparented to this owner instead of
escaping to init. A failure to enable subreaping is InvalidInfra before any child.

After joining the phase leader, enumerate the parent's remaining children and
descendants using numeric ps pid/ppid/pgid fields only. Use processes.kill_tree
for surviving owned leaders, and privileged stop_pilot for cross-user work. Reap
adopted children with waitpid(WNOHANG), repeat until no descendants remain, and
refuse after a bounded 30 seconds if any survive (raise InvalidInfra; do not
start another phase or writer). Exclude only the synchronous ps probe itself.
Never signal the parent's own group. The single-thread/exclusive-owner precondition
makes these descendants comparison-owned; publication subprocesses must already
have joined before cleanup. A child dying before its group acknowledgement is
still reaped through this same mechanism. Cancellation propagates only after
cleanup. Phase work remains durable. No Popen wrapper or process registry is added.

Production process execution is Linux-only. Pure producer/routing/record tests
run on all platforms. Fork/descendant tests run on Linux; on macOS they exercise
the protocol through a synchronous authored process transport and explicitly
skip the real-fork exam. This limitation is recorded in the suite and item-8
Linux qualification obligation; do not pretend a macOS fork test ran.

## 5. Stage execution, capture and recovery

Keep comparison.snapshot's current REUSABLE pass policy; do not relabel an old
opaque receipt as current. Each requested stage first checks its durable Records
record before entering the retry journal. A valid same-version pass OR fail is
returned without invoking the gate again. Restore its card/context projection.
Missing records run through gate_attempt.execute with attempts=2,
interruption=BudgetError and the phase infra-attempts.json. Use the ordinary
gate identity fields plus comparison identity/phase. publish forwards operational
state/elapsed/reused events to the parent publisher, never a child gate status on
the live card. record_crash writes a numbered phase-local gate-details/<stage>.
crash-N.json with the same type/message/traceback diagnostics as the pipeline. Capture inside invoke,
persisting proof before returning. Pending-shaped results write no scored
record and return pending. Infrastructure exhaustion is never regression. On gate_attempt's crashed outcome,
raise BudgetError('infrastructure_exhausted') to the parent, set its existing
infrastructure_gate to the stage and retain the phase-local diagnostic path.
Main's ordinary handler sets new_exhaustion and record_exhaustion queues diagnosis.
Do not publish a scored pair or silently retry the exhausted journal. A new
scientific version gets a new identity/journal; the same exhausted identity remains
held for the ordinary factory-bug diagnosis/fix route. This does not grant an
extra infrastructure attempt.

Use real r.g1 ... r.g17, not the writer/repair loop. G3 machine setup runs once
in each new child before any fresh measured gate; if its scored record exists,
restore the saved scientific result but still perform setup, as package replay
does. Later restores preserve fresh G3 preparation fields. G1 statement and
G8/G10 context are restored from Records on resumed stages. When snapshot reuses
an older pass without calling the evaluator, no fresh context is assumed:
G9 can obtain its ordinary retained panel answer, G10 runs unless its new durable
record is present, and G11 follows G10's newly restored context. No early probe,
parallel overlap, writer repair, seal pass or delivery publication runs in child.

stress uses the ordinary stress_categories function with a persistent independent
attack-state.json, operation ID and report under the phase work. Build the same
review receipt and completion callback as write_and_attack's stress-only segment,
then call attack_report and loop_freshness and apply its existing complete,
blocking and unfinished-diagnostic rules. Never call write_and_attack or consume
a writer round. Use the factory_waste comparison scope specified below. Stress freshness
public match is a scored stress failure with confirmed proof; unresolved
freshness remains pending. Supporting artifacts use Records.sources('stress').

G2 calls ordinary g2, including its existing evidence-refresh policy. The
evaluation case is an independent working copy: only freshness.jsonl may change
as derived search evidence. All other case bytes must remain identical to the
immutable input before every record publication. Retain refreshed freshness.jsonl
with the stage support. Workspace.case and retained originals never change.
A scientific input edit by any evaluator is pending and cannot publish a record
or pair. This is not permission to repair the bug. Subsequent gates in that phase
see the derived freshness evidence. On resume it remains in the phase case.

## 6. Shared accounting and checkpoints

Money remains the original ledger and authenticated B channel. Add
model_runtime.accounting_work(c) returning getattr(c,'accounting_work',c.work).
Use it only for reservation reconciliation, usage-receipt creation/read,
complete_invocation and the usage receipt checks in ModelRuntime.call.
Transcripts, ordinary-retry journals and model output stay in phase work.
The shared ledger and root usage-receipts survive even a SIGKILL before IPC.
Do not change budget.py validators or broaden receipt path acceptance.

Factory-waste comparison scopes use an explicit comparison=True parameter on
attempt/Attempt (default False); comparison=True forces link=None and NEVER calls
resume_scope or classify. They may publish their own invalid-infra factory-failures
proof, but never factory-replays. All ordinary callers retain default behavior.
The comparison scope uses a shallow owner context with work=accounting_work
when the attribute is present, so factory-failures/factory-replays and causal
reservation linkage remain in the original private root. Case hash and stage
still describe the evaluated revision. Existing ordinary attribution uses exactly
the old path and behavior. Do not reclassify comparison spend merely because
it is comparison work.

The child never seals its scientific scorecard. Its public progress callback
sends operational events to the parent; parent uses the ordinary publisher.
After model completion and after stage-record publication, send operational
effects (route_receipts, cleanup_errors, models_used, router waits/interrupted
calls, budget-resume flags) followed by a checkpoint request. Effects are
append-only/deduplicated by existing stable receipt identifiers; never copy
scientific keys, diagnosis/history, terminal labels or allowance fields.
Persist that operational message in phase work atomically before sending it;
parent drains it on resume before admission or final accounting.

The parent checkpoints the original owning context with ordinary
checkpoint_progress(c,r.seal,quiescent=True). Stress category publication requests
use interval=0 and require remote_durable as today; failure returns to the
ordinary publication retry path. No model is active at these boundaries.
Automatic child _opencode checkpointing is replaced with this parent callback,
not disabled without replacement. The whole comparison-runs tree is inside
the ordinary seal, so phase records and retry state travel on the normal restore.

Completed pairs are served before creating child processes or consulting money.
For unfinished comparisons, existing budget/deadline/provider/cancel boundaries
remain active. Propagate money_wait/provider_wait/retired_batch_bound; do not
translate them to scientific failure. Parent final accounting still runs normally.

Keep in-progress roots for retry. After a completed pair and a successful parent
checkpoint, remove its private bench copy and phase scratch, retaining only the
published comparison proof and root accounting receipts/transcripts. Move phase
transcripts into the original private archive before removal. Never remove
extension-snapshots. Older unfinished identities stay until a current completed
pair is checkpointed, then may be removed together. A cleanup failure cannot
change the scored pair or cause re-evaluation.

## 7. Files and implementation phases

1. Stable commit: pinned evaluator record versions; accounting-root helper; isolated
   evaluator, process protocol and durable stage capture; focused tests.
   Existing entry and routing still hold. No activation change.
2. Stable commit: subsequent_entry; opted-in existing admission routing and main
   integration; integration tests and checklist. No alternate launch path.
3. Commit the full-suite record, then obtain a fresh diff review.

Files: new factory/extension_evaluator.py and
tests/factory/test_stream_d_comparison.py; modify extension_package.py,
extension_compare.py (execution metadata only), model_runtime.py,
factory_waste.py, diagnosis_dispatch.py and the small main seam in run.py.
Update stream-d.md and stream-d-outcome-routes.md plus this design/reviews/reports.
Do not alter extension limits, resume attribution validators, activation or
Murphy status. Delete the unconditional history refusal in entry, replacing it
with the verified subsequent-entry path; delete no safety test.

## 8. Tests and exams

All model/HTTP/Docker transports are authored substitutes and labelled. No live
models or factory workers run for this increment. Reuse saved practice case and
HTTP/plain/reference/invalid checkpoint fixtures from test_stream_d_execution,
test_stream_d_entry and test_extension_compare. Do not generate expected receipt
bytes with the implementation under test.

- Actual process isolation: real G1 in a child over the saved practice case;
  real G4/G5 using saved checkpoint transports. Assert parent globals/env, live
  case/work cache and original snapshot bytes unchanged; all bench output paths
  private; entry/outcome work paths distinct. Record actual child PID.
- A single changed gate version: reusable unchanged passes kept; only required
  evaluations invoked; both versions equal current vector. Preserve original
  snapshots. Model/settings/prompt drift gets a new identity, never rewritten
  saved records. Pinned owner versions survive serial child execution; existing one-worker cache
  records still load with no version or fingerprint change.
- New phase with real G3 and authored Docker responses establishes setup before
  any fresh checkpoint. Resume after G10 record restores G10 context, reruns
  setup, invokes fresh G17/G11 only. G8 votes and pilot paths remain phase-local.
- Real G2 over saved HTTP evidence and a labelled independent answer, with
  freshness evidence refresh confined to the phase copy. Semantic mutation is
  pending; immutable Workspace and live case hashes unchanged.
- Real stress_categories with authored category answers: completed/blocked,
  interrupted publication, retry, confirmed public match and unresolved
  confirmation. Zero writer requests/round increments.
- Kill before/after stage record, after entry phase, after pair proof and before
  history append. A committed rejection never reruns; stale retry journal plus
  record replays. Incomplete execution remains pending, never no_progress.
- Missing/tampered/symlink record or support stays pending without new invocation.
  Previously scored retained pair stays authoritative. Repeated completed compare
  starts no child/model, makes no money check and returns identical evidence.
- Shared authenticated ledger under offline router fixtures from
  test_stream_d_dispatch/test_model_runtime: real reservation/settlement, root
  usage receipts on a killed child, unchanged caps and resumed source-generation,
  factory-failure proof still eligible and no invented waste attribution.
- Parent checkpoint callback archives only live owner state plus private
  comparison evidence; no child gate/status/card fields leak. Publication
  acknowledgement fails closed and retries only publication.
- Dispatch opt-in route reaches the sole entry producer before admission; pending producer
  forbids writer_request and pending_call. Non-opted-in guard still raises.
  Same-exhaustion package replay remains unchanged. A current progress pair
  returns selected outcome and proposes exactly the next ID, while regression/
  no-progress retire and pending holds.
- Run every existing outcome-route, factory-bug attribution, ordinary retry,
  history-before-card and first-entry test without weakening assertions.
- Final exam: uv run --with numpy --with scipy python -B tests/run.py, unique
  docs/reports/stream-d-current-comparison-suite-<UTC>-<uuid>.log and .json,
  record HEAD/tree, exact command, start/end, exit, script totals and log sha256.

One design/implementation cycle with two stable code commits, followed by the
full suite and independent diff review. Engineering cost is the isolated adapter
and its crash tests; execution cost is only changed/non-reusable checks under
the existing job money bound. Live time/cost and comparison activation remain
item-8 qualification obligations. No performance or cost claim is made from
offline fixtures. Source copying is expected to add tens of MB per active
comparison, and only one shared private bench copy is retained per identity.
Measure included source bytes in the implementation report; run_artifacts streams
the archive and r2_upload uses the existing single PUT with its 1800-second bound.
There is no local size cap in that uploader. Provider upload size/time is a live
qualification obligation, not an offline guarantee; keep it on item 8. Midterm is process isolation plus crash/receipt tests; final
is routed progress/pending/retirement, accounting, and the full suite.


## Round-1 review resolution and added exams

B1–B6 are accepted; the body above replaces their original text. The objective
for the operator is to decide automatically, without rerunning anything already
scored, whether the last extra writer round moved the case forward.

Additional required tests: a missing private manifest file yields pending, never
G1 fail; source symlinks refuse; lazy-imported InvalidInfra stays the same class;
a detached grandchild is killed or blocks the next phase; active thread refuses
fork; a saved factory-bug resume whose stage/hash matches the comparison must
produce no factory-replays and never call classify. Existing attribution tests
remain unchanged. Test infrastructure exhaustion through main final accounting
queues a new pending diagnosis rather than silently re-entering comparison.

compare still evaluates outcome after an entry-side pending result; leave that
existing policy unchanged in this increment. It can spend on the other side, but
durable stage records retain that work. Completed-pair proof verification remains
compare's existing fast-path check, not a duplicate subsequent_entry validator.
