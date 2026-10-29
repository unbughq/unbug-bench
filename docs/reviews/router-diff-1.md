**Verdict: BLOCKED.** Three of the findings below block the merge.

I did a read-only review of `ff5ed1a..447795b`. I read both reviewer roles, `docs/designs/router.md`, `docs/reviews/router-design-6.md`, the full diff and the tests it touches. I didn't run, compile or change anything. I read only the parts of `docs/ENGINEERING.md` and `docs/designs/interfaces.md` that `router.md` quotes, not the whole files.

## Blocking findings

**1. Critical: normal assistant text that mentions an HTTP error now kills the call and blocks the route for the whole batch**
- **Where:** `factory/budget.py`, in `classify_provider_failure` (the `\b(?:404|5\d\d)\b` check) and in `diagnostic()` (the `response` check followed by the call to `classify_provider_failure`).
- **Why:** On the response path, the check `\bhttp [45]\d\d\b` lets any final assistant message through if it contains "HTTP 404" or "HTTP 500". That covers Claude `result` text, Codex `agent_message` text and OpenCode `text` parts. `classify_provider_failure` then labels it `outage`, and the code raises `BudgetError('process_error')`. Before this change, the same text returned `False`. This is a bug benchmark, so writers and reviewers often say "the endpoint returns HTTP 500". The freshness reviewer's whole output is about HTTP 404s, and `tests/factory/test_freshness_archive.py:37` has exactly that text. The result is a finished call marked interrupted, and an `observe(outage)` that blocks `pool/route` for every worker for 15 to 60 minutes.
- **A second way in:** Claude `system/api_retry` events are passed through `json.dumps`, and the 5xx regex matches numbers inside them, such as `"retry_delay_ms": 500` or `"error_status": 529`. A transient overload that the Claude CLI was already retrying now aborts the call.
- **Action:** Match outages only on structured fields, such as an HTTP status field or the error type. Never apply the 404/5xx rule to response prose. Add negative tests: response prose containing "HTTP 404" and "HTTP 500", and an `api_retry` event with `retry_delay_ms: 500`. All three must not raise.

**2. Important: with the rollout flag off (the default), `await_lease` can wait forever and ignores the caller's deadline**
- **Where:** `factory/model_router.py`, `await_lease`, in the `while True` loop.
- **Why:**
  - When `stop_at` passes, the code raises `RouterUnavailable('admission deadline')`. The `except RouterUnavailable` in the same loop catches it and turns it into another wait. With `UNBUG_PROVIDER_WAIT=0`, nothing ever leaves the loop.
  - `router_uncertain` (set after a lost renew or finish) and `deferred` (set when a credential is missing) are never re-checked. So the loop never calls `_admit` again, even after the router recovers or B installs the credential.
  - The loop keeps touching `.router-wait`, so the watchdog treats the worker as making progress.
  - So a lost finish acknowledgement, a lost renewal, or a missing Codex RAM file leaves the worker stuck for good. The design expects the missing Codex file until B ships. This breaks the design's rule "Never sleep beyond … caller deadline …".
- **Action:**
  - Check `stop_at` outside the `try`, and raise a fixed `BudgetError` (`timeout` or `provider_wait_deadline`) even when the flag is off.
  - When the flag is off, re-run `_admit` and the credential check on each poll instead of reusing the deferred wait.
  - Clear `router_uncertain` once a status, cancel or finish RPC succeeds.
  - Add flag-off tests for: a passed caller deadline, a lost finish, and a credential that appears mid-wait.

**3. Important: wait records written after a cancel can't be resumed, and they drop usage from interrupted calls**
- **Where:**
  - `factory/model_runtime.py`, `call` (the `if not failure: raise` line)
  - the `opencode` wrapper in `factory/run.py`
  - the `provider_wait` ledger-stop allowlist in `factory/restart.py` `plan`
- **Why:** When a lease renewal is lost, the running CLI is cancelled through `role_cancel`. Any concurrent peer sharing that `role_cancel` is cancelled too. `_run_budgeted` then writes `terminal_stop='cancelled'` into the ledger. The `provider_wait` branch of `restart.plan` doesn't list `cancelled`, so it raises "provider wait cannot override a non-provider ledger stop". I worked this path out from the code but didn't confirm it end to end; please check that `budget` in `plan` is the same cumulative ledger.

  In the peer case there is a second problem. The cancelled peer's per-lease receipt is written, but it is never added to `router_waits`. Only a `ProviderWait` adds to that list. So the final record can say `denied_before_work` with `call_id=None` while another call was really interrupted. That breaks the design's "interrupted evidence wins" rule and its "union of per-lease receipts" rule, which D depends on.
- **Test gap:** `test_renewal_failure_cancels_and_defers_without_fallback` mocks `_invoke`, so the ledger never gets `cancelled`. `test_concurrent_wait_merge_keeps_all_usage_receipts` builds `router_waits` by hand.
- **Action:**
  - Record every lease that was invoked and then interrupted in `router_waits`, including `cancelled`.
  - Allow `cancelled` in `plan` when the card stop is `provider_wait`.
  - Add a test that drives the real `_run_budgeted` cancel path through to `restart.plan`.

## Non-blocking findings

4. **Minor: a lost finish is never retried** (`model_runtime.py`, the `finish` call in `call`'s `finally`). The design says to retry with the same ID before the next attempt. Instead the code waits for the 180-second expiry. The server then records `expired` with no receipt path, so the router's own status loses the evidence. The receipt does survive through the wait record. **Action:** retry `finish` within the 60-second wait window, or record this deviation in `router.md`.

5. **Minor: a retried acquire can be rejected as a changed request** (`model_router.py`, `_admit` sorting accounts by `(SECRETS / a).is_file()`). The account order is recomputed on every retry under the same attempt ID. If a credential file appears or disappears mid-wait, the request differs, the server returns "attempt id changed" (HTTP 400), and that ID stays stuck in `RouterUnavailable`. **Action:** fix the account order once per `await_lease`.

6. **Minor: one case's refusal blocks the route for everyone** (`model_runtime.py`, `refusal:` → `outage`). A refusal is triggered by one case's content, but the code records it as a route-wide health block across the batch. One case's Codex cybersecurity refusal then stops Codex for every case for 15 to 60 minutes. Treating a nonzero exit as an outage is what the design asked for; extending that to refusals wasn't. **Action:** keep refusal handling per call or per case, or get the design owner's agreement.

7. **Nit: strict first-come ordering can block requests that could be served.** The "older" check in `acquire` holds back a newer request if any older request could use the same pool, even when the older one will be served by a different pool. It is conservative and correct, but it can starve requests. Note it in the design.

8. **Nit: stale comment.** `model_runtime.py:375` still says `~/.codex/auth.json` is "pushed by launch.sh". That copy was removed in this diff.

9. **Nit: wrong pool for unknown models.** An unknown `opencode/<paid model>` is given `pool='opencode-free'` with `billing='paid'`, which mislabels its shared-capacity pool.

## Tests that are missing (counted against findings 1 to 3)
- No negative parser tests for response prose or `api_retry` events (finding 1).
- No flag-off tests for a passed deadline, `router_uncertain` or `deferred` (finding 2).
- No test of the real budget cancel path through to `restart.plan`, and no test of a concurrent peer's receipt being kept (finding 3).

## A interfaces that may get in the way of B or D
- `coordinator.decision` now always returns `account_id=None` and `selected={}`. B's launch path has to tolerate that and take the account from the router or the `provider_wait` projection. I didn't check whether it does today.
- `account_handoff.choose` only acts when `terminal_stop == 'provider_wait'`. Any account change B makes for other stops has to go through the router.
- Neither of these blocks B or D, but B should know about both.

## B and D behaviour I did not judge
- **D:** reservation, settlement and allowance integration. That covers deduplicating usage-receipt event IDs, settling and archiving `provider_wait.json`, moving writer `repair_pending` and stress reservations behind `before_attempt`, and exemption counting.
- **B:**
  - Lifecycle: the timer and dispatch of pending waits, and the authenticated collect → retire → relaunch at `retry_after`.
  - Router startup, plus delivering the token, certificate and RAM credentials.
  - Codex renewal and access-token delivery (row 20).
  - Healthy `observe` calls after a renewal or top-up.
  - Whether `launch.sh` / `factory_auto_resume` passes provider-wait cards into `restart.plan` correctly.
  - Capacity tuning.
- **Murphy rows:** 2, 3, 4, 20, 47 and 48 stay open, as you said. I didn't judge whether they can close.

I didn't merge or push anything.

## Elephant response

All findings accepted; none rejected. The founder clarified that flag-off
waiting suppresses only the 60-second provider_wait exit, never hard deadlines.

1. Structured provider diagnostics replace response-prose outage detection.
   `test_assistant_http_prose_and_retry_metadata_are_not_outages` drives the real
   budget boundary for Claude, Codex and OpenCode plus api_retry metadata.
2. Flag-off hard deadlines escape the polling loop. Missing credentials and
   recovered RPCs are rechecked; uncertain finish is retried idempotently without
   another invocation. Covered by `test_flag_off_deadlines_and_credentials_that_appear`
   and `test_flag_off_finish_retries_without_repeating_work`.
3. Cancelled invoked peers retain receipts and interrupted evidence; provider-wait
   restart accepts the cumulative ledger's cancelled stop. Covered through real
   `_run_budgeted` cancellation by
   `test_real_budget_cancel_peer_receipt_survives_into_restart`.
4. Finish retries use the same lease/receipt within the provider-condition window.
5. Account order is frozen per request ID. Covered by
   `test_lost_acquire_keeps_payload_frozen_when_files_change`.
6. Refusal exclusions are per logical call, never shared health. Covered by
   `test_refusal_does_not_block_other_cases`.
7. Conservative FIFO utilization limitation is documented in the design.
8. The stale Codex auth-copy comment is removed.
9. Unknown paid OpenCode models use Go account pools. Covered by
   `test_unknown_paid_model_uses_paid_account_pool`.

Additional checks retain a supplied lease when initial renewal fails before
execution and reject a second reviewer from the writer/stress family. All 29
router regressions pass. Full-suite evidence and fresh diff review follow on
the rebased branch. No Murphy row is closed by these unit tests.
