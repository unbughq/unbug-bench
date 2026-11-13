# Goldfish review: opt/integration (15 merged streams), diff 1

- Reviewer: egm-zoom-out (Skeptical Architect), Mode: REVIEW
- Scope: `git diff origin/main...HEAD` (66 files) against the PR description. There was no design step.
- Method: I read the factory diff in full, plus the code the merged streams touch at their seams:
  - `durable/engine.py`: `wait_for_bound`, `wait_for_fix`, `run_seq`
  - `durable/ledger.py`: `case_balance`
  - `gate_pipeline.py`: the run loop
  - `bin/checkpoint_evidence.read_completed`
  - `calibration.compatible_panel` and `calibration.completed_attempts`
  - DBOS 3.4.0: `DBOS.patch` and `_sys_db.check_operation_execution`
- I ran no tests. Every finding below comes from reading the code. The blocking item was checked against DBOS 3.4.0's own source.

## Verdict

**Request changes.** One blocking item: the PR says every engine step-sequence change is gated by `DBOS.patch`, and that is not true. `wait_for_bound` now records a step that older workflows never recorded.

Nothing I found weakens the exam directly. Here is how each thing the PR said it keeps unchanged holds up:
- Gates, pass criteria, seeds and cheat coverage are unchanged. G8/G9 are stricter now that both reviewers must approve.
- G7 reuse is limited to an identical whole-case fingerprint. That is the founder's ruling.
- Checkpoint receipts reuse only complete, valid, identical-identity batches. They are re-read with `require_valid`, and records are read from the copied directory.

Two items do soften exam-adjacent checks:
- G2 freshness evidence under the default-on fan-out (S3).
- Reuse logic that sits outside the verdict fingerprint (S4).

There are also three money and accounting interactions between streams that each looked fine alone (S1, S2, S6).

---

## Blocking

### B1. `wait_for_bound` adds an ungated `now_step()` to every poll, so pre-deploy workflows fail to replay

- **Severity:** blocking
- **Where:** `factory/durable/engine.py:1243-1246`
- **Old loop:**
  ```python
  while DBOS.recv(WAKE, ...) is None and blocks:
      if deadline is not None and now_step() >= deadline:
  ```
- **New loop:**
  ```python
  while DBOS.recv(WAKE, ...) is None and blocks:
      now = now_step()
      if deadline is not None and now >= deadline:
  ```
- **Why it breaks replay:** every non-admission bound wait passes `deadline=None` (`engine.py:1050`, `:1178`). That includes the G10 and GATES money waits. Old workflows therefore recorded only `recv, recv, recv, …` in this loop, and the new code calls `recv, now_step, recv, now_step, …`. The `keep_worker_through_waits` patch at the top of the function correctly returns False for those workflows, but it does not guard this line.
- **What DBOS does:** in DBOS 3.4.0, `_sys_db.check_operation_execution` compares function names and raises `DBOSUnexpectedStepError` when they differ (`_sys_db.py:3628`).
- **Failure scenario:**
  1. Before the deploy, a case sits in `waiting_for_bound` for a money or batch-bound wait, long enough for two or more `recv` timeouts to be recorded. This is exactly the state that "G10 money stop" cases are in.
  2. The deploy follows the PR order: drain, restart the router, roll. Draining does not finish parked workflows.
  3. DBOS recovery replays the workflow. The first `recv` matches, then `now_step` meets a recorded `DBOS.recv`, and recovery raises `DBOSUnexpectedStepError`.
  4. The case's workflow errors out and needs manual `--resume-case` work. That is exactly the pit stop this PR is trying to remove.
- **Why the tests miss it:** `tests/factory/test_keep_worker_waits.py::test_unpatched_replay_releases_up_front` stubs `now_step` with a clock iterator and never asserts the call count. It passes on the broken sequence.
- **Fix:** call `now_step()` only where the old code did, plus the patched keep-worker path. For example: `now = now_step() if deadline is not None or (keeps and self.worker_id is not None and started is not None) else None`. Then guard the comparisons. Add a test that records a workflow under the old loop with real DBOS on sqlite (the `EngineRun` fakes already run DBOS) and replays it under the new code.
- **Weakens exam:** no. It strands cases, so it costs throughput and money.

---

## Should-fix

### S1. Money auto-resume reads the case limit without the GATES extension and ignores batch-only reruns

- **Severity:** should-fix (an interaction between the priority/auto-resume stream and the up-front G10 money stream)
- **Where:**
  - `factory/durable/engine.py:1476`: `hold_clear_step(auto, …, self.spec.case_money_usd_micros)`
  - `factory/durable/executor.py` `money_allows`
  - `factory/durable/ledger.py:301`
- **The mismatch:** a GATES attempt now runs against `case_limit + $150` (`engine.py:1030-1032`). The "money" auto-resume, however, checks `case_balance(…, spec.case_money_usd_micros)`, which is the bare $50.
- **Failure scenario:**
  1. A GATES step spends $80, which the extension now allows, and then stops on the batch bound (`…:money`).
  2. The factory_bug diagnosis parks it with `auto="money"`.
  3. `case remaining = max(0, 50 - 80) = 0`, which is below `MIN_GRANT_USD_MICROS`, so `hold_clear_step` never returns True, even after the batch bound is raised.
  4. The case waits for a release or an operator. The feature never fires for exactly the GATES money stops it was built for.
- **A second problem:** the `policy.py` comment says a rerun after a diagnosis "draws on the batch only". The case-limit test should not apply to that rerun at all.
- **Fix:** pass the limit the next attempt will actually run against. That means the extension for GATES, and no case check when `draws_case_money` is false.
- **Weakens exam:** no.

### S2. The +$150 "G10 up-front" authority covers all GATES spending, and it compounds on bound retries

- **Severity:** should-fix (money accounting and limits)
- **Where:**
  - `factory/durable/policy.py:184-197`
  - `factory/durable/engine.py:1029-1032` and `:1129`
- **The cap is not scoped:** `gates_money_extension` raises both the request and the case limit for every GATES attempt by `3 × CLAUDE_CALL_USD`. Nothing ties that headroom to strong-calibrator tries. Any GATES spender can use it:
  - the now-mandatory second reviewer (the panel is twice as large)
  - G16/G17/G11
  - the G2 freshness top-up in the side lane
  - repaired fairness tries
- **What that means:** the effective per-case cap in GATES moves from $50 to $200. The claim that "real spend is unchanged" describes intent. Nothing enforces it.
- **It compounds on retries:** on a `WAIT_FOR_BOUND` retry, `requested_minimum = max(job["request"] * 2, 1)` already includes the extension. The next loop then adds the extension again, so the request grows as `2(b+e)+e`, then `2(2(b+e)+e)+e`, and so on. The ledger caps it eventually.
- **Batch effect:** every concurrent GATES attempt holds $150 more of batch authority up front. With about 24 parallel cases, that is about $3.6k of holds, which can push writer and stress steps into `WAIT_FOR_BOUND`. That is a throughput regression the per-stream tests cannot see.
- **Failure scenario:** a misbehaving reviewer route (the 11 November MiMo zero-usage holds are an example) or a G16 loop spends past $50 in GATES. Before this change the case stopped at $50; now it stops at $200.
- **Fix, either of:**
  - Confirm with the founder that "G10 money" means the whole GATES cap.
  - Scope the authority to strong-calibrator reservations, for example a role-tagged sub-limit in `reserve_invocation`, and add the extension once rather than through the doubling.
- **Weakens exam:** no.

### S3. The default-on freshness fan-out can drop a definite public hit and clears results from snippets

- **Severity:** should-fix
- **Weakens exam:** yes, mildly. G2 contamination evidence gets weaker.
- **Where:** `factory/freshness_fanout.py`, lines 26, 29 and 225-233. The flag is on by default (`run.py` `--freshness-fanout`, `default=True`).
- **Problems:**
  - **A true hit can be dropped.** `for r, (v, why) in flagged[:3]` keeps the first three non-miss results per query in search-result order. If a query returns three "unsure" results before a "close" one, only the three ambiguous rows are logged. The definite hit never reaches `freshness.jsonl`, and G2 sees only ambiguous rows for its flagged-hit review.
  - **Results are cleared without being read.** The scoring call clears results as "miss" from at most 1,000 characters of snippet. Only results under 40 characters (`THIN`) are forced to "unsure". The old agentic path opened pages. The role doing the clearing is the writer, which has an interest in a clean freshness verdict.
  - **Amended rows claim more than happened.** An amended repairable row keeps its old `url` and `hit` but gets `retrieved: True` and a "returned N results, none flagged" note. That holds even when the re-run found flagged leads (they are added as separate rows) or zero results. The row then claims a retrieval of a URL that nobody fetched.
- **Fix:**
  - Order `flagged` with "close" first, or log every "close" result.
  - Raise `THIN`, or require a deep dive for any web result whose snippet is truncated at `SNIPPET`.
  - Do not set `retrieved: True` on an amended row unless that row's own URL was retrieved.

### S4. Receipt-reuse decisions are excluded from the verdict fingerprint

- **Severity:** should-fix
- **Weakens exam:** potentially. Future edits could loosen reuse without invalidating caches.
- **Where:** `factory/gate_state.py:70-74`, which adds `_save_checkpoint`, `_saved_checkpoint` and `_checkpoint_receipt_dir` to `SIDE_EFFECTS`.
- **Why it matters:** `_saved_checkpoint` (`run.py:1283`) decides whether a saved batch stands in for a fresh bench run. It applies the symlink refusal, the `identity.json` equality and the `require_valid` re-read. That is sample-selection logic, not plumbing.
- **Failure scenario:** a later "plumbing" edit relaxes `_saved_checkpoint`, say by comparing only some identity keys. G4-G7 gate caches and engine checkpoints stay valid, and old receipts with a different seed or guard get reused.
- **Fix:** keep `_saved_checkpoint` in the hashed set. It changes rarely, so the cost is low. `_save_checkpoint` and `_checkpoint_receipt_dir` can stay excluded.

### S5. Helpers ship disabled but sit inside every bench gate's fingerprint

- **Severity:** should-fix (zoom-out, YAGNI)
- **Weakens exam:** no.
- **Where:**
  - `factory/durable/checkpoints.py:95` puts `durable/helpers.py` and `durable/helper_link.py` in `BENCH_VERDICT_CODE`.
  - `factory/gate_state.py` adds them to the G5, G6, G7 and G10 `DEPENDENCIES`.
- **The cost:** about 940 lines of transport and shard code are inert at deploy (no `--helper-workers`, no `helpers` block). Even so, any fix to them invalidates every case's G4-G7 engine checkpoints and the G5/G6/G7/G10 gate caches, for code that cannot have run. That is the cost the model/bench split in this same PR (`verdict_code(model=…)`) was built to remove for router edits.
- **Failure scenario:** someone fixes one of the known helper gaps, such as lost spend on a dead helper. Every in-flight case loses its bench-gate reuse on the next deploy and reruns hours of G4-G7.
- **Fix, either of:**
  - The simpler option, and the one I recommend: per ENGINEERING.md §4 ("Delete before adding"; "One launch path"), keep helpers on their branch until they are switched on.
  - Fingerprint the helper files only when the attempt actually used a helper (`helper_pool` bound).

### S6. Warm pool and six-hour held workers versus Boat limits (only if `warm_workers` is configured)

- **Severity:** should-fix if the deploy sets `warm_workers`; otherwise a nit.
- **Weakens exam:** no.
- **Where:**
  - `factory/durable/workers.py` `refill` / `_create` and `runtime._warm_pool`
  - `factory/durable/engine.py` `KEEP_WORKER_WAIT_S = 21_600`
  - `factory/durable/guard.py:301-306` (running cap) and `:307-309` (start allowance)
- **What goes outside the engine's admission gate:**
  - Warm creates bypass the engine's attempt gate and add up to 8 live workers.
  - `refill` recreates every warm worker whose release is no longer wanted. Each plumbing deploy can therefore spend up to 8 creates from the hourly start allowance. On 8 November the start allowance was the binding limit.
  - Held idle workers through money or router waits (up to 6 h per case) also count toward `max_running_sandboxes`.
- **Failure scenario:** 24 cases, several in long money waits holding workers, plus 8 warm workers. The total goes past `max_running_sandboxes`, and the guard raises `running_cap` and pauses new attempts. The waiting cases keep their workers, and the cases that could make progress cannot start.
- **Fix:**
  - Count warm workers against the same cap before refilling.
  - Release held workers when the guard reports over-cap.
  - Have refill go through the start-allowance check.
- **Also unconfirmed:** the PR says "Setup is warm". I could not see from the diff whether production config sets `warm_workers`. If it does not, that line in the PR is misleading.

---

## Nits

- **N1. `gate_pipeline.py:327, 368`, `lane_failed()`:** a failed G8/G9 is no longer recorded at the next boundary. It waits for `side_join` (G6), so G3-G5 and G16 still run, and G16 spends model money on a case that has already failed. This is deliberate (it keeps the earliest failure in gate order), but it is waste. Recording the failure early and only rewriting `failed_gate` at the join would give the same card.
- **N2. `calibration.py:265`:** the slot relaxation in `compatible_identity` contradicts `run.py:2711` ("Strict receipt identity … without equating different endpoints"). The early probe picked its slot precisely so that strict identity would hold. The relaxation is fine scientifically (the slot is only a port offset), but the comment is now stale.
- **N3. `invalid-runs-compat.json` `release_pins`:** a hand-maintained "this edit changes no verdict" escape hatch. It is valid today (both hashes check out), but it is a new mechanism that bypasses fingerprints on assertion alone. `gate_state.py` itself changed in this PR, so most gate caches invalidate anyway and the pin buys little this time. Use it sparingly, and only alongside a test that the pinned edit is verdict-neutral.
- **N4. Three reuse layers now overlap:**
  - engine `gate_call` receipts
  - `gate-cache`
  - the new per-checkpoint `gate-checkpoints` receipts, alongside `infra-attempts.json` retry identities

  Each is defensible, but the `RECEIPTS` global (`gate_state.py`) exists only to stitch layer 3's evidence into layer 2. Longer term, the per-checkpoint receipt could be the single source of evidence.
- **N5. `gate_state.forget_receipts`:** iterates a dict that a concurrent lane thread can grow (`note_receipt` from early-lane G5 key checks while a foreground gate starts), which can raise "dictionary changed size during iteration". Use `list(mine)`.
- **N6. `engine.keeps_worker_for`:** treats `release_worker_after_sleep_s == 1800.0` as "never set", so a batch that sets 1800 explicitly gets 6 h. Use `None` as the sentinel.
- **N7. `model_runtime.py:561`:** `stalled_routes` is per role for the whole context. A writer route that stalled once on selection is excluded from the writer's long construction calls too. If the chain has only one route, the writer has nowhere to go. It probably helps more than it hurts, but note it.
- **N8. Silent-worker retirement (`executor._silent_and_unrenewed`):** deletes a worker after 30 min with no poll answer plus 15 min of refused `boat extend`. Neither signal is specific to that worker. A Boat API refusal for an account-level reason, combined with ssh trouble from the control VM, would delete a live G10 worker and book the whole grant as waste. It is unlikely, but put the refusal reason in `renewed.json` and retire only on worker-specific refusals.

## What I checked and found sound

- **`DBOS.patch` placement** for `operational_wait_keeps_worker`, the pause path, the `short_sleep_keeps_worker` sleep path, `auto_resume_safe_holds` and `gates_money_up_front`. Each patch sits where an old workflow has a different recorded operation, so it returns False and the old sequence follows. Only B1 is ungated.
- **Checkpoint receipt identity** keeps case hash, guard and scenario digests, runs, seed, label, bench manifest and scoring identity. It drops only slot and workers. G10/G11 labels are never reused. `read_completed` reads records from the copied directory, so a receipt is self-contained.
- **G6/G7 `stop_on_pass`** only short-circuits a gate that is already failing. A passing case still runs every cheat and `verify-negative`. Cheat names written to `gate-details` are the case's own cheats plus `refuse-all`, so the writer learns nothing hidden.
- **The second reviewer:** five distinct families, imported-idea families excluded, and the G8/G9 identity carries both reviewers. `compatible_panel` cannot pass an old single-reviewer cache (models must match). The exam owner stays `reviewers[0]`, and `calibration_identity` uses only `reviewers[0]`, so finished G10 tries survive the adoption.
- **G10 parking:**
  - The join re-raises, and `run_step` keeps a recorded `failed_gate` over the parked BudgetError (`run.py:3542`).
  - The side lane is joined in `finally`.
  - The gates that run while G10 is parked (G13-G15, G7) do no model work.
- **With helpers off,** every helper path is gated on `helper_workers > 0` and a bound `helper_pool`. `bind_helpers` acts only if the control side wrote a spool config, which needs a `helpers` runtime block.
