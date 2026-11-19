# Diff review 8: neuralwatt item 8 confirm on c7fd7ccf (goldfish)

**FAIL.** There is one blocking finding. The Neuralwatt fix itself is correct, and the new test is real and fails without the fix.

**Blocking**

- **`factory/budget.py:1366-1367` with `factory/model_runtime.py:648-652`.** The terminal flag applies to every OpenCode route, including the account-backed free routes (`ACCOUNT_FREE_ROUTES`, whose pool is `opencode-go-key` or `-2`).
  - Before the fix, a free-tier 429 with a status code was let through and ended as `missing_usage`. That stop reroutes as `outage_if_free`, so it was a per-call exclusion of that one lane.
  - Now it ends as `provider_limit` with reason `rate`, which is not per-call. `model_router.observe` keys rate on `route['pool']` (`model_router.py:629`), so it blocks the whole Go account for 900 to 3600 s, Go plan routes included.
  - The quota branch at `model_runtime.py:648` already guards exactly this case ("says nothing about the account's Go plan"). Rate has no such guard.
  - The anonymous free lanes are hit the same way: a 429 on `opencode/glm-5.3-flash-free` now blocks the whole `opencode-free` pool, where before it excluded one lane.
  - **Fix:** extend that branch to `reason in ('quota', 'rate')` for `ACCOUNT_FREE_ROUTES` (and decide whether `opencode-free` wants the same), then add a test.

**Answers**

1. **Correctness:**
   - For Neuralwatt, the fix is correct. Claude, Codex and `openrouter/` routes are unchanged.
   - Go plan routes: a 429 used to end as `missing_usage`, which fails the step for Go. Now it defers and blocks the Go account. That is arguably better, but it is untested.
   - Unchecked risk: the classifier tests status 429 before the quota text. If a real `GoUsageLimitError` event carries `statusCode` 429, it is classed as `rate`, so `go_quota_moves_on` never fires. The test shapes (`test_budget.py:245`, `:493`) have no status code.
   - On "does OpenCode continue after a status-coded error event": there is no captured evidence either way. The only real error event is the 401. The argument that it's terminal is structural: retryable errors are retried inside OpenCode before `session.error`.
2. **Test:**
   - Without the fix, 6 errors, one per subtest (3 bodies × 2 step shapes). With it, `test_neuralwatt_budget` passes 14/14 and `test_budget` passes 51/51 (with `dbos==3.4.0`). I ran these on a scratch copy, not the worktree.
   - The test uses the real captured 401 `APIError` wrapper, with the status, message, `isRetryable` and body swapped in from the fixture's docs-sourced 429 bodies. That is fine.
3. **Item 8 in `docs/designs/neuralwatt-routes.md`:**
   - The 900 → 1800 → 3600 s pool block matches `retry_at`.
   - Rate deferring, because `go_quota_moves_on` is false for it, is accurate.

**Nits**
- The doc and code comment say "the AI SDK already retried". The retry is OpenCode's own, so the wording should say that.
- "The next lease goes to the OpenRouter twin" holds only while Go is blocked. Chains start at Go.
- No test drives a Go 429 or a free-route 429 through `run_budgeted` to the router outcome.

## Elephant response (2026-11-19)

- **Blocking (Go and free lanes):** fixed by narrowing, not by extending the quota branch. Only NW lanes treat a status-coded OpenCode error as terminal (`configured_model in NW_ROUTES`), so Go plan, account-free and anonymous free lanes behave exactly as before. `test_a_go_429_keeps_its_one_lane_exclusion` pins that.
- **Nits:** taken. The wording now says OpenCode retries, and "next lease" now says the chain's next open lane (Go if its plan has quota, else the OpenRouter twin). There is no Go or free-route router-outcome test, because those paths are unchanged.
- **Unchecked risk (a `GoUsageLimitError` carrying 429):** not touched by this change, since Go keeps its old path. Recorded for the Go-quota-timing follow-up.
