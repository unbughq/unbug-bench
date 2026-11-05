# Durable execution WP1: engine core, executor and policy

Status: **draft for diff review.** Package WP1 of `docs/designs/durable-execution.md`
(revision 5, design review 5 passed), wave-1 brief in
`docs/designs/durable-execution-wave1.md`. Branch `de/wp1`, cut from
`durable-execution` at `db13be8`. Contract: `factory/durable/contract.py` version 5,
unchanged.

## Problem

The reviewed design defines one durable workflow per case on the control VM, and a
policy for every outcome. Nothing runs it yet. WP1 builds the engine that does: the
batch and case workflows on DBOS 3.4.0, the executor that runs one attempt through the
seams the other packages build, the policy's open settlements, and the public
scorecard.

## What WP1 builds

| File | What it is |
|---|---|
| `factory/durable/policy.py` | The routing table (unchanged behaviour), plus the settlements below: request figures, minimum grant, deadlines, how each result settles. Pure. |
| `factory/durable/executor.py` | `Executor`: composes `WorkerPool`, `WorkerChannel`, `Ledger`, `ArtifactStore`, `Sealer` and `KeyService`. `run()` is the `StepExecutor` the engine calls only through `guarded_run`. The other methods (reserve, settle, cancel, release, seal history) are the engine's other side effects; each raises only a fixed `SeamError` code. |
| `factory/durable/engine.py` | `Engine` (construction, Conductor checks, launch, queue registration, attach-or-start, operator messages) and the DBOS workflows: `batch_workflow`, `case_workflow`, and one `attempt_workflow` per attempt. |
| `factory/durable/report.py` | The public scorecard, generated from the engine's own records (each case workflow's `card` event). Pure renderer plus a loader. |

### Seams

WP1 implements `StepExecutor` and calls every other protocol: `WorkerPool.acquire /
release / alive`, `WorkerChannel.start / poll / cancel`, `Ledger.open / raise_bound /
reserve / settle / settle_lost`, `ArtifactStore.put_sealed / get_sealed / exists`,
`Sealer.seal / open`, `KeyService.scope_key`, and `guarded_run`, `wait_seconds`,
`assert_no_conductor`, `check_result_for`. The `Classifier` is the worker's (WP5a
classifies the runner's stop before writing its result); the engine never sees stop
text, so WP1 does not call it.

### The three workflows

- **`batch_workflow(spec, initial_registry)`**, workflow ID = `batch_id`.
  - Opens the ledger, publishes the current releases as DBOS events (`plumbing`,
    `bench`), and starts `min(target_sealed, max_cases_started)` original cases as
    child workflows. Case IDs are `case-<batch>-<n>`, numbered in start order.
  - Then it loops on one internal topic (`case_event`). Cases report `line_stopped`,
    `sealed`, `stop_admission`, `waiting`, `settled` and `done`. The batch alone holds
    the batch-wide counts, so replacements, `max_cases_started`, the target, the
    deadline and STOP_ADMISSION are decided in one place, in order.
  - After each wake (a case event, or the poll timeout) it reads the three operator
    topics without waiting: `PLUMBING_RELEASE` and `BENCH_RELEASE` update the events;
    `BOUND_RAISED` calls `Ledger.raise_bound` and wakes waiting cases.
  - It ends when every started case is done, returning the sealed cases.
- **`case_workflow(spec, case_id, ...)`**, workflow ID = `case_id`. A loop over
  "The case, step by step": ADMIT, WRITER r, STRESS r, GATES r, SEAL, with every
  outcome routed through `policy.decide` / `decide_diagnosis`. Case state (seq, rounds,
  extensions, diagnoses, snapshot, feedback, ruling, evidence, passed gates, the GATES
  versions, the stop history) lives in workflow locals, rebuilt by replay. After every
  step it sets a content-free `card` event, which `report.py` reads.
- **`slot_workflow(...)`**, workflow ID = the attempt's idempotency key
  `case/seq/step/attempt`, is enqueued on `steps-<batch>` (global concurrency
  `max_concurrency`). An ADMIT additionally enqueues `attempt_workflow` on
  `admit-<batch>` (global concurrency 1); other steps invoke it directly.

  Once dequeued it runs these recorded steps: read the latest registry (ADMIT only),
  reserve, the minimum-grant check, cancel the previous attempt, `now`, the attempt
  itself (`guarded_run`), settle. It returns the result, the grant and whether it
  started. Holding the queue slot only for one attempt is how slots work: a case holds
  a slot while one of its attempts runs and none while it sleeps, waits, parks or
  retires. ADMIT holds both slots while it runs, so it is serialized and the
  global limit includes every model attempt.

### Engine rules, as built

1. Workflows are deterministic: the clock only through the `now` step; releases
   through `DBOS.get_event`; messages through `DBOS.recv`; no iteration over sets.
2. Every wait is `DBOS.sleep(wait_seconds(retry_at, now()))` or a `recv` with a
   positive timeout.
3. `Engine.start_batch` attaches with `retrieve_workflow` when the batch ID exists;
   it never starts an existing ID again.
4. Attempts are idempotent on `case/seq/step/attempt`: the attempt workflow's ID is
   the key, the ledger is keyed by it, and the worker refuses a second start.
5. `executor.run` is called only through `guarded_run`.
6. Queues are registered right after `launch()`, before any batch is started or
   attached. Queue rows persist in the system database, so a case recovered by
   `launch()` that enqueues before re-registration still lands on its
   concurrency-1 queue. Tested (below).
7. `application_version` is pinned to `factory-engine-1`. Workflows have
   `max_recovery_attempts=None`: a control-VM restart must never dead-letter a case.

## Settlements (wave-1 brief, reviews 3-5)

| Item | Settlement |
|---|---|
| **GATES deadline, from evidence** | `policy.GATES_DEADLINE_S = 43_200` (12 h); other steps keep `spec.step_deadline_s` (4 h). Evidence: over the 52 non-dry-run cards in `sealed/`, the slowest observed minutes per gate are G2 8.2, G3 3.7, G4 9.7, G5 29.3, G6 23.2, G8 19.9, G10 144.4 (18681d), G11 15.7, G13 17.2, G14 30.2, G15 61.5 (14d35a). Their sum, with G10 serial (it runs serially whenever `g10_overlap_reason` refuses overlap), is 363 min, about 6 h. G7, G9, G16 and G17 have no positive timing on any card. 12 h is twice the worst observed serial pipeline. A deadline kill is `infra:deadline`, a retried INFRA_ERROR that restores the snapshot, so too short a figure repeats work and too long a figure only holds a slot. The control side polls until `deadline_s + policy.POLL_GRACE_S` (900 s). |
| **ADMIT gives up its queue slot while it sleeps** | Each ADMIT attempt is its own `attempt_workflow` on the admit queue, and a PROVIDER_LIMIT result ends it. The case workflow sleeps outside the queue, then enqueues attempt n+1. Tested: a second case admits while the first sleeps. |
| **ADMIT reads the latest registry when dequeued** | The first step of a dequeued ADMIT attempt lists this batch's finished ADMIT attempt workflows and takes the newest successful registry, or the batch's initial registry. Because the queue runs one ADMIT at a time and recovery re-enqueues a pending attempt onto its own queue (`reenqueue_for_recovery` keeps `queue_name`), the newest successful ADMIT is the one every later ADMIT must build on. Tested: three cases admit in a chain, each reading the previous output, including after kills. |
| **The engine's stop history as a DIAGNOSTIC** | Each finished attempt adds `{seq, step, attempt, outcome, reason, paid}` to the case's history (codes and numbers only). On DIAGNOSE, a step seals it with the case key as a `DIAGNOSTIC` (`Sealer`, stored in the case scope) and adds its Ref to the evidence, after every receipt, diagnostic and report the case's results carried. Tested: the diagnosis input carries it, and it opens with the case key to the recorded history. |
| **Retrying a cancel after a transport failure** | A cancel is confirmed by a DONE result or by proven worker death. If a start returns ABSENT, cancel creates a tombstone before another attempt may begin. The control-side deadline begins no earlier than the end of input transfer, so it cannot cancel a newly started worker early. Reattachment may postpone the control-side cancel; the worker still enforces its original deadline. After deadline plus grace, repeated cancel/poll continues while a live worker is unreachable. A late DONE result is kept with its usage. This favors safety over liveness during an indefinite outage. |
| **The minimum grant** | `policy.MIN_GRANT_USD_MICROS = 1_000_000` ($1). The cheapest identified writer round in Stream D's cost evidence is $0.4463424, so a smaller grant cannot finish one. `policy.decide_grant`: a sub-minimum grant labelled CASE is the case's give-up (DIAGNOSE; STOP_ADMISSION for ADMIT) without starting, because case money never comes back; labelled BATCH it waits (WAIT_FOR_BOUND); labelled NOTHING it starts, since the request itself was that small. An unstarted reservation is released with `settle(key, Usage())`. Tested, each label. |
| **A request figure for batch-only steps** | A batch-only step starts with the larger of the case money and $33. A money stop under a whole, unlimited grant retries; if no money was spent, the next request doubles until the call fits or the ledger limits it by the remaining batch bound. A BATCH-limited money stop waits. A lost attempt books its full grant as waste, which can exceed the starting request. |
| **SEAL only under the GATES versions** | Plumbing is selected when an attempt is dequeued, and the bench when GATES is dequeued. The case records the actual successful GATES versions. SEAL checks both versions again after dequeue; if either changed, it returns without starting and the case reruns GATES. |
| **Waking waiting cases on settle** | After every settle and `settle_lost`, the attempt workflow sends `settled` to the batch. A case in WAIT_FOR_BOUND sends `waiting` and then waits on `recv("wake")`. The batch wakes every waiting case on each `settled` and each `BOUND_RAISED`, then forgets them (a case still short sends `waiting` again). A waiting case also rechecks every `wake_poll_s` (default 300 s), which covers a `settled` that raced ahead of its `waiting`. A waiting case holds no slot (it is outside the queue). Tested: a case waits on the bound and resumes when another case settles, with no `BOUND_RAISED`. |
| **Registering queues before recovery enqueues** | Rule 6 above. Test: a batch is killed while a case's ADMIT is enqueued but not yet run; the restart registers queues after `launch()`, and the recovered ADMITs still never overlap. |
| **Checking the constructed instance for Conductor** | `assert_no_conductor(os.environ, config)` before construction; `engine.check_instance(dbos)` after: `conductor_key` and `conductor_url` are None and `GlobalParams.dbos_cloud` is false, else `ContractError` before `launch()`. Tested both ways. |
| **Sub-minimum CASE grant diagnoses, sub-minimum BATCH grant waits** | `decide_grant` above. |
| **Every `infra:cancelled` result settles with `settle_lost`** | `policy.settles_lost(result)`: `infra:cancelled`, plus the executor's own codes for an attempt whose usage is unknown (`infra:worker_lost`, `infra:attempt_absent`, `engine:executor_raised`, `engine:executor_bad_result`). They book the whole grant (at most one request figure) as waste. Every other result settles its real usage, with `waste=settles_as_waste(result)`. Tested. |

### Settled after WP4 (`de/wp4`, `factory/durable/classify.py`)

| Item | Settlement |
|---|---|
| **Operator pauses** | WP4 maps `PauseRequested` and `paused` to INFRA_ERROR `infra:paused`. `policy.is_pause` names that code (`PAUSE_REASONS`), and `decide` RETRIES it whatever the infra count. The engine does not count it in `step_infra_errors`, waits `Timing.pause_retry_s` (default 900 s, WP4's flat backoff; releasing the worker if that exceeds `release_worker_after_sleep_s`), then starts attempt n+1. A pause therefore never uses the infra-retry allowance, never leads to DIAGNOSE and is never scored; it settles as waste, never against the case's money. Tested in policy and on DBOS (four pauses with an allowance of one still seal). |
| **`reset_at`** | The engine never sees stop text and does not call the Classifier: the worker classifies the runner's stop before writing its result (contract `Classifier` docstring; design, "Workers and the wire protocol"). So the call site that can pass a known reset time (the ledger's `claude_resets_at`, `provider_failure.reset_at`) is WP5a's `worker_step.py`. The engine uses `StepResult.retry_at` as given, through `wait_seconds`. Nothing changes in WP1; WP5a should pass `reset_at` when it holds one. |
| **Provider limits and credentials** | The founder's 2026-11-05 decision supersedes the handoff's generic 96-limit cutoff: genuine provider limits wait without a count-based stop, and credential problems are visible, unscored configuration waits. See `durable-execution-provider-waits.md`; WP5a and WP8 integration gates remain open. |
| **Batch-deadline stops** | At or after `deadline_epoch`, `infra:deadline` does not count against the infra allowance and never causes a diagnosis. The engine waits `pause_retry_s` before each retry. The same code can mean a worker deadline, so after the batch deadline such a worker timeout also retries without a cap; WP5a must remove batch-deadline checks in the step path. |
| **A money stop before any spend** | `money_wait` can occur when the next call cannot fit, even if the current grant has not been spent. Under a positive BATCH-limited grant it waits; a round limit is not a money wait. Batch-only work with a fully granted request retries with an increased request, even when the prior attempt spent money. Ordinary case-limited work gives up. |
| **`money_wait`, other cases** | The same routing applies when some, but not all, of a batch-only grant has been spent. A fresh attempt gets a fresh grant; there is no per-step monetary cap. |
| **GATES-level EXHAUSTED under `engine:`** | Noted. The engine routes on outcome, not stage, so `engine:` changes nothing here; `report.py` shows it only if allowlisted. |

### Other decisions

- **INPUTS keep their batch scope.** Each StepInput carries the original batch INPUTS
  Ref and its ciphertext is fetched from the batch scope. Only ADMIT gets the batch
  key. Non-ADMIT steps use the case settings restored from their snapshot; WP11 must
  put the required settings in that snapshot. See the rejected alternative and its
  review in `durable-execution-case-inputs.md` and the corresponding review record.
- **The first registry is a launch argument.** `BatchSpec` has no registry Ref, and
  ADMIT requires one. `Engine.start_batch(spec, initial_registry)` takes it; WP8's
  launch command seals it. Contract finding (below).
- **Worker release.** Every provider or credential wait releases the worker. Other
  sleeps longer than `release_worker_after_sleep_s`, and terminal and escalated
  states, also release the case's last lease. A worker that `alive()` reports gone while its attempt
  polls RUNNING ends the attempt as `infra:worker_lost`; n+1 acquires a new worker
  and restores the snapshot.
- **ABSENT** is tombstoned and confirmed before it becomes `infra:attempt_absent`.
  A DONE result whose output Refs are confirmed missing becomes `infra:output_missing`;
  conclusively invalid ciphertext becomes `infra:output_invalid`. Temporary store,
  key-service or age failures retry verification of the same result rather than
  launching another attempt. A checkpoint is kept only after the same check.
- **Restoring from snapshot.** Every attempt restores the case's latest snapshot. A
  non-OK result that carries a snapshot replaces it, so a retry restores it (design,
  "The snapshot").
- **Extensions** set `in_extension` from EXTEND until the extension's GATES result;
  `progressed()` compares the passed gates before the extension with the extension's
  GATES `passed`. No extension starts after `deadline_epoch` (it RETIREs).
- **Replacements.** A case sends `line_stopped` once, the first time its action is in
  `ENDS_LINE_OF_WORK`; the batch applies `starts_replacement` with admission open
  meaning: no STOP_ADMISSION, before the deadline, and fewer than `target_sealed`
  sealed.
- **Seam failures.** Ledger and other engine-side seam errors carry only fixed codes.
  Pool failures preserve WP2's fixed `PoolError.reason`, free the unstarted grant,
  and follow the normal infra retry policy. Replay uses the already-recorded worker
  lease; if inputs cannot be fetched, it still reconciles that worker and never
  assumes a previous execution spent zero. If `guarded_run` catches an unexpected
  executor failure or invalid result, the attempt reconciles that same lease before
  settlement, accepting a late valid result or waiting for a tombstone or proven
  worker death. An unreachable worker retains its grant rather than racing a retry.

## What it deletes

Nothing yet. WP9 deletes the old paths after the final exam.

## Tests

Workflow tests use real DBOS 3.4.0 on SQLite with the following seam fakes; executor
tests also exercise the real WP3 age sealer and local store: a file-backed worker (`start` with O_EXCL
markers, per-case `attempt_busy`, tombstoning `cancel`, first-wins results, a
deadline, injectable transport failures and worker death), a file-backed ledger
following the `Ledger` docstring (labels, waste, `settle_lost`, idempotent replay), a
directory artifact store, a keyed-stream sealer using `derive_keys` and
`artifact_digest`, and a fixed key service.

| File | Tests | Covers |
|---|---|---|
| `tests/factory/test_durable_policy.py` | Policy routing, deadlines, genuine provider waits, money-stop cases, absolute extension and resume ceilings, and settlement. |
| `tests/factory/test_durable_engine_fakes.py` | Contract-oriented worker, ledger and artifact fakes and the DBOS test harness. |
| `tests/factory/test_durable_engine_executor.py` | Worker reconciliation after lost transport or replay; original leases; safe pool reasons; real age/store scope and output authentication; settlement. |
| `tests/factory/test_durable_engine.py` | DBOS sequences, failures, retries, provider sleeps, releases, money, queued version changes, global concurrency, worker cleanup, and recovery. |
| `tests/factory/test_durable_report.py` | Failed or missing case cards reflect the DBOS workflow failure. |
| `tests/factory/test_durable_engine_exam.py` | The 20-kill mid-term exam: same case sequence and ledger as an uninterrupted batch, without duplicate worker execution or overlapping ADMIT. Must be rerun after these changes. |

The fake ledger labels a tie between the request and the case's remaining money as
NOTHING ("capped" read strictly), and a tie with the batch's remaining bound as BATCH, as
the docstring says. For an ordinary step, `decide` gives the same action for NOTHING and
CASE; only `decide_grant` tells them apart, and only below the $1 minimum, which a tie
reaches only if `case_money_usd_micros` itself is below $1. So WP6's reading of that tie
does not change the engine's behaviour at any real setting.

## Murphy rows targeted

Rows 5, 18, 19, 28, 33 and 51 (design, "Murphy rows"). None closes in WP1: ENGINEERING
section 2 closes a row only with a test on real artifacts, and WP1 tests on fakes.
WP1's tests prove the engine half of each:

- 5 (two-day continuation) and 51 (restart resumes the whole state machine): the exam
  and the provider-sleep replay;
- 18 (one failure aborts the launch): each case and attempt is its own workflow; an
  attempt failure is an outcome of that case only;
- 19 (no controller after a Mac outage) and 28 (holder bottleneck): the engine on the
  control VM owns dispatch through durable queues;
- 33 (worker loss): `infra:worker_lost`, then a new worker restoring the snapshot.

They close with WP9's live final exam.

## Contract findings

1. **INPUTS scope.** `BATCH_SCOPED` holds `INPUTS`, `StepInput.inputs` is required
   on every step, and the design sends the batch key only to ADMIT. A non-ADMIT worker
   keeps the Ref for provenance but obtains its settings from the case snapshot.
2. **No initial registry.** `BatchSpec` ("the factory's whole input") has no
   `STATEMENT_REGISTRY` Ref, but the first ADMIT needs one. WP1 takes it as a launch
   argument.
