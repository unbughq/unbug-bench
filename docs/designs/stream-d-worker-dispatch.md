# Stream D worker dispatch

This is the implementation addendum to `stream-d.md`, not a new launch or
money contract. Read its diagnosis, extension, queued-input and incremental
implementation sections, and interfaces §8, together with this addendum.

## Problem and boundary

The retained diagnosis inputs, held findings and extension histories have no
worker caller. An ordinary resume still reaches `build` and can consume another
ordinary writer round before recognizing the pending diagnosis. Copying files
for an existing reviewer is also insufficient: that reviewer runs as the runner.

The change composes those existing helpers at the ordinary runner entry, using
B's same-owner restore and A's reviewer admission. B's `DIAGNOSIS_ENABLED` stays
false and is now also read by the worker before diagnosis reservation (see Stops).
No enforced-route bound, release qualification, launcher, job configuration
field, new money owner, repair ruling or runtime-enable flag is added.

The next implementation/review boundary is **diagnosis only**: entry, settlement,
immutable replay, isolated reviewer, schema repair and outcome persistence.
Extension admission/execution is a subsequent separately designed and reviewed
piece, followed by real-artifact qualification. Design-1 B1/B2 and extension
parts of M5/M6 remain accepted, open obligations; this scope change does not
resolve them. No piece is called a complete dispatcher until both diagnosis and
extension execution are present. In this slice a close-to-passing decision is
retained and stops `extension_comparison_pending`; it cannot fall through to
ordinary build or invoke a writer. Active extensions likewise stop pending and
preserve their history. No extension method is wired to a writer in this slice.

## Runner entry and settlement

Immediately after `job_config.install` in the runner's existing try/finally,
before `raised_limits`, `restore_gate_crash`, Compose setup, pilot-home archival,
`pick_models` or `build`, inspect the authenticated `checkpoint_card` and verified
private extension history. Restore
the operational diagnosis/extension state and original code-recorded stop
context; do not infer authority from current CLI stop labels. Ordinary cases
continue through the existing path. Factor only the existing pilot archival and
cleanup into a helper for this slice; Compose and extension startup refactors
remain extension work. Pending diagnosis, a completed decision
awaiting application, and an active extension enter the dispatcher. Held or
history/input-invalid cases stop before any role selection or model work.

Copy only these archived fields on the dispatcher path, byte-for-byte when
present: `source`, `seed`, `rotation_slot`, `roles`, `models`, `models_used`,
`gates`, `gate_results`, `gate_minutes`, `early_gates`, `failed_gate`,
`failed_detail`, `infrastructure_gate`, `late_defect`, `stress_review`,
`statement_sha256`, `admission`, `dedup`, `dedup_skipped`, `idea_realism`,
`candidate_attempts`, `rejected_candidates`, `builder_rounds`, `recovery_config`,
`factory_slots_prepared`, `diagnosis_state`, `extension_history`, `factory_bug`
and `factory_bug_resume_count`. Case identity must already match current
authenticated authority. Do not copy archived sha256, current money authority,
provider configuration, current route receipts or current accounting. Normal
finalization recomputes accounting; only status, terminal_stop and intended
diagnosis transitions change carried lifecycle fields. Historical gate fields
remain historical evidence, not a new gate certification. Normal publication
sanitization still controls the public card.

Before reconciliation/snapshot and before making a diagnosis pilot, run the
factored existing archive/kill/remove step for **all** pilot identities, including
pilot-strong and pilot-easy. Kill/join first, remove their firewall chains, then
archive their homes and remove users. Do not shred retained home evidence that
ordinary resume would have archived. This needs no Compose or base scenario.
The factored old-role cleanup runs on every factory worker resume, including
held/retired and non-dispatch paths. It enumerates every canonical UUID child of
`/var/lib/unbug-diagnosis/<current case>/`, not only the current exhaustion ID,
and collects audit-only output then removes each stale tree. Do not depend on
VM disposal or a later diagnosis to erase a previous outcome's plaintext copy.
Unknown/noncanonical names refuse cleanup as infrastructure; never follow links.

Prevent completed-state re-minting at its producer: `record_exhaustion` may
replace a completed diagnosis only when `new_exhaustion` is true **and** the
current terminal_stop itself passes `_trigger(card, terminal_stop, history)`.
Use that literal stop for the new state; a retained infrastructure marker cannot
substitute a trigger or change its identity. Pending-state preservation and
first-exhaustion behavior stay unchanged. Thus extension_comparison_pending,
money_wait, runner errors and every other dispatcher stop preserve a completed
ID even if the outer exception handler marks exhaustion_occurred. Test two
resumes through real finalization with an exhausted infrastructure marker,
completed close-to-passing state and each of those stops: identical ID, no new
reservation. A distinct literal exhaustion still creates exactly one new ID.

Serialize through the existing model dispatch lock, settle a restored provider
wait using `resume_provider_wait`, reconcile invocation reservations, and require
no active model calls or pending reservation rows before taking queued inputs.
The lock alone is not a claim that background gates have joined: this entry runs
before any gate executor starts, and later transitions occur only after its join.
Decide unknown-at-restore with `batch_accounting.card_total(checkpoint_card) is
None`, using the authenticated archived card before reconciliation, never the
post-settlement card. If unknown with a **pending** state, settle and checkpoint
`diagnosis_pending` without a model. B must collect and acknowledge the known
total before the next diagnosis resume. This pending-state branch does not call
`queued_inputs`, so it cannot freeze a pre-ACK ledger/generation.

If unknown with a **completed** state, settle, verify the already-existing
immutable manifest/inputs through `queued_inputs`, and replay the retained
decision/finding model-free. No new snapshot may be created for a completed
state; a missing manifest or required private result refuses input-invalid.
Re-emit the verified outcome's stop: factory_bug_held, retired_not_converging or
extension_comparison_pending. Do not derive an unverified outcome from the
public label or rewrite a completed state to diagnosis_pending. This branch
also makes no reservation or model call and exits after settlement; test each
completed outcome across two finalizations. The archived receipt proves extraction;
it does not supply money or replace B's current RAM configuration.

Call `queued_inputs` before finding/decision replay, reservation or invocation.
Use its original manifest generation and inputs root for every validation.
Later live ledger and restore-receipt changes never replace those inputs.
History-invalid is sticky and never relabelled as input-invalid. The first run
that exhausts still records pending state in finalization and exits; it never
dispatches diagnosis inline before collection.

## Diagnosis result and retry lifecycle

Resolve the archived `roles.reviewer.model`, check its actual family against the
archived writer, stress tester and strong calibrator models, and reject contradictory family
metadata. Keep that reviewer family through A's approved fallbacks. No arbitrary
current reviewer override can change the queued role's family. Existing model
runtime still validates the current role and every reserved lease.
Copy the archived resolved roles into `c.card['roles']` for dispatch, derive
`c.models` from those same records, and qualify the archived reviewer driver via
`worker_release.verify_selected_drivers` before invoking it. Missing/contradictory
roles stop `diagnosis_input_invalid`. Use `run.opencode` (whose diagnosis call
names map to reviewer), never `pending_call`, which owns attack-state.json.
Use its `before_attempt` callback to bind the actual admitted invocation.

The fixed templates are `factory/prompts/diagnosis.md` and
`factory/prompts/diagnosis-repair.md`. The judgment template states the three
outcomes and their lack of authority, requires schema-v1 JSON at the fixed
output/result.json, states the exact original manifest generation, and tells the
role to cite nonempty relative evidence paths and hashes from its exposed inputs
copy. Validation always uses the runner's original frozen inputs root; the
exposed copy must hash identically. No role-produced verdict can change a gate,
grant money or certify its own provenance.

The repair template gets the retained bounded raw bytes (UTF-8 with explicit
replacement for invalid bytes), the fixed validator error class, and the same
schema only. It requests syntax/schema repair without a new scientific judgment;
no case/evidence tree is exposed in repair mode. Both modes receive fixed case,
generation and output identifiers, never model-chosen destinations. A strict
`RESULT_SCHEMA` JSON object in diagnosis.py describes the existing result schema
including additionalProperties:false. The existing validator remains the
semantic/evidence authority. Contract tests keep its field set and schema in
agreement. `schema_sha256 = carry_over.digest({schema: RESULT_SCHEMA,
judgment_template: <exact template UTF-8>, repair_template: <exact template UTF-8>})`.
Both journal and decision `input_sha256` mean `carry_over.digest(manifest)`.
Templates are read from the selected frozen release source, not replaced by
live prompt edits on replay. These digests never grant authority.

Use the exact call names `diagnosis-<exhaustion_id>` and
`diagnosis-<exhaustion_id>-repair-<ordinal>`. The first logical judgment uses the
unsuffixed name. Every later logical call uses a globally increasing ordinal,
including a fresh judgment on a fallback route; journal `kind`, not this suffix,
distinguishes judgment from schema repair. Retain exact bytes privately as
`raw-bytes-<byte-sha256>` before validation, including malformed/partial output.
The existing `raw-result-<canonical-json-sha256>.json` producer remains unchanged
and cannot overwrite these files. Missing-manifest binding checks must also
recognize raw-bytes files, audit-bytes files, attempts.json and decision.json
before orphan cleanup. Interrupted/predecessor/orphan bytes are audit-only and
use `audit-bytes-<byte-sha256>`. They are legal unreferenced audit artifacts.
For each nonempty or non-missing audit collection, retain a companion
`audit-<canonical-record-sha256>.json` with exactly `{schema_version:1, status,
inputs_sha256, raw_sha256}` from the bounded helper response. Raw audit bytes
are persisted first, then this metadata; neither is authority or an answer.
Include audit-*.json in the missing-manifest binding check as well. An interrupted
audit write is preserved but cannot change journal status or diagnosis state.
Only a raw-bytes file referenced by a journal row's raw_sha256 can be an answer;
unreferenced raw-bytes files are interrupted publication artifacts, never answers,
and are preserved for audit without changing the row's status.

A private `attempts.json` has exactly `{schema_version:1, exhaustion_id,
input_sha256, schema_sha256, family, attempts}`. `attempts` is an ordered list
whose rows have exactly `{ordinal, kind, call_name, operation_id, status,
repair_of, invocations, raw_sha256, error}`. Ordinals start at zero; kind is
`judgment|repair`; status is `pending|valid|malformed`; repair_of is null for
judgments or the immediately preceding malformed judgment ordinal for repairs.
Raw digest and error are null while pending; a malformed result has its byte
digest and fixed code error class, a valid result has its digest and null error.
Each invocation is exactly `{lease_id, invocation_id, route, pool}` and must
match a retained ledger reservation's operation and call name. Append the actual
invocation in `opencode.before_attempt`, after reservation and before process start.
The journal never derives those fields from model output.
All three record types and raw bytes live beside finding.json under
`work/diagnosis/<exhaustion_id>/`, using the existing `_finding_path` parent.
Write a pending logical row with a new UUID operation and invocations:[] before
opencode. Set `c.model_operation_id` to that durable row's operation for the call;
restore/remove the prior value in finally on every exit. A retry after a wait or
crash uses the same row and operation, not a fresh implicit runtime UUID.

A pre-admission denial has no invocation row. An interrupted call remains
pending, with its retained invocation reconciled from the ledger before another
invocation is appended to that logical operation. A completion whose raw file
was not yet retained is conservatively interrupted; it does not fabricate an
answer. Only completed valid/malformed transport calls consume deterministic
judgment/repair slots; interruptions remain bounded by the same money/deadline.
Provider waits preserve the pending logical attempt. Exact schema, ordinal,
repair adjacency, digest and ledger binding checks reject mutated journals.
At every actual `before_attempt`, after journaling its reservation and before
process start, use the trusted helper to retain any partial predecessor output,
empty and recreate output/ as pilot:pilot 0700. Never accept a first invocation's
partial result as a fallback invocation's answer. On a fresh dispatcher entry,
kill/join the old UID, collect any bounded orphan output for audit only, remove
the stale task tree without following links, and rebuild from verified inputs.
Orphan bytes alone do not turn an interrupted journal row into a completed call.
The completed logical call's route is the last journaled invocation's route;
earlier transport-failed invocations do not consume a deterministic route slot.

After a completed malformed answer, request one schema-only repair of those
retained bytes from the same family. If still malformed, exclude **every**
`pool + '/' + route` entry for that route from `model_router.routes`, through
A's existing `router_excluded` input, then ask A for the next approved equivalent.
Each approved route gets one original judgment and one repair for this immutable
input/schema. Different accounts on one route do not reset that count. When all
configured equivalent routes are deterministically exhausted, detect that from
the journal and `routes(model)` **before** awaiting another lease and stop
`retired_diagnosis_malformed`. A's all-excluded provider-wait behavior is not the
exhaustion test. Unbounded/unavailable routes remain A/B
waits, not deterministic failures. Preserve and restore caller router settings
so diagnosis exclusions never affect the next writer.
Pin schema repair to the route of its completed malformed judgment by excluding
all other configured routes, while allowing any pool on that same route. A
provider outage therefore waits through A instead of moving the repair to a
different route. After malformed repair, exclusion targets that judgment route.
Scope and restore both exclusions and model_operation_id in finally.
Today only GATED_CLAUDE has an enforced maximum. Other reviewer families therefore
wait on `unbounded_route`; they are neither silently rerouted across families nor
declared deterministically exhausted. At most two completed diagnosis calls per
approved same-family route are made for these immutable inputs/schema.
In today's two rotation tables only one of eight slots has an Anthropic reviewer.
Only that slot can currently obtain a bounded diagnosis route; the rest wait.
The completed-call ceiling there is twice GATED_CLAUDE's qualified max_usd per
input/schema, plus interrupted invocations at their conservative reservations,
all within the unchanged current job commitment and deadline.
`retired_diagnosis_malformed` leaves diagnosis_state pending; there is no fourth
completed outcome. Re-entry re-detects deterministic exhaustion from the verified
journal without a model and stops again. The retired stop projects None.
Perform this re-detection in model-free replay **before** the activation gate,
so a disabled gate cannot relabel a retired malformed diagnosis as pending.

Persist the validated normalized decision in `decision.json` before changing
public lifecycle state. It has exactly `schema_version:1`, `exhaustion_id`,
`input_sha256` (canonical manifest digest), and `diagnosis` (the existing strict
result schema). Replay validates it against the original immutable inputs and
never invokes a model. A completed state without its required private decision
or held finding refuses; it is not permission to start over.

For `factory_bug`, use the existing held producer and finding, with no new waste
attribution or later-batch import. Validate/replay a retained held finding after
input verification. For `not_converging`, atomically complete diagnosis state
and stop `retired_not_converging`. For `close_to_passing`, complete diagnosis
state and stop `extension_comparison_pending` until the reviewed extension
controller exists. A decision never grants
an extension, money, a gate pass or a writer call.
The complete durable order is: raw bytes; journal row marked valid/malformed
with its raw digest; decision (valid only); finding (factory bug only); completed
public state. A valid journal row with retained referenced bytes but no decision
is completed model-free during replay **before** the activation gate: re-run the
strict validator against the original frozen inputs and write decision.json.
This makes no role, lease or reservation. Missing referenced bytes or validation
failure on a row marked valid is diagnosis_input_invalid, not a retry. A
malformed row with no next repair row may only start that repair after activation
and normal admission. An unreferenced raw file or a pending row is not sufficient
to derive a decision. A valid
factory-bug decision with no finding replays through `persist_factory_bug`.
A legacy retained finding with no decision replays through `restore_factory_bug`
without synthesizing an old model answer. If both exist, require their normalized
diagnosis payloads to agree before replay. Disagreement or corrupt/missing durable
decision state stops `diagnosis_input_invalid`, preserving existing bytes/IDs.

## Role isolation

Reuse the existing disposable `pilot` UID. Add explicit `diagnosis=True` to
`make_pilots`; in that mode skip both general configuration/auth copies and call
`pilot_wall` with `slot=None`. That wall variant never loads a scenario or opens
bench ports, so early exhaustion without a base scenario is supported. The
runner home remains mode 0700, hiding the actual case,
work, bench, other cases, restore keys and job authority. Prepare a separate copy
of the verified immutable inputs, not a symlink to the runner workspace.
The task tree is `/var/lib/unbug-diagnosis/<case>/<exhaustion_id>`: ancestors are
root-owned 0755, the task directory root:pilot 0750, `inputs` and all descendants
root:pilot (0550 directories, 0440 files), and `output` pilot:pilot 0700.
The task parent and every ancestor are non-writable by pilot; the input cannot
be renamed out through a pilot-owned home. Normalize copied case inputs using
`case_permissions`, then make every
input file and directory root-owned, group-readable by this UID and unwritable
by it. Make the containing directory root-owned too, so it cannot rename and
replace the inputs. The only writable task directory is a separate output area.
Re-hash the exposed input copy before and after the role and compare it with the
manifest. The shipped trusted helper is `factory/diagnosis_task.py`, included in
the authenticated worker manifest and selected factory source. Its command is
`sudo -- python3 -I -B <job_config.FACTORY/diagnosis_task.py> <operation> <case> <exhaustion_id>`.
Operations are exactly prepare, reset, collect and remove. Case must match
`case-[A-Za-z0-9-]{1,128}` and exhaustion_id must be canonical UUID4. There are no
path arguments. Source work is the invoking runner's passwd home (from sudo's
SUDO_UID), followed by work/<case>/diagnosis/<id>/inputs; task paths are derived
under the fixed /var/lib root. Ancestors must be directories, never symlinks.
Prepare reads the verified manifest/journal from the fixed runner work path;
judgment mode copies inputs, repair mode exposes no case/evidence copy. Root
ownership is set before the UID may access the tree. Remove unlinks a stale
leaf symlink rather than following it, and refuses symlink ancestors.
Prepare derives mode from the **last pending journal row's kind**; a missing,
nonpending or contradictory row returns input_invalid. Prepare always removes
the previous task tree before rebuilding it, including any old inputs subtree.
Call prepare once for each logical row immediately before opencode (again on a
new process resuming that same row), not for A's internal invocation retries.
Finish collection and task removal for one logical row before appending the next
row, so repair can never inherit a judgment's exposed input tree. Reset/collect
read the last row's kind even after it has been marked valid/malformed; no new
logical row is appended while an old task tree is live.

After the role is killed/joined, collect reads the exposed tree and fixed
output/result.json through regular/no-follow/nonblocking descriptors. Output
is bounded at **65536 bytes**, reading at most one extra byte to detect excess.
Missing, symlinked, FIFO/nonregular and oversized results are malformed outputs,
not transport retries. For excess retain exactly the bounded prefix and its
digest; a malformed prefix cannot be validated as a complete result. For absent
or unsafe output retain an empty prefix plus the fixed error class. Only the
post-role collect in the same process that received successful prepare for that
logical row enforces the exposed copy's integrity as input-invalid. Orphan,
stale-tree, interrupted-call and predecessor collects are **audit-only**: record
their bounded status/map digest with audit bytes, but never use either to change
diagnosis state or terminal_stop. A partial copy left by a crash during prepare
is disposable plumbing, not evidence that the runner's frozen inputs changed.
Always verify the original frozen root separately through queued_inputs.

The bounded captured response is one JSON object with exactly
`{schema_version:1, status, inputs_sha256, raw_sha256, raw_base64}`. Status is
ok, missing, unsafe, oversized or input_invalid. inputs_sha256 is
`carry_over.digest(_input_inventory(exposed))`, which must equal
`carry_over.digest(manifest['files'])`, and is null in repair mode; raw fields are
the exact retained prefix and its SHA-256. Prepare/reset/remove return the same
shape with empty raw bytes and status ok only on success. The runner rejects
unexpected fields, identity/root mismatch, invalid base64/digest or a response
larger than 96 KiB before decoding. The fixed helper command itself carries
case/id; no result text supplies a path or authority. Capture through a private
pipe, never stdio logs. Before reset, the runner separately calls collect and
persists any predecessor bytes as audit-bytes-*. Reset itself returns empty raw
bytes and recreates output/ after confirming no pilot process remains. A final
successful transport collection is retained as raw-bytes-* and referenced by
its journal row; interruption/cleanup collections are audit-bytes-* only.
Persist bytes before task-tree deletion.
An audit collect with status missing and zero bytes writes neither audit bytes
nor metadata. This is the normal first-before_attempt case on an empty output
directory. Other statuses, including input_invalid on a stale partial tree,
remain audit-only and do not prevent remove/rebuild or a gate-false pending stop.

Remove runs in finally after each logical call and again idempotently at every
dispatcher exit if a task tree exists or setup began. Provider wait, money wait
and exceptions do not skip it. A removal failure stops as infrastructure
(`runner_error:DiagnosisTaskCleanupError`), preserving journal/input state; no
new model call is allowed before cleanup succeeds. Fresh entry kills old pilots,
collects bounded orphan bytes for audit and removes any stale task tree as part
of old-role cleanup before replay/activation. With no old task, a disabled gate
causes no helper call at all. Cleaning an existing stale tree is the only
gate-false helper exception; it never creates a UID, task tree or inference.

Do not copy the runner's general configuration or credential stores into this
task home. Model runtime prepares only its existing per-invocation provider
transport and scratch state. Filter the diagnosis invocation environment to the
driver's required transport/configuration keys; do not inherit cloud, restore,
job-authority or judge secrets. Exact policy for this role:

- Common nonsecret keys: PATH, HOME (pilot home), LANG, LC_ALL, TMPDIR (pilot
  scratch). No other ambient key is copied.
- OpenCode: OPENCODE_CONFIG and XDG_DATA_HOME are generated for this invocation;
  add only the selected lease account's OPENCODE_API_KEY or OPENROUTER_API_KEY,
  never both or an ambient Claude credential. Provider URLs come from the frozen
  config, not inherited overrides. Disable Exa (no OPENCODE_ENABLE_EXA) and
  webfetch/websearch permission in this diagnosis config; no general user config
  or auth.json is copied. The selected model remains the compaction model.
- Claude: after A's existing enforcement wrapper, keep only model_call_gate.ENV_KEYS
  from this already filtered environment plus the wrapper's generated transport
  fields. No new real credential is inserted into prompt/evidence. No WebSearch
  or WebFetch tools are enabled.
- Codex: preserve only CODEX_HOME and PATH through sudo, as today. Its existing
  per-invocation auth.json scratch copy and disabled external features/MCP
  configuration remain unchanged.

Provider transport credentials are not diagnosis evidence. This does not claim
that a general CLI cannot read its own transport credential. The role gets no
factory/cloud/restore secret and no other provider account. Public provider
egress remains existing runtime behavior; disabling built-in web tools is not
claimed to be a network sandbox for arbitrary Bash.

The no-bench-port wall also needs the existing bounded Claude transport to work:
after `model_call_gate.enforce` creates its private listener, add a temporary
UID-specific allow for that exact loopback port and remove it in finally before
the listener closes. Only the trusted runtime's newly created gate supplies the
port, never the model or a file. Insert both direct and conntrack ORIGINAL
loopback permits with `-I factory-pilot 1`, ahead of LOCAL REJECT, inside
`with enforce(...)` in `_invoke`, only for user pilot and diagnosis call names.
Remove those exact rules in finally; the next make_pilots flushes the old chain
after a crash. All other local/container ports remain denied. Test cleanup on
success, failure and cancellation. The analogous pre-existing Claude calibrator
loopback issue is outside this diagnosis slice and is not claimed fixed here.

Kill/join the role's process tree, retain raw output and usage, remove its network
rules and dispose of the home before any checkpoint or extension work. A cleanup
failure stops as infrastructure. No mutable pilot home goes into the snapshot.
The implementation must test permissions and cleanup paths; an allowlist or a
prompt saying "read only" cannot substitute for this boundary.

## Extension implementation obligations (not ready for wiring)

This section records accepted work for the next extension addendum, not approval
to implement the earlier sketches. The two design-1 blockers remain open until
a fresh design review passes their concrete implementation and tests.

For B1, replace the implicit `active_extension_id` budget-bypass test with an
explicit `pending_call(..., extension_proposal=...)` path. Under the existing
dispatch lock, immediately before reservation, require exact equality with a
fresh `extensions.propose` for the current completed close-to-passing exhaustion
and current verified snapshot. Existing active histories must instead verify
the stored round/operation. Only then bypass the ordinary limit; the unchanged
`require_case_budget(..., job_authority=...)` and reservation checks still enforce
B's committed total and deadline. Pass the proposal as a local argument, not a
mutable bypass attribute. Clear scoped active-extension context in finally on
every exit. The saved 5813be ledger must prove over-ordinary-budget admission and
forged/stale proposal refusal. A crash after reservation but before admission can
conservatively book the full maximum; tests must not expect zero.

For B2, the comparison outcome must be the unchanged live case, with its tree
digest equal to the stored outcome. Re-evaluate it in place so its current
snapshot can exactly match `extensions.propose`'s comparison outcome. Only the
entry revision is disposable. Its evaluator must redirect **all** work, bench
results and service slots; copying case bytes alone is forbidden. A fresh evaluator
process with a private copy of shipped bench files and distinct prepared slots
is the proposed seam, but slot preparation, result roots, context authentication
and cleanup must be specified and reviewed before implementation. Never mutate
runner module globals while another executor can run. Extract a stress-only
evaluator from write_and_attack and prove there is no reachable authoring path.
Name its model call IDs/reservations, stop handling and result-import validation
in that next addendum. Test no live evidence mutation during entry evaluation and
successful proposal after a real scientific-version change. Reconstruction calls
draw from the same current job commitment; they gain no additional money.

The remaining requirements from the parent design are retained below. They need
the exact stage receipt/status mapping and resumed-work contract requested in
design-1 M5/M6 before this section can pass implementation readiness.

Extend `gate_state`'s lazy scientific inventory to every stage in the existing
ordered extension vector, including stress. Separate versions from case, seed,
slot and whole-cache-file hashes. Exclude pure routing/accounting/publication
dependencies, while retaining actual evaluator, prompt, model, scientific
settings and judge environment dependencies as specified in `stream-d.md`.
Do not make additional gates reusable merely by giving them a version.

After each valid stress/gate evaluation retain a private stage receipt in
`work/evidence/extension-stages/`. Each receipt binds schema, stage, scientific
version, full input fingerprint, pass/fail status, and the paths/digests of
supporting artifacts. Invalid infrastructure is pending and creates no verdict.
Snapshot construction checks current bindings and actual files; public pass
labels alone cannot produce extension evidence. Retain these receipts and their
supporting files in the immutable entry/outcome snapshots. A missing receipt
for a previously evaluated stage requires reconstruction, not an assumed pass.
Stages never evaluated remain unreached.

Build entry snapshots only from verified current evidence. For a completed prior
extension, use `extensions.progress` at identical ordered versions. On a version
change, evaluate changed stages and invalidated successors on disposable copies
of the retained entry and outcome revisions, under current scientific versions
and the same current money owner; keep originals immutable. Retain the resulting
pair through `retain_comparison`. No authoring is allowed in reconstruction.
Missing or interrupted evidence remains pending until normal continuation or
batch retirement, never regression or a reset of the lifetime count.

Call `extensions.propose` before seeking a writer lease. Carry its proposal into
`pending_call`; call `extensions.admit` only after the real writer reservation
exists, before invalidating gates or invoking the writer. Save that extension ID,
round and operation in the existing attack receipt. If interrupted between
history and receipt writes, recover from the retained history and reservation;
do not allocate another ordinal or operation. A pre-admission wait writes no
history. An active extension reuses exactly its stored round and operation.

Use the existing writer/stress loop with a one-round range and the existing
modern budget bypass restricted to a verified active extension. Skip ordinary
prototype/reselection/extra repair authoring in this path. Cumulative
`builder_rounds` is preserved. A completed writer resumes at validation, never
authoring; an unfinished writer resumes the same operation. Stress resumes its
unfinished work. No freshness repair or early failure may start a second writer.
Set `validate_and_repair`'s repair count to zero during extensions.

After joined evaluation, append one immutable outcome. Complete valid defects
stop `extension_incomplete` and finalization records a fresh exhaustion ID.
Infrastructure/provider interruptions keep the active extension and do not
append an outcome. Evaluate any entry passes needed to establish no regression,
even if the ordinary traversal stopped earlier. All-pass outcomes use normal
sealing. Progress, stress eligibility, five lifetime extensions and batch money
remain code decisions. The next completed diagnosis may propose another round
only if the existing immutable comparison proves strict progress.

## Stops and current B boundary

| Exit | Worker terminal_stop | Current control behavior |
| --- | --- | --- |
| Unknown exhausted input, settlement complete | diagnosis_pending | Present pending projection permits B's existing same-owner settlement/diagnosis request when its planner is enabled. No snapshot/model before the next ACK. |
| Pending diagnosis, provider admission or mid-call wait | provider_wait | Retain pending state and A's existing provider_wait.json. B's ordinary provider-wait resume adapter is required before activation; this slice adds no queue. |
| Pending diagnosis, commitment insufficient | money_wait | Preserve state; await B's ordinary money revision/resume adapter. No new D money grant or projection is invented. Completed-decision replay needs no model or money. |
| Completed close-to-passing decision; active extension; reconstruction not implemented | extension_comparison_pending | Projection remains None. Current batch_service does not enqueue this case; B's resumable-work adapter and the extension controller are required before activation. |
| Crash before/after a retained decision | Existing runner_error:<type> checkpoint, or process death without a new checkpoint | Existing restart/holder/explicit resume paths can already deliver this card. Retained decisions replay before a model; new model admission still requires B's shared activation gate and verified money authority. |
| Input/history corruption | diagnosis_input_invalid / factory_bug_history_invalid | Terminal None projection; retain evidence and no automatic reset. |
| Accepted factory bug / not converging / malformed-route exhaustion | factory_bug_held / retired_not_converging / retired_diagnosis_malformed | Completed/retired None projection, no more model work for this diagnosis. |

Existing `recovery.require_restart_stop` / RETRY accepts runner_error and several
transport stops; key_holder's HOLDER_STOPS and an explicitly authorized ordinary
same-owner resume (including a raised-budget resume) can already deliver a
dispatcher-eligible card. Entering dispatch through those paths is intended;
none may fall through to a writer. They do not bypass activation or create money.

Immediately after settlement, queued-input verification and model-free outcome
replay/application, and **before** driver qualification, pilot creation, helper
prepare, router exclusions, leases or reservations, read the single existing
`batch_service.DIAGNOSIS_ENABLED` from the verified installed release. Here that
means the batch_service module imported from job_config.FACTORY in this worker,
read as `batch_service.DIAGNOSIS_ENABLED is True`, not a file parse or a value
copied into c. Require it
to be literal True. False or an unavailable gate stops diagnosis_pending while
preserving the same exhaustion ID. This is a second consumer of B's existing
activation gate, not a new worker flag, config field or grant of authority. Do
not cache a copied flag value or change its default. Verified immutable replay
and held/retired outcome application remain model-free and can proceed while
the gate is false. Every enabled invocation still requires normal job authority,
lease, enforced route bound and reservation. This honors the user's instruction
that money admission remains fail-closed until B runtime activation; changing
the shared flag belongs to the future reviewed B/D integration, not this slice.
The installed release is immutable during a worker process, so this check is
not repeated inside A's internal retry loop. With the gate false, only retained
model-free outcomes may be applied; otherwise stop diagnosis_pending. No role
qualification or setup occurs. The already-required old-pilot/stale-task cleanup
is the only privileged work allowed before this check. Test a fresh false-gate
entry with make_pilots, verify_selected_drivers and the helper patched to fail if
called; separately test stale-task false-gate entry permits collect/remove only,
without creating a task, user, lease or reservation.

Current `batch_service._enqueue` handles present diagnosis projections and
unknown-total exhaustion only; it is not the missing extension/provider/money
adapter. Until B supplies those adapters, interrupted/completed-decision work
waits behind disabled activation and remains subject to B's batch deadline;
this code does not promise a working automatic resume path for it. No new
launcher is added. The fail-closed test asserts `batch_service.plan` returns
`diagnosis_unavailable` and an empty queue with DIAGNOSIS_ENABLED false, plus
worker refusal without verified job authority. Also test the same flag false in
the dispatcher on an actual restart-eligible runner_error card: no writer, no
lease and no reservation. With that shared flag patched true in offline control
tests, assert at most the bounded diagnosis attempts and no writer. This tests
the future path without enabling production or adding a worker-specific toggle.

## Deletions, tests and Murphy rows

In this slice skip the ordinary `build()` and `validate_and_repair()` calls for
dispatched pending/completed diagnosis and active-extension cases; normal cases
retain their existing path. The future extension slice must delete the legacy
post-loop `builder-precheck` call and its rechecks for dispatched extensions,
while retaining the modern exhaustion/stop emission. Reuse A's
router, B's restore/money/collection, the existing process UID boundary and D's
state helpers. Do not add a second scheduler, launch mode or retry money system.

Offline tests use the verified public-practice tree, saved 5813be ledger, saved
malformed reviewer/stress artifacts where available, and saved real bench
receipts. Mark authored lifecycle, admission and permission-command controls
explicitly. Test settlement-before-snapshot, unknown-to-known ACK separation,
replay after ledger growth/later generation, no model for retained decisions,
family mismatch, schema repair/fallback and route exhaustion, provider waits,
isolation/cleanup, no writer after close-to-passing, and the precise B-planner and
worker-authority refusals above. Reuse the
existing input refusals and history-invalid None projections as controls.
Add controls for operation UUID preservation across provider wait/crash, stale
output across A's internal retry and stale task-tree rebuild, repair-route
pinning, fixed helper bounds and no-follow handling (symlink/FIFO/missing/oversized),
exact public-field carry-forward, archival of all pilot identities, and orphan
refusal for raw-bytes/audit-bytes/attempts/decision without input.json. Exercise finalization
twice on completed close-to-passing infrastructure state for comparison_pending
and money_wait, proving unchanged IDs and no new reservations. These remain
authored control envelopes over the saved real input/ledger artifacts.
Also cover unknown-total completed factory_bug, not_converging and close-to-passing
states: verification/replay keeps the correct outcome stop and ID through two
finalizations, without new snapshots or calls. Test judgment-to-repair removes
the inputs subtree, legal audit-only/unreferenced interrupted bytes never become
answers, per-call and exit removal, and cleanup failure followed by safe resume.
Add gate-false replay controls for a valid row with retained bytes but no decision
(decision completes model-free), and missing/invalid referenced bytes (input
invalid, no setup). Crash mid-prepare with a partial exposed inputs tree, then
resume: audit/remove preserve the ID; false gate stops diagnosis_pending, patched
true gate re-prepares the same logical row. Cleanup must also remove prior-ID
task trees on terminal and ordinary resumes. Assert each driver's environment
contains no cloud/restore/job/judge key; OpenCode gets at most its selected single
provider key and no OPENCODE_ENABLE_EXA; Codex sudo preserves only CODEX_HOME,PATH.

The later extension increment's tests must exercise real reservation/history producers, the crash between
admission and attack receipt, completed-writer validation, active stress resume,
one writer only, immutable snapshots, stable versions under plumbing changes,
changed-version baseline reconstruction, invalid execution pending, strict
progress/regression, fifth-extension limit and batch-bound retirement. Every
increment runs the full required suite and receives a fresh diff goldfish.

This design closes no Murphy row by itself. Rows 8–13, 15, 21 and 39 remain open
until the corresponding real-artifact exams prove their full claim, including
any A/B/E dependency. Offline authored dispatch controls are not live isolation,
bounded-provider or collection qualification. No launch or decryption is required
or authorized by this design.
