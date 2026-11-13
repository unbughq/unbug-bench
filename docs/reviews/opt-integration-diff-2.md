# Goldfish review: opt/integration diff (deploy readiness)

- Persona: implementation readiness, REVIEW mode.
- Scope: `git diff origin/main...HEAD` on `opt/integration` (6452636e), checked against the PR description `pr-body.md`.
- Angle: is this safe to deploy to the production factory tonight?
- Persona files: they are not in this worktree. I read them from the main checkout, `tools/egm/agents/implementation_readiness.md` and `tools/egm/document_standards/implementation-readiness-standard.md`.

## Verdict

**Not ready tonight. One blocking finding.**

The bound-wait loop in the engine changed its DBOS step order without a patch gate. A case that is parked on money when the drain happens will crash with `DBOSUnexpectedStepError` when the new engine recovers it. I reproduced this against real dbos 3.4.0.

The fix is one line plus a real-DBOS replay test. Once that lands, and the deploy notes cover the batch-bound and guard points below, I see nothing else that blocks a deploy.

## Findings

### 1. BLOCKING: a recovered money wait crashes on replay

- **Where:** `factory/durable/engine.py:1243-1245` (`_Case.wait_for_bound`).
- **The change:**
  - On main, the loop called `now_step()` only when a deadline was set (`if deadline is not None and now_step() >= deadline`).
  - The new loop always calls `now = now_step()` after each `DBOS.recv` timeout. Nothing patch-gates this.
- **Why it matters:** the `deadline is None` path is the ordinary money wait. Its callers are at `engine.py:1050` and `:1178`, which pass `None` whenever the step is not an unstarted ADMIT.
- **What a workflow recorded on main contains:** the patch marker for `bound_wait_blocks`, then `recv`, `recv`, `recv`, … (`wake_poll_s` = 300 s).
- **What the new code does when it recovers that workflow:**
  1. It replays the first `recv`.
  2. It then calls `now_step` where the record holds the second `recv`.
  3. DBOS raises.
- **Repro:**
  - Script: `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/35da1f8b-8fdf-431c-a84e-d725cb8c71d1/scratchpad/replay/wf.py`.
  - Steps: record the old loop body in a sqlite DBOS app, kill the process, then recover the workflow with the new loop body.
  - Result:
    ```
    DBOSUnexpectedStepError: DBOS Error 11: During execution of workflow w1 step 4,
    function DBOS.recv was recorded when now_step was expected.
    ```
- **Failure scenario tonight:**
  1. We drain. `Engine.drain` only lets attempts in flight settle, so case workflows stay PENDING.
  2. Any case that is `waiting_for_bound` past two polls (about 5–10 minutes) is one of those pending workflows.
  3. The new process recovers it, it errors on replay, and the case workflow dies.
  - With 24 cases in parallel and a tight batch bound, some cases will be parked like this at any moment. Finding 2 makes that more likely after the deploy.
- **The PR's claim:** "every engine step-sequence change is gated by `DBOS.patch`". That is false for this one line.
- **Why the tests missed it:** `tests/factory/test_keep_worker_waits.py:56` (`test_unpatched_replay_releases_up_front`) fakes `DBOS` and `now_step`. It asserts only which worker was released, never the step sequence, so it passes.
- **Fix:** call `now_step()` only where the old code did, or where the new patch is on:
  ```python
  now = now_step() if deadline is not None or started is not None else None
  ```
  Guard the keep-limit check on `now is not None`. Add one replay test on real DBOS (sqlite) that records the old loop and recovers it with the new one.
- **Exam:** not weakened. This is an availability and case-loss bug.

### 2. SHOULD-FIX (deploy config): the $150 GATES extension is held against the batch bound, and a lost attempt books all of it as waste

- **Where:** `factory/durable/engine.py:1029-1032` and `factory/durable/policy.py:190-197`. The ledger side is `factory/durable/ledger.py:214-218` and `:140-144`.
- **What changes:**
  - `job["request"]` grows by 3 × `CLAUDE_CALL_USD` (the PR says $150).
  - `ledger.reserve` grants `min(request, batch_left, case_left)`. While a GATES attempt is HELD, that whole grant counts against the batch bound.
  - A LOST attempt counts `granted_usd_micros` as both spent and waste. LOST covers `infra:worker_lost`, `infra:cancelled`, `engine:executor_raised` and similar.
- **What that means:**
  - The claim "real spend is unchanged" holds for settled attempts only.
  - Every concurrent GATES step holds up to $150 more of batch headroom.
  - Every lost GATES attempt books up to $150 more waste.
  - The new silent-worker retirement (`executor.py:120-123`) adds a new route to LOST.
- **Failure scenario:**
  - The batch bound is sized for today's grants. Twelve cases reach GATES together and hold about $1,800 more between them.
  - Writer and stress requests then get `WAIT_FOR_BOUND`, which also feeds finding 1.
  - One worker lost mid-G10 now books about $200 as waste instead of about $50. That shows up on the infra-waste line.
- **Fix:**
  - Either raise the batch bound by $150 × the expected number of concurrent GATES steps, and write that into the deploy notes,
  - or settle a lost GATES attempt at its base request rather than the extended grant.
  - At minimum, the PR's Money section should say that holds and losses grow.
- **Exam:** not weakened.

### 3. SHOULD-FIX (deploy order): the guard, the broker and the router path are missing from the deploy notes

The deploy order lists drain → router → workers. Three more pieces have changed or are now read:

- **Guard.** `factory/durable/guard.py:326-336` now writes `guard/renewed.json`, and silent-worker retirement reads it (`guard.renewing`).
  - If the guard process stays on old code, `renewing()` returns `None` forever.
  - That fails safe: no early retirement. But one of the 15 streams then silently does nothing.
  - Restart the guard with the engine.
- **Router books.** `router_clear` (`factory/durable/runtime.py:90-93` → `model_router.production_database({})`) reads `~/.unbug-control/router/factory.sqlite3` of the engine's own user.
  - `production_database` raises if `UNBUG_CONTROL_HOME` is set.
  - Engine on another user or host, or with that variable set: `hold_clear_step` swallows the error, so quota auto-resume never fires. Again fail-safe but dead.
  - The runtime config key `router_db` exists for this case, but nothing documents it.
- **Warm workers.** "Setup is warm" in the PR is off unless the runtime config sets `warm_workers` (`runtime.py:186`, default 0). No doc mentions the key.
  - Either say "warm pool off at deploy" next to "helpers off", or give the value to set.
- **Exam:** not weakened.

### 4. SHOULD-FIX: freshness fan-out is on by default and leans on unauthenticated public endpoints

- **Where:** `factory/freshness_fanout.py:24,38-80` and `factory/run.py:3598`.
- **What it calls:**
  - Exa through the keyless MCP endpoint.
  - GitHub search with no token unless the worker already has `GITHUB_TOKEN`/`GH_TOKEN`. Workers are not documented to have one.
- **The limit:** unauthenticated GitHub search allows about 10 requests per minute per IP. Each GitHub query costs 2 requests (issues plus commits). Each case fires all its queries at once on up to 16 threads, and up to 24 cases run in parallel.
- **What happens when it fails:**
  - 403s and 429s become `None` and the query is dropped (`freshness_fanout.py:166-169`).
  - The role stays short and falls through to the agentic top-up. That fails safe.
  - But the plan call was paid for and saved nothing. Under load, fan-out mostly adds a model call per role.
- **Fix:** give workers a read-only GitHub token through the credential bundle, or keep `--no-freshness-fanout` until throughput is measured on a real batch.
- **Exam:** not weakened. Evidence rows still go through `search_evidence_error` and G2.
- **Evidence-quality nit:** an amended row (`freshness_fanout.py:228-230`) gets the note "Fan-out search returned N results, none flagged" even when results from the same query were flagged and appended as new rows. It also gets that note when the original row had `hit: true`. A G2 reviewer then reads a contradictory note on a hit row. Write the note from `flagged`.

### 5. SHOULD-FIX: two reviewers turn every split vote into a founder stop

- **Where:** `factory/run.py:2290` (two reviewers are now mandatory), together with the existing `_split_panel` → `NEEDS_FOUNDER` (`run.py:3427-3431, 3472-3473`).
- **What changes:** with one reviewer a split vote could not happen. Now any 1/2 at G8 or G9 parks the case for the founder instead of sending a repair to the writer.
- **Exam:** stricter, not weaker.
- **Throughput:** this is a new pit stop. It works against the 6–8 h goal and the "no serial per-case nursing" aim. It is not mentioned in the PR, so confirm the founder wants a split to stop the case rather than repair it.
- **Edge case:**
  - `second_reviewer` raises `ValueError` when an imported idea's `idea_families` cover both `xiaomi` and `z-ai`.
  - On an in-flight case, that error comes from `with_second_reviewer` in engine setup (`run.py:3113-3114`) and crashes the step.
  - That is rare and the error message is clear.

### 6. NIT: "first passing cheat stops G6/G7" changes what the writer is told

- **Where:** `factory/run.py:2250-2256` and `:2275-2277`.
- **The verdict:** unchanged. The gate passes only at zero solving cheats.
- **What the writer sees:** `record_passing_cheats` now names one cheat per round instead of all of them. A case with three solving cheats may need three repair rounds instead of one, and can run out of rounds sooner.
- **Exam:** not weakened. It is a throughput and outcome trade-off worth stating in the PR.

### 7. NIT: a comment says pending tries keep the strict identity, but the code does not

- **Where:** `factory/calibration.py:262-267` and `:325-331`.
- **The mismatch:** the comment says an unfinished (pending) attempt keeps the strict identity. But `completed_attempts` applies the relaxed comparison to every row, interrupted ones included, before it writes `pending-{try}.json` with the current identity.
- **Exam:** not affected, since the slot is a port offset. Fix the comment or the code.

### 8. NIT: helper files are now in the G5/G6/G7/G10 fingerprints although helpers are off

- **Where:** `factory/gate_state.py:44-62` and `factory/durable/checkpoints.py:91-93`.
- **Effect:**
  - Any future edit to `durable/helpers.py` or `durable/helper_link.py` invalidates finished bench gates for every in-flight case, even while helpers are off.
  - The PR states that this deploy itself restarts engine checkpoints. Every in-flight case therefore reruns G5, G6 and G7 (hours) after tonight.
- **Fix:** none needed now. Make sure the operator expects that cost, given the "reuse finished work" rule.

### 9. NIT: router priority can starve writers

- **Where:** `factory/model_router.py:59-63` and `:501-503`.
- **The issue:** there is no aging, and the code says so.
- **Old/new mixes are fine:**
  - Old queued payloads without `priority` read as 0.
  - Old workers send no priority.
  - Only a new worker on the old router fails, which the stated order handles.

## Old/new process mismatches checked

| Pair | Result |
|---|---|
| New worker + old router | Rejected (`invalid admission fields`). The stated order (router before workers) covers it. |
| Old worker / old queued requests + new router | OK. `priority` defaults to 0. |
| Old DBOS workflows + new engine | Patch-gated everywhere **except `wait_for_bound`** (finding 1). The op-wait, pause, sleep, `wait_for_fix` and GATES extension paths are gated correctly. |
| Old pool records + new `BoatPool` | OK. The slot lives in a sidecar file and the record keeps its three-key shape. Warm is off, so no rollback hazard tonight. |
| Old guard + new engine | Fail-safe. `renewing()` is `None`, so there is no early retirement (finding 3). |
| Old router `health` rows + `router_clear` | OK. The schema is unchanged and credit rows do clear (`model_router.py:578`). |
| Old cards with one reviewer | `with_second_reviewer` plus the admit pin tolerance. The G8/G9 identity includes reviewers, so they rerun (no stale single-reviewer pass is reused). The other gates strip reviewer2 from their identity. |
| Old calibration receipts (other slot) | Accepted by the relaxed slot comparison. The `calibration.py` release pin's hashes match: main `ec49b1…`, branch `257d4e…`. |
| Old gate-cache records | They miss on identity (helper deps, narrowed verdict code) and the gates rerun. Expected, and stated in the PR. |

## Helpers off and the new defaults

- **No `helpers` runtime block:** `Runtime.helpers = None` and `BoatChannel.helpers = None`.
- **On the worker:** `Worker.bind_helpers` finds no spool config, so `c.helper_pool` is never set.
- **Shard paths are inert:** `cheat_runs`, `g5_shards` and `hosted_tries` all require `helper_workers > 0` and a `helper_pool`.
- **`--helper-workers`** defaults to 0.
- **Warm pool:** off by default.
- **Freshness fan-out:** on by default. See finding 4.

## Do the tests fail without the change? (spot check)

- **Method:** I copied each test onto an `origin/main` export (`git archive`) and ran it.
- **All 15 test files I tried fail on main:** `test_keep_worker_waits`, `test_image_restore_wait`, `test_g10_money`, `test_narrow_fingerprints`, `test_silent_writer_route`, `test_reliability_writer_deadline`, `test_g1_isolation_warning`, `test_model_router`, `test_g8_two_reviewers`, `test_resume_reuse`, `test_fairness`, `test_durable_guard`, `test_freshness_concurrent`, `test_gate_checkpoint_receipts`, `test_durable_engine_executor`.
- **Caveat:** several of them fail on main only with `ImportError` because the new symbol is missing. That shows the symbol is new, not that the behaviour is pinned. The behavioural assertions in those files look real.
- **The gap:** none of them checks DBOS replay determinism of the changed engine loops (finding 1). That is the one class of bug that would hurt tonight.

## TODOs and half-wired code

- No `TODO`/`FIXME`/`XXX` was added.
- These pieces are wired but switched off, and only the helpers are called out as off in the PR:
  - helpers
  - the warm pool
  - `router_db`
- Undocumented config: `warm_workers` and `router_db`. The `helpers` keys are listed only in a comment at `runtime.py:194`.
