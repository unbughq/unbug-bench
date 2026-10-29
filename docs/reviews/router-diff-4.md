**Verdict: PASS.** I found no blocking findings. All findings from diff reviews 1–3 are fixed. This review doesn't cover the test suite: the full-suite log for this head was still running when I read it, so merging still has to wait for that run to finish green.

# Router diff review 4: stream A, `3f7521bd..d1ced53d`

This was a read-only goldfish review in `Mode: REVIEW`. I read the `zoom_out` and `implementation_readiness` personas and `implementation-readiness-standard.md`. I read all of `docs/ENGINEERING.md`, `docs/designs/interfaces.md` and `docs/designs/router.md`, then `router-design-6.md` and `router-diff-1.md` to `router-diff-3.md` with their elephant responses. Then I read the full committed diff, focusing on `6120f4b..d1ced53`, along with the code and tests it touches (`budget.py` diagnostics, `model_runtime.call`, `model_router` acquire/`await_lease`, `run.write_provider_wait`, the G10 overlap path). I didn't edit anything, run tests or delegate. I touched no models, cases, workers, secrets or `main`. My only process check was reading `/tmp/router-final-full.log` and running `pgrep`.

## Blocking findings

None.

## Non-blocking findings

**F1. Major: a failure caused by one case's own content, such as a prompt that's too long, now becomes a resumable `outage` wait instead of stopping the case.**
- **Where:** `factory/model_runtime.py:280-283`, where label-only failures are marked `per_call` with reason `outage`. Then `model_router.await_lease`, where `exhausted` sets `deferred` and the wait becomes a `ProviderWait`.
- **Why:**
  - A label-only failure (`claude_error` such as "prompt too long", `codex_error` such as context overflow, `process_error`) now excludes only its lane. That part is correct: no shared health block, and the second Claude account is tried.
  - Once every lane is excluded, though, the flag-on path writes a `provider_wait` with reason `outage`, and B relaunches it.
  - At the base commit these labels stopped the case, and auto-resume never retried them ("failures/caps never").
  - The same content fails the same way after each relaunch. A case-content failure therefore uses B's relaunch cap and infra-waste spend, plus one invocation per account per relaunch. It reaches the diagnosis agent only as `provider_wait_unrecoverable`.
  - The design (`router.md:464-465`, "per-call outage evidence") and the original approved design ("nonzero exit is outage") both allow this. So it is not an A contract violation, and B's cap bounds it.
- **Action:** don't change A. Record in `router.md` or as a B/D follow-up that label-only exhaustion is a case/factory-bug stop candidate, not a provider condition. Alternatively, have B count repeated label-only outage relaunches of the same case toward the diagnosis threshold.

**F2. Minor: the shared Codex expiry rule includes a loose pattern, and a block it creates never clears on its own.**
- **Where:** `factory/budget.py:367-376`. The clause `('401' in text and ('unauthorized' in text or 'authentication' in text))` now raises a **shared** `credential_expiring`, with no `per_call`.
- **Why:**
  - The brief and `router.md:347-349` describe trusted metadata as "the CLI's exact Codex login-expiry diagnostics".
  - The refresh-token, `workspace routing discovery unauthorized` and `authentication token has expired` phrases are exact. The generic 401 clause isn't.
  - The guard `not response` keeps assistant prose out. That's correct, and it means only non-JSON lines and `turn.failed`/`error` messages can reach this clause.
  - A shared `credential_expiring` block clears only through B's healthy `observe`. One false positive would block Codex for every case until B's next renewal receipt.
  - I found no current source of non-CLI 401 lines (MCP servers are stripped from `config.toml`), so this risk is narrow.
- **Action:** keep the generic 401 clause `per_call`, and give shared scope only to the exact phrases. Or record this as accepted, relying on B's renewal observe to clear it.

**F3. Minor: the test for the Go key-2 fallback injects the failure instead of producing the real Go signal.**
- **Where:** `tests/factory/test_model_router.py:569`, `test_per_call_quota_keeps_other_subscription_account`.
- **Why:**
  - The test raises a synthetic `provider_failure` marked `per_call`.
  - After this commit, the real Go signal (`silent_limit`, `budget.py:345`) is **shared**. Key 2 is then chosen through the key 1 health block, not through lane exclusion.
  - So the test proves that per-call exclusion keeps key 2, but not the real log-line path. The behaviour is correct as read: `observe(quota)` blocks pool `opencode-go-key`, and the next `_admit` picks key 2.
- **Action:** optionally, drive `budget.run_budgeted` with a timestamped `usage limit exceeded` log line, as `test_silent_limit.py` does, through `runtime.call`, and assert that the next account used is key 2.

**F4. Nit: a Go log line from the previous call can be wrongly charged to the next one.**
- **Where:** `budget.py:345`, `l[10:29] >= started_utc`, which compares at one-second resolution.
- **Why:** the OpenCode log directory is shared by the worker's non-user calls.
  - Suppose key 1's usage-limit line was written in the same second that the immediate key 2 retry started.
  - If key 2 then stays silent for 60 seconds, its check reads that line and blocks key 2 as well, so the call can fall back to paid OpenRouter.
  - The old code already had this problem; only its effect is now shared. The window is under one second.
- **Action:** optional. Use a strict `>`, or record the subsecond start time.

## What happened to each earlier finding

| Review | # | Finding | Now |
|---|---|---|---|
| diff-1 | 1 | Outage from response prose or `api_retry` numbers | **Fixed.** Still holds: `if response: return False` comes before classification, and `api_retry` uses `allow_outage=False`. |
| diff-1 | 2 | Flag off ignored deadlines; uncertain/deferred state never rechecked | **Fixed.** The deadline check is outside the `try` (`model_router.py:404-407`). |
| diff-1 | 3 | Cancelled peer receipts lost; restart rejected `cancelled` | **Fixed.** Unchanged in this commit. |
| diff-1 | 4 | Lost finish never retried | **Fixed.** `_finish_until_known`. |
| diff-1 | 5 | Account order recomputed under the same ID | **Fixed.** `excluded_lanes` is part of the frozen payload, so a retry under the same ID sends the same request. |
| diff-1 | 6 | Refusal blocked the route for everyone | **Fixed.** Refusals are now per lane. |
| diff-1 | 7 | FIFO starvation | **Fixed:** documented. The FIFO check now honours older requests' `excluded_lanes` (`:200`). |
| diff-1 | 8 | Stale Codex auth comment | **Fixed.** |
| diff-1 | 9 | Unknown paid OpenCode model in the free pool | **Fixed.** |
| diff-2 | N1 | Response text with 402/429/quota blocks shared health | **Fixed.** Prose never reaches the classifier. |
| diff-2 | N2 | TLS handshake on the accept loop | **Fixed.** |
| diff-2 | N3 | Stale cancelled entries reused as evidence | **Fixed.** Old card fields are also dropped in `run.opencode` (`run.py:192-193`). |
| diff-2 | N4 | Flag-off refusal waited for nothing | **Fixed.** Exhaustion is now checked per lane (`:382-384`). The test is updated to use the lane key. |
| diff-2 | N5–N7 | Reset docs, `model_lease`, restart comment | **Fixed.** |
| diff-3 | R1 | Label-only errors made batch-wide outage blocks | **Fixed.** Every label-derived failure is `per_call`, so there is no `observe` (`model_runtime.py:282`, `:322`). `test_label_only_budget_errors_leave_peer_capacity_healthy` drives the real budget `turn.failed` and Claude `is_error` events, asserts health stays `{}`, and checks that a peer is admitted. `router.md:190` is corrected. See F1 for the resulting behaviour. |
| diff-3 | R2 | Route exclusion removed both accounts and lost the reason | **Fixed.** Exclusions are pool plus route on client and server (`:184`, `:311`, `:200`). The trusted CLI metadata keeps shared scope: Go log `:345`, `api_retry` `:507`, Codex expiry `:375`. When every lane is excluded, the wait keeps the last reason (`:400`). All three tests named in review 3 are present (`:569`, `:584`, `:602`). The Codex test asserts `credential_expiring` plus `interrupted` in the record and in router health. See F2 and F3. |
| diff-3 | R3 | TLS test had its own server construction | **Fixed.** `Server.enable_tls` is used by both `main()` and the test. |
| diff-3 | R4 | Unbounded slow-header threads | **Accepted.** Documented at `router.md:380-383`. |
| diff-3 | R5 | Old cards keep scratch fields | **Fixed.** `run.py:192-193`. |
| diff-3 | R6 | `provider_routes_exhausted` not described | **Fixed.** Documented as a terminal, non-resumable rollout stop. |

## Contract and scope checks (no findings)
- **Admission API:**
  - `await_lease` is still the only public admission seam, and `_admit` is private.
  - `excluded_lanes` is an internal acquire field and doesn't change interfaces §2.
  - Leases renew every 60 seconds and expire after 180. Every exit calls `finish`, which books nothing. `capacity` counts the exact route only. `observe(healthy=True)` is idempotent per observation ID.
- **Wait record:** the eight public fields, `terminal_stop` and the projection are written together, unchanged. Interrupted evidence still wins.
- **Shared health:** only structured provider fields or the trusted CLI metadata named in `router.md:347-349` reach `observe`. `credit` and `credential_expiring` blocks still never clear on time alone.
- **Edits in other streams' areas:**
  - `launch.sh` has only the auth-copy removal and the `provider_wait` counter guard.
  - The `budget.py` diff doesn't touch subprocess, timeout, kill or selector code (E).
  - No scoring or gate files changed (C). D's settlement and reservations and B's lifecycle are untouched.
- **Murphy rows:** `docs/murphy-register.md` isn't in the diff. Rows 2, 3, 4, 20, 47 and 48 stay OPEN, which is correct.
- **Simplicity:**
  - The fix commit is a net simplification: one helper for TLS, the lane key, and the `per_call` decision in one place.
  - The module is still stdlib only, with no new abstractions.
  - Weeds are acceptable for a diff review.

## Evidence I couldn't judge
- `/tmp/router-final-full.log` was 1.1K at 23:33. It ends at the header `tests/bench/test-launch-guards.py` with no result line.
  - Earlier files (`test-exam-round`, `test-factory-adopt`, `test-fake-pass-rules`, `test-guard-bounds`) passed.
  - The suite process (pid 95704) was still running, and so was a second concurrent suite (pid 83269).
  - This is consistent with your note about the slow launcher simulation, and I don't infer a deadlock.
  - I make **no claim** that the full suite passes at `d1ced53`.
- I didn't run any tests. The 36 router tests and 39 budget tests you report passing are unverified by me.
- B and D behaviour is out of scope.

## Requested before merge
1. A completed, green full-suite log for `d1ced53`, as the user requires.
2. A merge commit with `Reviewed-by:` trailers for `router-design-1..6` and `router-diff-1..4`.
3. A decision on F1–F4: fix or record as accepted. None of them block.

Don't merge or push.

## Elephant response

PASS recorded verbatim. No blocking finding remains. F1–F4 are recorded in
`docs/designs/router.md` under Passing diff-review follow-ups:

- F1 is a B/D diagnosis follow-up; A retains its approved bounded per-call outage.
- F2's non-response CLI-only 401 scope is accepted, with B's renewal observation
  clearing the pool. No current non-CLI source was found and row 20 stays open.
- F3's injected test proves per-call lane exclusion; the existing real-log parser
  test remains separate. Combined Go-log/account-switch lifecycle evidence is
  still required and no row is closed.
- F4's inherited subsecond log-alias risk is accepted for this slice and remains
  part of the open account lifecycle proof.

The parent owns merging and must retain Reviewed-by trailers naming every
router-design-1..6 and router-diff-1..4 review. This branch is not merged or pushed.
Production code is unchanged after reviewed head
`d1ced53d0f196557f26226efb1f3d74ef1e7de9b`. The full suite exposed one stale
test fixture: test_fallback_is_shared_and_billing_is_explicit still used a bare
opencode_error to establish shared health. It now supplies a parser-classified
404, matching the reviewed distinction. All four provider-route tests pass.
That small test correction gets a fresh diff review, and the full suite is rerun.
