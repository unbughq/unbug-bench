# Durable execution for the case factory

Status: design for review, 2026-11-05. Branch `durable-execution`, cut from
`factory-simplify` at `2df5664`. Picture: the "Case Factory Blueprint" page
(private claude.ai artifact, link in the session that wrote this design).

## Problem

The factory turns three inputs into sealed cases:

```
app pin (repo + commit) + promise + case count  ->  factory  ->  sealed cases
```

The step from inputs to cases is long (cases ran 30–77 wall-clock hours on
Oct 14–20), expensive in quota, and interrupted constantly. The 50 real case
scorecards in `sealed/` record about 460 interruptions: 210 `opencode_error`,
99 provider limits, 74 stalls, 23 timeouts, 11 Codex errors. A case cannot be
restarted from scratch after each one; it has to carry on.

Today "carry on" is hand-built. `docs/factory-single-path.md` lists 12 launch and
recovery paths, each with its own locks, key handling, receipts and rules of proof.
State is spread over public cards, continuation ledgers, encrypted checkpoints,
holder memory, coordinator journals, R2 and the founder's Mac. Most open rows in
`docs/murphy-register.md` are two copies of that state disagreeing, or a crash
between two writes. Each fix adds another receipt, which adds the next row.

This is the problem durable-execution engines exist to solve.

## Change

Replace the lifecycle layer with one durable workflow per case on the always-on
control VM, using DBOS (Python library, `dbos==3.4.0`) on Postgres. Keep the bench
logic. Steps return typed outcomes; one pure function decides what happens next.

### Shape

- **Batch workflow.** Input: `BatchSpec` (the three inputs plus bounds). Starts
  case workflows up to `max_concurrency`. When a case retires, it starts a
  replacement at once. Stops at `target_sealed`, the money bound, or the deadline.
- **Case workflow.** An ordinary Python function: admit, then writer and stress
  rounds, then each gate in `run.GATES` order, then seal. Each of these is one
  engine **step**. The engine records each step's result the moment it finishes.
  After a crash, replay returns recorded results without re-running them; only
  the open step runs again. Proven on the real engine in
  `tests/factory/test_durable_replay.py`.
- **Six outcomes, one policy.** Every attempt ends in one `Outcome` (ok,
  infra_error, provider_limit, gate_failed, exhausted, needs_founder).
  `contract.decide()` maps it to an `Action` (advance, retry, sleep, repair,
  retire, diagnose, escalate). Provider limits become durable sleeps that spend
  no allowance and hold no worker.
- **Workers are dumb and disposable.** Steps run on the control VM and drive a
  Boat worker over `boat ssh`: send the step input, let the worker restore the
  input snapshot, run the existing code, write an encrypted output snapshot to
  R2, and return a `StepResult`. A case keeps its worker between steps because
  the shop build is expensive, but that is a cache, not state. A dead worker
  means a new worker restores the last snapshot.
  - Push, not pull: DBOS steps run in the process that owns the workflow. With
    push, workers never need database access, and the database stays private
    to the control VM. (Figure 1 of the blueprint page shows workers pulling
    from a queue; that figure gets corrected to this.)
- **One database of record.** DBOS keeps its journal in Postgres on the control
  VM. The same Postgres holds the spend ledger and the gate-result cache (WP6,
  later the cache). The public scorecard becomes a report generated from these
  tables. No code reads a scorecard back to make a decision.
- **Secrecy is a payload rule.** DBOS records every step argument and result, so
  they hold only identifiers, sha256 hashes, short reason codes and numbers.
  `contract.py` refuses anything else. Case content (statements, patches,
  transcripts, feedback) lives only in age-encrypted R2 artifacts, opened in
  worker RAM with the case key from the key service. DBOS Conductor (its hosted
  console) is not configured, so the engine makes no outbound connection.

### The frozen contract

`factory/durable/contract.py` is the shared language of every work package. It
holds `BatchSpec`, `Step`, `StepInput`, `StepResult`, `Outcome`, `Usage`,
`Ref`/`ArtifactKind`, `SealedCase`, the `ArtifactStore` and `StepExecutor`
protocols, `decide()`, and strict record conversion. It is pure: no I/O and no
engine import. A change to it needs a change to this design.

### Engine rules (from the probe and the replay test)

1. Workflow functions are deterministic. No clock, randomness, file or network
   reads outside steps. Use `DBOS.sleep` for waits.
2. To resume a case, attach to it (`DBOS.retrieve_workflow`), never start an
   existing ID again. Starting a pending ID again raced DBOS's own recovery in
   the first version of the replay test and failed with a determinism error.
3. A step is idempotent on `StepInput.idempotency_key`. The control VM can crash
   after a worker has finished. On replay, the executor asks the worker for that
   key's result before running anything.
4. Code changes ship as a new `application_version`. A case pins its bench
   version; plumbing fixes apply at the next step boundary.

### Granularity

The first version uses coarse steps: one writer round, one stress round, one
gate. Today's in-round recovery keeps working inside a step. Snapshots after
every model call come later (WP5f), once the coarse version runs live.

## Work packages

Each package gets its own branch, `de/<id>`, cut from `durable-execution`. Each
follows the ENGINEERING.md flow: a short design note for packages over about 20
lines, then a diff goldfish. Packages merge back into `durable-execution`. Write
ownership is disjoint, so wave 1 can run in parallel.

| ID | Package | Owns (writes) | Needs | Done when |
|---|---|---|---|---|
| WP1 | Engine core: batch and case workflows on DBOS | `factory/durable/engine.py`, its tests | contract | A fake executor drives whole cases. Tests kill the engine at each step boundary and in a sleep, and a replacement starts on retire, against real DBOS on SQLite. |
| WP2 | Worker pool and remote executor | `factory/durable/workers.py`, `factory/durable/remote.py` | contract | Boat create/delete use idempotency labels. Orphans are adopted or deleted on restart. `run()` reattaches by key. Tests use real saved Boat CLI outputs. |
| WP3 | Encrypted artifact store | `factory/durable/artifacts.py` | contract | age-encrypted, content-addressed put/get/exists, with an R2 backend and a local backend. The same bytes give the same `Ref`. A truncated upload is never visible. |
| WP4 | Typed router outcomes | `factory/model_router.py`, `factory/model_runtime.py` (failure classification only) | contract | Every stop kind seen in the 50 real scorecards maps to one `Outcome`, with `retry_at` for limits. Tested on those real records, plus the top `opencode_error` causes found in their logs. |
| WP5a | Step seam in the runner | `factory/durable/worker_step.py`, minimal `factory/run.py` hooks | contract, WP3 interface | On a worker: restore a snapshot into a case directory, build the runner context, run G1 (then writer and stress rounds), snapshot, and classify into a `StepResult`. Tested on the public practice case. |
| WP6 | Spend ledger and batch money bound | `factory/durable/ledger.py` | contract | `Usage` per attempt is recorded in the app database. The bound is checked before every paid step. The ledger is rebuilt identically after replay. |
| WP7 | Key service | `factory/durable/keys.py` | contract | The scoped VM key (founder-approved 2026-10-29) wraps per-case keys. A worker receives its case key over the ssh channel into RAM only. |
| WP5b–e | Remaining gates as steps | one file per gate group under `factory/durable/steps/` | WP5a | G2–G5 and G16; G8, G9, G6; G13–G15 and G7; G10, G17, G11. Each group is tested on the practice case. |
| WP8 | Control-VM deployment | `control/`, deploy scripts | WP1, WP2 | Postgres and a systemd unit for the engine. One release digest per batch. The engine restarts on reboot and resumes its cases. |
| WP9 | Cutover and deletion | the deletion list below | all; one live practice batch | A practice batch survives a killed worker and a control-VM restart without a human. Then the old paths are deleted and the Murphy rows are closed with those runs. |
| WP5f | Snapshot after every model call | `worker_step.py`, `model_runtime.py` | WP9 | An interrupted writer round resumes after its last finished call. |

Waves: **1** is WP1, WP2, WP3, WP4, WP5a, WP6 and WP7 in parallel. **2** is WP5b–e
and WP8. **3** is the integration practice batch, then WP9. **4** is WP5f and the
gate-result cache.

`durable-execution` merges `factory-simplify` in at least daily. Everything
before WP9 is additive (new files plus small hooks), so those merges stay cheap.

## What it deletes (at WP9, not before)

These modules are replaced by the engine and Postgres: `key_holder`, `batch_holder`, `batch_service`, `batch_transfer`,
`batch_status`, `control_resume`, `coordinator`, `coordinator_inventory`,
`restart`, `recovery`, `durable_checkpoint`, `restore_ledger`, `restore_sync`,
`collection`, the `launch.sh` monitor loop.

These special paths are deleted: `restore_bundle`, `late_rehearsal`,
`ttl_continuation`, `late_recovery`, `carry_over`, `resume-in-place.sh`,
`founder_ruling`, the salvage path.

Legacy checkpoints are retired, not migrated (founder decision 2 below). This is
about 10.6k lines of Python and shell, plus the roughly 12k lines of tests around
them. The exact list is confirmed by reading each module during WP9.

## Tests

Added now:
- `tests/factory/test_durable_contract.py`: the gate order equals `run.GATES`;
  free text and non-hash references are refused; records round-trip exactly and
  reject extra fields; the `decide()` table covers every outcome.
- `tests/factory/test_durable_replay.py`: the real DBOS engine. A crash mid-step
  reruns only the open step. A second start attaches. A crash during a provider
  sleep keeps the original wake time (it finishes in under 5.5 s after a 6 s
  limit, 4 s of which elapsed while nothing was running).

Each package adds its own tests under "Done when". All tests use the real engine
and real saved artifacts, per ENGINEERING.md section 4.

## Murphy rows

None close with this design; it adds no production path. These rows are the
targets. Each closes only when its package's test, on real artifacts, proves it.

- WP1, WP8: 5, 9, 16, 18, 19, 26, 28, 33, 51.
- WP3: 27, 34, 35, `new-batch-service-2`.
- WP2: 17, 29, `new-boat-stop-capture-1`.
- WP4: 2, 4, 47, and part of 48.
- WP7: 1.
- WP9 (the path is deleted along with its row): `new-single-path-1`,
  `new-batch-service-1`, `new-batch-service-4`, `new-batch-auth-inputs-1`,
  `new-registry-pending-promotion-1`, `new-batch-restore-admission-1`,
  `new-preallocation-import-recovery-1`.

## What this does not fix

Gate science, router policy, Docker and SQL hangs inside a step, stray-process
cleanup, and the causes of model-CLI errors all stay as work. The engine makes
each of these a typed, retried, cheap event. They still happen.

## Founder decisions needed

1. **Freeze new lifecycle work** (streams B and E) on `factory-simplify` while
   wave 1 runs, so the packages do not chase a moving target. Bench-logic fixes
   continue.
2. **Retire legacy checkpoints** (43, of which 30 have no case key) instead of
   migrating them. Rerun the three cases that passed G1–G15.
3. **Postgres on the control VM** as a new dependency, with backups.
4. **DBOS over Temporal.** DBOS is a library with no extra server. Temporal is
   more mature, but needs a server and has stricter worker rules.
5. Whether the overnight stopgap (a supervisor around today's same-worker resume)
   still runs while this is built.
