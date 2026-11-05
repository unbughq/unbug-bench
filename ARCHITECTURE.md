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

`factory/durable/contract.py` v5 defines the shared records, wire protocol, keyed
references and package interfaces. It remains unchanged. The candidate integrates the DBOS engine, executor,
Boat worker pool/channel, worker-side steps, SQL ledger and wrapped-key service.
`runtime.py` composes these components; `cli.py` exposes a private operator socket.
The control units and setup script live under `control/`. ADMIT reuses the existing
selector, registry, freshness and idea-realism screens. DIAGNOSIS uses the existing
review contract through an isolated pilot user. These paths still need combined
and live qualification before replacing the production release.

The target is DBOS 3.4.0 on control-side Postgres. Workflow replay reuses recorded
results, with idempotent attempts keyed by case, sequence, step and attempt.
Workflow functions remain deterministic: clock reads and external effects go
through steps, waits use DBOS, and workflow changes use `DBOS.patch()`. Pin the
application version for the database lifetime and register admission queues before
recovered work can enqueue. Attach to existing workflow IDs when resuming.

The case sequence is ADMIT → WRITER → STRESS → GATES → SEAL, with bounded repair,
diagnosis, extension and reviewer-escalation paths. ADMIT is serialized per batch;
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

Reserve allowance before dispatch and settle actual usage idempotently. Worker
model calls atomically reserve their router Lease maxima against that attempt
before launch, including parallel roles. Supported provider gates must enforce
those maxima; unbounded routes are refused. This requires live qualification. Lost
attempts book the grant as infrastructure waste; broken runs charge the batch's
waste line, not the case. Ordinary work draws on case and batch money; diagnosis,
extensions and post-diagnosis work draw only on the batch bound. Batch exhaustion
waits without holding a concurrency slot. Zero-cost genuine provider limits wait
without an attempt-count cutoff; they never retire a case merely for recurring.

Poll transport failures do not prove a worker is absent. Cancel or establish that
the old attempt is finished before starting another. Enforce release identity and
attempt deadlines; SEAL must use the versions under which GATES passed. Startup reconciles pool ownership before DBOS recovers workflows. Ambiguous
creates retain their original identity rather than issuing another create.
Ciphertext publication exports the wrapped scope key first, and fetched worker
outputs authenticate before entering immutable storage. Cold backup/restore has a disposable PostgreSQL exercise that preserves grants,
keys, artifacts and release pins. Scheduled backups pause the controller and invalidate only their own restore fence before restarting it;
R2 ciphertext stays in immutable storage. Normal handover requires the source fence.
Lost-source or stale archives restore into a quarantine that cannot execute work
until external ownership and spending have been reconciled. This path does not
claim automatic recovery from unrecorded post-backup spending. Legacy lifecycle modules and their obsolete tests have been removed from this
candidate. Final combined offline qualification and live Boat/R2/provider fault injection
remain before production cutover.
