# Durable execution for the case factory

Status: design for review, revision 2 (2026-11-05), after
`docs/reviews/durable-execution-design-1.md`. Branch `durable-execution`, cut
from `factory-simplify` at `2df5664`. This supersedes the "no second event engine"
direction of `docs/factory-single-path.md`. Picture: the "Case Factory Blueprint"
page (private claude.ai artifact).

## Problem

The factory turns three inputs into sealed cases:

```
app pin (repo + commit) + promise + case count  ->  factory  ->  sealed cases
```

Turning inputs into cases takes a long time: cases ran 30–77 wall-clock hours on
Oct 14–20. It costs a lot of quota, and it is interrupted constantly. The 50
non-dry-run scorecards in `sealed/` record about 460 interruptions:

| Interruption | Count |
|---|---|
| `opencode_error` | 210 |
| Provider limits | 99 |
| Stalls | 74 |
| Timeouts | 23 |
| Codex errors | 11 |

To reproduce these counts, count each card's `continuation_budget.previous_stops`
entries and its `terminal_stop`, prefix before `:`, over
`sealed/case-*.scorecard.json` where `dry_run` is false.

A case cannot restart from scratch after each interruption; it has to carry on.
Today, carrying on is hand-built. `docs/factory-single-path.md` lists 12 launch
and recovery paths, each with its own locks, key handling, receipts and rules of
proof. State is spread over public cards, continuation ledgers, encrypted
checkpoints, holder memory, coordinator journals, R2 and the founder's Mac. Most
open rows in `docs/murphy-register.md` are two copies of that state disagreeing, or
a crash between two writes. Each fix adds a receipt, and the receipt adds the next
row.

## Goal, and how we know it works

A batch launched from its inputs runs until it has `target_sealed` cases, or until
it hits its money bound or its deadline. Killed workers, a rebooted control VM and
provider limits never need a human. Only a real disagreement between reviewers
reaches the founder.

- **Mid-term exam (end of wave 1).** WP1's integration test: a batch of three cases
  on fake workers survives a `kill -9` of the engine at 20 random points, with no
  step run twice after it finished.
- **Final exam (WP9).** A live practice batch survives a deleted worker and a
  restarted control VM without a human.

## Change

There is one durable workflow per case, on the always-on control VM. The engine is
DBOS (a Python library, `dbos==3.4.0`) on Postgres; tests use SQLite. Bench logic
is kept. Steps return typed outcomes, and pure functions in
`factory/durable/contract.py` decide what happens next.

### The case, step by step

The engine **records** each step's result the moment it finishes. After a crash,
the engine **replays** the case. Replay returns recorded results without running
them again, and only the step that was open when the crash happened runs again.
`tests/factory/test_durable_replay.py` proves this on the real engine.

1. **ADMIT.** Choose the bug and admit its statement. This runs on a batch-level
   DBOS queue with concurrency 1, so concurrent cases and replacements can never
   choose the same bug. It reads and updates the `STATEMENT_REGISTRY` artifact.
2. **WRITER round r**, carrying the feedback from the previous round, if any.
3. **STRESS round r.**
   - Clean (OK, no feedback): go to the gates.
   - Findings (OK with feedback): REPAIR, which is the next writer round, while
     rounds remain. Otherwise DIAGNOSE.
4. **Gates in `GATES` order.**
   - A gate is skipped when its last pass was on a snapshot with the same digest,
     under the same gate `bench_version`. Today's early checks (G3, G4, G5 and
     G15) and early reviews (G8, G9) are explicit GATE steps that the workflow
     inserts after a writer round. The same rule reuses their results.
   - G10 starts as a child workflow when G6 passes. It runs beside G13–G15 and
     G7, and is joined before G17 (`CONCURRENT_FROM`).
   - Gate steps never change the case snapshot; their evidence goes into
     receipts. That is what makes the concurrent join trivial. WP5a enforces it
     with a test that the output digest equals the input digest.
   - A repairable failure means REPAIR, back to step 2 with the feedback. The
     new snapshot invalidates every gate, so all gates rerun, as
     `validate_and_repair` does today. A non-repairable failure is a scored
     rejection and the case RETIREs.
5. **SEAL** (G12) produces a `SealedCase`. The control VM generates the public
   scorecard from the engine tables. No code reads a scorecard back to make a
   decision.

### What happens after each outcome

These outcomes come out of `decide()` and `decide_diagnosis()` (ENGINEERING
section 3):

- **PROVIDER_LIMIT.** SLEEP until `retry_at`. A sleep spends no allowance. Only
  more than `max_consecutive_limits` limit attempts that each spent money go to
  DIAGNOSE, as a guard against a misclassified error. If a sleep lasts longer
  than `release_worker_after_sleep_s`, the worker is released.
- **INFRA_ERROR.** RETRY, never scored and never sent as writer feedback. After
  `max_infra_retries_per_step`, go to DIAGNOSE.
- **EXHAUSTED.** DIAGNOSE. The case ran out of its own rounds or its money.
  - Only the worker emits EXHAUSTED: it emits it when an attempt reaches its
    `money_ceiling_usd_micros` or the runner's own limits.
  - The batch money bound is not a case outcome. When `Ledger.reserve` refuses a
    paid step, that case waits for a "bound raised" message, and the batch stops
    starting new cases.
- **DIAGNOSE.** The batch starts a replacement case at once. The original case
  runs a DIAGNOSIS step, and its verdict goes through `decide_diagnosis`:
  - `factory_bug`: RESUME_AFTER_FIX. The case waits for a "plumbing release"
    message, then resumes. At most 3 times, then RETIRE.
  - `close_to_passing`: EXTEND, meaning one writer round, its stress round and a
    gate rerun. At most 5 extensions. Every extension after the first needs
    `progressed()`. Extensions spend from the batch money bound.
  - `not_converging`: RETIRE.

  If both the extended original and its replacement seal, both are kept.
- **NEEDS_FOUNDER.** ESCALATE. The case parks and waits for a founder message,
  frees its slot and its worker, and the batch starts a replacement. Only the
  steps that run independent reviews (G8, G9, G16, G17 and stress review) may
  return it.

### Workers

The control VM runs every step and drives a Boat worker through `WorkerChannel`
over `boat ssh`. Workers never touch the database.

- `start()` sends the step-input record and the scope key on stdin.
- The worker detaches the attempt (systemd-run or setsid), so a dropped ssh
  session or a control-VM restart never stops it.
- The worker restores the input snapshot, runs today's code, and writes an
  encrypted output snapshot to R2. It writes the `StepResult` record under the
  step's idempotency key and nowhere else.
- `poll()` returns that record. A replayed step polls before it starts anything.
- The worker kills an attempt at `deadline_s` and reports `infra:deadline`. The
  control side stops polling at the deadline plus a grace period, then cancels.
- A case keeps its worker between steps, because the shop build is expensive.
  That is a cache, not state. If the worker dies, the next attempt acquires a new
  worker, which restores the last snapshot.

**The snapshot** (`CASE_SNAPSHOT`) is the `c.case` tree plus a retained subset of
`c.work`. The subset starts with `attack-state.json`, `prototype.json`,
`infra-attempts.json`, `gate_state/` and the admission files. WP5a owns the exact
list. Its test: a fresh worker that restores a mid-round snapshot continues the
round's recovery.

The step-internal layers keep working inside a step in waves 1–2: `gate_attempt`,
`factory_waste.attempt`, `infra-attempts.json` and the `gate_state` fingerprints.
Reuse across steps moves to the engine's digest rule. WP9 decides which in-step
layers can then go.

### Money

`Ledger.reserve` holds each paid attempt's ceiling against the batch bound before
the attempt starts, so concurrent cases can never overshoot the bound together.
`settle` books the actual usage and frees the rest. The worker stops at the
ceiling.

### Versions

- **Engine version.** DBOS recovers only workflows whose `application_version`
  matches the running engine. So the version is pinned (`factory-engine-1`) for
  the life of the engine database.
- **Plumbing.** Plumbing lives in step code, which replay never checks, so a fix
  applies from the next step that runs. Proven: a restart under changed step code
  resumes the case, and the open step runs the new code.
- **Workflow functions.** Changes go behind `DBOS.patch()`.
- **StepInput fields.**
  - `plumbing_version`: the release current when the attempt started.
  - `bench_version`: for a GATE step, the digest of that gate's own code and
    data; for other steps, the bench as a whole. Pinned per case, so a gate
    change reruns only that gate.

### Secrecy

DBOS records every step argument, result and exception, so all of them are
content-free by construction:

- **Reason codes** follow a fixed grammar, `<stage>:<lowercase_and_underscores>`:
  no paths, no digits, no dots. The public card shows outcomes and stages, plus
  only the reasons on WP4's published allowlist.
- **Exceptions.** `guarded_run` is the only way the engine calls an executor. It
  turns any exception into `engine:executor_raised`.
- **Artifact digests.** `Ref.digest` is HMAC-SHA256 under the scope key (the case
  key, or the batch key for inputs and the registry). A guessed plaintext cannot
  be confirmed, and two cases cannot be compared.
- **Conductor.** The engine refuses to start if DBOS Conductor (its hosted
  console) is configured (`assert_no_conductor`).
- **Case content** lives only in age-encrypted R2 artifacts, opened in worker RAM
  with the scope key from the key service.

### Engine rules

1. Workflow functions are deterministic. Read the clock only through a step (a
   `now()` step), and never read files or the network outside steps.
2. Waits use `DBOS.sleep(wait_seconds(retry_at, now()))`. The duration is always
   positive, because DBOS records nothing for sleep(0) and replay would then lose
   its place. Proven: a restart after the wake time has passed still resumes.
3. To resume a case, attach to it (`DBOS.retrieve_workflow`). Never start an
   existing ID again; that races DBOS's own recovery.
4. A step is idempotent on `seq/step/attempt`. `seq` increases with every new
   step, repair, extension and resume, so keys never repeat.
5. The engine calls executors only through `guarded_run`.
6. The `application_version` stays pinned (see Versions).

### The frozen contract

`factory/durable/contract.py` (version 2) is pure, with no I/O and no engine
import. It holds:

- the types: `BatchSpec`, `Step`, `StepInput`, `StepResult`, `Outcome`,
  `Verdict`, `Usage`, `Ref`/`ArtifactKind`, `SealedCase` and `Counters`;
- the policy: `decide`, `decide_diagnosis` and `progressed`;
- the protocols: `ArtifactStore`, `KeyService`, `WorkerPool`, `WorkerChannel`,
  `Ledger` and `StepExecutor`;
- the helpers: `guarded_run`, `wait_seconds` and `assert_no_conductor`;
- strict record conversion.

A change to the contract needs a change to this design and a design review.

## Work packages

Each package gets its own branch, `de/<id>`, cut from `durable-execution`. Each one
needs a short design note if it's over about 20 lines, and a diff goldfish. It
merges back into `durable-execution`.

**Approved exception to ENGINEERING section 1:** `durable-execution` is the
integration branch for this design. It merges `factory-simplify` in at least daily.
New Murphy rows found on it are named `new-durable-<n>` until it merges.

Within a wave, no two packages write the same file.

| ID | Wave | Package | Owns (writes) | Done when |
|---|---|---|---|---|
| WP1 | 1 | Engine core | `factory/durable/engine.py` | Runs on fake pool, channel, ledger and store. The full step sequence, the outcome routing, the G10 child-workflow join, the serialized admission queue, replacements, diagnosis, extensions, resume-after-fix and escalation parking. The mid-term exam. |
| WP2 | 1 | Worker pool and channel, control side | `factory/durable/workers.py`, `factory/durable/channel.py` | Boat creation and deletion use idempotency labels. On restart, orphans are adopted or deleted. `start` for a known key does nothing. Polling stops at the deadline. Tests use real saved Boat CLI outputs. |
| WP3 | 1 | Artifact store | `factory/durable/artifacts.py` | age encryption to the scope key and HMAC digests, with an R2 backend and a local one. A truncated upload is never visible. |
| WP4 | 1 | Failure classification | `factory/durable/classify.py` | A pure `classify(stop) -> (Outcome, reason, retry_at)`. Every stop kind in the 50 real scorecards maps to an outcome. A limit with no reset time gets a defined backoff. Ships the published-reason allowlist and the top `opencode_error` causes from the real logs. |
| WP5a | 1 | Worker-side step runner | `factory/durable/worker_step.py`; the **only** writer of `factory/run.py` in waves 1–2 | Adds these `run.py` hooks: `context_for_step`, `run_step` (dispatch to writer round, stress round or gN), `retained_paths`, and turning off the in-process gate loop and early reuse when running under the engine. Implements detach, restore, run, snapshot and the result under its key. Calls `classify`. G1, writer and stress steps run on the public practice case. Gate steps leave the digest unchanged. |
| WP6 | 1 | Ledger | `factory/durable/ledger.py` | Reserve, settle and replay give an identical ledger, and two concurrent reservations never exceed the bound. |
| WP7 | 1 | Key service | `factory/durable/keys.py` | The scoped VM key (approved 2026-10-29) wraps scope keys. A scope key reaches a worker only over the channel's stdin. |
| WP5b–e | 2 | Remaining gates | one file per group under `factory/durable/steps/`, registered through WP5a's `run_step` | The groups: G2–G5 and G16; G8, G9 and G6; G13–G15 and G7; G10, G17 and G11. Each is tested on the practice case. A needed `run.py` change goes through WP5a's owner. |
| WP10 | 2 | Diagnosis and extensions as steps | `factory/durable/steps/diagnosis.py`; adapts `diagnosis.py`, `diagnosis_dispatch.py`, `extensions.py`, `extension_package.py` and `extension_*.py` | A DIAGNOSIS step returns a verdict, and an EXTEND runs as engine steps. The dispatch and state parts of those modules are listed for WP9. |
| WP11 | 2 | Admission and registry | `factory/durable/steps/admit.py`; adapts `admission.py`, `registry.py` | Two concurrent cases plus a replacement never admit the same bug. The registry survives replay. |
| WP8 | 2 | Control-VM deployment | `control/`, deploy scripts | Postgres with nightly encrypted backups to R2, and a systemd unit for the engine. After a reboot, the cases resume. |
| WP9 | 3 | Cutover and deletion | the deletion list, `factory/run.py` from wave 3 | The final exam passes, then the old paths are deleted and their Murphy rows closed with those runs. |
| WP5f | 4 | Snapshot after every model call | `worker_step.py`, `factory/model_runtime.py` | An interrupted writer round resumes after its last finished call. |

## What it deletes (in WP9, not before)

Each module is read again in WP9 before it goes.

**Replaced by the engine, Postgres and `BatchSpec`** (about 6.4k lines):

- Python: `key_holder`, `batch_holder`, `batch_service`, `batch_transfer`,
  `batch_status`, `batch`, `control_resume`, `coordinator`,
  `coordinator_inventory`, `restart`, `recovery`, `durable_checkpoint`,
  `restore_ledger`, `restore_sync`, `collection`, `job_config`, `job_authority`,
  `founder_decisions` (replaced by escalation messages), `statement_round`
  (replaced by ADMIT).
- Shell: `launch.sh`, `launch-slots.sh`, `collect.sh`, `restore-cases.sh`,
  `statements-round.sh`, `bin/factory-adopt`.

**Deleted outright** (about 1.6k lines): `restore_bundle`, `late_rehearsal`,
`ttl_continuation`, `late_recovery`, `carry_over`, `founder_ruling`,
`resume-in-place.sh`, and the salvage path `run.py:restore_gate_crash`.

**Decided in WP9:**

- `account_handoff.py`: delete it if router account switching covers it.
- `bin/boat-launch-guards.sh` and `control/unbug-resume-launches.*`.
- The dispatch and state parts of the diagnosis and extension modules.

**Kept as offline tools** for cases that are already sealed: `sealed_audit.py`
and `g11_review.py`.

Legacy checkpoints are retired, not migrated (founder decision 2).

## Cost and timeline

**Infrastructure.** One Postgres on the existing control VM. The journal is small,
because it holds only digests and codes. Nightly encrypted backups go to R2. There
are no new paid services; DBOS is a library.

**Effort.**
- Wave 1 is seven packages in parallel, each with a design note, an implementation
  and a diff review.
- Wave 2 is six more packages in parallel.
- Wave 3 is bounded by live runs. One practice batch is at least a day of wall
  clock.

**Timeline.** Waves are gated by their exams, not by dates.

## Tests

Added with this design:

- `tests/factory/test_durable_contract.py` (21 tests):
  - the gate order equals `run.GATES`;
  - the reason grammar refuses paths and sentences, and no exception text reaches
    a record;
  - the Conductor check;
  - the outcome and per-step shape rules;
  - keys never collide across repairs;
  - strict round-trips at every depth;
  - the `decide()` and `decide_diagnosis()` tables, including at most 5
    extensions, at most 3 factory-bug resumes, and progress after the first
    extension.
- `tests/factory/test_durable_replay.py` (4 tests, real DBOS on SQLite):
  - a crash mid-step reruns only the open step, and a second start attaches;
  - a crash during a provider sleep keeps its wake time;
  - a restart after the wake time has passed still replays;
  - a restart under changed step code resumes under the pinned version.

  Passed 3 runs in a row alone, and 4 copies run at once.

Every package adds the tests in its "Done when". They use the real engine and real
saved artifacts (ENGINEERING section 4).

## Murphy rows

None close with this design, because it adds no production path. These rows are
the targets. Each closes only when its package's test, on real artifacts, proves it.

| Package | Target rows |
|---|---|
| WP1, WP8 | 5, 16, 18, 19, 26, 28, 33, 51 |
| WP10 | 9, `new-stream-d-outcome-routes-1`, `new-stream-d-current-comparison-1` |
| WP3 | 27, 34, `new-batch-service-2` |
| WP5f | 35 (coarse steps leave a writer round or G10 without an off-worker boundary until then) |
| WP2 | 17, 29, `new-boat-stop-capture-1`; with WP7, `new-worker-router-delivery-1` |
| WP4 | 4, part of 48 |
| WP7 | 1 |
| WP9 (the path is deleted along with its row) | `new-single-path-1`, `new-batch-service-1`, `new-batch-service-3`, `new-batch-service-4`, `new-batch-auth-inputs-1`, `new-registry-pending-promotion-1`, `new-batch-restore-admission-1`, `new-preallocation-import-recovery-1`, `new-ancestor-release-binding-1`, `new-predispatch-import-recovery-1` |

Rows 2 and 47 need a batch-wide account scheduler and shared account health. That
is router work outside this design.

## What this does not fix

These all stay as work:

- gate science;
- router policy and account scheduling;
- Docker and SQL hangs inside a step;
- stray-process cleanup;
- the causes of model-CLI errors.

The engine turns each of these into a typed, retried, cheap event. It does not
make them stop happening.

## Founder decisions needed

1. **Freeze new lifecycle work** (streams B and E) on `factory-simplify` while
   waves 1–2 run. Bench-logic fixes continue.
2. **Retire legacy checkpoints** (43, of which 30 have no case key) instead of
   migrating them. Rerun the three cases that passed G1–G15.
3. **Postgres on the control VM**, with nightly encrypted backups.
4. **DBOS over Temporal.** DBOS is a library with no extra server. Temporal is
   more mature, but needs a server and has stricter worker rules.
5. **The integration-branch exception** above.
6. **The overnight stopgap.** Does a supervisor around today's same-worker resume
   still run while this is built?
