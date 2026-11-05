# Durable execution for the case factory

Status: design for review, revision 4 (2026-11-05), after design reviews 1–3
(`docs/reviews/durable-execution-design-{1,2,3}.md`). Branch `durable-execution`,
cut from `factory-simplify` at `2df5664`. This supersedes the "no second event engine"
direction of `docs/factory-single-path.md`.

## What changed in revisions 3 and 4, and why

Review 2 found ten new blocking gaps. Most came from two choices in revision 2:
running each gate as its own engine step, and freezing the engine's policy into the
shared contract. Revision 3 removes both instead of patching around them.

- **One GATES step.** It runs today's whole gate pipeline (`run.run_gates`) on one
  worker. Today's code already handles G10's overlap with G13–G15, early-check
  reuse, and per-gate invalidation (`gate_state` fingerprints, which exclude
  `freshness.jsonl` and `BUILD-NOTES.md` where they should), and keeps doing so.
  The engine adds durability around the pipeline, not a second copy of it.
  - The cost: a worker that dies mid-GATES loses the step's unsaved progress. A
    retry on the same live worker reuses the `gate-cache` as today.
    `Poll.checkpoint` is already in the contract, so WP5f can add in-step
    checkpoints later without a contract change.
- **Policy is WP1's.** `factory/durable/policy.py` is owned by WP1 and is not
  frozen. `contract.py` keeps only what crosses a package boundary.

Review 3 accepted the trade and found four small gaps, fixed in revision 4 with
contract version 4:

- a GATES result now names every gate that passed (`passed`);
- the `poll` and `cancel` frames and the release identity are frozen;
- a transport failure can never start a second attempt beside a live one;
- per-step price caps are gone, because no evidence prices a step.

The trade's real costs, which revision 3 understated:

- **Early-check reuse is partial.** Today's in-memory early reuse (`c.early`)
  does not cross a step boundary. So G3, which is not in `gate_state.REUSABLE`,
  reruns inside GATES. G4, G5 and G15 are reused only through `gate_state`, from
  the evidence kept in the snapshot.
- **Unsaved progress is lost** when the worker dies, and also when the worker is
  released during a long sleep. Non-OK results therefore carry their snapshot
  whenever the worker can produce one, and a retry restores it. Gates outside the
  cache (G1, G2, G3, G7, G11 and G17) rerun.

## Problem

The factory turns three inputs into sealed cases:

```
app pin (repo + commit) + promise + case count  ->  factory  ->  sealed cases
```

Turning inputs into cases takes a long time: cases ran 30–77 wall-clock hours on
Oct 14–20. It costs a lot of quota, and it is interrupted constantly. The 50
non-dry-run scorecards in `sealed/` record 435 interruptions:

| Interruption | Count |
|---|---|
| `opencode_error` | 210 |
| Provider limits | 99 |
| Stalls | 74 |
| Timeouts | 23 |
| Codex errors | 11 |
| Process errors | 9 |
| Call limits, cancellations and permission errors | 9 |

Method: count each card's `continuation_budget.previous_stops` and its terminal
stop, by the prefix before `:`. This excludes 61 operator pauses (`PauseRequested`
or `paused`) and 16 non-stops (`complete`, empty).

A case cannot restart from scratch after each interruption; it has to carry on.
Today, carrying on is hand-built:

- 12 launch and recovery paths (`docs/factory-single-path.md`);
- state spread over cards, ledgers, checkpoints, holder memory, journals, R2 and
  the founder's Mac;
- most open Murphy rows are copies of state disagreeing, or a crash between two
  writes.

## Goal, and how we know it works

A batch launched from its inputs runs until it has `target_sealed` cases, or until
it hits its money bound, its deadline or `max_cases_started`. Killed workers, a
rebooted control VM and provider limits never need a human. Only a real disagreement
between reviewers reaches the founder.

- **Mid-term exam (end of wave 1).** WP1's integration test: a batch of three cases
  on fake workers survives a `kill -9` of the engine at 20 random points, with no
  step run twice after it finished.
- **Final exam (WP9).** A live practice batch survives a deleted worker and a
  restarted control VM without a human.

## Change

There is one durable workflow per case, on the always-on control VM. The engine is
DBOS (a Python library, `dbos==3.4.0`) on Postgres; tests use SQLite.

The engine **records** each step's result the moment it finishes. After a crash,
it **replays** the case: recorded results come back without running again, and only
the step that was open runs again. `tests/factory/test_durable_replay.py` proves
this on the real engine.

### The case, step by step

1. **ADMIT.** Runs on a batch DBOS queue with concurrency 1, so concurrent cases
   and replacements never choose the same bug.
   - It receives `inputs` and `registry`, plus the case and batch keys.
   - It returns the updated `registry` and the first case snapshot.
2. **WRITER round r.** Today's writer round, with today's G1 and early checks
   inside it (G3, G4, G5 and G15 through `early_checks`). An early-check failure
   is repaired within the round, as today.
3. **STRESS round r.** Today's stress round, with today's early reviews (G8, G9)
   inside it after a clean round.
   - Clean (OK, no feedback): go to GATES.
   - Findings (OK with feedback): REPAIR, which is the next writer round.
4. **GATES r.** Today's `run_gates`, with G10 overlap, `gate-cache` reuse and
   G17. Every result lists the gates that passed or were reused (`passed`), which
   is what `progressed()` and `report.py` read. It ends in one of three ways:
   - OK.
   - GATE_FAILED, naming the gate. A repairable failure carries feedback and
     REPAIRs; a non-repairable one RETIREs.
   - NEEDS_FOUNDER, from G8, G9, G16 or G17 only.
5. **SEAL** (G12). Returns `archive` and `hard`.
6. The control VM then generates the public scorecard from the engine tables (WP1)
   and publishes it (WP8). No code reads the public scorecard back to make a
   decision. The worker's private card (`c.work/scorecard.json`) is part of the
   snapshot and is read on every step, as today.

**Extensions.** An EXTEND runs one more writer round, its stress round and GATES,
with the diagnosis's feedback. Extension rounds count in `extensions_used`, not in
`writer_rounds_used`.

- An extension never repairs (`Counters.in_extension`). A failure inside it goes
  straight back to diagnosis.
- A close-to-passing verdict must carry its writer feedback.
- Extensions draw only on the batch bound, not on the case's own money.

### What happens after each outcome

`policy.py` decides; this is its starting behaviour, implementing ENGINEERING section 3.

- **PROVIDER_LIMIT.** SLEEP until `retry_at`, spending no allowance.
  - Only more than `max_spent_limits_per_step` limits on one step that each spent
    money give up. That is a guard against misclassification.
  - A sleep longer than `release_worker_after_sleep_s` releases the worker.
- **INFRA_ERROR.** RETRY, never scored. After `max_infra_retries_per_step`, give up.
- **GATE_FAILED, repairable.** REPAIR while rounds remain, then give up.
- **GATE_FAILED, not repairable.** RETIRE. This is a scored rejection.
- **EXHAUSTED.** Only the worker emits it, when the attempt reaches its
  `money_ceiling_usd_micros` or the runner's own limits.
  - If the batch bound shaped that attempt's grant, WAIT_FOR_BOUND: wait for
    `BOUND_RAISED`, then retry.
  - Otherwise, give up.
- **Giving up** depends on the step:
  - an ordinary step goes to DIAGNOSE;
  - a DIAGNOSIS step RETIREs; a diagnosis is never diagnosed;
  - an ADMIT goes to STOP_ADMISSION: the case retires, and the batch starts no
    new cases.
- **DIAGNOSE** runs a DIAGNOSIS step with `evidence`: every receipt, diagnostic and
  report of the case. Its verdict:
  - `factory_bug`: HOLD, per the Stream D parent ruling of 2026-10-30. The case
    stops unscored as `factory_bug_held`. A later batch release may resume it, at
    most 3 times across its lineage. There is no in-batch wait for a fix.
  - `close_to_passing`: EXTEND, at most 5 times. Every extension after the first
    needs `progressed()`.
  - `not_converging`: RETIRE.
- **NEEDS_FOUNDER.** ESCALATE: the case parks until a `FounderReply`.
  - CONTINUE reruns the escalated step with the ruling as input.
  - RETIRE retires the case.

**Replacements.** A case starts at most one replacement over its life, the first time
its own line of work stops (DIAGNOSE, RETIRE, ESCALATE or HOLD). No replacement starts
after STOP_ADMISSION, after the deadline, or beyond `max_cases_started`. If both an
extended original and its replacement seal, both are kept.

**Slots.** A case holds a `max_concurrency` slot while it runs model steps,
including DIAGNOSIS and EXTEND. A parked, held or retired case holds none.

**Target reached.** When `target_sealed` is reached, no new case starts. Cases and
extensions already running finish, and their seals are kept.

### Money

There are no per-step price caps. No evidence prices a step (Stream D's cost
evidence), and a cap would turn plumbing into a case result.

**Grants.** Before a paid attempt starts, the engine requests the case's whole
remaining money. `Ledger.reserve` grants and holds the smallest of:

- that request;
- the case's remaining money, `case_money_usd_micros` (default $50, today's
  default);
- the batch's remaining bound, `money_bound_usd_micros`.

The grant becomes `money_ceiling_usd_micros`. Concurrent cases can therefore never
overshoot either limit.

**When the money runs out.**

- If the case's own money is exhausted, that is a case outcome (DIAGNOSE).
- If the batch bound is exhausted, the case waits for `BOUND_RAISED`
  (WAIT_FOR_BOUND), and the batch starts no new cases.
- Extension attempts pass `draws_case_money=False`, so they draw only on the batch
  bound.

**Booking.** `settle` books the real usage and frees the rest. `settle_lost` books
the whole grant for an attempt that produced no usage.

With `max_concurrency` cases running at once, a batch bound below `max_concurrency`
× $50 makes some cases wait. This is intended.

### Workers and the wire protocol

These are frozen in `contract.py`: `WORKER_COMMAND`, `attempt_paths`,
`start_frame`, `Poll` and `PollState`.

- **The command.** The control VM runs `python3 -B factory/durable/worker_step.py
  start|poll|cancel` over `boat ssh`.
- **start.** The control side first pushes the input ciphertexts into `blobs/`.
  Then it sends one JSON frame on stdin, `{"input": <StepInput record>, "keys":
  {scope: base64}}`, carrying the case key and, for ADMIT, the batch key. The
  worker:
  1. creates the attempt directory with O_EXCL, so a second start does nothing;
  2. detaches the attempt as a systemd unit `durable-<id16>` (or setsid), so ssh
     drops and control-VM restarts never stop it;
  3. checks that its installed release (`RELEASE.json`, written by WP2) matches
     `plumbing_version` and `bench_version`, and otherwise ends with
     `infra:version_mismatch`. The two versions are the factory bundle sha256 and
     `run.bench_manifest()`, as `launch.sh` computes them today. Gate code is in
     the factory bundle, so a gate fix is a plumbing release, and `gate_state`
     fingerprints rerun only the gates whose sources changed;
  4. restores the snapshot and runs the step;
  5. writes output ciphertexts into `out/`;
  6. writes the result once, by atomic rename.
- **poll and cancel** read `key_frame(key)` on stdin. `poll` prints one line, the
  `Poll` record. Exit codes and outputs are in the `RELEASE_MANIFEST` docstring
  in the contract.
- **poll results.** RUNNING, DONE (with the result) or ABSENT.
  - ABSENT only when the worker answered and has neither a result nor a live unit.
    The engine then retries at once.
  - A transport failure is RUNNING, bounded by the deadline plus a grace period,
    so a network flake can never start a second attempt beside a live one.
  - Before attempt n+1, the engine cancels attempt n.
  - `start` refuses (`infra:attempt_busy`) while another attempt of the same case
    is live.
  - DONE output blobs go into the ArtifactStore before poll returns.
- **Deadlines.** The worker kills an attempt at `deadline_s` (`infra:deadline`). The
  control side stops polling at the deadline plus a grace period, then cancels.
- **No R2 on workers.** The control side moves every blob, so workers need no R2
  credentials.
- **Keys.** A scope key is 32 random bytes. `derive_keys` gives the age X25519
  secret, encoded as an age identity for the existing `age` CLI, and the artifact
  HMAC key. `Ref.digest` is the HMAC of the plaintext under that key.
- **Provisioning.** `WorkerPool.acquire(case_id, plumbing_version, bench_version)`
  returns the case's live worker with that release installed and verified, or
  provisions one under an idempotency label (WP2, taking over `launch.sh:685-707`).
  A case keeps its worker between steps as a cache. If the worker dies, the next
  attempt gets a new one and restores the snapshot.
- **The snapshot** (`CASE_SNAPSHOT`) is `c.case` plus the retained `c.work`
  subset, which WP5a lists exactly. The subset starts with:
  - `gate-cache/`, and the evidence `gate_state.load` checks (`gate-details/`,
    `judge_breadth/`, `review-*/`, `bench-results/`);
  - G10's attempt receipts;
  - the private card `scorecard.json`;
  - `attack-state.json`, `prototype.json` and `infra-attempts.json`;
  - the admission files.

  Non-OK results carry their snapshot when the worker can produce one, and a retry
  restores it. Test: a fresh worker restoring a GATES snapshot reuses that
  snapshot's passed gates.

### Versions and messages

- **The engine version.** `application_version` is pinned (`factory-engine-1`)
  for the life of the database, because DBOS recovers only matching versions.
- **Workflow functions.** Changes go behind `DBOS.patch()`.
- **Messages.** The engine waits for these with `DBOS.recv` in a loop, because a
  receive times out after 60 s by default:

  | Topic | Payload | Effect |
  |---|---|---|
  | `PLUMBING_RELEASE` | `plumbing_version` | Steps started afterwards use the new plumbing. Proven: a restart under changed step code resumes, and the open step runs the new code. |
  | `BENCH_RELEASE` | `bench_version` | Each case adopts it at its next GATES step. `gate_state` fingerprints (`STAGE_DEPENDENCIES`) rerun only the gates whose inputs changed (ENGINEERING section 3). |
  | `BOUND_RAISED` | `money_bound_usd_micros` | The batch money bound is raised. |
  | `FOUNDER_REPLY` | `FounderReply` | The answer to an escalation. |

  WP8 ships the operator command that sends them.

### Secrecy

DBOS records every step argument, result and exception, so all of them are
content-free by construction:

- **Reason codes** follow a fixed grammar: no paths, no digits, no dots.
- **Exceptions.** `guarded_run` turns any exception into a fixed code.
- **Gate names** must match `G1`–`G17`.
- **Digests** are keyed per scope.
- **Conductor.** `assert_no_conductor` runs before construction; WP1 also checks
  the constructed instance and DBOS Cloud mode.
- **Public card.** It shows outcomes, stages and gates, plus only the reasons on
  WP4's published allowlist.
- **Case content** lives only in age-encrypted artifacts, opened in worker RAM.

### Engine rules

1. Workflow functions are deterministic. Read the clock only through a step.
2. Waits use `DBOS.sleep(wait_seconds(retry_at, now()))`, which is always positive.
   Proven by a restart after the wake time has passed.
3. To resume a case, attach to it (`retrieve_workflow`). Never start an existing ID
   again.
4. Attempts are idempotent on `case/seq/step/attempt`.
5. The engine calls executors only through `guarded_run`.
6. Register the queues before recovered cases can enqueue (`register_queue` works
   only after `launch()`; WP1 tests the order).

### The frozen contract

`factory/durable/contract.py` (version 4) is pure, with no I/O and no engine import.
It holds:

- the records: `BatchSpec`, `Step`, `StepInput`, `StepResult`, `Usage`, `Ref`,
  `SealedCase`, `Poll`, `Classified` and the message payloads;
- the per-step result rules;
- the wire layout;
- the key derivation, with an RFC 5869 test vector;
- the protocols: `Classifier`, `ArtifactStore`, `Sealer`, `KeyService`,
  `WorkerPool`, `WorkerChannel`, `Ledger` and `StepExecutor`;
- strict record conversion.

Changing it needs a design change and a design review. `policy.py` is WP1's.

## Work packages

Each package gets its own branch, `de/<id>`, cut from `durable-execution`. Each one
needs a short design note if it's over about 20 lines, and a diff goldfish. It
merges back into `durable-execution`.

**Approved exception to ENGINEERING section 1:** `durable-execution` is the
integration branch. It merges `factory-simplify` in at least daily, and WP5a's owner
resolves any `run.py` conflicts. New Murphy rows are named `new-durable-<n>`.

Within a wave, no two packages write the same file.

| ID | Wave | Package | Owns (writes) | Done when |
|---|---|---|---|---|
| WP1 | 1 | Engine core, executor and policy | `factory/durable/engine.py`, `executor.py`, `policy.py`, `report.py` | Batch and case workflows on fakes cover the step sequence, outcome routing, admission queue, replacements, diagnosis, extensions, hold, escalation, the bound wait and messages. The executor composes the seams inside `guarded_run`, and grants, cancel-before-retry and restore-from-snapshot behave as above. `report.py` generates the scorecard from `passed`. Settled in WP1's own note: <ul><li>a GATES deadline taken from evidence (real cards show over 2.5 h before G7), not the 4 h default;</li><li>an ADMIT that hits a provider limit gives up its queue slot while it sleeps;</li><li>ADMIT reads the latest registry when dequeued;</li><li>the engine seals its own stop history as a `DIAGNOSTIC` for DIAGNOSIS evidence.</li></ul> Includes the queue-order test and the constructed-instance Conductor check. The mid-term exam. |
| WP2 | 1 | Worker pool, provisioning and channel | `factory/durable/workers.py`, `factory/durable/channel.py` | Boat creation uses idempotency labels. Release install and verification replace `launch.sh:685-707`. On restart, orphans are adopted or deleted. The channel side of the wire protocol is in place. Tests use real saved Boat CLI outputs. |
| WP3 | 1 | Sealer and artifact store | `factory/durable/artifacts.py` | `Sealer` with the age CLI and `derive_keys`, plus an R2 store and a local store. A truncated upload is never visible. Ciphertext opens only with its scope key. |
| WP4 | 1 | Failure classification | `factory/durable/classify.py` | Implements `Classifier`. Every stop kind in the 50 real scorecards maps to an outcome. A limit with no reset time gets a defined backoff from `now`. Ships the published-reason allowlist and the top `opencode_error` causes from the real logs. |
| WP5a | 1 | Worker-side step runner | `factory/durable/worker_step.py`; the only writer of `factory/run.py` in waves 1–2 | The worker side of the wire protocol: detach, `attempt_busy`, version check, restore, run, snapshot, result. Adds the `run.py` hooks `context_for_step`, `run_step` (ADMIT through WP11's adapter, WRITER, STRESS, GATES and SEAL) and `retained_paths`. Under the engine it turns off the in-process lifecycle: <ul><li>`validate_and_repair`'s repair loop, with `late_recovery` marking;</li><li>the final builder-precheck call and `stop_defect` in the stress path;</li><li>`reselect_candidate`;</li><li>`_gate_completed`'s `checkpoint_progress`.</li></ul> Each step runs on the public practice case. The GATES snapshot-reuse test. |
| WP6 | 1 | Ledger | `factory/durable/ledger.py` | Implements `Ledger` in the engine database. Replay gives an identical ledger. Concurrent reservations never exceed either limit. |
| WP7 | 1 | Key service | `factory/durable/keys.py` | The scoped VM key (approved 2026-10-29) wraps 32-byte scope keys. A key reaches a worker only inside `start_frame`. |
| WP10 | 2 | Diagnosis and extensions | `factory/durable/steps/diagnosis.py`; adapts `diagnosis.py`, `diagnosis_dispatch.py`, `extensions.py`, `extension_package.py` and `extension_*.py` | A DIAGNOSIS step returns a verdict, and close-to-passing feedback. The modules' dispatch and state parts are listed for WP9. |
| WP11 | 2 | Admission and registry | `factory/durable/steps/admit.py`; adapts `admission.py`, `registry.py` | Two concurrent cases and a replacement never admit the same bug. The registry survives replay. |
| WP8 | 2 | Deployment, publication, operator command | `control/`, deploy scripts | Postgres with nightly encrypted R2 backups, and a systemd unit for the engine. The scorecard is published. The operator command sends the four messages. After a reboot, the cases resume. |
| WP9 | 3 | Cutover and deletion | the deletion list, `factory/run.py` from wave 3 | The final exam passes, then the old paths are deleted and their Murphy rows closed with those runs. |
| WP5f | 4 | In-step checkpoints | `worker_step.py`, `factory/model_runtime.py` | `Poll.checkpoint` after every model call and every finished gate. A retry on a new worker resumes there. |

## What it deletes (in WP9, not before)

Each module is read again in WP9 before it goes.

**Replaced** (about 6.4k lines):

- Python: `key_holder`, `batch_holder`, `batch_service`, `batch_transfer`,
  `batch_status`, `batch`, `control_resume`, `coordinator`,
  `coordinator_inventory`, `restart`, `recovery`, `durable_checkpoint`,
  `restore_ledger`, `restore_sync`, `collection`, `job_config`, `job_authority`,
  `founder_decisions`, `statement_round`.
- Shell: `launch.sh`, `launch-slots.sh`, `collect.sh`, `restore-cases.sh`,
  `statements-round.sh`, `bin/factory-adopt`.

**Deleted** (about 1.6k lines): `restore_bundle`, `late_rehearsal`,
`ttl_continuation`, `late_recovery`, `carry_over`, `founder_ruling`,
`resume-in-place.sh`, and `run.py:restore_gate_crash` (the salvage path).

**Decided in WP9:**

- `account_handoff.py`;
- `bin/boat-launch-guards.sh` and `control/unbug-resume-launches.*`;
- the diagnosis and extension dispatch;
- which step-internal retry layers (`gate_attempt`, `factory_waste`,
  `infra-attempts.json`) the engine makes redundant.

**Kept** as offline tools: `sealed_audit.py` and `g11_review.py`.

Legacy checkpoints are retired, not migrated (founder decision 2).

## Cost and timeline

**Infrastructure.** One Postgres on the existing control VM. The journal holds only
digests, codes and numbers. Nightly encrypted backups go to R2. There are no new
paid services.

**Effort.** These estimates are wall clock with parallel agents, including reviews:

| Wave | What | Estimate |
|---|---|---|
| 1 | Seven packages in parallel | 1–2 days |
| 2 | Four packages | 1–2 days |
| 3 | One live practice batch, then deletion | at least 2 days, bounded by live runs |

The exams gate each wave, not the dates.

## Tests

| File | Tests | What they cover |
|---|---|---|
| `tests/factory/test_durable_contract.py` | 24 | passed gates; poll and cancel frames; grants; reason grammar; exception containment; Conductor check; RFC 5869 HKDF vector and keyed digests; wire layout, start frame and three-state poll; outcome and per-step rules, including who may escalate and what ADMIT and SEAL return; inputs, evidence and ruling placement; keys never collide across repairs; spec ceilings; message payloads; `Classified` shapes; strict round-trips |
| `tests/factory/test_durable_policy.py` | 11 | an extension never repairs; batch money waits while case money diagnoses; the section 3 table; a diagnosis is never diagnosed; admission failure stops admission; one replacement per case, bounded by `max_cases_started`; diagnosis limits; progress |
| `tests/factory/test_durable_replay.py` | 4 | real DBOS: a crash mid-step reruns only the open step; a provider sleep keeps its wake time (20 s limit, under 17 s after 12 s of downtime); a restart after the wake time has passed; changed step code resumes under the pinned version |

Every package adds the tests in its "Done when", using the real engine and real saved
artifacts.

## Murphy rows

None close with this design. These rows are targets, and each closes only when its
package's test, on real artifacts, proves it.

| Package | Target rows |
|---|---|
| WP1 | 5, 18, 19, 28, 33, 51 |
| WP8 | 16, 26 |
| WP3 | 27, 34, `new-batch-service-2` |
| WP10 | 9, `new-stream-d-outcome-routes-1`, `new-stream-d-current-comparison-1` |
| WP5f | 35 |
| WP2 | 17, 29, `new-boat-stop-capture-1`; with WP7, `new-worker-router-delivery-1` |
| WP4 | 4, part of 48 |
| WP7 | 1 |
| WP9 (the path is deleted along with its row) | `new-single-path-1`, `new-batch-service-1`, `new-batch-service-3`, `new-batch-service-4`, `new-batch-auth-inputs-1`, `new-registry-pending-promotion-1`, `new-batch-restore-admission-1`, `new-preallocation-import-recovery-1`, `new-ancestor-release-binding-1`, `new-predispatch-import-recovery-1` |

Rows 2 and 47 need a batch-wide account scheduler. That is router work outside this
design.

**Planned contract change outside wave 1.** A `BatchSpec` input for HOLD cases a
later batch resumes, carrying their lineage counters, will be designed with WP10.

## What this does not fix

These all stay as work:

- gate science;
- router policy and account scheduling;
- Docker and SQL hangs inside a step;
- stray-process cleanup;
- the causes of model-CLI errors;
- loss of unsaved in-step progress when a worker dies or is released during a long
  sleep, and reruns of the gates outside the cache (G1, G2, G3, G7, G11 and G17),
  until WP5f.

## Founder decisions needed

1. **Freeze new lifecycle work** (streams B and E) on `factory-simplify` while
   waves 1–2 run.
2. **Retire legacy checkpoints** (43, of which 30 have no case key) instead of
   migrating them.
3. **Postgres on the control VM**, with nightly encrypted backups.
4. **DBOS over Temporal.**
5. **The integration-branch exception.**
6. **The default money settings:** per-case money ($50, extensions excluded) and
   `max_cases_started` (24).
7. **The overnight stopgap.** Does a supervisor around today's same-worker resume
   still run while this is built?
