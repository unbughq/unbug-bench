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

Add keyword comparison_route=False to apply, replay, dispatch, _dispatch and
invoke. Forward it at every edge: dispatch -> _dispatch; _dispatch -> replay ->
apply; _dispatch's valid-journal branch -> apply; and _dispatch -> invoke -> apply
for a fresh diagnosis. Test all three apply call sites, including fresh invoke. Existing callers keep the conservative hold.
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

Keep the first-entry implementation intact. At entry's existing
if extensions.read(owner) branch, before its evidence-mapping try block, call
subsequent_entry(c,r) with the LIVE runner context c, not the copied owner.
Every operational marker, checkpoint and early-G3 reset below targets this live
c. Neither entry's copy nor compare's internal owner copy receives these effects.
The first-entry evidence mapping must not catch subsequent_entry exceptions. Reject active rows, reused
diagnoses and the extension limit using the existing extensions eligibility
rules before evaluation. Require extensions.digest(extensions.tree(c.case)) to equal the retained latest
outcome case_sha256, including freshness.jsonl. A mismatch raises
extension_snapshot_changed, as verify_proposal does. Do not use semantic
run.case_hash or update live bytes to make them match.

Run extension_compare.compare(c, last.extension_id, r.BENCH, evaluator) inside
the evaluator's lifetime. It still owns common-version pinning, immutable
originals, snapshot production and retain_comparison. Select the resulting pair
with extensions.comparison_pair using the current vector. Rely on compare's existing _load checks over every scored receipt on its fast
path; do not add a second receipt verifier. Return a deep copy of the selected outcome with source_generation
rebound to job_authority.for_case(c).source_generation. No other field changes.

A pending producer result follows the exhaustive recovery table below; it never
ends as extension_comparison_pending on the opted-in production route.
no_progress or regression ->
retired_no_progress (the same decision propose enforces). progress returns the
snapshot, and extensions.propose/verify_proposal remain mandatory before the
writer reservation. Missing/tampered scored proof in a previously retained comparison keeps compare's
existing pending return and never gets re-evaluated. Evaluator Records errors
are distinct: extension_snapshot_changed and extension_reservation_mismatch
propagate as evidence stops; ordinary Records retain their version-mismatch label; evaluator identity/version
mismatch maps to extension_snapshot_changed as specified in the recovery table.
Do not translate malformed envelopes/support to InvalidInfra or retry them. Original snapshots/history rows are never rewritten.

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
__enter__ records configuration only. Copy installation, manifest validation,
subreaper enablement and child startup are lazy inside the first parent evaluator
invoke; a verified completed-pair fast path starts no setup or processes.

One OS child per phase runs gates serially. Use multiprocessing.get_context(
'fork') and a duplex Pipe on the Linux worker. No serialised credentials or
authenticated channel file is written. Fork only with no active model calls
and threading.active_count() == 1. Wait up to 30 seconds for leftover diagnosis
threads to exit, checking cancellation and deadline, before refusing the fork.
Refusal raises InvalidInfra INSIDE the parent attempt and consumes that attempt;
a subsequent retry can wait again. No active model calls are allowed during this
wait. A daemon that exits within the bound is accepted. The child calls os.setpgid(0,0) before any work. Immediately rebind r.seal to a
stub raising RuntimeError('child seal'), then acknowledge its process-group ID.
The parent runner module is unaffected by the fork-local rebinding. Here r is
the passed runner object (normally sys.modules['__main__']); apply child-only
seal/_opencode/BENCH/COMPOSE and serial rebindings to it and also to sys.modules[
'run'] if a second runner module has been imported.
The parent retains original runner globals. In the child only:
- set run.BENCH/COMPOSE to a private copied bench;
- put that bench's bin first on sys.path and evict only bench, factory_pool and
  claims, whose globals resolve bench paths; never evict run_validity;
- set BENCH in the child environment;
- set run.parallel_calibrators = lambda c: False and
  run.g10_overlap_reason = lambda c: 'comparison serial';
- preserve the original factory module objects and exception classes; assert
  run_validity.InvalidInfra is extension_compare.InvalidInfra after imports.
  After eviction, fail InvalidInfra if any module other than run_validity and
  processes still has __file__ under the original bin directory. This explicit
  fail-closed allowlist catches future path-bound in-process imports.
Subprocess checkpoint/setup tools therefore import the copied bin modules.
No parent environment or sys.modules changes.

Private sources are copied, never linked, under
c.work/comparison-runs/<extension-id>/<identity>/bench.
Extract the existing bench_manifest inclusion predicate into a pure helper in
run.py and use it unchanged both for manifest hashing and source copying. Copy
all files included by that predicate, plus the factory source tree needed by
subprocess imports (excluding __pycache__). Excluded trees are never traversed.
For an included symlink, accept only a relative link whose fully resolved target
is a regular file inside the source root AND in the included file set. Materialize
its target bytes as a regular file at the link's relative destination (including
the real CLAUDE.md -> AGENTS.md link). Reject absolute, escaping, dangling,
cyclic, directory or excluded-target links as InvalidInfra. No destination
symlinks are created. No secret/credential paths are added to the source set. Verify the source
manifest equals c.manifest0 before copying, then compute bench_manifest over the
installed copy and require equality with c.manifest0 before a gate may run.
A missing file, changed source or bad copy is InvalidInfra counted by the parent
attempt, never a G1 failure.
Repeat checks on an existing copy and before its first stage in each process.
Also hash the copied factory tree separately: ordered relative file names and
sha256 values using the same inclusion/symlink materialization rule, excluding
__pycache__. Retain that digest in the installed-source manifest and require
source/copy equality before execution; scientific-vector checks are additional,
not a replacement for full copied-source integrity.

Identity is extensions.digest of schema_version=1, extension_id, both original
case hashes, and the ordered current version vector. The copy is atomically
installed; never refresh over existing execution evidence. Mutable bench results
and seed IDs are private. Docker services are exclusively used sequentially by
this job and freshly set up per phase. The fixed unbug-bench Compose project and
unbug-bench-medusa:latest image tag are shared; private G3 rebuilds that tag from
manifest-identical source, not a distinct concurrent application. This does not claim concurrent-container
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
pilot_passes, role_cancel, audit attributes, or live scientific cache. Remove recipient from the phase context explicitly. Keep authenticated job
configuration, ledger path and source_generation. Set c.stress_checkpoint to
send an owner-checkpoint request over Pipe and return the parent's remote_durable
boolean. Never put an encryption key or R2 destination into the phase context. Set
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
Unexpected child death is InvalidInfra inside the parent attempt. No partial reply scores.
The parent uses processes.kill_tree while the child leader still exists, then
os.killpg(child.pid, SIGKILL) and join, never its own group. Cooperative child
shutdown runs pilot disposal first: stop_pilot for each pilot_homes user (which
uses sudo pkill and diagnosis_task._quiet), removes pilot walls, and disposes
homes through ordinary archive_pilot_state. Model subprocess ownership stays
with budget/processes.run and their existing finally/kill_tree paths. Parent
repeats privileged stop_pilot checks after child death, including forced death.

Before fork the parent becomes a Linux child subreaper using
ctypes.CDLL(None, use_errno=True).prctl
(PR_GET_CHILD_SUBREAPER=37, PR_SET_CHILD_SUBREAPER=36), saving the previous value
and restoring it after final cleanup. Clear errno before each call; a nonzero
return or nonzero errno is InvalidInfra, including failure to restore. No other subprocess owner may run in the
parent during the evaluator lifetime except its synchronous checkpoint helpers.
Double-forked or detached orphans are then reparented to this owner instead of
escaping to init. A failure to enable subreaping is InvalidInfra before any child.

After joining the phase leader, enumerate the parent's remaining children and
descendants using numeric ps pid/ppid/pgid fields only. Use processes.kill_tree
for surviving owned leaders, and privileged stop_pilot for cross-user work. Reap
adopted children with waitpid(WNOHANG) until no descendants remain.
Each kill_tree retains its existing 60-second ps allowance. After the last
kill_tree returns, allow a total of 30 seconds for numeric verification/reaping,
with each verification probe bounded by the remaining time. Any probe timeout
means quiescence is unproved (survivors present), not success. If the verification
window expires, raise InvalidInfra and do not start another phase or writer. Exclude only the synchronous ps probe itself.
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
The PARENT owns gate_attempt.execute for each stage, with attempts=2,
interruption=BudgetError and the durable phase infra-attempts.json. Its invoke
performs lazy phase setup, sends one request and waits for the reply. Child death,
IPC failure, invalid copy/manifest, fork/quiescence/subreaper/cleanup failure
raise InvalidInfra inside invoke and are counted. Before retry, finish cleanup;
start a fresh phase child and re-run machine setup as required. The child owns
no second gate_attempt journal. It evaluates once and commits Records before
replying. A committed record is checked before entering the parent journal,
including after a lost reply; replay it rather than invoking again.

Use ordinary gate identity fields plus comparison identity/phase. publish
forwards only operational state/elapsed/reused events. record_crash writes
numbered phase-local gate-details/<stage>.crash-N.json with type/message/traceback.
A pending-shaped returned gate result is InvalidInfra inside invoke, not a saved
score. A stress freshness hold follows the recovery table below. The parent
checks returned proof and source versions before returning a scored tuple.

On gate_attempt's crashed outcome, for a G stage the LIVE PARENT c sets
c.card['infrastructure_gate'] = {'gate': stage, 'error_type': error_type,
'classification': 'invalid-infra', 'exhausted': True,
'diagnostic': retained_diagnostic_relative_path}, then raises
BudgetError('infrastructure_exhausted'). For stress set no infrastructure_gate
and raise BudgetError('stress_validation_exhausted'). These labels pass main's
new_exhaustion accounting into record_exhaustion. No child terminal/card fields
are copied through the effects channel. A scientific version or retry runtime
revision change follows existing journal identities; unchanged exhausted journals
never acquire extra attempts. A new diagnosis does not itself reset a journal.

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
a writer round. The parent owns the factory_waste comparison scope specified below; no child scope is opened. Stress freshness
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

Parent-owned factory-waste comparison scopes wrap each stage invoke. Before
starting IPC, snapshot the shared ledger reservation IDs; in invoke's finally,
read new reservation rows and call factory_waste.record_reservation on each while
the parent scope is active, before propagating the result/error. Exclusive case
ownership and no concurrent model calls ensure these rows belong to this attempt.
Thus child death does not discard causal reservation linkage. Never infer spend
from timestamps or public card totals. The child opens no publishing factory-waste scope. It uses the forwarding scope
specified in the round-4 binding section, replacing the inherited parent object.
The parent uses an explicit comparison=True parameter on
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
The child-only evaluator wraps run._opencode: call the original; after a successful
return, durably send effects and request exactly one normal parent checkpoint
for non-user, non-stress_category_call serial calls. Removing recipient prevents
the original _opencode checkpoint. The wrapper does not checkpoint twice through
on_complete. stress_category_call uses c.stress_checkpoint through the ordinary
category publication barrier instead. The run.seal trap catches every accidental
child seal, including _gate_completed if mistakenly called. Thus automatic
checkpointing is replaced at a named seam, not disabled without replacement. The whole comparison-runs tree is inside
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
extension_compare.py (execution metadata and extracted existing fast-path verifier), model_runtime.py,
factory_waste.py, diagnosis_dispatch.py, diagnosis.py (selected comparison
crash inputs only) and the small main/manifest-helper seams in run.py.
Update stream-d.md and stream-d-outcome-routes.md plus this design/reviews/reports.
Do not alter extension limits, resume attribution validators, activation or
existing Murphy statuses; add only the explicitly deferred static-review row below. Delete the unconditional history refusal in entry, replacing it
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
- Missing/tampered/symlink evaluator record or support raises its evidence-stop
  label without new invocation. A missing not-yet-executed stage remains pending
  only for an interrupted execution; missing authoritative committed records
  are never permission to reroll.
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
G1 fail; the real repository copy materializes CLAUDE.md safely and matches the
source bench_manifest, while unsafe symlinks refuse; lazy-imported InvalidInfra stays the same class;
a detached grandchild is killed or blocks the next phase; active thread refuses
fork; a saved factory-bug resume whose stage/hash matches the comparison must
produce no factory-replays and never call classify. Existing attribution tests
remain unchanged. Test infrastructure exhaustion through main final accounting
queues a new pending diagnosis rather than silently re-entering comparison.

compare still evaluates outcome after an entry-side pending result; leave that
existing policy unchanged in this increment. It can spend on the other side, but
durable stage records retain that work. Completed-pair proof verification remains
compare's existing fast-path check, not a duplicate subsequent_entry validator.

## Round-2 review resolution and diagnostic handoff

N1–N3 and M1–M5 are accepted and incorporated above. Add two exact checkpoint
exams: a child G2 non-user model completion produces exactly one parent
checkpoint; a completed stress category publication produces exactly one forced
parent checkpoint. Child SEALED/R2 adapters raise if touched. Inspect the owner
card passed to sealing for absence of phase gate/status fields.

On exhaustion the parent copies the phase infra-attempts.json, phase manifest,
and gate-details/*.crash-*.json to
work/comparison-diagnostics/<identity>/<phase>/, preserving bytes via safe readers.
Publish a small index with extension_id, phase, pinned versions and evaluated
case_sha256; no verdict is synthesized. Add comparison-diagnostics to the selected
work roots in diagnosis._write_input_tree. Do not add the private bench or whole
comparison-runs tree. queued_inputs must carry these exact files and hashes so
the reviewer can distinguish a comparison failure from ordinary gate evidence.

Expected path is one normal resumed launch that diagnoses and completes comparison
then admits, without an extra coordinator relaunch. A provider/money interruption
uses the existing bounded relaunch policy, not a new allowance. Infrastructure
exhaustion queues diagnosis with the above crash/journal inputs; a repeated
close_to_passing decision at unchanged runtime cannot reset that exhausted journal
and remains an infrastructure stop. A factory-bug decision is held under the existing workflow, but the return target
after a fix is a known separate gap recorded below; this design does not claim
that it resumes comparison automatically. This design does not promise that a wrong
repeated diagnosis can never consume the coordinator's three-launch limit; live
qualification must measure it. No reset, silent retry, extra launch or automatic
spend is added to hide that limit.

Exercise G and stress exhaustion through finalize_accounting -> record_exhaustion
-> queued_inputs with real saved diagnosis fixtures and labelled authored stop
metadata. Assert pending diagnosis, valid G marker or no stress marker, and
included comparison diagnostics, never diagnosis_input_invalid. Default
comparison_route=False remains a compatibility/testing boundary; record its
removal as an item-7 cleanup after every production caller has the producer.

## Round-3 recovery contract (binding)

B1 and M1–M3 are accepted. Parent attempts replace the child retry/exhaustion
message. Add a thin pair-level gate_attempt.execute around compare only for
failures outside a requested stage (not another layer of stage retries). Its
identity is operation='extension-comparison', extension_id, both immutable case
hashes and pinned versions; journal is identity-root/pair-attempts.json. It has
the same two-attempt bound. Stage exhaustion is a BudgetError and propagates
through it without consuming or resetting a pair attempt. No third allowance.
Pair-level record_crash writes comparison-diagnostics; exhausted pair attempts
raise stress_validation_exhausted with no G marker. Successful stage Records
survive pair retry, so a scored pass or rejection is never rerolled.

Extract compare's existing current completed-pair verification into an internal
helper used by compare and the producer. Call it BEFORE the pair retry journal:
a verified terminal current pair returns immediately even if an old journal was
left running. A selected terminal retained pair with bad bytes raises the existing
extension_snapshot_changed evidence stop. This is the existing proof check moved
to a reusable function, not a second validation implementation.

Exhaustive sources of incompleteness on subsequent_entry:

| Source | Route |
| --- | --- |
| Child/IPC/setup/manifest/thread/subreaper/cleanup failure | InvalidInfra within parent stage invoke; at most two attempts; then G infrastructure_exhausted or stress_validation_exhausted, both diagnosis triggers. |
| Pending-shaped evaluator result | Same stage-attempt invalid-infrastructure route; never publish a pending score as a fail. |
| Stress freshness_unresolved or a freshness-only unresolved result | BudgetError('freshness_evidence_unavailable'); existing diagnosis trigger, no G marker, retain actual freshness proof. |
| Ordinary G2 freshness_evidence_unavailable, malformed_output_exhausted, stress_validation_exhausted | Propagate unchanged; existing diagnosis triggers. |
| Source/config/version drift caught before/after a stage | InvalidInfra within that parent stage attempt. |
| Drift or other pending result returned by compare outside a stage | InvalidInfra inside pair invoke; preserve scored Records; after two attempts stress_validation_exhausted with pair diagnostic. |
| Selected retained terminal pair fails proof verification | extension_snapshot_changed evidence stop; never evaluate or relabel it. |
| Malformed/tampered Records or support | Propagate extension_snapshot_changed/extension_reservation_mismatch evidence stop; never retry scored evidence. |
| Records pinned-version mismatch | Treat as evidence mismatch, extension_snapshot_changed, because each execution identity already pins the full vector; do not map it to a held comparison. |
| Money/provider/deadline/cancel | Propagate existing operational BudgetError labels unchanged through both attempts. |

The production producer therefore has no non-retryable
extension_comparison_pending exit. Non-opted-in dispatch and first-entry holds
remain unchanged. Evidence stops intentionally end cleanly, as existing evidence
validation does; they are not claimed retryable. A historical active row and
invalid/used diagnosis fail existing eligibility checks before attempts.

Before the first comparison checkpoint, the LIVE c removes stale failed_gate,
failed_detail and infrastructure_gate, sets failed_gate=None, status='stopped',
and terminal_stop='runner_error:comparison_in_progress'. This existing RETRY label
is a checkpoint recovery marker, not an exhaustion. Keep diagnosis_state and
extension history intact. Every parent comparison checkpoint uses that context.
Save exact pre-producer status/terminal_stop values, including whether each key
was absent. On successful producer return restore those values exactly before
ordinary admission, so first and subsequent entry hand the writer the same state; on an exception main writes the actual stop. The producer
must not replace a later failure with its in-progress marker. Test the sealed
mid-comparison card with recovery.require_restart_stop and restart.plan using
saved restore artifacts. A kill then re-enters the same sole entry producer.

Additional exams: one child death then success finishes without relaunch; two
child deaths queue a diagnosis; out-of-band setup failures consume parent
attempts; a thread exiting inside 30 seconds permits fork while a longer one
consumes an attempt; the mid-comparison checkpoint is retryable; each table row
has either a valid diagnosis input/restart route or the named intentional evidence
stop. No unresolved infrastructure fault ends as extension_comparison_pending.

Deferred static finding new-stream-d-current-comparison-1: after a post-extension
factory-bug fix, resume_factory_bug removes diagnosis_state and _dispatch returns
False, so main resumes ordinary build/validation rather than the interrupted
comparison. Record this as open in docs/murphy-register.md, with this review and
code paths as static evidence, not a claimed live incident. It needs a separately
reviewed durable resume target across factory-bug admission and comparison.
Do not claim it fixed or close item 7. Existing resume/extension/retire limits
remain unchanged. This is an explicit remaining item-7 obligation.

## Round-4 attribution and retry details (binding)

B1 and M1–M4 are accepted. Add factory_waste.forward_attempt(mark_unpublishable)
as a context manager with a small proxy scope. Its only public behavior is
mark_unpublishable(reason); factory_waste.record_reservation returns immediately
for this proxy, since the parent collects authoritative ledger rows. Ordinary
Attempt and ordinary callers are unchanged. Immediately after fork replace the
inherited _attempt contextvar with this proxy; enter/reset it for EACH stage
request, bound to the parent's active Attempt.value['attempt_id'], not just the
first stage that caused the fork. There is never a stale first-stage scope.

A mark is first atomically persisted/fsynced in phase work at
attempt-effects/<attempt-id>.json with exact fields schema_version=1, attempt_id,
and unpublishable (a list of nonempty reason strings). Then send an effect
message with that attempt ID and wait for parent acknowledgement. Serialize
Pipe requests with one child lock (including request/reply pairing), so an owner
handler thread cannot interleave bytes with a checkpoint message. Parent verifies
ID against the active scope, calls mark_unpublishable(reason), then acknowledges.
The parent's finally safely reads this same attempt's durable effect file before
scope exit, including after child death, and applies all reasons idempotently.
On lost IPC/child death where no complete effects acknowledgement is available,
mark the attempt unpublishable('comparison_child_lost') conservatively. Do not
publish waste from an ambiguous cleanup. The attempt still counts as invalid
infrastructure in the retry journal.

This non-None forwarding scope preserves exam_responder.owner_channel's scoped
drain behavior. It must still raise InvalidInfra on an incomplete drain. Test an
authored G10 owner_drain_timeout through the child protocol: parent attempt gets
the signal before publish, no factory-failures/factory-replays file is written,
and the invalid attempt count increments. Also test the signal delivered after
an earlier stage in the same child, and lost-ack replay from the durable file.

After any failed child invocation, fully quiesce its descendants, then call
budget.reconcile_reservations(c.work,c.ledger) on the LIVE parent before allowing
the stage retry. Child root usage receipts are already there. Do not reconcile
while a model or descendant may still run. A reconciliation BudgetError propagates
unchanged; it cannot be masked by an InvalidInfra retry. Test a dead child with a
pending reservation and valid retained final usage: settlement precedes retry
admission and releases the known unused reservation without a spurious money_wait.
Unknown usage retains the existing conservative reservation charge.

Pair journal version identity is computed before entering execute with
extension_compare._versions on a Workspace using the owner's unchanged args,
models and source BENCH. The phase records share that pinned vector. Pair
publish is operational events only (stage label 'comparison', state/elapsed/reused),
never live gate results. Every other non-BudgetError exception escaping compare,
including diagnostic RuntimeError and ValueError, counts as a pair attempt.
After two, use the existing stress_validation_exhausted trigger, but the copied
diagnostic index has scope='pair' (stage indices use scope='stage') so diagnosis
sees that stress itself need not have failed. BudgetError labels propagate except
for the explicit freshness translation already specified.

The pre-producer failure fields remain in the immutable diagnosis-input card.
The live card intentionally removes them for the in-progress checkpoint's restart
eligibility; an evidence-stop card does not restore them and cannot claim a new
scientific gate failure. Success restores only the exact saved status/terminal_stop;
G3 setup remains invalidated and historical failure proof remains in the diagnosis
input, not a misleading live failed_gate.

Explicit test disposition: test_stream_d_entry.test_history_refuses_without_snapshot_or_evaluation
currently mocks extensions.read to return an invalid untyped history row, then
expects the now-superseded all-history hold. Replace that authored stub with a real
malformed extension-history.json and assert extension_history_invalid. Retain and
strengthen its no-work contract by patching both snapshot and evaluator construction
to raise if reached. Add a separate valid completed-history test demonstrating the
new producer route. This is the only superseded first-entry expectation changed;
all outcome-route, history-before-card, attribution and retry assertions stay intact.
