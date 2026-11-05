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
| `factory/batch*.py`, `factory/key_holder.py` | Approved batch releases, control-side admission, budgets and dispatch. |
| `factory/launch.sh`, `factory/collect.sh`, `factory/control_resume.py` | Worker launch, collection and checkpoint continuation. |
| `factory/run_artifacts.py`, `factory/restore*.py` | Sealed evidence and authenticated restoration. |
| `control/` | Control VM setup and services. |
| `harbor/` | Harbor task packaging and adapters. |
| `tests/` | Offline regressions, explicit live probes and retained evidence fixtures. |

A batch is built from a clean, pinned Git commit and admitted through the control
service. Workers run the case builder, then the configured gate pipeline. The
runner records scorecards and checkpoints; collection returns encrypted evidence
and publishes the allowed summary. The existing control service and checkpoint
machinery own recovery. This branch has the durable-execution contract, classifier and artifact store;
the workflow engine and worker integration are not yet merged.

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
references and package interfaces. It remains unchanged by this cleanup.
`classify.py`, `artifacts.py` and `policy.py` are present. Engine/executor work is
on `de/wp1`; worker provisioning/channel on `de/wp2`; worker-side execution on
`de/wp5a`; ledger/key service on `de/wp6-wp7`. These are unfinished integration
work, not an operational replacement for the existing launcher.

The target is DBOS 3.4.0 on control-side Postgres. Workflow replay reuses recorded
results, with idempotent attempts keyed by case, sequence, step and attempt.
Workflow functions remain deterministic: clock reads and external effects go
through steps, waits use DBOS, and workflow changes use `DBOS.patch()`. Pin the
application version for the database lifetime and register admission queues before
recovered work can enqueue. Attach to existing workflow IDs when resuming.

The case sequence is ADMIT → WRITER → STRESS → GATES → SEAL, with bounded repair,
diagnosis, extension and reviewer-escalation paths. ADMIT is serialized per batch;
GATES retains the existing pipeline and per-gate cache rather than duplicating it.
A worker loss can lose progress not included in the last encrypted snapshot.

DBOS records identifiers, keyed digests, fixed reason codes and numbers only.
Case material belongs in encrypted artifacts, opened in worker RAM. The control
side transfers blobs; workers receive no R2 credentials. Invoke executors through
`guarded_run`; sanitize exception paths and disable Conductor/DBOS Cloud.

Reserve allowance before dispatch and settle actual usage idempotently. Lost
attempts book the grant as infrastructure waste; broken runs charge the batch's
waste line, not the case. Ordinary work draws on case and batch money; diagnosis,
extensions and post-diagnosis work draw only on the batch bound. Batch exhaustion
waits without holding a concurrency slot. Zero-cost genuine provider limits wait
without an attempt-count cutoff; they never retire a case merely for recurring.

Poll transport failures do not prove a worker is absent. Cancel or establish that
the old attempt is finished before starting another. Enforce release identity and
attempt deadlines; SEAL must use the versions under which GATES passed. Adoption,
publication and retirement of legacy recovery paths still need implementation and
live fault-injection validation before production use.
