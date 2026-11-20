# Diff review 2: credit-park-wake (goldfish)

## Scope

- **Diff:** commit 235849f9 together with its rework 97250377. Their net effect on factory code is `git diff 19647dad 97250377`: `engine.py`, the tests and the fakes, with `model_router.py` back to its original bytes. I also reviewed the pin commit 14d512bd (`factory/invalid-runs-compat.json`, model `to` only).
- **Checked against:**
  - the design, `docs/designs/credit-park-wake.md`;
  - the Murphy row `new-credit-park-wake-1`;
  - review 1 (`docs/reviews/credit-park-wake-diff-1.md`) and the author's responses;
  - the founder's problem statement (wake after the backoff, one retry, a refused retry parks again, never counted or diagnosed, not waste, router lift semantics unchanged).
- **Personas:** `zoom_out` and `implementation_readiness`, in Mode: REVIEW, against `implementation-readiness-standard.md` and ENGINEERING §1, §2 and §4.
- **Code read:**
  - `engine.py`:
    - `Timing`;
    - `credit_ready_step`;
    - the attempt loop in `run_seq`, including how it counts PROVIDER_LIMIT (`limits`/`free`, lines 1524-1528);
    - the SLEEP branch at 1596-1611;
    - `wait_for_credit` at 1691-1715;
    - `nap`, `stop_check`, `replaying`, `release_worker`, `keeps_worker_for`.
  - `policy.decide`: PROVIDER_LIMIT always returns SLEEP. `settles_as_waste(credit_park=True)` is False.
  - The `DBOS.patch` source in dbos 3.4.0 (`_dbos.py:4180`). If a recorded checkpoint with another name sits at the patch's position, the call answers False and consumes no position. If no checkpoint is there, it records a marker and answers True.
  - `checkpoints.verdict_code`, and the CreditPark test class and its fakes.
- **What I ran:**
  - `test_durable_engine.py CreditPark`: 5 tests, OK (72 s).
  - `checkpoints.verdict_code(model=True)` on the worktree answers `802bfc8f…`. That is the pinned `from`, so the `to` value `01433a26…` is the right digest. `engine.py` is not in `VERDICT_CODE` (`MODEL_CODE` = ordinary_retry, model_runtime, model_router, model_call_gate).
  - `git diff --stat 35f7c49d 14d512bd -- factory/model_router.py` is empty. The router is byte-for-byte unchanged by this change.

## Review 1 blocking findings: re-checked

### 1. Spin after a 30-minute-old block: FIXED

- `credit_ready` is strict again, so the SLEEP branch (`engine.py:1599-1601`) parks whenever the block exists, whatever the refusal source was: a 402, a short balance, or a refusal at lease time.
- The bound now lives only in `wait_for_credit`, counted on each case's own park. There is no path left where the engine sees a `router:credit` stop, finds the block, and takes the short sleep on its worker.
- Each park gives exactly one attempt. If the woken retry is refused, `credit_ready_step()` returns False at line 1600, so the case calls `wait_for_credit` again, which calls `release_worker()` and naps again.
- Without the patch, the loop is unchanged: `while not credit_ready_step(): nap(wake_poll_s)`.

### 2. Tests did not prove the row: FIXED (with a disclosed, acceptable gap)

- The router books stay blocked for the whole test (`router_credit: "0.2"`, never topped up, no knob changed mid-test). `credit_recheck_s` is set once, at the start.
- The test asserts:
  - two `router:credit` parks;
  - for each park, a `release` of that attempt's worker before the next retry starts;
  - exactly three `gates:1` attempts, so one retry per park and no spin;
  - a seal, with `max_infra_retries_per_step: 0` (any counted stop would have led to a diagnosis) and 0 waste.
- The test's second half disables the patch. That park then waits for a top-up, which proves the bounded path is what wakes the case.
- The second refusal is still a scripted stop, not a refusal staged at lease time. After the fix, that no longer matters to the engine: the park decision reads only the real blocked books and the `router:credit` reason, never which path produced the refusal. This is acceptable.

## Other checks

- **DBOS patch placement:** the patch sits after `self.nap(seconds)` and before the first `credit_ready_step()`.
  - A park recorded before the deploy that already polled has `credit_ready_step` at that position. The patch answers False and consumes no position, so replay keeps the same unbounded loop.
  - A park cut off mid-backoff (its `recv` not recorded) finds an empty position and takes the patch.
  - Each `wait_for_credit` call evaluates the patch on its own, so a recorded park followed by a new live park mixes safely.
  - `self.replaying` returns before the patch.
  - Correct.
- **Never counted, never diagnosed, not waste:** a PROVIDER_LIMIT stop only adds to `limits`/`free`, and `decide` returns SLEEP before reading any counter. `settles_as_waste` is False under `credit_park`. The test confirms this.
- **Router lift semantics:** untouched (see above).
- **Gate identity and verdict pin:** `engine.py` is outside `VERDICT_CODE` and gate identity, and the pin answers `802bfc8f…`.

## Findings

### 1. NIT: the number of recorded steps in a bounded park now depends on two Timing defaults

- **Where:**
  - `factory/durable/engine.py:1707-1712`;
  - `factory/durable/engine.py:78` (`credit_recheck_s`);
  - `factory/durable/engine.py:62` (`wake_poll_s`).
- **Mechanism:**
  - The loop breaks after `ceil(credit_recheck_s / wake_poll_s)` polls (6 in production). That ratio is not recorded anywhere.
  - Up to now, `wake_poll_s` only set nap durations, which replay ignores.
  - If either default changes, every case workflow with a bounded park in its history replays a different number of `credit_ready_step`/`recv` steps after a controller restart. DBOS then raises an unexpected-step error.
  - The codebase already has a precedent: `OPERATIONAL_RECHECK_S` has the same property. But the new field's comment ("so tests can shorten it") invites tuning.
- **Fix:** add a comment on both fields: "changing it changes the recorded step count of a credit park; ship a new patch name instead". If you want the bound to be replay-proof regardless of constants, an alternative is to read `started = now_step()` once and make the break decision inside a recorded step.

### 2. NIT: the cases parked at deploy (1108c's situation) do not wake by themselves, and the design gives no operator step

- **Where:** `docs/designs/credit-park-wake.md:28-31` (the Replay bullet).
- **Mechanism:** the design states this correctly: a park that already polled keeps the unbounded wait. With no top-up coming, such a case waits forever. The founder's ask was "credit-parked cases wake by themselves", and those cases are the ones that prompted it.
- **Fix:** add a deploy note naming the remedy. After the controller restart, any case still `waiting_for_credit` from before the patch either gets a founder-approved stop and resume (one launch path; the new workflow is patched), or one `lift_credit --force` (`model_router.py:1228`), accepting that the next 402 blocks the pool again. Pick one, so the operator makes no decision at deploy time.

### 3. NIT: the worker churn is stated per case, but not as a total across all parked cases

- **Where:** `docs/designs/credit-park-wake.md:32-36`.
- **Mechanism:**
  - Each retry creates a worker. A case whose chain can only be served on the paid lane cycles forever, at fewer than 2 creations an hour.
  - The design's own benchmark: 5 cases at 4 creations an hour (about 20 an hour) spent the whole creation allowance on 8 November. About 10 cases parked at once would reach the same rate.
  - The per-case stagger helps, but it does not bound the total.
  - A shortfall shows up as pool waits, which are not counted, so this degrades throughput rather than breaking cases.
- **Fix:** state the total ("2 × parked cases per hour; about 10 parked cases match the 8 November rate") next to the existing `ponytail` note. No code change needed now.

## Verdict

**PASS.** Both blocking findings from review 1 are fixed and verified:

- The refused retry always parks again and releases its worker.
- The engine test proves the Murphy row on real, never-lifted router books.

Placing `DBOS.patch` after the backoff nap is safe for replay. No retry is counted, diagnosed or booked as waste, the router is unchanged, and the verdict pin holds. The three findings above are optional nits.

## Elephant response

- Nit 1 (step count depends on two Timing values): comment added on `Timing.credit_recheck_s` and a bullet in the design: changing either ships under a new patch name.
- Nit 2 (cases parked at deploy do not wake): a Deploy section now says so and names it a founder decision (stop and resume, or a one-off force lift). Choosing is not this change's call.
- Nit 3 (total churn): the design states it (2 creations an hour per parked case; about 10 parked cases match 8 November).
