I've finished the review. **Code verdict: PASS**, with no Blocker or Major findings and three Nits. The full suite for 2451d19 is still running, so it has not passed yet. Review text for `docs/reviews/router-claude-tariff-diff-1.md` follows.

---

# Router Claude standard/global tariff — diff review 1

Reviewer: goldfish (fresh, read-only), personas `zoom_out` + `implementation_readiness`, Mode: REVIEW.
Standards: `zoom-out-standard.md`, `implementation-readiness-standard.md`.
Reviewed: `ef5cf77..2451d1972363df4ee59dd74b5ea57f582f392b6d` (one implementation commit) in `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-b7dfac7a`.
Read against: `docs/designs/router.md` § "Claude standard/global tariff correction" (L1097–1216), `docs/designs/interfaces.md` §7, Murphy row `new-router-maxima-1`, `router-claude-tariff-validation.md`, `router-claude-tariff-mutations.json`.
Not done: no edits, compiles, test runs or model calls.

## Verdict

- **Code: PASS.** No Blocker or Major findings are open.
- **Full suite: NOT YET PASSED.** `/tmp/router-claude-tariff-full-2451d19.json` still reads `"status": "running"` for `tested_sha` 2451d19, started 2026-10-30T06:02:10Z. The log was last seen at `tests/bench/test-launch-guards.py`. Merge needs this to finish with exit 0 and 0 failed. Focused-test claims in `validation.md` are the writer's own record; I did not re-run them.

## Root cause and fit to the design

- **Root cause.** One premium multiplier (2·1.1) was applied to every Claude usage, including standard/global receipts. That made W = $19.04 and stopped the lease at about $14.07 list. The fix removes the multiplier at its single source. `_claude_list_cost` (`factory/token_prices.py:62-67`) now feeds `claude_cost` (L85-86) and `claude_gate_cost` (L70-72). `claude_gate_maximum` (L75-80) drops the same factor. The dead helper `invocation_maximum` (L36-39) also drops 2.2, and its stale docstring is corrected (L20-22). This is the root-cause fix, not a patch in each caller. There is no new pricing inventory.
- **Lease contract.** The new values match the design and interfaces.md §7 exactly:
  - max_input 250,000,000 = 50e6/0.2;
  - max_output 2,500,000 = 50e6/20;
  - price_source is `token_prices:2026-10-30:claude-opus-5-5:4.0,0.2,8.0,20.0:1.0:standard-global:joint-gate-v1`;
  - W = 1e6·8/1e6 + 32768·20/1e6 = 8.65536.

  List rates are unchanged. The test `lease()` (`tests/factory/test_model_call_maxima.py:55-57`) uses production `router.route_maximum`, so the lease assertions exercise the real route.
- **Mode predicate.** `claude_standard_usage` (`token_prices.py:56-59`) accepts speed absent or `standard`, and geo absent or `global`. Explicit `None`, `''`, `False`, `{}`, `fast`, `us` and non-dict usage all fail. This matches the design ("explicit null, empty string … is unknown"). Bool counters are rejected because `type(v) in (int, float)` excludes `bool`.
- **Outbound geo.** `model_call_gate.py:89` sets `inference_geo='global'` after the closed `BODY_FIELDS` check at L84. `BODY_FIELDS` (L30) does not include `inference_geo`, so an incoming override gets 400. The tests cover both the 400 for `us` (L560) and the forwarded `global` (L568).
- **Sticky gate invalidity.**
  - `Usage.merge` (L228-229) now sets the existing `self.invalid` flag on any non-standard observation and returns early.
  - `feed` stops once invalid. `final()` returns `None` whenever `invalid` is set.
  - So a premium `message_start` followed by an absent-mode `message_delta` cannot refund W. `test_mode_metadata_is_strict_and_parser_invalidity_is_sticky` covers this, including the final update that omits the mode and the fast mode arriving only on a delta.
- **Direct inputs.** `claude_gate_cost` returns `None` on invalid input, and `Allowance.finish` (L181-182) treats `None` as unknown and retains the full allowance. Before this change, a missing key would have raised inside `finish`. That is an improvement.
- **Budget aggregation.** Invalidity is now sticky at both partial seams the design names:
  - per-message accumulation (`factory/budget.py:964`): the `speed='unknown'` marker survives the max-merge, because that loop iterates only `required`;
  - session sum after a lost result (`budget.py:1223`).

  `claude_cost` → `None` → `missing_usage` is caught at L1229. `starts - finishes` then appends `unpriced_invocations`, so D's full commitment is retained. This is the minimum wiring needed and adds no new path.
- **Completed costs.** `subscription_usage(..., partial=False)` never calls `claude_cost` (L900-901). Completed results still book `total_cost_usd` as `list_cost_usd`, which the transport test checks for both writers (`complete=True`). The only `claude_cost` caller in the repo is `budget.py:901`, and no historical ledger is repriced.
- **Small-change bar.** The production delta is about 40 lines across three files. There is no new module, config or staging path. The YAGNI and placement checks pass.

## Murphy `new-router-maxima-1`: does the conditional proof qualify for closure?

**Yes, it qualifies, with the conditions written into the closure record.** Reasons:

1. **The row asks for this proof.** Its own Fix column says "Prove both real writer envelopes conditionally, since no request trace survives." The test does what the row and design say. It does not claim more.
2. **It uses real artifacts.** The ids, call counts (110 and 135), counters and recorded costs come from `router-paid-deepseek.json.gz`. All 32 saved Claude receipts are asserted standard/global.
   - Settled is set to max(recorded CLI cost, shared list estimate) together with the whole-run token aggregates. That is a test-only upper bound, and production never reads it.
   - The test checks admission against the production lease with 0, the tolerated count, and tolerated+1 unknown holds plus the next W.
3. **The arithmetic is tight.** For 873d7f: 15.05 + 4·8.655 = 49.67 is admitted, and 5·8.655 + 15.05 = 58.3 is rejected. For e15450: 19.08 + 3·8.655 = 45.04 is admitted, and 4·8.655 + 19.08 = 53.7 is rejected. These match the stated tolerances of ≤3 and ≤2 unknowns.
4. **The mutation is real.** `mutations.json` multiplies only the shared return expression by 2.2. Both writer subtests then fail at next-request admission (L142), and the restored SHA matches the original.
5. **Concurrency does not break the argument.** Terminal exhaustion depends only on settled + retained. Concurrent active holds only cause bounded waits, so parallel requests do not weaken the monotonic argument.

Closure still needs this in the closing commit, as `docs/ENGINEERING.md` §2 requires:
- `Status=closed`;
- `Closed by=tests/factory/test_model_call_maxima.py::test_real_writer_envelopes_fit_with_bounded_unknown_attempts`;
- the Evidence or Closed-by cell must state the two hypotheses and the 3/2 unknown tolerance.

This commit correctly leaves the row `open` until this review.

## Findings

**Blocker:** none.

**Major:** none.

**Nit 1: forced geo has no live-endpoint evidence.** `factory/model_call_gate.py:89`. The design relies on the documented data-residency contract. No captured run shows the OAuth/subscription endpoint accepting an explicit `inference_geo`. If the endpoint rejected the field, every gated Claude request would fail. That would fail closed: 400s retain W, and about 5 failures exhaust the lease into `model_call_cap`. It would still stop every writer round on the first launch. Recommendation: make the first gated launch's first request an explicit smoke check, or capture one real accepted request, before relying on this at batch scale. This does not block, because the design passed on the provider contract, the failure loses no money, and this increment needs no launch.

**Nit 2: the `invocation_maximum` Claude branch has no direct test.** `factory/token_prices.py:36-39`. The fix is correct, but nothing directly asserts the new Claude result: max(4, .2, 8)·input + 20·output with no 2.2 factor. Its only consumer is `tests/factory/test_stream_d_runtime.py:78`. A one-line assertion would pin it. This is optional.

**Nit 3: the unknown marker reuses the `speed` field.** `factory/budget.py:964,1223`. The marker is written as `speed='unknown'`. That works because the shared predicate rejects it, and it avoids a new field. A later reader could mistake it for provider data. A short trailing comment would help. This is optional.

## Validation evidence

- Focused tests are as recorded in `validation.md`: maxima 21, budget 39 with one existing skip, case_budget 33, D-runtime 21. The record discloses that case_budget failed two subprocess imports when first run standalone without BENCH, and passed with BENCH set as `tests/run.py` sets it. No source was changed to suppress the failure. I accept that as an invocation-context issue, not a defect.
- The D-runtime change from .1232 to .056 is exactly 1/2.2 of the old estimate (.1232/2.2 = .056). The change is consistent.
- Edits to existing tests move the boundary constants to the new W:
  - 2 → 5 concurrent holds;
  - settled 32 → 42;
  - held 38.08 → 43.28 (5·8.65536);
  - near-ceiling usages rebuilt for the new W.

  The tests' intent is kept.
- The full suite is still running; see the Verdict section.

## Set aside as out of scope (not reviewed or implemented here)

- The gate-wall (`new-router-gate-wall-1`) implementation, and cheap-route enablement. Their designs are on the same branch, but they are not in this diff.
- Correctness of the provider's published list rates, and the CLI's own `total_cost_usd`.
- Any live-account behaviour of explicit `inference_geo` (Nit 1).
- Historical ledger repricing, which the design explicitly excludes.
- Hostile Bash or direct-network spend outside the gate (the existing §7 non-claim).
- Rollout of old-tariff leases. Exact-policy rejection plus the existing drained-rollout requirement is assumed.

## Author response

Accepted; no findings rejected. Murphy closure will carry the two hypotheses and
the 3/2 unknown tolerance. The full suite remains a separate terminal gate.
N1 is retained as a live-rollout limitation: no real model call is authorized
for this tariff increment. N2 and N3 are optional and deferred to keep this
reviewed implementation frozen during its full suite.

### Subsequent full-suite record

The reviewed SHA completed with exit 0 and 144 scripts / 0 failed at
2026-10-30T06:16:47.971248Z. See router-claude-tariff-full-2451d19.json and
its SHA-256-linked gzip log. The original review-time running status above
is preserved as history.
