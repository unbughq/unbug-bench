# Diff review 3: router retry on 67a16a12 (goldfish confirm)

**PASS**

**How I checked**
- I read the delta 83c659f8..67a16a12, review 2 and the author's response.
- I ran the three new tests on a scratch copy, which is now deleted. All pass. Repeated runs were all green: 30/30, 10/10 and 15/15.
- I ran one mutation: I replaced the new guard at `model_call_gate.py:647` with `if True:`. The new tests catch that removal only some of the time, through a race (finding 1).

**Gate change (`model_call_gate.py:645-649`): how each way out of the loop ends**

| How the loop ends | What gets recorded | What `enforce`'s `finally` (`:906-913`) raises |
|---|---|---|
| Definite `credit` | Always recorded, even over a peer's stop or a cap | `shared_paid_spend_wait` credit. Same as base. |
| `binding` after retries, or lost replies until `until`, while the call is still live | `router_unavailable` | `shared_paid_spend_wait` router_unavailable. Same as base. |
| A peer already stopped the call (`paid_failure` set) | The peer's reason is kept | The peer's reason. Before this change B overwrote it, so a peer's credit became router_unavailable. |
| The call hit its cap (`exhaustion`) | Nothing | `model_call_cap`. Before, it was mislabelled `shared_paid_spend_wait`. |
| Cancel | Nothing | No paid stop. A lease loss is still labelled through `lost` (`model_runtime.py:642`). An engine cancel now stays `cancelled` instead of being relabelled as a paid wait. |
| `closed` | Nothing | `closed` is only set in `close()`, just before `finally` reads `paid_failure` once. Any write after that was a race the read mostly missed anyway. |

- **Money:** `paid_failure` takes no part in money accounting. It is read only at `:615` and `:906`.
  - `finish(identity, None if not definite)` is unchanged, so a hold that may have been granted stays retained and unknown.
  - The router's pending row still reaches `unknown`, then reconcile, when the lease ends.
  - No call loses money accounting.
  - The only stops that disappear are ones that hid a truer stop (cap, cancel, a peer's stop).
- **Locking:** the new check runs under `gate.state.condition`.

**New tests**
- `test_a_reserve_retry_stops_when_its_call_ends`:
  - It proves the `closed` check. Without it, the loop runs on for 30 s and `asked ≫ ended+1`.
  - `ended` is read after close, so the bound of "+1 in-flight try" holds.
  - The post thread is a daemon and is joined. It is not flaky.
- `test_the_background_pass_reads_the_balance_as_it_starts`:
  - With `interval=60`, only the start refresh can set `balance` within 5 s.
  - The thread is stopped in cleanup and only waits after that refresh. It is robust.
- `test_a_renewal_answer_with_a_changed_binding_ends_the_call_at_once`:
  - It checks `renewals == 2`, which is deterministic because the renew thread returns after `RouterRejected` (`model_router.py:1110`).
  - Under the old `RouterUnavailable`, the cancel never comes and `execute` fails its 2 s wait.

**Author's "not changed" reasons**
- **Nit 2 holds.**
  - `credit` on `openrouter-key` classifies as `router:credit` (PROVIDER_LIMIT).
  - Its retry time is `retry_at('credit')`, which is now + 900 s, and `classify._retry_at` keeps it.
  - In the engine's SLEEP branch (`engine.py:1538-1550`), the case parks only when `not credit_ready_step()`. With no pool block it falls through to `nap(seconds)` (about 900 s).
  - It keeps its worker, because `KEEP_WORKER_WAIT_S` is 21 600.
  - So it is not an immediate relaunch, and the `shared_paid` path (`model_runtime.py:754-758`) raises ProviderWait directly.
- **Nit 1 holds as a nit.**
  - Storing a live read in `self.balance` would change how a process without the background pass behaves (`rpc`, `model_router.py:477`).
  - It would also change how tests that move the balance between requests behave.
  - It costs only extra live reads, and no money.

**Findings**

1. **NIT: the review-2 nit-3 fix has no deterministic test.**
   - With `:647` replaced by `if True:`, `test_a_reserve_retry_stops_when_its_call_ends` failed in only 7 of 20 runs. It fails when the late `router_unavailable` write wins the race against `enforce`'s `finally`.
   - The peer-stop and cap cases are not covered at all.
   - Fix: add one test in `PaidWireTests`. In the `paid_reserve` stub, on the second try, set `gate.state.exhaustion` (or set `paid_failure = 'credit'` under the condition), then raise `RouterUnavailable`. Assert two things:
     - `enforce` raises `model_call_cap`, or `provider_failure['reason'] == 'credit'` in the second variant.
     - `seen == []`.

## Elephant response (2026-11-20)

PASS. Nit 1 fixed: added `test_router_paid_spend.PaidWireTests.test_a_retry_cut_short_by_a_peers_credit_refusal_keeps_that_stop` (the `paid_reserve` stub records a concurrent request's `credit` refusal under the condition, then loses its reply; `enforce` must raise with `provider_failure['reason'] == 'credit'` and nothing is forwarded). With the guard replaced by `if True:` on a scratch copy it failed 3 of 3 runs; with the guard it passes.
