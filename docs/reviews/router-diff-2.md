**Verdict: BLOCKED.** Two new blocking findings. All nine findings from review 1 are resolved; finding 1 is resolved for outages only, and new finding N1 is the same bug in a related form.

# Router diff review 2: stream A, `3f7521bd..cb1f6822`

This was a read-only goldfish review in `Mode: REVIEW`. I read the `zoom_out` and `implementation_readiness` personas and `implementation-readiness-standard.md`. I read all of `docs/ENGINEERING.md` and `docs/designs/interfaces.md`, then `docs/designs/router.md`, `router-design-6.md` and `router-diff-1.md`. Then I read the full committed diff and the tests it touches. I didn't run, edit or delegate anything, and I touched no secrets, cases, workers or `main`.

`interfaces.md` §6 already says that with the flag off, explicit caller and batch deadlines still raise `timeout` or `provider_wait_deadline`. So it matches the founder's narrower reading, and nothing there needs updating.

## Blocking findings

**N1. Important: assistant text that mentions HTTP 402 or 429 now blocks the shared wallet or account for the whole batch. A 402 block never clears on its own.**
- **Where:** `factory/budget.py`, in `diagnostic()` (the response check) and `classify_provider_failure`. The resulting `observe` call is in `factory/model_runtime.py`, `ModelRuntime.call`, in the `finally` block.
- **Why:**
  - The fix for finding 1 turned off only the *outage* reason on the response path (`allow_outage=... and not response`).
  - The response check still lets any assistant text through if it contains `\bhttp [45]\d\d\b` or `insufficient credits` anywhere. That covers OpenCode `text`, Codex `agent_message` and Claude `result`.
  - `classify_provider_failure` then searches that text:
    - `\b402\b` gives `credit` with scope `wallet`;
    - `\b429\b` or `rate limit` gives `rate`;
    - `usage limit` or `limit reached` gives `quota`.
  - Because the call was invoked and this is not a refusal, the runtime calls `observe(reason='credit')` on the lease's pool.
- **Impact:**
  - A writer or reviewer on a bug case saying "the handler returns HTTP 402 Payment Required" blocks `openrouter-key` for every case.
  - Credit blocks are cleared only by B's `observe(healthy=True)`, and B isn't merged yet.
  - Text mentioning `HTTP 429` blocks the account's pool batch-wide for at least 15 minutes. On OpenRouter this happens at the first occurrence; elsewhere at the second.
  - Before this diff, the same text only stopped that one case.
  - The new test `test_assistant_http_prose_and_retry_metadata_are_not_outages` checks only 404 and 500.
- **Action:**
  - Only structured provider error events (error, failed-turn or error-result events) may produce a shared health `observe`.
  - A response-path match must stay case-local: treat it as per-call (`per_call`), or keep the old case stop with no `observe`.
  - Add negative tests through the real budget subprocess: response text containing "HTTP 402", "insufficient credits" and "HTTP 429" on all three drivers. None may write a pool health block.

**N2. Important: one TCP client that never finishes the TLS handshake stops all admission.**
- **Where:** `factory/model_router.py:511-514`, `main()`: `context.wrap_socket(server.socket, server_side=True)` followed by `serve_forever()`.
- **Why:**
  - With the default `do_handshake_on_connect=True`, `SSLSocket.accept()` does the TLS handshake on the `serve_forever` thread, before `ThreadingHTTPServer` hands the connection to a worker thread.
  - The accepted socket has no timeout. `Handler`'s `settimeout(5)` runs only inside `do_POST`, after the handshake.
  - The service binds `0.0.0.0:8765`. A port scanner, or a worker that stalls mid-connect, blocks `accept()` for as long as it likes. Every other acquire, renew and finish then times out at 5 seconds.
- **Impact:**
  - Every worker raises `router_unavailable`. Running calls lose their renewal and are cancelled.
  - systemd doesn't restart the service, because it hasn't crashed.
  - The design promises that a router outage produces a *bounded* `provider_wait`. Here a trivial trigger makes the outage open-ended, and B's 10-relaunch cap turns it into `provider_wait_unrecoverable`.
  - No test covers the TLS server path.
- **Action:**
  - Wrap with `do_handshake_on_connect=False` and do the handshake in the handler thread under a timeout, or set a socket timeout before the handshake (for example with `Handler.timeout`).
  - Add a loopback TLS test with a self-signed certificate: an idle raw TCP connection must not delay a concurrent `capacity` RPC.

## Non-blocking findings

**N3. Minor: old cancelled-call entries can be wrongly treated as interrupted evidence later.**
- **Where:** `model_runtime.py`, `call`, where it appends to `router_interrupted_calls` when `cancelled and invoked`; and `run.py`'s `write_provider_wait`.
- **Why:**
  - Any cancellation, including an operator pause or a watchdog, appends an entry, whether or not a provider wait is involved.
  - Only `write_provider_wait` removes entries, so they stay on the card and in later checkpoints.
  - A later, unrelated provider wait then marks itself `interrupted` using `interrupted[0]['lease_id']` from an earlier generation. D matches `lease_id` against `repair_pending`/`review_pending`, so it would treat a wait that was really denied before work as a crash, or the other way round.
- **Action:** record an entry only when a provider or router condition caused the cancellation, or clear the list at each logical-call boundary. Don't persist `router_waits` and `router_interrupted_calls` on the public card when they're empty.

**N4. Minor: with the flag off, a refusal can wait a long time for nothing.**
- **Where:** `model_runtime.py`'s refusal exclusion together with `model_router.await_lease`; the 7-day default is in `_deadlines`.
- **Why:**
  - A refusal excludes its route for that logical call. If it was the only route (for example `codex/...`), every later acquire returns `outage` and can never succeed.
  - With the flag off, there's no 60-second exit. With no caller deadline and no `FACTORY_BATCH_DEADLINE`, the worker heartbeats for up to 7 days, and the watchdog sees that as progress.
  - Before this diff, a refusal stopped the case.
  - No batch may run with the flag off, which is why this is minor.
- **Action:** with the flag off, raise straight away when the call has no candidate route left that isn't excluded.

**N5. Nit: Claude reset delay in `restart.plan`.** The 6-hour cap is gone, and a past `claude_resets_at` now waits 17 minutes instead of 60 seconds. A far-off weekly reset now fails with "insufficient time" instead of retrying. This may be intended (the design reuses the router's reset calculation), but `router.md` should say so.

**N6. Nit: `c.model_lease` is shared between concurrent calls.** In `call`, `c.model_lease = lease` is written to the shared case object, so concurrent peers overwrite each other. No current `before_attempt` reads it: the one caller, `run.py:1785`, only deletes a file. D passes `lease=` directly. Expose it on `context` only, or document that it's only reliable for serial calls.

**N7. Nit:** `restart.plan` skips `ledger_agrees` entirely for `provider_wait` and relies on the new allowlist instead. That's acceptable, but add a one-line comment saying why.

## What happened to each review 1 finding

| # | Finding | Now |
|---|---|---|
| 1 | Critical: outage from response text and `api_retry` numbers | **Fixed for outage.** Outages now need a structured `status_code`/`error_type`, `api_retry` is passed with `allow_outage=False`, and the new test drives the real budget path. **The same bug remains for credit, rate and quota (N1).** |
| 2 | Flag off ignored deadlines, and `router_uncertain`/`deferred` were never re-checked | **Fixed.** The deadline check is outside the `try` (`model_router.py:401-404`). With the flag off, admission and the credential check re-run on every poll. A successful `status` clears `router_uncertain`. Tests added. |
| 3 | Cancelled peers lost their receipts; restart rejected the ledger's `cancelled` | **Fixed.** Receipts are unioned and interrupted evidence wins, and `restart.plan` allows `cancelled` only for `provider_wait`. The test uses the real `_run_budgeted` path. N3 is a remaining edge case. |
| 4 | Lost finish acknowledgement never retried | **Fixed.** `_finish_until_known` retries with the same lease and receipt, bounded by 60 seconds with the flag on and by the deadlines with it off. |
| 5 | Account order changed under the same ID | **Fixed.** Order is set once per ID, and regenerated together with the ID only on the flag-off credential path. |
| 6 | One refusal blocked the route for everyone | **Fixed.** Refusals are now per call (`per_call`, `router_excluded` on the call's own context), with no `observe`. See N4. |
| 7 | Strict first-come ordering can starve requests | **Fixed:** documented in `router.md`. |
| 8 | Stale Codex auth comment | **Fixed.** |
| 9 | Unknown paid OpenCode model in the free pool | **Fixed:** it now uses the Go account pools. |

## Contract and scope checks (no findings)
- **Admission API:** `await_lease` is the only public admission call, and `_admit` is private. Renewal is every 60 seconds, leases expire after 180, and every exit path calls `finish`. `capacity(route)` counts the exact route only. `observe(pool, healthy=True, observation_id=...)` is idempotent. All of this matches `interfaces.md` §2 and §7.
- **Wait record:** the fields match §3 exactly. The card copy holds only the eight public fields and is set in the same write as `terminal_stop`. An unsettled record raises `provider_wait_unsettled` and is archived only after settlement.
- **Edits in other streams' areas stay minimal:**
  - `launch.sh`: the auth copy is removed, and a `provider_wait` stop doesn't add to `.autoresumes`.
  - `restart`: `provider_wait` is exempt from the three-restart limit.
  - `g11_review`: one call to the shared record writer.
  - `account_handoff`: no more blacklist; it only carries the account the router chose. Claude is limited to labels 1 and 2, so the exam account is never used. The router's account list also leaves it out.
  - D's reservation and settlement logic and B's lifecycle are untouched.
- **Simplicity:** the module is stdlib only. The duplicate `family()`, `PROVIDER_ROUTES`/`FREE_FALLBACK` and the coordinator's quota scheduling are deleted.
- **Murphy rows:** `docs/murphy-register.md` isn't touched. Rows 2, 3, 4, 20, 47 and 48 stay open, which is correct.

## Evidence I couldn't judge
- `/tmp/router-rebased-full.log` ends at the header `tests/bench/test-launch-guards.py` with no result line, so the full suite was incomplete when I read it. I make no claim about full-suite status at `cb1f682`.
- I didn't check B's or D's behaviour, as the brief asked.

## Requested before merge
Fix N1 and N2, each with the tests named above. Then attach a completed full-suite log for the fixed head, and run a fresh diff review.

## Elephant response

All findings accepted; none rejected.

- N1: normal responses never establish provider health. Only structured provider
  errors create shared observations; unstructured CLI diagnostics are per-call.
  The real budget subprocess test now includes HTTP 402, insufficient credits,
  HTTP 429 and quota prose on all three drivers as well as 404/500 and api_retry.
- N2: TLS handshakes run in handler threads under a five-second timeout.
  `test_idle_tcp_client_does_not_block_tls_capacity` uses a loopback TLS server
  and a self-signed certificate, holds an idle raw connection and completes a
  concurrent authenticated capacity request within two seconds.
- N3: wait/peer lists are transient context attributes, shared by shallow role
  copies, rather than checkpointed public-card fields. Old card scratch is
  discarded. `test_old_cancelled_receipts_are_not_checkpointed_or_reused` proves
  an old generation cannot turn a denied wait into interrupted evidence.
- N4: flag-off admission raises provider_routes_exhausted immediately once no
  unexcluded route remains. Tested by
  `test_flag_off_exhausted_refusal_routes_do_not_wait`.
- N5: the design documents expired/far-future reset behavior on legacy restarts.
- N6: the design documents model_lease as a serial callback convenience;
  concurrent code passes its Lease explicitly.
- N7: restart now explains why provider_wait uses its allowlist instead of
  ordinary ledger-stop equality.

The full suite is rerun for the fixed code and another fresh diff review follows.
All assigned Murphy rows remain open.
