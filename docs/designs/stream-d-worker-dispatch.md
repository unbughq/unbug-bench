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
false. No enforced-route bound, release qualification, launcher, job configuration
field, new money owner, repair ruling or runtime-enable flag is added.

There are three reviewable implementation pieces: worker diagnosis dispatch;
versioned stage evidence and one-round extension execution; then real-artifact
qualification and any justified Murphy closures. A piece is not claimed as a
complete dispatcher until both diagnosis and extension execution are present.

## Runner entry and settlement

After `job_config.install`, before `build` or any gate/model call, inspect the
authenticated `checkpoint_card` and verified private extension history. Restore
the operational diagnosis/extension state and original code-recorded stop
context; do not infer authority from current CLI stop labels. Ordinary cases
continue through the existing path. Pending diagnosis, a completed decision
awaiting application, and an active extension enter the dispatcher. Held or
history/input-invalid cases stop before any role selection or model work.

Serialize through the existing model dispatch lock, settle a restored provider
wait using `resume_provider_wait`, reconcile invocation reservations, and require
no active model calls or pending reservation rows before taking queued inputs.
The lock alone is not a claim that background gates have joined: this entry runs
before any gate executor starts, and later transitions occur only after its join.
If the exhausted input's accounting was unknown at restore, settle and checkpoint
`diagnosis_pending` without a model. B must collect and acknowledge the known
total before the next ordinary resume. The archived receipt proves extraction;
it does not supply money or replace B's current RAM configuration.

Call `queued_inputs` before finding/decision replay, reservation or invocation.
Use its original manifest generation and inputs root for every validation.
Later live ledger and restore-receipt changes never replace those inputs.
History-invalid is sticky and never relabelled as input-invalid. The first run
that exhausts still records pending state in finalization and exits; it never
dispatches diagnosis inline before collection.

## Diagnosis result and retry lifecycle

Resolve the archived `roles.reviewer.model`, check its actual family against the
archived writer and strong calibrator models, and reject contradictory family
metadata. Keep that reviewer family through A's approved fallbacks. No arbitrary
current reviewer override can change the queued role's family. Existing model
runtime still validates the current role and every reserved lease.

Use the exact call names `diagnosis-<exhaustion_id>` and
`diagnosis-<exhaustion_id>-repair-<ordinal>`. Retain output bytes privately under
the existing `raw-result-<sha256>.json` convention before validation, including
malformed and partial output. Hash the raw bytes for non-JSON output; accepted
factory-bug normalization continues to preserve the original raw judgment.

A private `attempts.json` under this exhaustion records only code-owned identity:
schema version, immutable input-manifest digest, schema digest, reviewer family,
and ordered attempts. Each attempt binds call name, operation UUID, selected
route, phase (`pending` or `completed`), raw digest (null until collected), and
validation error class (never model prose). Write the admission identity from
the actual reservation before invocation. Provider waits preserve the same
logical attempt; they do not consume a malformed-answer retry. Reconcile an
interrupted invocation before retrying it. Unknown/mutated journals refuse.

After a completed malformed answer, request one schema-only repair of those
retained bytes from the same family. If still malformed, exclude that route
through A's existing `router_excluded` input and try its next approved equivalent.
Each approved route gets one original judgment and one repair for this immutable
input/schema. Different accounts on one route do not reset that count. When all
configured equivalent routes are deterministically exhausted, retire with an
operational malformed-output reason. Unbounded/unavailable routes remain A/B
waits, not deterministic failures. Preserve and restore caller router settings
so diagnosis exclusions never affect the next writer.

Persist the validated normalized decision in `decision.json` before changing
public lifecycle state. It has exactly `schema_version:1`, `exhaustion_id`,
`input_sha256` (canonical manifest digest), and `diagnosis` (the existing strict
result schema). Replay validates it against the original immutable inputs and
never invokes a model. A completed state without its required private decision
or held finding refuses; it is not permission to start over.

For `factory_bug`, use the existing held producer and finding, with no new waste
attribution or later-batch import. Replay a retained held finding first, after
input verification. For `not_converging`, atomically complete diagnosis state
and stop `retired_not_converging`. For `close_to_passing`, complete diagnosis
state then enter code-controlled extension eligibility. A decision never grants
an extension, money, a gate pass or a writer call.

## Role isolation

Reuse the existing disposable `pilot` UID and `make_pilots`/`pilot_wall` lifecycle
on the joined worker. The runner home remains mode 0700, hiding the actual case,
work, bench, other cases, restore keys and job authority. Prepare a separate copy
of the verified immutable inputs, not a symlink to the runner workspace.
Normalize the copied case inputs using `case_permissions`, then make every
input file and directory root-owned, group-readable by this UID and unwritable
by it. Make the containing directory root-owned too, so it cannot rename and
replace the inputs. The only writable task directory is a separate output area.
Re-hash the exposed input copy before and after the role and compare it with the
manifest. Read the result with the descriptor-based regular/no-follow reader.

Do not copy the runner's general configuration or credential stores into this
task home. Model runtime prepares only its existing per-invocation provider
transport and scratch state. Filter the diagnosis invocation environment to the
driver's required transport/configuration keys; do not inherit cloud, restore,
job-authority or judge secrets. Provider credentials remain runtime transport,
never diagnosis evidence or prompt data. The existing CLI transport's access to
its own provider credential is not a new credential-isolation guarantee.

Kill/join the role's process tree, retain raw output and usage, remove its network
rules and dispose of the home before any checkpoint or extension work. A cleanup
failure stops as infrastructure. No mutable pilot home goes into the snapshot.
The implementation must test permissions and cleanup paths; an allowlist or a
prompt saying "read only" cannot substitute for this boundary.

## Stage evidence and one-round extensions

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

## Deletions, tests and Murphy rows

Delete the ordinary build/repair fall-through for dispatched cases and the
possibility of multiple author calls inside an admitted extension. Reuse A's
router, B's restore/money/collection, the existing process UID boundary and D's
state helpers. Do not add a second scheduler, launch mode or retry money system.

Offline tests use the verified public-practice tree, saved 5813be ledger, saved
malformed reviewer/stress artifacts where available, and saved real bench
receipts. Mark authored lifecycle, admission and permission-command controls
explicitly. Test settlement-before-snapshot, unknown-to-known ACK separation,
replay after ledger growth/later generation, no model for retained decisions,
family mismatch, schema repair/fallback and route exhaustion, provider waits,
isolation/cleanup, and no admission while B runtime is disabled. Reuse the
existing input refusals and history-invalid None projections as controls.

Extension tests exercise real reservation/history producers, the crash between
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
