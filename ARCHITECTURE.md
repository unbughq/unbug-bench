# Architecture

The repository contains a local inventory benchmark, a scored exam, and a factory
that builds sealed exam cases. This describes the implementation on this branch.

| Area | Ownership |
| --- | --- |
| `projects/medusa/` | Pinned application, Docker Compose services, seeding and database baseline. |
| `cases/`, `guards/`, `scenarios/` | Traffic, promises, guard implementations and maintenance changes. |
| `bin/bench.py`, `bin/bench_judging.py` | Runtime orchestration and pure verdict calculations. |
| `bin/checkpoint*`, `bin/exam*`, `bin/strategy*` | Trial evidence, exam execution and strategy simulation. |
| `factory/run.py` | One case's builder, qualification gates and scientific criteria. |
| `factory/gate_pipeline.py`, `factory/calibration.py` | Gate sequencing, reusable passes and calibrator attempts. |
| `factory/model_runtime.py`, `factory/model_router.py` | Model execution, routing, usage accounting and provider handling. |
| `factory/durable/engine.py`, `executor.py`, `runtime.py` | Durable scheduling, execution and control-side composition. |
| `factory/durable/workers.py`, `channel.py`, `worker_step.py` | Worker provisioning, authenticated transport and execution. |
| `factory/durable/ledger.py`, `keys.py`, `artifacts.py` | Money reservations, scoped keys and encrypted artifacts. |
| `factory/durable/checkpoints.py` | In-step snapshots and evidence-bound completion receipts. |
| `control/` | Control VM setup and services. |
| `harbor/` | Harbor task packaging and adapters. |
| `tests/` | Offline regressions, explicit live probes and retained evidence fixtures. |

A batch is built from a clean, pinned Git commit and admitted through the control
service. Workers run the case builder, then the configured gate pipeline. The
runner records scorecards and checkpoints; collection returns encrypted evidence
and publishes the allowed summary. The existing production release remains pinned for rollback. This candidate has
removed its legacy launchers and controllers; shared runner and budget callers
now use the durable path. Live cutover is not yet qualified.

The benchmark resets its own Postgres/Redis stack for each trial. The checker uses
read-only database access. Parallel factory slots have separate Compose projects,
volumes, ports and seed manifests. Model roles run with information walls between
case internals, testers and contestant-visible material.
Durable OpenCode calls put each role's private CLI state on an executable tmpfs.
After process containment closes, cleanup unmounts that state instead of overwriting
a potentially large disk cache. Failed cleanup remains an infrastructure failure.

## Invariants

- Infrastructure failures are invalid runs, never scientific passes or failures.
- Gates and judging own case results; launch and recovery plumbing only carry them.
- Preserve contestant secrecy, role isolation and authenticated checkpoint inputs.
- Enforce approved money, call and time ceilings across retries and continuations.
- Genuine provider limits are handled by waiting, account switching or an approved
  fallback in the same model family; they must not shrink or terminate the plan.
- The control VM and remote artifact storage own batch lifecycle. The founder's
  laptop must be able to disconnect without stopping it.
- Resume follows the checkpoint launch path. Avoid one-off per-case rescue paths.

These are engineering requirements, not a claim that every failure mode is already
automatically recoverable. Unit tests do not qualify a live worker release.

## Durable-execution migration

`factory/durable/contract.py` v6 defines the shared records, wire protocol, keyed
references and package interfaces. Its reviewed change permits restoring ADMIT
checkpoints; the wire fields remain the same. The candidate integrates the DBOS engine, executor,
Boat worker pool/channel, worker-side steps, SQL ledger and wrapped-key service.
`guard.py` is the campaign's minute-by-minute check, for one batch (`batch_id`) or several started side
by side (`batch_ids`: each keeps its own bound, the campaign finishes when all are terminal, and one live
worker per watched batch is allowed): failures pause new attempts. Only a money,
deadline or confirmed Boat limit is a hard stop: after a bounded checkpoint grace the guard stops the
controller and deletes the workers. On SIGTERM the engine drains, then
exits without touching DBOS again, and systemd restarts it unless an operator stopped it.
`runtime.py` composes these components; `cli.py` exposes a private operator socket.
`client.py` reads that operator's public status/report over SSH using a saved local
connection and default batch. `bin/install-unbug` packages a standalone read-only
client with Python's standard library; it neither imports DBOS nor starts recovery.
Controller-local status clients enrich the public scorecard with read-only ledger
and DBOS observations plus worker ownership journals. They never poll workers,
decrypt artifacts, start recovery or change reservations. The formatted output
distinguishes current attempts from historical results and reserved from spent funds.
Status/report clients remain available while the controller is stopped; they read
persisted cards via DBOSClient and show service liveness separately from workflow state.
Plumbing bundles include their authenticated `bin/processes.py` runtime helper;
factory imports and qualification use that release copy. Scientific bench files
remain on the separately pinned worker image.
Images may supply `~/bench-source/prepare.py` to verify their bound public source
and prune obsolete files restored by a snapshot overlay. This runs before release
qualification and key delivery; changed source fails preparation.
The control units and setup script live under `control/`. ADMIT reuses the existing
selector, registry, freshness and idea-realism screens. DIAGNOSIS uses the existing
review contract through an isolated pilot user. These paths passed combined offline
qualification; live worker qualification remains before replacing the production
release.

The target is DBOS 3.4.0 on control-side Postgres. Workflow replay reuses recorded
results, with idempotent attempts keyed by case, sequence, step and attempt.
Workflow functions remain deterministic: clock reads and external effects go
through steps, waits use DBOS, and workflow changes use `DBOS.patch()`. Pin the
application version for the database lifetime and register admission queues before
recovered work can enqueue. Attach to existing workflow IDs when resuming.

The case sequence is ADMIT → WRITER → STRESS → GATES → SEAL, with bounded repair,
diagnosis, extension and reviewer-escalation paths. ADMIT is serialized per batch;
the active scheduler checks its recorded deadline after funding, before the first
ADMIT dispatch. Queued or unfunded admissions expire with their holds released;
an ADMIT already dispatched may continue across the cutoff and provider waits.
GATES retains the existing pipeline and per-gate cache rather than duplicating it.
Workers publish encrypted snapshots at model and gate boundaries. The channel
fetches the latest committed snapshot; progress not fetched before a worker loss
can still be lost. Completion receipts reuse work only under matching instructions,
inputs and release bindings. Same-case mutable model calls serialize for coherent
snapshots, and isolated calibrator snapshots wait until their workspaces join.

DBOS records identifiers, keyed digests, fixed reason codes and numbers only.
Case material belongs in encrypted artifacts, opened in worker RAM. The control
side transfers blobs; workers receive no R2 credentials. Invoke executors through
`guarded_run`; sanitize exception paths and disable Conductor/DBOS Cloud.
Worker steps share structured wait classification: quota/rate/credit wait durably,
credential delivery, unbounded routes and router outages park without consuming
infrastructure retries; known CLI and unavailable-model faults retain the finite
infrastructure allowance. Each wait retains an
encrypted operational diagnostic with allowlisted causes, retry times and lease
IDs. Worker diagnostics automatically include safe HTTP statuses and error categories.
Scope-bound `durable.diagnostics` inspection runs in worker memory and exports
only operational codes and numeric usage; it never extracts or returns case text.
ADMIT's first attempt may have no snapshot; retries restore the last authenticated
case snapshot under the same case key, retaining its ledger and completed model
receipts while reading the current serialized registry. Contract version 6 relaxes
only ADMIT's input snapshot restriction; other steps still require a snapshot.
The engine guards the changed retry input with a DBOS patch for replay compatibility.
An ADMIT infrastructure failure that exhausts its retries backs off without a
queue slot or outstanding grant, keeping any healthy worker so retries don't spend the
worker creation allowance, then retries the same release once from its snapshot and ledger. The wait doubles to an hour. The case is held after eight backoffs, and as
soon as its infrastructure waste reaches the case's money or the worker creation limit
is hit, with no further retry. After a batch deadline, checked again after each wait,
admission stops.

Workflows that parked before this path existed replay as `waiting_for_release`: a
different plumbing release resumes the same case and sequence from its snapshot and
ledger, previously failed releases cannot resume it, and repair-release continuations
are capped at three and by `max_factory_bug_resumes`. Candidate exhaustion still stops
admission. A DBOS patch preserves historical terminal behavior; already
completed workflows are not revived by deploying the new code. Original admission
exceptions and chained tracebacks stay inside encrypted diagnostics. Snapshots survive
a repair release; generic completion receipts remain bound to their original release.
Malformed retained answers exhaust routes within one Engine attempt. A new funded
attempt may append a fresh judgment, retaining prior rows, outputs and all spending.
Same-attempt replay cannot reopen that allowance, and pending or valid completed
answers are reused. Legacy retry state adopts its first observed attempt key without
guessing that an exhausted allowance can be reset.
Optional `worker_credentials` configuration names an encrypted bundle, control
identity, router client file and selected model accounts. The controller decrypts
in memory and delivers only those accounts and router authority into worker RAM
after release qualification, including on reuse. Credentials never enter images,
release bundles or workflow records; isolated model users lose router authority.
For a legacy registry, `worker_credentials.legacy_registry` also delivers its
statement identity to worker RAM. ADMIT verifies and rewraps occupied statements
under the batch key there, preserving registry history without opening case
material on the controller. The source registry remains untouched.

A pre-durable case can be imported as a one-case batch. On the founder's Mac,
`bin/rewrap-legacy-checkpoint` streams its founder-encrypted archive to the statement
recipient; `prepare <first case id> case <file>` stores that ciphertext unopened under the
case scope, and `start --import-file` passes the ref as the first ADMIT snapshot (only with
`max_cases_started` 1 and `legacy_registry`). ADMIT opens it in worker RAM with the
statement key and keeps only the old case tree: its card, ledger, caches, reviews and
search evidence are dropped, and the old card survives as numbers in `imported_from`.
The existing screens then run once on the case's own statement, skipping only its old
registry entry, and a rejection ends the case without selecting another idea. A case
whose old card passed G1 starts at STRESS; others start at WRITER. Every gate reruns.
The old writer must share today's writer family, so separation rules still hold. Unless
INPUTS pins models or a slot, ADMIT takes the first rotation slot with that writer family;
only an October family absent from the table, or a conflicting pin, refuses the import. The
old spend is not carried in the ledger: INPUTS declares it as `import_spent_usd_micros`,
ADMIT refuses unless it matches the old card, and `start` refuses unless it plus the
batch's `case_money_usd_micros` fits the default per-case ceiling. Import refusals
(`admit:import_invalid`) are deterministic, so they end admission instead of retrying.

A rejected idea publishes `admit:<screen>_<evidence>` (`durable/admission_reasons.py`): the
screen (dedup, freshness, realism, other) and a fixed evidence kind read from structured
fields only, such as `freshness_upstream_fix`. The sealed card keeps per-candidate codes
(duplicate case ID, confirmed source classes, a release tag's version against the pin).
`python3 factory/durable/admission_reasons.py --config <config> <case|batch>...` prints
those codes for finished cases on the control VM: read-only, existing keys only.

OpenCode's free routes (DeepSeek, MiniMax and GLM flash) are bounded at $0 with no gate: a call that books
any cost, or reports a step from another provider or model, is stopped. It runs with OpenCode's own
provider and its one model only, no outside config and no self-update. A calibrator is never leased one,
since behind the wall it reaches only a gate's port: it takes its chain's next bounded route, and a chain
with none (GLM and MiniMax free today) is refused up front as `unbounded_route`. A full or failing free
lane hands an unwalled call to the next route in its chain (DeepSeek: paid OpenRouter).

A durable case stopped by an infrastructure failure resumes instead: `start --resume-case
<case>` makes it the only case of a new batch. It keeps its case ID, so its key, artifacts,
snapshot card and admission binding stay valid. Only its workflow is new (`<case>@<batch>`),
and the batch maps it back for cards and seals. `engine.resume_point` allows this only when every
workflow of the case finished held or retired and its last attempt ended `infra_error` or
`provider_limit`, never after a verdict, gate, limit or founder decision. The new workflow
replays every earlier seq from the attempts recorded under the case's keys, with no worker,
wait or message. If any attempt it needs is missing, it fails (`resume:diverged`) rather than
starting new work in that history. The stopped seq first restores its recorded attempts
(their snapshots, diagnostics and keys, so a changed step also diverges), then continues
with a fresh infra retry allowance.
Counters, snapshot and evidence therefore come out of the same code that built them. `start`
refuses unless the earlier spend (the ledger across the original and every earlier resume
batch, plus any declared import spend) plus the batch's
case money fits the default per-case ceiling. Run the resume batch with the stopped batch's
limits, or the replay diverges.

Reserve allowance before dispatch and settle actual usage idempotently. A call whose gate refused
every request (exhausted, nothing forwarded) settles at $0, not its hold; `start` refuses a batch
whose batch or case money cannot hold one request on its dearest gated route (`bound_below_call_hold`;
a Claude request reserves $9.52, its full context with the uplift). Worker
model calls atomically reserve their router Lease maxima against that attempt
before launch, including parallel roles. Supported provider gates must enforce
those maxima; unbounded routes are refused. This requires live qualification. Lost
attempts book the grant as infrastructure waste; broken runs charge the batch's
waste line, not the case. Ordinary work draws on case and batch money; diagnosis,
extensions and post-diagnosis work draw only on the batch bound. Batch exhaustion
waits without holding a concurrency slot. Zero-cost genuine provider limits wait
without an attempt-count cutoff; they never retire a case merely for recurring.
Claude OAuth requests omit the organization-dependent `inference_geo` parameter.
Modern-model holds cover the 1.1x regional uplift; missing/unavailable response
geography stays conservatively priced, while explicit global usage releases it.
Engine invocations request a quote bounded by their currently uncommitted attempt
funding. OpenRouter qualification-sized default windows are replaced by this
funded window (at most $50); explicit Claude profile ceilings remain binding.
The router persists and validates that quote, and the worker atomically reserves
it before execution. Exam calibrators leave a qualified reviewer window outside
their hold so nested owner questions remain funded. This changes no case/batch bound and retains unknown charges.
The router's operator configuration may set `paid_ceiling_usd`, an absolute shared
wallet spending limit including all retained charges. Restart applies an explicit
limit transactionally without resetting settled or uncertain spending; live wallet
credit is checked separately on every paid request. Without this setting, the
historical first-use qualification ceiling remains fixed across restarts.

Poll transport failures do not prove a worker is absent. Cancel or establish that
the old attempt is finished before starting another. Enforce release identity and
attempt deadlines; SEAL must use the versions under which GATES passed. Startup reconciles pool ownership before DBOS recovers workflows. An unconfirmed
create keeps its identity for 15 minutes from its saved intent, then a new create may go ahead and any
late sandbox of an older identity is deleted by its ownership name. A failed create or Boat inventory outage waits
and retries without spending the case's infra allowance, for at most six hours per step, and ADMIT stops after the
batch deadline. A control-side sweep every five minutes deletes owned sandboxes that no record claims and resolves
settled creates. After a normal restore, launch deletes such strays; a quarantined restore still refuses them
(`restore_unclaimed_worker`) after reconcile until its first clean launch, and `restored.json` keeps the reconcile attestation.
Boat ownership uses a versioned 106-character sandbox name containing pool and
case hashes plus the saved create nonce. Inventory resolves case hashes only from
saved pool journals; unknown owned hashes identify orphans, never invented case ids.
The operator `publish` command writes the allowlisted scorecard (codes and numbers
only) to `scorecards/<batch>/<digest>.json` in the object store; it is not yet
called automatically at batch completion.
Ciphertext publication exports the wrapped scope key first, and fetched worker
outputs authenticate before entering immutable storage. Cold backup/restore has a disposable PostgreSQL exercise that preserves grants,
keys, artifacts and release pins. Scheduled backups pause the controller and invalidate only their own restore fence before restarting it;
R2 ciphertext stays in immutable storage. Normal handover requires the source fence.
Lost-source or stale archives restore into a quarantine that cannot execute work
until external ownership and spending have been reconciled. Only the operator's
`reconcile --ownership-reconciled --spending-reconciled` releases it: it works on a
quarantined restore alone, under the state and database locks, refuses while a pool
record is uncertain unless the operator names it with `--cleared-record`, and records the attestation and time before removing the fence.
This path does not claim automatic recovery from unrecorded post-backup spending
and cannot see a stale source controller elsewhere. Legacy lifecycle modules and their obsolete tests have been removed from this
candidate. The clean offline suite passed (151 scripts), along with Linux worker
checks and a disposable PostgreSQL restore exercise. Model-free live checks cover
Boat/R2, Docker, control restart, worker replacement and authenticated checkpoint
reuse. Model access, routing and provider spending ceilings still require live
qualification before production cutover. The practice fixture is not a scientific case.
