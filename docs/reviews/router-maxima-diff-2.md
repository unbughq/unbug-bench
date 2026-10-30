# Router maxima diff review 2

**Reviewer:** a fresh goldfish from a different model family than the author. Read-only. Personas: `zoom_out` and `implementation_readiness`, `Mode: REVIEW`.
**Scope:** frozen HEAD `d6e1f80bc9343b32766592eb4edd54ee7dd58e97` against base `a3bb9dc`. I looked hardest at the diff-1 fixes in `de33c1b..d6e1f80`.
**Read before the code:** the egm `zoom_out` and `implementation_readiness` agents and their standards; the founder's current `ENGINEERING.md`; `docs/murphy-register.md`; `docs/factory-single-path.md`; the router.md follow-up and interfaces §§2/3/4/7; design reviews 2–4 and their responses; diff-1 in full, with its author response.
**What I did not do:** edit files, compile, run tests, or launch anything.

## Verdict: code PASS. 0 Blockers, 0 Majors, 3 Nits. Full-suite validation is still pending.

Merging still needs the final full suite on `d6e1f80` to pass (ENGINEERING step 4). When I last checked, `/tmp/router-maxima-full-d6e1f80.log` had reached 7 test scripts with no failures. `/tmp/router-maxima-full-d6e1f80.json` did not exist yet. **I make no claim that the full suite passes.** The author must add the final metadata here. If any script fails, this verdict becomes FAIL until it is fixed and reviewed again.

---

## M1 (diff-1 Major): fixed and verified

**Where:** `factory/model_call_gate.py:151-174`, `Allowance.reserve`.

**How admission now works:**
- **Terminal test.** It checks settled + retained (unknown) + W + headroom. Settled and retained only ever grow, so once this test fails it can never pass again. Exhaustion is then genuinely permanent: the gate sets it, wakes every waiter and returns.
- **Forwarding test.** This still checks settled + held (retained + active) + W + headroom, the same as before. Nothing is forwarded unless every dollar and token inequality fits under the lock. The money guarantee from diff-1 is unchanged.
- **Waiting.** If the only reason a request does not fit is active allowances, it waits on `Condition(self.lock)`. Each wait lasts at most `min(.05, remaining)`. The waiter checks again every time it wakes, so early wakeups are harmless and parent cancellation is noticed within 50 ms. The parent cancel is not a Condition, so it has to be polled.

**Wakeups:**
- `finish` and `close` call `notify_all` under the lock.
- `close` sets `closed` before notifying, so waiters return `None` without setting exhaustion.
- The deadline is the gate's fixed monotonic deadline, passed in from `Gate.__init__`.
- `Gate.close`: `state.close()` wakes the waiting handler threads before `server.shutdown()` runs.

**Races I checked:**
- **Exhaustion while others wait.** The waiter that sets exhaustion wakes the others. They leave through `is_set()` and get `model_call_cap`.
- **Validated finish while waiting.** The waiter re-runs both tests and forwards only if they fit.
- **Unknown finish while waiting.** Retained grows, so the terminal test now fails, which is the right outcome (test case `unknown`).
- **Finish after close.** The `pop` returns `None`, so nothing is refunded.
- **The label read outside the lock** (`exhaustion.is_set()` after `reserve`) is safe because exhaustion never clears.

**Tests:**
- `test_concurrent_reservations_and_close_never_refund_unknown`: the third request waits, is not exhausted while `forwarded==2`, and forwards after a validated finish.
- `test_waiting_request_rechecks_unknowns_close_cancel_and_deadline`: covers all four exits. Exhaustion is set only for `unknown`, and it stays set: `reserve(1)` still returns `None` afterwards.
- The token-only exhaustion check now settles real output first, so it exercises the permanent path rather than an overlap.

**Native evidence:**
- I opened `router-maxima-linux-gate.json.gz`. It holds exactly 10 records.
- I recomputed the 7 recorded `source_sha256` values against HEAD and **all match**: budget, gate_state, model_call_gate, model_router, model_runtime, token_prices and the probe.
- **Concurrency, both architectures:** `queued=True`, extra CLI return codes `[0,0]`, 3 forwarded, 3 validated, 0 unknown, not exhausted, `final_usage_known=True`, one acquire and one start.
- **The original 8 records:** tools 3/3/0, retry 2/0/2 ending in `model_call_cap`, compaction 4/3/1 with `final_usage_known=False`, output 2/2/0.
- Every receipt carries `max_usd=50.0` and the `joint-gate-v1` price source.
- The probe forces the M1 situation: two upstream replies are held until the third request actually calls `condition.wait`.
- The scope disclaimer is accurate. These are test-only parallel clients, not live WebFetch.

## The other diff-1 findings

| Finding | Status at `d6e1f80` |
|---|---|
| N1: provider observation lost when the cap label overrides | **Accepted as documented** (router.md: the observation is deliberately dropped; retained W stays; D diagnoses). Conservative, and no money effect. |
| N2: `cancellation_failed` overwritten | **Fixed.** `enforce` keeps the inner `BudgetError` and does not override `cancellation_failed`. `cap_used.exhausted` still records the stop. Tested. |
| N3: parent cancel reported as `model_call_cap` | **Fixed.** Cancel, close and deadline return `invocation_stopped`. Tested: exhausted=false, no upstream request. |
| N4: release path tested only on synthetic SSE | **Handled within scope.** The strict parser stays. B's practice exam must show `validated_requests>0` and `unknown_requests==0` (interfaces and router.md). An explicit `null` in usage still counts as unknown and fails closed, which is acceptable. |
| N5: rollout note understated | **Fixed.** router.md now says the changed runtime, prices and calibration identities invalidate all calibration attempts and G8/G9/G16 reuse records, which means paid reruns on resume. |
| N6: gate missing from `gate_state.MODEL` | **Fixed** with a one-line addition. It changes evidence identity only; scoring logic is untouched. |
| N7: optional `calibration.py` label | **Kept**, which is acceptable. It is a diagnostic label, and C's pinned target is still enforced by the test. |
| N8: conditional negative checks | **Fixed.** `assertNotEqual` / `assertFalse` now run unconditionally for both the identity and the panel. The seed and `bench.py` mutation negatives are kept. |

## The original brief and design

- **Every Lease carries the four fields:** `max_usd` (float), `max_input_tokens` (int), `max_output_tokens` (int), `price_source` (str).
  - `valid_maximum` checks exact type and value against `route_maximum()`, which comes from `token_prices.py`.
  - The check runs at four points: router acquire/replay, `_admit`, `running.renew_once`, and `_start`.
  - It runs again at runtime (`valid_lease`) and in `_invoke`, which also requires a one-use launch permit, and in `enforce`.
  - Supplied, forged or unbounded leases end up as `Wait('unbounded_route')`, and capacity for them is 0.
- **There is a real positive route.** `claude/claude-opus-5-5` gets a Lease with the 50.0 / 113636363 / 1136363 maxima (`test_real_routes_fail_closed…`). The native records show completed, validated runs. The result does not rest on denials alone.
- **Arithmetic:** W = 19.041792. Pricing uses Decimal ×2.2. Headroom is 1e-6. The 153 real aggregate receipts break down 143 / 2 / 8, which matches design review 4. Settled pricing and W use the same estimator.
- **Per-lease receipt:** it holds the maxima, `cap_used`, and a `final_usage_known` that requires the gate to be closed with no unknown and no in-flight requests.
- **Single path:** every inference goes through `run.opencode → runtime.call → _invoke`, so the gate always applies.
- **Unchanged:** D accounting, E's subprocess handling, and C's scoring. `run_budgeted` receives `cancel=gate`, a combined event, without changing its own semantics. Role, family and readiness independence are preserved, because `router_unbounded` is set on the per-call `context` copy.
- **No overclaims.** No Murphy row is claimed closed: 2, 3, 4, 20, 47 and 48 stay OPEN. There are no deploy, merge or credential changes.
- **Zoom-out:** the M1 fix is about 20 lines of stdlib `Condition` on the existing lock. There is no new abstraction, staging path or configuration. Evidence-identity changes are limited to the `gate_state.MODEL` line and the launch-manifest entries the release needs.

---

## Nits (optional)

**N1. A waiter can forward a request after its CLI client has given up.**
- **Where:** `model_call_gate.py:334` (`reserve`) followed by the upstream connect at `:343`.
- **What happens:** while a handler waits, the CLI's own HTTP timeout keeps running. That timeout is about 10 minutes by default; `API_TIMEOUT_MS` is not in `ENV_KEYS`. If the CLI aborts first, the handler is later admitted and forwards an orphan request. Writing back to the client fails, so the full W is retained as unknown. Two orphans can then make exhaustion terminal for real.
- **How likely:** it needs two concurrent active requests that each run for more than 10 minutes. The money bound still holds; the cost is wasted quota and a possible avoidable cap.
- **Action (optional):** after admission, before connecting upstream, check whether the client socket has already hit EOF. If it has, call `finish(identity, usage=None)` and return. Or simply document the limit.

**N2. Two wording mismatches.**
- `test_concurrent_reservations_and_close_never_refund_unknown` now makes its reservations sequentially, so the name no longer describes it.
- router.md says "finish/close/terminal exhaustion notify". That is accurate, but cancellation is polled, not notified. The 50 ms bound is worth stating.
- These are cosmetic.

**N3. A request past its deadline that could never fit gets `invocation_stopped`, not `model_call_cap`.**
- `reserve` checks the deadline before the terminal test. So a request that is both past the deadline and permanently unfit returns `invocation_stopped`.
- This does not matter in practice, because `run_budgeted` times out the invocation anyway. No action needed.

---

## Still needed before merge

1. A green result from `uv run --with numpy --with scipy python -B tests/run.py` on `d6e1f80`. The author should add the terminal metadata from `/tmp/router-maxima-full-d6e1f80.json` to this file and to `router-maxima-validation.md`.
2. No source change after this freeze. Any change requires another fresh review.

Nothing was saved and no files were modified.

## Author response

Code PASS accepted; no blocking finding remains and none was rejected. The full suite was interrupted for the mandatory integration rebase onto factory-simplify 6abe169. Its partial log/metadata are router-maxima-full-d6e1f80.log.gz and .json; no green full result is claimed for this reviewed old base. A fresh integration review and full run will replace it for handoff. No implementation or test source changes follow the reviewed freeze.

Optional N1 documented: a client that abandons a queued request at its own HTTP timeout may leave a handler that later forwards an orphan. It still consumes W before network and retains W if the response cannot be delivered, so the monetary bound holds; wasted quota/avoidable cap remains an availability limitation for B's practice qualification. No new transport/cancellation mechanism is added here.

Optional N2 is cosmetic and left unchanged. Cancellation is polled at most every50ms; finish/close/terminal exhaustion notify. N3 needs no action; the existing invocation timeout wins after deadline. These are optional nits, not rejected blocking findings.
