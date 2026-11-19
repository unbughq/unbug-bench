# Diff review 7: neuralwatt item 8 on d329ae64 (goldfish)

**FAIL.** There is one blocking finding. The 402 path is sound.

**Blocking**

- **docs/designs/neuralwatt-routes.md:138-145 with factory/budget.py:1159-1160.** The doc says "every 429 is `rate`" and "`rate` waits". That holds only when you call the classifier directly. On the real OpenCode path it is false.
  - `diagnostic()` lets the first rate error through (`rate_limits < 2` and not `openrouter/`). That allowance suits a CLI that keeps going after a retry notice, but an OpenCode `error` event is the end of the call.
  - I checked this with a scratch probe. It used the harness of `test_neuralwatt_budget.py` and fed in the fixture's `uncached_too_large` and `concurrent` bodies, wrapped like `CREDIT_402`.
  - Result, both with and without steps before the error: `missing_usage`, `provider_failure=None`, and a phantom tail of $0.570 booked. That happens because `open_steps` is forced to at least 1 when the stop is not a classified refusal (`budget.py:1450-1452`).
  - So a Paid-level `concurrent_budget_exceeded`, or a cold request over 1M tokens, ends the attempt as `missing_usage`. It is never published to the router as `rate`, and it books $0.57 that was never spent.
  - The other possibility is that OpenCode retries 429s itself (AI SDK marks 429 retryable). Then no event arrives and the call sits until a stall or the deadline. Either way, "`rate` waits" is not the mechanism.
  - `test_every_neuralwatt_error_body_classifies` cannot catch this, because it bypasses `run_budgeted`.
  - **Fix:** either stop applying the allowance to a terminal error from the `opencode` driver (about one line in `diagnostic`/`consume`), or rewrite the doc to state the real cost. Then add a 429 run through `run_budgeted`, the way `CREDIT_402` does it.

**Answers**

1. **402:** "no classifier change" is right for credit. `test_a_402_before_any_step_books_no_tail` runs `CREDIT_402` through `run_budgeted` → `consume` → `provider_diagnostic`. That reads `error.data.statusCode` and gets credit/wallet, with no allowance applied to credit. The 402 message by itself would not classify: there's no "insufficient credits" text, and "allowance reached" matches none of the quota patterns. So everything depends on the wrapper around the body, and that wrapper is hand-built. No real OpenCode `APIError` event exists anywhere in the repo. One free OpenCode run with a bad key on the VM would capture the real wrapper with its 401 status code (strong nit).
2. **`rate` on neuralwatt:** if a rate error does reach the router, `go_quota_moves_on` is false, so the attempt defers. Meanwhile the router blocks the whole `neuralwatt-key` pool for 900 s, rising to 3600 s. The reason is that no reset time is passed on: `retry_strategy` and the retry-after header aren't read. The next lease then goes to the OpenRouter twin or waits. One oversized request therefore blocks Neuralwatt for every case, which the doc doesn't say. On a Trial key, ordinary steps over 75k would hit this on every call. There's no money burn (a refused 429 isn't billed), but each one costs an attempt and a $0.57 tail. The "Paid or higher" precondition is checked by operators only, with no code check, even though the `x-subscription-plan` response header is available.
3. **Seats = 3 is right:** MiMo and GLM Flash sit in separate Neuralwatt pools with a floor of 3 each. One router pool of 3 never goes over either, and it leaves the burst unused.
4. **Tests:**
   - The `include_usage`/`max_tokens` test only checks the fixture. That's fine, because `test_neuralwatt_runtime.py:43` guards the config itself.
   - The stream test fails if Neuralwatt bookings drop to 0. But Neuralwatt's own cost equals the twin's in this capture, so the test can't tell "max(twin, OpenCode)" apart from "OpenCode's cost". The synthetic control test covers that case.
   - Nit: `test_neuralwatt_budget.py:189` uses `zip`, so if no events were booked the loop passes without checking anything. Assert that the lengths match.
   - The bodies, streams and requests are real (§2 met). The error wrapper is not.
5. **Fixture:** clean. No key or auth headers, generic prompts (`date -u`). Request IDs and session IDs are harmless.

**Nits**
- A revoked key (401) ends every Neuralwatt call as `opencode_error` without telling the router, so the next call will likely pick the same dead key again.
- `retry_strategy.suggested_initial_delay_s` is ignored.

The probe script is at /private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/35da1f8b-8fdf-431c-a84e-d725cb8c71d1/scratchpad/probe429.py. I changed no repo files.

## Elephant response (2026-11-19)

- **Blocking (OpenCode 429 swallowed):** fixed at the shared spot in `budget._run_budgeted`. An OpenCode error event with an HTTP status is terminal, so the one-notice allowance no longer skips it. A status-less "retrying" message keeps the allowance, as `test_budget.test_rate_limit_must_persist_and_tool_text_is_not_a_provider_error` pins. The new `test_a_neuralwatt_429_ends_the_call_as_rate_with_no_phantom_tail` fails without the fix and passes with it. Item 8's text now describes the real mechanism: the pool is blocked for 900-3600 s, the next lease goes to OpenRouter, and the known cost is restated.
- **Strong nit (hand-built wrapper):** taken. OpenCode's real `APIError` event was captured free on the VM with an invalid key and saved in the fixture, and the 402/429 test events are built from it.
- **Nit (zip):** taken. The length is asserted before the loop.
- **Nits (401 not reported to the router; `retry_strategy` ignored):** recorded in item 8, not built. A revoked key shows up as repeated `opencode_error`, and the operator rotates it.
