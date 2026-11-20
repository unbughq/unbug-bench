# Diff review 1: router retry on 70d78f1f (goldfish)

**FAIL**

How I checked: I exported both commits into a scratch folder (now deleted). The three changed test files all pass on 70d78f1f (56, 10 and 51 tests). I ran each new test on 3dfdde3c: each one fails or hangs there. I also ran two mutations on the new code, described in findings 1 and 7.

1. **BLOCKING: the line that keeps the cached balance safe for money has no test, and a mutation that breaks it passes.**
   - `factory/model_router.py:478` sets `credit, fetched_at = cached`. This makes `_paid_counts(db, fetched_at - CREDIT_OVERLAP)` (line ~720) count charges back to 900 s before the balance was read, not 900 s before now.
   - The code is correct as written. I reviewed `Store.rpc`, `refresh_credit` (whose `at` is the start of the read) and `_paid_reserve`. Every hold granted since the read is still counted, either pending or settled after the read. So spend stays within credit plus one hold, as before.
   - I changed it to `credit = cached[0]`, which keeps `fetched_at = now`. All 48 `PaidTests` still pass. The new test only settles rows within 100 s, so the 900 s window hides the difference.
   - With that mutation, charges settled between 900 s before the read and 900 s before now are dropped from what is counted against a balance that may not show them yet. That is up to 120 s of spend, which can be more than one hold.
   - Fix: add a test that settles a row about 850 s before `refresh_credit()`, advances the clock about 100 s, and asserts that a reserve which fits only without that row is refused with `credit`.

2. **BLOCKING: workers still running old code turn `no_route` into `infra:router_unavailable`.**
   - The new router sends `no_route` to every client (`model_router.py:601`).
   - Old worker code checks `result.get('reason') not in REASONS`, and its `REASONS` has no `no_route`. It raises `RouterUnavailable('invalid admission response')` (`_admit`, line ~920). After 60 s that ends as `ProviderWait('router_unavailable')`, which classifies as `infra:router_unavailable`.
   - The engine still takes the same retry path it took for `router:outage`, so behaviour is no worse than today. But running cases still loop, and the stop is now labelled with the exact reason this change is meant to drive to zero. That would hide whether fixes 1 and 2 worked.
   - The same function already guards this case for `capacity` (comment at line 592: "an older one rejects the reason as an invalid response").
   - Fix: send `no_route` only to clients that declare they understand it. Add a new field to the allowed `acquire` set (e.g. `route_protocol`), have new workers send it, and answer `outage` to clients without it. Deploy the router first.

3. **NIT: after a credit block is lifted, the cached balance can still be the one from before the top-up.**
   - `lift_credit` (`model_router.py:744`) reads the balance live and lifts the block, but does not update `self.balance`.
   - The operator's `--lift-credit` runs in a separate process, so it can never update the router's cache.
   - If the top-up arrives less than 60 s before the lift, a case woken by it reserves against the old low balance. It gets `short`, the pool is blocked again, and the gate ends the call at once on `credit`.
   - Fix: in `lift_credit`, set `self.balance = (credit, read_start)`. Better still, before `_paid_reserve` returns `short` from a cached balance, re-read the balance live once. That keeps a "real out of credit" answer final, as asked.

4. **NIT: an unreadable balance is still final at once.**
   - When the cache is older than 120 s and the live read fails, `credit is None` returns `denied('credit')` (line 712). The gate treats that as final and ends the call.
   - This is the same "one provider round trip ends the call" pattern, though it now needs two background reads in a row to fail first.
   - Consider answering `binding` there so the gate's 30 s retry covers it. Today's behaviour is money-safe, so this is optional.

5. **NIT: one unexpected error can stop the background pass for good.**
   - `reconcile_forever` (line 1181) calls `store.refresh_credit()` outside a `try`. `refresh_credit` only guards `credit_reader()`; `_nano(observed)` can still raise.
   - If it does, the thread dies silently, and reconcile and `lift_credit` stop for the rest of the router's life. The production reader makes this unlikely, but the cost is high.
   - Fix: wrap it like its siblings (`try: … except Exception: pass`), or move `_nano` inside the existing `try`.

6. **NIT: the router now reads the balance before it starts serving.**
   - `main()` calls `store.refresh_credit()` (line 1208) before `serve_forever()`. The report notes that DNS has no timeout, so a stuck OpenRouter lookup delays router start indefinitely, which is a new dependency.
   - Fix: call it at the top of the `reconcile_forever` thread, before the first wait.

7. **NIT: gate retry loop edge cases** (`model_call_gate.py:625-649`). The handling of `duplicate`, `binding` and the deadline is correct:
   - A row is only inserted on a grant, so `duplicate` always means an earlier try was granted.
   - A later try that sees no row returns `binding`. The 4 s self-refusal makes an earlier, slower try fail too, so treating the result as definite and zero-cost is sound.
   - `gate.deadline` is on the monotonic clock, the same clock the loop compares it with.

   The gaps:
   - (a) The loop does not stop when the gate closes. `is_set()` does not cover `state.closed`, so a cancelled or finished call keeps asking for up to 30 s. A late grant then leaves a pending row at its full hold. Fix: add `or gate.state.closed` to the break test.
   - (b) When the loop ends without a definite answer after a try that may have been granted, the early `return` at line 649 skips `paid_settle`. The row stays at its full hold and ends up `unknown`, with no generation id to reconcile against. This existed before but is now more likely. The gate knows the request was never sent upstream, so it could settle it at zero usage.
   - (c) Renewal: `renew_once` raises `RouterUnavailable('lease binding changed')` (line 1083) on a definite router answer, and that is now retried for up to 150 s. Raise `RouterRejected` there so it still ends the call at once.

   The rest of the renewal logic is right:
   - Retries stop once 150 s have passed since the last successful renewal (counted from when it was sent), which is inside the router's 180 s lease and leaves 25 s for clock skew.
   - A `RouterRejected` is still final.
   - The `worker_stalled` label is unchanged. A mutation that retries refusals is caught by `test_a_refusal_within_the_lease_from_a_healthy_worker_stays_router_unavailable`.

8. **NIT: test strength.**
   - `test_the_background_pass_refreshes_the_balance_before_reconciling` hangs on the old code instead of failing. `reconcile_forever` swallows the error from the missing `balance`, so `stopped` is never set. Run it in a thread with `join(timeout)` and assert.
   - Several old-code failures are only `AttributeError` from the patched constants (`RENEW_RETRY_SECONDS`, `PAID_RESERVE_PAUSE_SECONDS`). Their assertions would also fail on behaviour, so this is acceptable.
   - The real-HTTP write-lock test is good evidence for fix 2.

**`no_route` end to end, with new code on both sides:** it is correct.
- The router answers it only when a request has no eligible lane at all.
- The `observe` operation refuses it, so workers never publish it as a provider limit.
- `classify_wait` maps it to a provider limit labelled `router:no_route` and keeps the router's retry time.
- `policy.decide` returns `SLEEP` (it is not in `is_operational_wait`), and the engine sleeps to that time.
- `stop_registry`, `diagnostics.REASONS` and `PUBLISHED_REASONS` all include it.

A configuration that can never be routed (every lane excluded or disabled) now sleeps in 15-minute cycles with no end. That matches today's endless retry and what the founder asked for, but nothing flags it.

**Backlog 128:** correct and tested.

## Elephant response (2026-11-20)

Fixed:
1. Added `test_a_cached_balance_counts_charges_from_before_its_own_read_not_before_now` (a charge settled 850 s before the read, reserves 100 s after it). Checked on a scratch copy: the `credit = cached[0]` mutation now fails it.
2. `no_route` is answered only to a worker sending `capacity_protocol: 2` (new workers send 2); an older one (1) still gets `outage`. A new key was not used because the router validates the acquire key set: a new worker on an old router would have every acquire refused. With `capacity_protocol: 2` on an old router a new worker only gets `rate` instead of `capacity` for a full seat, so the router deploys first. The test asserts the old-client answer.
3. Took the "better still" option: a `short` computed from a cached balance rolls back its transaction and is re-read live once (`Store.rpc(..., live=True)`); only a live short blocks the pool. This covers both the in-process lift and the operator's `--lift-credit`. Test `test_a_short_cached_balance_is_confirmed_live_before_it_parks_anything`; a mutation that skips the recheck fails it.
5. `_nano` moved inside the `try` in `refresh_credit`.
6. The startup refresh moved to the top of `reconcile_forever` (off the serving thread); `main()` no longer reads before serving.
7a. The retry loop also stops when `gate.state.closed`.
7c. `lease binding changed` now raises `RouterRejected`, so it is not retried.
8. The background-pass test runs the loop in a thread with `join(5)` and asserts.

Not changed:
4. An unreadable balance (cache stale and the live read failing) stays a `credit` refusal, as before this change; the reviewer marks it optional and money-safe. Turning it into a retry would change how those stops are labelled and parked (`router:credit` with no block keeps a short sleep on its worker); out of scope.
7b. A try that was granted but whose reply was lost every time for 30 s still keeps its hold (pre-existing: "Failed RPC leaves the entire hold"; money-safe, and the usage bound in `reconcile` releases it later). It is less likely than before, not more: a lost reply is now usually followed by a `duplicate` answer that the call uses.
