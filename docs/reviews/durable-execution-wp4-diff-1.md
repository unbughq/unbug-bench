# durable-execution WP4 diff review 1

Reviewer: fresh goldfish subagent (general-purpose), read-only, personas zoom_out and
implementation_readiness, Mode: REVIEW. Reviewed `de/wp4` at 22d4ff7 against
`durable-execution` at db13be8. Verdict: **FAIL** (findings 1 and 2 blocking).
Verbatim below; the resolution follows at the end.

---

# Diff review: `de/wp4` (22d4ff7) against `durable-execution` (db13be8). WP4, failure classification

Personas used: zoom_out and implementation_readiness, in Mode REVIEW. The standard is implementation-readiness-standard.md.

**Scope.** I read `git diff db13be8 de/wp4`, which touches four files:
- `factory/durable/classify.py`
- `tests/factory/test_durable_classify.py`
- `docs/designs/durable-execution-wp4.md`
- `docs/reports/durable-execution-wp4-stops.md`

I checked the diff against:
- the WP4 brief (`durable-execution-wave1.md` lines 98–109);
- the main design (outcome policy and secrecy sections, WP table line 377);
- the frozen `factory/durable/contract.py`;
- the places that actually raise the stops: `factory/budget.py`, `model_router.py`, `model_runtime.py`, `model_call_gate.py`, `job_authority.py`, `batch_money.py` and `run.py`.

**Test run.** In a detached worktree at 22d4ff7, which I have since removed:
`BENCH="$PWD" uv run -q --with numpy --with scipy --with dbos==3.4.0 python -B tests/factory/test_durable_classify.py` gives **18 tests, OK** (0.15 s). `tests/run.py --list` picks up the new file.

**What holds:**
- **Purity.** `classify` imports only the contract and the stdlib, and the test enforces this.
- **No echo.** Every reason comes from fixed tables. The only stop text ever read after the `:` is the route prefix of a `provider_limit`, and it only picks one of five fixed codes.
- **Finite retry time.** Every PROVIDER_LIMIT gets a finite `retry_at`. The contract's `Classified` checks it too.
- **No verdicts from stops.** OK, GATE_FAILED and NEEDS_FOUNDER never come out of a stop.
- **Protocol compatibility.** The optional `reset_at` keyword fits the `Classifier` protocol: a call through the protocol simply omits it.
- **Real artifacts.** The tests load the 57 tracked `sealed/*.scorecard.json` at test time and filter to the 50 with `dry_run: false`. They pin exact per-kind counts (511 / 33 / 1), so a mapping regression on any real stop fails the test.
- **Scope.** The branch writes only WP4's files and closes no Murphy row, which is correct.
- **Report numbers.** I recomputed them independently and they match: 210 `opencode_error`, 33 affected cards, 32 free-route cards with 206 stops, 13 fallback cards with 89 stops, the run-length histogram, the per-day counts, 19 cards with `claude_resets_at`, and 56 allowlist entries.

---

### 1. BLOCKING: `money_wait` and `retired_batch_bound` are both mapped to `EXHAUSTED` / `batch:money_bound`, but the runner raises neither one as "the batch money bound"

**Where:** `factory/durable/classify.py:98-100`. The design's reasoning, "`money_wait` and `retired_batch_bound` are the batch bound", is at `docs/designs/durable-execution-wp4.md:85` and `:100-103`.

**`retired_batch_bound` is the batch *deadline* (a time), not money.** Every place that raises it:
- `budget.py:143-145` (`reserve_invocation`): `expired = epoch(authority.batch_deadline) <= time.time()` → `retired_batch_bound`.
- `budget.py:836-837` (`run_budgeted`): `remaining = epoch(job_authority.batch_deadline) - time.time(); if remaining <= 0: raise BudgetError('retired_batch_bound')`. `batch_limited = remaining < timeout`.
- `budget.py:1220` and `:1247`: `raise BudgetError('retired_batch_bound' if batch_limited else 'timeout')`. This is the per-call timeout, cut short because the batch deadline falls first.
- `job_authority.py:46-47`, `batch_money.py:177-178` and `batch_holder.py:307-308`: all "deadline <= now".

So the branch maps a wall-clock stop to EXHAUSTED and gives it a reason, published per `PUBLISHED_REASONS`, that claims a money cause. The branch maps the sibling `timeout` stop to INFRA_ERROR. Under the design's policy, an EXHAUSTED whose grant was not batch-limited, or whose usage did not reach the grant, means "give up". That sends an ordinary step to DIAGNOSE, and an ADMIT to STOP_ADMISSION for the whole batch. The cause is a clock, not a case limit.

**`money_wait` is not specific to the batch either:**
- `budget.py:939-941` (`check_limits`) raises it when the case's spend plus outstanding reservations exceeds `job_authority.committed_total_usd`. That is the attempt's own committed money. Under the engine this is the grant, whose label may be CASE.
- `budget.py:141`, `:144`, `:714`, and `job_authority.py:51`, `:63`, `:71`, `:73` also raise it for a missing, malformed or mismatched JobAuthority. Those are plumbing faults.

So `batch:money_bound` is the wrong published reason whenever the grant was limited by CASE. For example, a case that spent its own $50 would show "batch money bound" on the public card.

**Tests.** `test_durable_classify.py:148-149` pins the wrong mapping for `money_wait`. `retired_batch_bound` is only checked by the budget.py label sweep (`:151-164`), which asserts nothing beyond "not unclassified". Neither label occurs in the 50 real cards, so no real artifact supports either mapping.

**Fix:**
- Map `retired_batch_bound` to `(INFRA_ERROR, "infra:deadline")`, which is the contract's existing code for an attempt cut off at its deadline. A new `batch:deadline` code is the alternative.
- Map `money_wait` like `cost_limit`: `EXHAUSTED` with `<step stage>:money`. That leaves "batch versus case" to the policy's Grant label, as the main design specifies.
- In the design note, list the plumbing-fault sources of `money_wait` and state that WP5a must not emit `money_wait` for them.
- Update lines 85 and 99-103 of the design note, and update the test so it asserts both new mappings with the budget.py line references.

### 2. BLOCKING: the report's `opencode_error` cause analysis presents card-level co-occurrence as cause counts

**Where:** `docs/reports/durable-execution-wp4-stops.md:148-158` and the rank table at `:191-194`.

The counts are correct. The causal wording is not supported:
- **Line 148**, "Free OpenCode Zen routes **account for** 206 of the 210 (98%)": the 206 are stops on cards that gave a free route to the writer, stress or reviewer role. Nothing ties any single stop to a free-route call. Stop history has no route, as lines 119-121 admit.
- **Lines 157-158**, "So the difference is the free Zen routes, not the CLI": this is a causal conclusion from a comparison with confounders. The 32 free-route cards average 14.6 stops per card; the 17 other cards average 2.6, so they ran very different amounts of work. Role assignments also differ between the two groups.
- **Rank 1 in the table** includes GLM 5.3 Flash in the cause. But the report says at line 154 that every card, including the 17-card comparison group with only 4 errors, has the free GLM easy calibrator. The 206 is computed from MiniMax and DeepSeek role assignments only. So the cause named in rank 1 and the stop count in rank 1 describe different things.
- **The column headed "Stops"** under "Cause" therefore reads as attributed stops, which it is not.

This is the brief's "Ship" item ("top `opencode_error` causes ... with counts"), so a reader will act on it.

**Fix (wording only):**
- Retitle rank 1 "Co-occurs with free Zen routes in writer, stress or reviewer roles (MiniMax, DeepSeek)", and rename the column to "Stops on those cards".
- Make GLM a separate row: "≥13 attributed by `free_model_fallback.why`".
- Replace "the difference is the free Zen routes, not the CLI" with a sentence that states the correlation and the stops-per-card confounder.
- Keep the existing statement that the real cause needs the encrypted transcripts.

### 3. NIT: the label sweep covers only `budget.py`, though the table maps labels from four other files

**Where:** `test_durable_classify.py:151-164`.

Several `_FIXED` entries come from other files, and no test pins them:
- `model_call_gate.py`: `shared_paid_spend_wait` (:540, :721), `unbounded_route` (:693), `credential_expiring` (:699);
- `model_router.py`: `router_batch_unconfigured` (:520), `provider_routes_exhausted` (:614);
- `run.py`: `provider_preflight_failed`.

Those files also raise about 60 more labels that fall through to `infra:unclassified_stop`. Examples are `provider_wait_deadline` (model_router.py:523, :593, :642), `provider_wait_unsettled`, `stress_validation_exhausted` and `malformed_output_exhausted`. INFRA_ERROR is a safe default, but the design claims an exhaustive table. `provider_wait_deadline` is the same batch-deadline stop as finding 1.

**Fix:** extend the AST sweep to `model_router.py`, `model_runtime.py`, `model_call_gate.py` and `run.py`. Assert the expected outcome for each mapped label, not only "not unclassified". Assert an explicit, reviewed set of labels that are expected to stay unclassified.

### 4. NIT: `credential_expiring` is also raised for a missing local secret, and that sleeps forever

**Where:** `model_call_gate.py:699` raises `credential_expiring` when the token environment variable is empty. `model_runtime.py:405-407` raises it when the secret file is missing. Both are configuration faults.

As PROVIDER_LIMIT (`classify.py:53-54`) these spend no money, so the design's only give-up rule never fires: that rule gives up only after more than `max_spent_limits_per_step` limits that each spent money. The step therefore sleeps in 15-minute cycles indefinitely. The design note (lines 104-108) accepts this. It is still a hang of the kind the Murphy register exists to track.

**Fix:** add a `new-wp4-1` Murphy row, or a stated cap that WP1 must enforce, for limits that never end and spend nothing.

### 5. NIT: `budget_exhausted` is also raised for a configuration fault

**Where:** `budget.py:720-721`. It is raised when `configured_model` starts with `codex/` and is not in `CODEX_PRICES`. That is an unpriced route, which is plumbing, yet it is mapped to EXHAUSTED `<stage>:money` (`classify.py:104`).

Under the engine, WP5a turns off the in-process case budget, so this is mostly legacy.

**Fix:** state this in the design note's mapping rationale.

### 6. NIT: GATES-level EXHAUSTED publishes as `engine:*`

**Where:** `classify.py:37-38`. The stage `engine:` otherwise means an engine or executor fault (`engine:executor_raised`). On the public card, `engine:call_limit` for a calibrator running out of calls reads as a factory fault.

Contract finding 2 already reports this.

**Fix:** none in WP4 beyond the finding. The elephant should carry the `gates` stage into the next contract revision.

### 7. NIT: only one runner wrapper is stripped

**Where:** `classify.py:131-138`. A ledger `terminal_stop` can hold an already-wrapped message: the real card text is `Budget ledger stopped: codex_error`, and `budget.py:358` stores `str(error)`. That stop can come back as `Budget ledger stopped: Budget ledger stopped: codex_error`, which classifies as `infra:unclassified_stop`. The outcome is still INFRA_ERROR, but the reason is wrong.

**Fix:** strip wrappers in a loop, with a bound.

---

**Verdict: FAIL.** Findings 1 and 2 are blocking. Finding 1 needs two remapped labels, a corrected design rationale and test updates. Finding 2 is a wording fix in the report.

---

## Resolution (elephant)

Recorded after the fixes; see the end of this file.
