# Diff review 1: credit-park-wake (goldfish)

## Scope

- **Diff:** commit 235849f9 (engine.py, model_router.py, the design, two test files and the fakes), plus the pin commit f0eec9d9 (`factory/invalid-runs-compat.json`, model pin `to` only).
- **Checked against:**
  - the design, `docs/designs/credit-park-wake.md`;
  - the Murphy row `new-credit-park-wake-1`;
  - the founder problem statement as relayed: "after the backoff, wake and retry; if the retry is still refused, park again; one retry, never counted or diagnosed, not waste; change only `credit_ready`/`wait_for_credit` preferably; router lift semantics unchanged".
- **Personas:** `zoom_out` and `implementation_readiness`, in Mode: REVIEW, against `implementation-readiness-standard.md` and ENGINEERING §1, §2 and §4.
- **Code read:**
  - `model_router.py`: `Store.rpc` (the health load, `blocked`, the `paid_reserve` short path, the acquire no-lease branch, `finish`, `observe`), `lift_credit`, `retry_at`, `credit_stuck`, `credit_ready`, and the client acquire loop (`WAIT_SECONDS`, `ProviderWait`).
  - `durable/engine.py`: the SLEEP branch at 1590-1607, `wait_for_credit`, `keeps_worker_for`/`KEEP_WORKER_WAIT_S`, `nap`, `credit_ready_step`, and `credit_park` settlement at 1046-1048.
  - `durable/policy.py` (`decide`, `settles_as_waste`), `durable/classify.py` (`classify_wait`, `_retry_at`, `BACKOFF_S`), `run.py` (`engine_provider_wait`, `write_provider_wait`), `durable/contract.wait_seconds`, `durable/guard.py` (`PARKED_WAITS`, no_progress), and `durable/checkpoints.verdict_code`.
- **Readers of `credit_ready`:** only `durable/runtime._credit_ready`, which feeds `credit_ready_step`. The engine calls that step at two points: `engine.py:1597` (whether to park at all) and `engine.py:1704` (the wake loop). Nothing in gate identity reads it.
- **What I ran:**
  - `tests/factory/test_router_paid_spend.py`: 62 tests, OK.
  - `checkpoints.verdict_code(model=True)` on the worktree answers `802bfc8f…`, the pinned `from`. The pin holds.
  - **A probe on the real router `Store`, kept in my scratchpad and not in the repo.** Setup: a short balance at the gate, then the clock moved +1900 s. Results:
    - `credit_ready` is True.
    - A new acquire answers `wait`/`credit` with `retry_after = now + 1.0`.
    - The refusal leaves `observed_at` unchanged, so `credit_ready` stays True.
    - `classify._retry_at` with the worker clock 0.2 s later passes the reset through (+0.8 s).
  - **Not run:** the engine `CreditPark` tests. A full suite is already running on the host.
- **Confirmed sound:**
  - Router lift semantics are unchanged: `lift_credit`, `lasting`, `observe`, the cap and the margin are untouched.
  - A `router:credit` stop is PROVIDER_LIMIT, so `decide` returns SLEEP. It is never counted or diagnosed, and `settles_as_waste(credit_park=True)` is False.
  - The DBOS step sequence of this commit is unchanged.
  - Catching `TypeError` in `credit_ready` is harmless.

## Findings

### 1. BLOCKING: once a block is 30 minutes old, a refused retry never parks again; it spins on its worker about once a minute

- **Where:** `factory/durable/engine.py:1596-1598`, together with `factory/model_router.py:1206`. The design's "Change" bullets and "Why 30 minutes" make claims that the code does not meet.
- **Mechanism:**
  - Nothing the router does while the pool is blocked refreshes `observed_at` (at least on the paths I traced):
    - `free()` returns 0 for a blocked route, so no paid lease is granted and `paid_reserve` never runs again.
    - The acquire no-lease branch (`model_router.py:610-627`) writes no health.
    - `finish done` skips `observed_at` while the pool is blocked.
  - The only refreshers are a 402 on a call already in flight, or a `paid_reserve` short. Both stop happening soon after the block starts. So 30 minutes after the block, `credit_ready` is True permanently until a top-up.
  - From then on, any `router:credit` stop goes like this. It covers the woken case's own retry, and any new case whose call can only take the paid lane:
    1. The router answers `retry_after = max(now+1, blocked_until)`. For a short-balance block, or a 402 block with 1-2 refusals, `blocked_until` is already past, so the answer is now+1 (confirmed by the probe).
    2. The client polls it about once a second for `WAIT_SECONDS` = 60 s, then raises `ProviderWait`.
    3. On the worker, `engine_provider_wait(now=time.time())` runs `classify_wait`. `_retry_at` keeps a reset that is still in the future, so `retry_at` is about 1 s ahead (probe: +0.8 s).
    4. In the engine, `credit_ready_step()` at line 1597 is True, so the case **does not park**. It takes the short-sleep path. `keeps_worker_for(≈0.001 s)` is true, so it keeps its worker, naps `wait_seconds` (0.001 s), and retries.
- **Result:** every affected case loops forever.
  - Each loop is one uncounted step attempt plus about 60 router acquires per minute.
  - The case holds a worker, with status `running` and not `waiting_for_credit`. It is therefore not in `PARKED_WAITS`, and the guard's no_progress stall alert will fire.
  - If clock skew pushes `now` past the reset, the backoff falls back to `BACKOFF_S` = 900 s. That still means four retries an hour on a held worker, not the "two retries an hour per parked case" the design promises.
- **What this breaks:**
  - It contradicts the founder spec: "if the retry is still refused, park again; one retry".
  - It contradicts the Murphy row: "a refused retry parks again".
  - It contradicts the design. The design notes that a lease-time refusal does not restart the clock, but then assumes the case "naps for its wait's own backoff, 900 s or the block's end". Neither holds. It is not a park, and the backoff is about 1 s.
- **Fix (stays inside `wait_for_credit`, as the founder preferred; the router is untouched):**
  - **Revert `model_router.credit_ready` to the strict check.** No `CREDIT_RECHECK_S`, no `now` argument. Line 1597 then always parks while a block exists, and releases the worker.
  - **In `_Case.wait_for_credit`, under a new `DBOS.patch("credit_park_recheck")`, bound the wake loop by the case's own park time.** For example, after `self.nap(seconds)`:
    - set `polls = math.ceil(_RT.timing.credit_recheck_s / _RT.timing.wake_poll_s)`;
    - loop `for _ in range(polls): if credit_ready_step(): break; self.nap(_RT.timing.wake_poll_s)`;
    - add `credit_recheck_s: float = 1800.0` to `Timing`, so tests can shorten it.
  - **Unpatched (recorded) workflows keep the unbounded `while`.** A case parked mid-loop at deploy then replays identically.
  - **Effect:** exactly one retry per 30 minutes of each case's own park, wherever the refusal came from. The case parks again through line 1597, and the cadence cannot spin.
    - It needs no reasoning about which router path refreshes `observed_at`.
    - It also staggers wakes per case, instead of every case parked on one block waking within the same `wake_poll_s` and recreating workers together.
  - `model_router.py` returns to its prior bytes, so recompute the shared model pin afterwards (finding 4).
- **Alternative, not preferred:** have the acquire no-lease branch stamp `health[PAID_POOL]['observed_at'] = now` when it answers `credit` for the lasting paid block.
  - It is one line, but it changes the router's acquire path, which the founder asked to leave alone.
  - A trickle of new credit stops would keep the block "fresh", so parked cases could go a long time without waking.

### 2. BLOCKING: the tests do not prove the Murphy row; the engine test simulates a freshness the real system never produces

- **Where:**
  - `tests/factory/test_durable_engine.py:2374-2395`, the test `test_a_parked_case_wakes_without_a_top_up_and_a_refused_retry_parks_again_uncounted`;
  - `tests/factory/test_router_paid_spend.py:291-312`.
- **The engine test:** its second stop is a scripted `CREDIT` result. It parks a second time only because the action `{"when": {"started": second}, "credit_recheck_s": 1800}` forces `credit_ready` back to False.
  - In production that second refusal happens at lease time, which does not refresh `observed_at` (finding 1). With the real router books left alone, the case would take the short-sleep path, keep its worker, and never show `waiting_for_credit` twice.
  - So the assertion "parked twice" proves a premise, not the code.
  - ENGINEERING §2 says a row closes only by a test that really proves it.
- **The router test** ends with `admit(...)['reason'] == 'credit'` and `ready(0)` both true. That is exactly the precondition for the spin, and the test asserts it as the desired outcome.
- **Fix, with finding 1's fix:**
  - Keep the router books real for the whole engine test. Never mutate `CREDIT_RECHECK_S` or `credit_recheck_s` between the first and second park. Set a short `timing.credit_recheck_s` once, at the start.
  - Assert all of the following:
    - two `waiting_for_credit` parks;
    - a `release` in `pool_log` before each park's nap;
    - no attempt started between the second stop and the second wake, other than the one retry;
    - seal, with no diagnosis and 0 waste.
  - Also make at least one refusal come from the real router's lease path, not only a scripted stop, if the fakes allow it. The existing `router_credit` books plus a paid-only chain should.
  - Revert the router test to strict `credit_ready` semantics, or delete it if `credit_ready` is reverted.

### 3. NIT: the design misstates who reads `credit_ready`, and its cadence

- **Where:** `docs/designs/credit-park-wake.md`, "Gate identity and verdict code" and "Why 30 minutes".
- **What is wrong:**
  - "`credit_ready` is read only by the controller" is true at module level. But the design never notes that the engine reads it at two decision points, the park entry at 1597 and the wake loop. That gap is the root of finding 1.
  - "Two retries an hour" and "900 s or the block's end" are wrong, as shown in finding 1.
- **Fix:** rewrite those bullets to describe the per-park clock from finding 1's fix. State that line 1597 stays strict.

### 4. NIT: re-pin after the fix

- **Where:** `factory/invalid-runs-compat.json`, `verdict_code_pins.model`.
- **What to do:** the current pin is correct for 235849f9 (it answers `802bfc8f…`). Finding 1's fix changes `model_router.py` again: it reverts `credit_ready`, and the diagnosis commit's changes stay. The `to` digest must be recomputed on the final head.
- **Not needed:** `engine.py` is not in `VERDICT_CODE`, so the engine-side fix needs no pin.

## Verdict

**FAIL.** Two blocking findings are open:

1. Once a block is 30 minutes old, a refused retry never parks again; it spins on its worker.
2. The tests do not prove the Murphy row.

Everything else checked out: router lift semantics, no counting, no diagnosis, no waste, an unchanged DBOS step order, gate identity untouched, and the verdict pin answering its pinned value.

## Elephant response

- Finding 1 (BLOCKING, a 30-minute-old block makes refused retries spin on their worker): fixed as suggested. `model_router.credit_ready` is back to its original bytes (strict). `_Case.wait_for_credit`, under the new patch `credit_park_recheck`, ends the wake loop after `Timing.credit_recheck_s` (1800 s) of its own park. A refused retry then finds the block at the SLEEP branch and parks again, releasing its worker.
- Finding 2 (BLOCKING, tests do not prove the row): fixed. The router test is removed (no router change). The engine test keeps the real router books blocked the whole time (no top-up, no mid-test knob), sets `credit_recheck_s` once, and asserts two parks, a release before each retry, one retry per park, seal, no diagnosis and 0 waste, plus the unpatched path waiting for a top-up. A lease-time refusal by the real router is not staged; the second stop is scripted.
- Nit 3 (design text): the design is rewritten for the per-park clock.
- Nit 4 (re-pin): done on the final head.
