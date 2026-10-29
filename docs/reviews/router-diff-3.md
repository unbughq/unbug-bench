**Verdict: BLOCKED.** Two new blocking findings. Both come from the review 2 fix: case-local errors still reach shared health, and the new per-call route exclusion turns off account switching. The fix for N2 (TLS handshake) is correct. N3–N7 are resolved.

# Router diff review 3: stream A, `3f7521bd..6120f4bf`

This was a read-only goldfish review in `Mode: REVIEW`. I read the `zoom_out` and `implementation_readiness` personas and `implementation-readiness-standard.md`. I read all of `docs/ENGINEERING.md` and `docs/designs/interfaces.md`, then `docs/designs/router.md`, `router-design-6.md`, and `router-diff-1.md` and `router-diff-2.md` with their elephant responses. Then I read the full committed diff, focusing on `cb1f682..6120f4b`, along with the code and tests it touches. I didn't edit, run tests, or delegate. I touched no cases, models, workers, secrets or `main`. My only process check was `pgrep`/`stat` on the suite log.

## Blocking findings

**R1. Important: errors that carry only a label still create batch-wide outage blocks, so one case's content can block a route for every case.**
- **Where:** `factory/model_runtime.py:280-283`, the label fallback, together with the `observe` call in `finally` (`:322-327`). The labels come from `factory/budget.py`:
  - `turn.failed` raises `codex_error` (`:441`);
  - Claude `result.is_error` raises `claude_error` (`:474`);
  - a nonzero exit raises `process_error` (`model_runtime.py`, the `if code:` line).
- **Why:**
  - When an error has no `provider_failure`, the runtime maps `codex_error`, `claude_error`, `opencode_error` and `process_error` to `outage`. It doesn't mark these `per_call`.
  - So the runtime calls `observe(reason='outage')`, which blocks `pool/route` for 15, then 30, then 60 minutes.
  - These labels need no provider evidence. A Codex `turn.failed` for context-window overflow, a Claude `is_error` result such as "prompt too long" or max turns, or an OpenCode crash on case input all qualify.
  - This contradicts the rule the N1 fix established and `router.md:345-346` now states: "All shared health observations require structured provider errors." The same design still says "Nonzero CLI exit is outage observation" (`:190`), so the design contradicts itself.
- **Impact:**
  - Codex has one account and one pool. One case that keeps overflowing Codex's context blocks Codex for every case.
  - Each retry of that case runs into the same content, re-blocks the route, and raises `failures`, so the block grows to 60 minutes.
  - With the flag off, that case keeps waiting and retrying until its deadline. With the flag on, B relaunches it up to 10 times. Either way the block repeats.
  - Before this diff, a `codex_error` stopped only that case.
- **Action:**
  - Mark label-only failures `per_call`, with no `observe`. Shared health should come only from a `provider_failure` built from structured evidence.
  - Fix `router.md:190` to match `:345`.
  - Add a test: a real-budget `turn.failed` with a non-provider message, and a Claude `is_error` result. Neither may write a pool health block, and a peer case must still be admitted.

**R2. Important: excluding a route for one call now also excludes the account fallback on that route, and a per-call `credential_expiring` loses its reason.**
- **Where:**
  - `factory/model_runtime.py:285-286`: `router_excluded += lease.route` for every `per_call` failure. Before this commit, only refusals were excluded.
  - `factory/budget.py`:
    - `diagnostic(... shared=False)` default and the `per_call` tagging (`:384`);
    - `silent_limit` (`:346-347`);
    - the `system` events (`:508`);
    - the `codex_login_expired` branch for non-JSON lines (`:376-377`, `:492`).
  - `factory/model_router.py`: the server-side `excluded_routes` filter (`:183-184`) and the no-choice `outage` wait (`:214`).
- **Why:**
  - Exclusion uses the route string only. Both Claude accounts serve the same `claude/<model>`, and both Go keys serve the same `opencode-go/<model>`. Excluding the route therefore removes the second account as well.
  - The fix for N1 also made these failures `per_call`. They are the real diagnostics the CLIs emit, not model text:
    - the OpenCode Go `usage limit exceeded` log line (the 2026-10-19 failure that `test_silent_limit.py` covers);
    - Claude `system/api_retry` events with `error_status` 429; the second one raises `provider_limit`;
    - Codex login expiry on plain lines, such as "Failed to refresh token…" and "workspace routing discovery unauthorized (401)". These are the real messages in `test_codex_login_rotation.py:132`.
- **Impact, against the brief** ("Claude 2 accounts with same-family fallbacks, shared health"):
  - **Go quota on key 1:**
    - Key 2 is never tried.
    - A chained model falls back to paid OpenRouter, so money is spent while a subscription key is free.
    - An unchained Go model, with the flag off, stops at once as `provider_routes_exhausted`.
    - No shared cooldown is recorded, so every other case hits the exhausted key 1 again, each hanging until the log check (up to about 60 seconds).
  - **Two Claude `api_retry` 429s,** which the Claude CLI was itself retrying, exclude both Claude accounts. With the flag off the case stops as `provider_routes_exhausted`, a stop that no restart allowlist accepts. With the flag on it becomes an `outage` provider wait.
  - **Codex login expiry on a plain line:**
    - With the flag off, it stops as `provider_routes_exhausted`.
    - With the flag on, the route is excluded, so the server has no choices and returns `outage` (`:214`). `await_lease` then replaces the reason, so the record says `outage` instead of `credential_expiring`.
    - B's renewal and healthy-observe path (interfaces §2, row 20) is keyed on the wrong reason, and the case relaunches every 15 minutes into the 10-relaunch cap.
    - This breaks the design table at `router.md:179` (`codex_login_expired`: `credential_expiring`, scope account).
- **Action:**
  - Exclude by pool and route (`lease.pool + '/' + lease.route`), or account plus route, and filter on that on the server. Then a per-call failure on one account still lets the router try the other account on the same route.
  - Keep a `credential_expiring` reason through to the record when the route is excluded. One option is to classify the CLI's own login-expiry lines as shared, since they are CLI metadata and not model output. Another is to carry the last reason when the router has no choices left.
  - Decide in `router.md` whether trusted CLI metadata counts as structured provider evidence. That covers the Go log line and Claude's `api_retry` `error_status`. If it does, restore shared observations for them.
  - Tests:
    - a per-call Go quota on key 1 admits key 2 within the same logical call;
    - two `api_retry` 429 events switch to the second Claude account;
    - a plain-line Codex expiry produces a `credential_expiring` record with the flag on.

## Non-blocking findings

- **R3. Minor: the TLS test builds its own server instead of using `main()`.** `test_idle_tcp_client_does_not_block_tls_capacity` sets up its own copy of the wrap with `do_handshake_on_connect=False`. Dropping that flag in `main()` wouldn't fail the test. **Action:** move the server construction into a small helper that `main()` and the test both call, or patch `main`'s inputs. The behaviour itself is correct:
  - `SSLSocket.accept()` inherits the flag;
  - the handshake runs in the handler thread under the 5-second timeout;
  - a failure is swallowed by `handle_error` and the connection is closed.
- **R4. Nit: TLS connection threads are unbounded.** A client that sends headers slowly keeps one daemon thread per connection, because the 5-second timeout applies to each read, not to the whole request. It no longer blocks admission. Note it as accepted if wanted.
- **R5. Nit: old cards keep scratch fields.** Old cards still carrying `router_waits` or `router_interrupted_calls` are cleaned only inside `write_provider_wait`. The fields are never read again, so they are only public-card noise until the next provider wait. You could drop them when the card loads.
- **R6. Nit: the N4 stop loses the refusal label.** `provider_routes_exhausted` (flag off) replaces the earlier `refusal:<model>` stop. `restart.py:95` lists `refusal:` but not the new label, and nothing else consumes it. That's acceptable while no batch runs with the flag off, but the design should name it as a terminal, non-resumable stop.

## What happened to each review 2 finding

| # | Finding | Now |
|---|---|---|
| N1 | Response text containing 402, 429 or quota prose blocks shared health | **Fixed for assistant text.** `diagnostic` returns `False` for any response, and the real-budget test covers 402, credits, 429, quota prose, 404 and 500 on all three drivers, plus `api_retry` 529. **Two related defects remain:** label-only errors (R1), and per-call failures turning off account switching (R2). |
| N2 | A stalled TLS handshake blocks the accept loop | **Fixed** (`model_router.py:486-489`, `:520`). There is a loopback test; see R3. |
| N3 | Stale cancelled-call entries reused as evidence | **Fixed.** The lists are in-memory `Ctx` attributes shared by shallow copies. They are cleared and dropped from the card in `write_provider_wait`, and there is a test. |
| N4 | A refusal with the flag off waits for nothing | **Fixed** (`await_lease:381-383`, with a test). See R6. |
| N5 | Claude reset in `restart.plan` | **Fixed:** documented at `router.md:371-375`. |
| N6 | `c.model_lease` shared between concurrent calls | **Fixed:** documented at `router.md:363-365`. |
| N7 | `restart.plan` skips `ledger_agrees` without saying why | **Fixed:** comment at `restart.py:97-98`. |

The review 1 findings stay fixed, as review 2 confirmed. I found no regression in them, apart from the new R1 and R2.

## Contract and scope checks (no findings)
- **Admission API:** `await_lease` is the only public admission call, and `_admit` is private. Renewal is every 60 seconds and leases expire after 180. `finish` returns outcomes and books nothing. `capacity` counts the exact route only. `observe(healthy=True)` is idempotent. All of this is unchanged and matches interfaces §2 and §7.
- **Wait record:** the fields and the eight public card fields are unchanged. The record is set in the same write as `terminal_stop`.
- **Edits in other streams' areas stay minimal:**
  - `launch.sh`: the auth-copy deletion and the counter guard are unchanged.
  - E's `sh()` subprocess helper and C's scoring are untouched.
  - D's reservation and settlement logic and B's lifecycle are untouched.
- **What I counted as B/D work, not A defects:** healthy `observe` after renewal or top-up, relaunch caps and journal, `settle()`, real-402 evidence, and `provider_wait_deadline` import. Rows 2, 3, 4, 20, 47 and 48 are correctly still OPEN, and `murphy-register.md` isn't touched.
- **Simplicity:** this commit adds no new abstractions, and it's still stdlib only.

## Evidence I couldn't judge
- `/tmp/router-diff2-fixed-full.log` was 1,128 bytes and last written at 23:18:04. It ends at the header `tests/bench/test-launch-guards.py` with no result line. At 23:24 the suite process was still running.
- That is the same place the review 2 log (`/tmp/router-rebased-full.log`) stopped. A separate full-suite run from another worktree was running at the same time.
- So I make **no claim** about the full suite at `6120f4b`. If `test-launch-guards.py` keeps stalling there, check whether it is slow, deadlocked, or slowed by the concurrent run.
- I ran no tests, so I can't confirm the 32 router and 39 budget test passes the elephant reported.

## Requested before merge
Fix R1 and R2, each with the tests named above. Attach a completed full-suite log for the fixed head, then run a fresh diff review. Don't merge or push.

## Elephant response

All findings accepted; none rejected.

- R1: label-only errors are per-call. Only parsed provider failures or explicit
  trusted CLI metadata may update shared health. The contradictory nonzero-exit
  design sentence is corrected. `test_label_only_budget_errors_leave_peer_capacity_healthy`
  drives real budget failed-turn and Claude error-result events, then admits a
  peer with no health block.
- R2: exclusions identify pool plus route, retaining a second account on the
  same route. Exhaustion preserves the last condition's reason. Trusted metadata
  is explicitly defined to include Go's timestamped usage-limit log, Claude's
  retry rate-status event and exact Codex login diagnostics. Tests:
  `test_per_call_quota_keeps_other_subscription_account`,
  `test_claude_retry_metadata_switches_shared_account`, and
  `test_plain_codex_expiry_preserves_renewal_reason`.
- R3: the service and TLS test now call the same `Server.enable_tls` method.
- R4: the daemon-thread/per-read timeout ceiling is documented as an accepted
  batch-network availability risk.
- R5: the wrapper drops obsolete public-card scratch before admission.
- R6: provider_routes_exhausted is documented as terminal and non-resumable
  while the rollout flag is off.

The completed full-suite output and next independent diff verdict follow.
All Murphy rows remain open; no merge or push is performed.
