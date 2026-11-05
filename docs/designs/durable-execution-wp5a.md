# WP5a: worker-side step runner

Status: design note for WP5a of `docs/designs/durable-execution.md` (wave 1, brief in
`docs/designs/durable-execution-wave1.md`). Branch `de/wp5a`, cut from
`durable-execution` at `db13be8`.

## Problem

The engine (WP1) runs one attempt of one step at a time on a worker, over `boat ssh`,
through the frozen wire protocol in `factory/durable/contract.py` (v5). Nothing on the
worker answers that protocol yet, and `factory/run.py` can only run a whole case from
`main()`, with its own in-process lifecycle: repair loops, final repairs, candidate
reselection, mid-step checkpoints to R2 and a cumulative $50 case budget. Under the
engine those decisions belong to the engine, so they must be switched off there, and
each step must run alone from a restored snapshot.

## What WP5a builds

Files written: `factory/durable/worker_step.py`, `factory/run.py` (hooks only),
`tests/factory/test_durable_worker_step*.py`, and this note.

### 1. The worker command (`factory/durable/worker_step.py`)

`python3 -B factory/durable/worker_step.py start|poll|cancel`, cwd `RELEASE_ROOT`, paths
relative to the worker user's home, exactly as `attempt_paths` lays them out. Extra
worker-private files, all under `durable/`:

| Path | Purpose |
|---|---|
| `durable/locks/<h>.lock` | per-case `flock`, `h` = sha256 of the case id (first 32 hex) |
| `durable/cases/<h>/<attempt id>` | index of the case's started attempts, for the busy check |
| `<attempt>/unit.json` | `{unit, pid, starttime}` of the detached supervisor |
| `<attempt>/supervisor.log` | the supervisor's own log (no keys) |

- **start.** Reads one `start_frame` JSON object on stdin and parses it strictly
  (`step_input_from_record`; keys must be base64 of 32 bytes, the case key present, only
  case and batch scopes). An unparsable `input` exits 2 (a transport failure: the
  control side's frame is broken, and there is no key to answer under). Then, under the
  per-case lock:
  1. `mkdir` of the attempt directory, which fails if it exists: an existing marker
     (an earlier start, or a cancel tombstone) means exit 0 and do nothing;
  2. busy check: any other indexed attempt of the case that has no result and a live
     unit makes this attempt write `INFRA_ERROR infra:attempt_busy` (first-wins) and
     exit 0;
  3. a bad `keys` object gets `INFRA_ERROR infra:bad_frame`;
  4. otherwise it forks the supervisor (`setsid`, stdio to `supervisor.log`), records
     `unit.json` while still holding the lock, and exits 0.

  The keys never touch the worker's disk: the supervisor and step process inherit the
  frame in memory through `fork`.
- **Detach: setsid, not systemd.** The design allows either. A systemd unit would need
  the keys passed through a file or a socket, so WP5a uses `fork` + `setsid`, and the
  unit name `durable-<id16>` is recorded in `unit.json`. Every process of the attempt
  carries `DURABLE_ATTEMPT=<attempt id>` in its environment, which is how the worker
  finds them again, including processes a model CLI re-parented to init.
- **Live** means: no result file, and some process of the attempt still running (the
  supervisor recorded in `unit.json` with the same `/proc` start time, or any process
  carrying the attempt's environment tag). A unit tearing down after its result is
  written is therefore never live, so it never makes the next seq busy.
- **Supervisor.** Forks the step process, waits for it, and enforces `deadline_s`: at
  the deadline it kills the attempt's processes and writes `INFRA_ERROR infra:deadline`.
  If the step process exits without a result it writes `INFRA_ERROR infra:step_crashed`.
- **Step process**, in order:
  1. reads `RELEASE.json` (`RELEASE_MANIFEST`); it must hold exactly `plumbing_version`
     and `bench_version` equal to the StepInput's, else `infra:version_mismatch`
     (`infra:release_unreadable` if it cannot be read as that object);
  2. ADMIT and DIAGNOSIS end at once with `INFRA_ERROR engine:admit_unavailable` and
     `INFRA_ERROR engine:diagnosis_unavailable`. **Not implemented yet:** ADMIT runs
     through WP11's adapter and DIAGNOSIS through WP10's, both in wave 2;
  3. opens the snapshot blob (`blobs/<digest>.case.age`) with the case key and
     restores it into `~/work/<case_id>` (the old directory is removed first, so the
     restored tree is exactly the snapshot); also opens `feedback` and `ruling` blobs;
  4. runs `run.context_for_step` and `run.run_step` (below);
  5. classifies a stop with the `Classifier` (WP4), builds the snapshot from
     `run.retained_paths`, seals every output with the `Sealer` (WP3) into `out/`, and
     writes the result last, first-wins: the record goes to a temporary file and is
     `link()`ed to `results/<id>.json`, so neither an attempt nor a cancel can replace
     the other's result.
- **poll.** Reads `key_frame`. Prints `Poll(DONE, result)` if the result exists,
  `Poll(RUNNING)` if the unit is live, otherwise `Poll(ABSENT)`. `checkpoint` is always
  null until WP5f.
- **cancel.** Reads `key_frame`. Under the per-case lock: creates the attempt marker if
  missing (a tombstone, so a late `start` does nothing), kills the attempt's processes
  (SIGTERM, then SIGKILL after 5 s; `sudo -n kill` for processes of the isolated
  calibrator users), and writes `INFRA_ERROR infra:cancelled` with `Usage()` if no result
  exists. WP1 settles every `infra:cancelled` with `settle_lost` (review 5, N6).
- **Exit codes.** `start`, `poll` and `cancel` exit 0 whenever they answered. Anything
  else (bad frame, I/O error) exits non-zero, which the channel treats as a transport
  failure (RUNNING).
- **Seams.** The Sealer and Classifier are injected (`Worker(sealer=..., classifier=...)`).
  The command-line default loads `durable.artifacts.AgeSealer()` (WP3) and
  `durable.classify.classify` (WP4); until those merge, a missing module ends the attempt
  with `INFRA_ERROR infra:sealer_unavailable` or `infra:classifier_unavailable`. Tests
  inject an age-CLI sealer and a minimal classifier written from the protocols.

### 2. Result rules (what the worker reports)

| Step | Worker result |
|---|---|
| WRITER | OK `writer:validated` once G1 and today's early checks pass. A stop goes to the Classifier. A writer that changes nothing for its feedback, or still fails G1/early checks after `rounds` writer calls, is EXHAUSTED (`writer:unchanged_repair`, `writer:rounds_exhausted`). |
| STRESS | OK `stress:clean` (no feedback), or OK `stress:findings` with WRITER_FEEDBACK holding the stress findings or the early-review (G8/G9) problems. A malformed or unfinished report is INFRA_ERROR (`stress:malformed_report`, `stress:interrupted_review`, `stress:unfinished_validation`, `stress:unfinished_diagnostic`, `stress:case_changed`): a broken run, never writer feedback. |
| GATES | OK `engine:gates_passed`; GATE_FAILED `g<n>:failed` naming the gate, repairable with feedback for today's repairable set (G4, G5, G6, G8, G9, G11, G13–G17), not repairable otherwise; NEEDS_FOUNDER `g<n>:reviewers_disagree` for a split G8/G9 panel (some but not all approve) and `g<n>:review_inconclusive` for an inconclusive G16/G17 review; INFRA_ERROR `infra:gate_error` for a gate failure that is an operational error, and the Classifier's answer for `infrastructure_exhausted`. Every result names `passed`: gates whose card status is `pass`, reused ones included. A GATE_RECEIPT holds the card's gate fields. |
| SEAL | OK `seal:sealed` with SEALED_ARCHIVE (tar.gz of the work tree after today's evidence gathering) and `hard` (`difficulty == "hard"`). |

Every result after a restore carries a CASE_SNAPSHOT when the worker can produce one;
OK always does (if it cannot, the result is `INFRA_ERROR infra:snapshot_failed`). Non-OK
results also carry a DIAGNOSTIC: the stop text, traceback and the tail of the runner
log. Every result is checked with `StepResult(...)` and `check_result_for` before it is
written; a result that fails them is written as `INFRA_ERROR infra:bad_result`.

**WRITER_FEEDBACK format** (WP5a writes it from STRESS and GATES; WP10's diagnosis must
write the same): JSON `{"version": 1, "source": "stress"|"gates"|"diagnosis",
"problems": [str], "attack_report": "round-<n>.json" | null}`. `attack_report` names a
report under the snapshot's `attacks/`.

**Usage.** Read from the worker's case ledger (`continuation-budget.json`), as the
difference between the attempt's start and its end: `calls`; `paid_usd_micros` is the
change of today's case-spend valuation (`case_spending(...)["total_spent_usd"]`: priced
cost plus the subscription list-price estimates), rounded up to the micro-dollar, which
is the figure the money ceiling is enforced on; `list_usd_micros` is the list-price part
of the new events alone (`list_cost_usd` plus `estimated_subscription_cost_usd`). If the
ledger has unpriced events, `paid_usd_micros` is at least the grant.

### 3. The `run.py` hooks

All new code is behind `c.engine` (set only by `context_for_step`); `main()` never sets
it, so behaviour without the engine is unchanged.

- **`context_for_step(step_input, work)`** builds the run context from a restored work
  tree: `case_id`, `work`, `case`, the private card `scorecard.json`, `models`, `seed`,
  `statement`, `prepared_factory_slots`, `manifest0 = bench_manifest()`, and `c.args`
  from the parser defaults plus the card's `recovery_config`. It sets the ledger to
  `work/continuation-budget.json` (inside the snapshot), clears a sticky ledger stop
  with `budget.resume_ledger`, and normalizes case permissions as a resume does.
- **`run_step(c, step_input, feedback=None, ruling=None)`** dispatches WRITER, STRESS,
  GATES and SEAL (ADMIT and DIAGNOSIS never reach it). It returns a plain dict the
  worker turns into a StepResult, with a stop string for the Classifier when the step
  stopped.
- **`retained_paths(c)`** lists the snapshot, relative to `c.work`. It first copies the
  bench-side evidence named by `gate-cache/*.json` from `BENCH/results` into
  `c.work/bench-results/`, where `gate_state.load` also looks. The list, exactly:
  - the case: `case/`;
  - the private card `scorecard.json`, the ledger `continuation-budget.json`, and
    `usage-receipts/`;
  - gate evidence: `gate-cache/`, `gate-details/`, `judge_breadth/`, `review-*/`,
    `bench-results/`, `fairness-*/`, `g11-evidence/`, `g2-url-retrieval/`,
    `strategy-g14-checkpoints/`, `delivery-provenance.json`;
  - G10's attempt receipts: `strong_calibrator/`, `easy_calibrator/`, `early_probe/`;
  - writer and stress state: `attack-state.json`, `attacks/`, `diagnostic-budgets/`,
    `infra-attempts.json`, `selection-rejections.json`, `fixes/`;
  - admission files: `prototype.json`, `public-search.json`, `freshness-verdict.json`,
    `freshness-repair.json`, `freshness-inflight.json`, `freshness-restored.jsonl`,
    `idea-realism.json`, `statements/`;
  - the audit trail: `logs/`, `transcripts/`;
  - engine inputs: `engine-feedback.json`, `engine-ruling.json`.

  Everything else is dropped, named in `run.SNAPSHOT_DROPPED`: `agent-state/` (gathered
  only at SEAL), the legacy lifecycle's files (`durable-checkpoint.json`,
  `stress-publication.json`, `provider_wait.json`, `provider_waits/`,
  `operational-effects.json`, `job-money*.json`, `gate-continuation.json`,
  `late-defect.json`, `founder-ruling-applied.json`, `extension-*`, `rehearsal-*`),
  rejected candidates and the ledger's lock files. `c.early` and `early_hash` are not
  persisted, so G3 reruns inside GATES; G4, G5 and G15 are reused through `gate_state`.

**Lifecycle branches switched off under the engine** (design WP5a row; reviews 3 N8 and
5 N5):

| Branch | Under the engine |
|---|---|
| `validate_and_repair`: repair loop, `late_recovery.mark_gates`/`invalidate`, `stop_defect` | runs `run_gates` once and returns; the engine REPAIRs |
| `write_and_attack`: final `builder-precheck` call and `stop_defect` | not reached by the engine; guarded to stop with `rounds_exhausted` instead |
| `reselect_candidate` | raises `BudgetError("engine_reselection_disabled")`; reselection is ADMIT's |
| `_gate_completed`: `checkpoint_progress` | skipped (also the identical call in `_opencode`) |
| in-process case budget: `writer_round_estimate` reservations (`write_and_attack`, two places) | skipped |
| cumulative `case_budget.limit_usd` | replaced by the attempt's own ceiling (below) |

**Money: the ceiling is the only money stop.** `context_for_step` reads the restored
ledger's `spent_usd` as the attempt's baseline and sets `c.args.case_budget = baseline +
money_ceiling_usd_micros / 1e6`. Every existing check (`case_budget_boundary` before
each call and between gates, `require_case_budget` in `run_budgeted`) then compares
cumulative spend with that figure, which is the same as comparing this attempt's spend
with its ceiling. `c.args.max_cost` (the cumulative opencode-only cap) is set to a
constant `ENGINE_COST_CAP = 1e9`: off, and constant so gate fingerprints and the stress
binding, which hash it, stay identical across steps. A case that has spent $55 and gets
a $20 grant therefore runs its writer round, and stops at the first model call after
its own spend reaches $20 (`budget_exhausted`, EXHAUSTED `writer:money`). As today, an
in-flight model call is not interrupted, so an attempt can overshoot its ceiling by the
call in flight (contract finding 3).

The engine's WRITER and STRESS bodies are new functions (`engine_writer_round`,
`engine_stress_round`) built from today's pieces (`prompt`, `run_context`, `opencode`,
`g1`, `early_checks`, `attack_report`, `loop_freshness`, `early_review`), rather than
flags threaded through `write_and_attack`, whose receipts and resume heuristics are the
in-process recovery the engine replaces (WP9 deletes them).

## What it deletes

Nothing yet. WP9 deletes the switched-off branches once the final exam passes.

## Tests

`tests/factory/test_durable_worker_step.py`, on the public practice case
(`run.build_fixture`, the dry-run fixture) and real tooling: the real `age` CLI, real
`bin/` tooling for G1, the real e15450 ledger (spent $52.79) from
`tests/factory/fixtures/router-paid-deepseek.json.gz`, and the real `budget.run_budgeted`
with a local process standing in for the model CLI (no provider is called).

- the wire protocol end to end through the real command, as subprocesses on this
  machine: start, detach (the start returns while the step runs), poll RUNNING then
  DONE, the output blobs, ABSENT for an unknown attempt;
- a repeated start does nothing; a cancel tombstone makes a late start do nothing;
- `attempt_busy` under the per-case lock, including two concurrent starts of the same
  case; a unit whose result exists is not live;
- first-wins: a cancel after DONE keeps the result; a cancel of a live attempt kills its
  processes and its late result cannot replace `infra:cancelled`;
- the deadline kills the attempt (`infra:deadline`);
- version mismatch and an unreadable `RELEASE.json`;
- restore and snapshot round trip: exact retained subset, dropped names, bench evidence
  copied into `bench-results/`, ledger and card restored;
- ADMIT gives `engine:admit_unavailable`;
- WRITER, STRESS and GATES dispatch up to the Docker boundary;
- the lifecycle switches: one gate pass without repair, no `mark_gates`, no
  `checkpoint_progress`, no reselection, no final builder call;
- money: a restored $52.79 ledger with a $20 ceiling runs its writer round; the next
  call after the attempt's own spend reaches the ceiling is refused;
- **GATES snapshot reuse** (Done when): a GATES step on one worker home, its snapshot
  restored on a fresh worker home, a second GATES step reuses the first one's passed
  gates.

**Needs a Docker host.** The GATES reuse test runs the real gates (G3 builds the shop),
so it skips here with an explicit reason and runs where Docker exists. The WRITER money
test runs here: in the dry-run practice case the writer round has no early checks, and
only the bench preparation (`engine_prepare_bench`, the Docker boundary) is replaced.
A Docker-host variant runs it with the real preparation.

## Contract findings (reported, not changed)

1. **INPUTS cannot be opened by non-ADMIT steps.** `INPUTS` is batch-scoped, and only
   ADMIT receives the batch key, yet every StepInput must carry `inputs`. The worker
   therefore ignores `inputs` outside ADMIT; ADMIT (WP11) must copy what later steps need
   (models, rotation, source, runner settings) into the case snapshot. Consistent, but
   the contract does not say it.
2. **No trusted reset time reaches the Classifier.** The protocol is
   `classify(stop, *, step, now)`. The router's `ProviderWait` carries `retry_after`, and
   WP4's `classify` accepts an optional `reset_at`, but the frozen protocol does not.
   WP5a passes only the protocol arguments, so every provider limit sleeps WP4's
   backoff.
3. **The ceiling is checked before calls, not during them.** The runner cannot stop a
   model call in flight, so one attempt can overshoot `money_ceiling_usd_micros` by its
   last call, and "concurrent cases can never overshoot either limit" holds only up to
   one call per running attempt.
4. **GATES OK has no stage of its own.** `REASON` has no `gates` stage; WP5a uses
   `engine:gates_passed` (WP4 also uses `engine` for GATES).

## Open items for other packages

- **WP11:** the initial snapshot must hold `case/` (statement, admitted prototype),
  `scorecard.json` with `case`, `dry_run`, `source`, `seed`, `models`, `roles`,
  `recovery_config` and `factory_slots_prepared`, and optionally the ledger.
- **WP4/WP1:** stops raised inside STRESS that are verdicts rather than faults
  (`freshness_public_match`, `freshness_unresolved`) reach the Classifier and become
  `infra:unclassified_stop`.
- **Founder rulings** are restored to `engine-ruling.json` and exposed as
  `c.engine_ruling`, but no gate reads them yet.
- **SEAL** does not encrypt the statement to the statements recipient (that is the
  registry, WP11) and does not upload anything (the control side moves blobs).

## Murphy rows

None close with WP5a. It contributes the recovery package for row 34 (with WP3's
store) and removes the worker-side half of row 9 (the in-process $50 stop), but each
closes only with the live runs of WP9.
