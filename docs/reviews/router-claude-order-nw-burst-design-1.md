# Design review 1: router Claude order + Neuralwatt burst (goldfish)

Reviewer: fresh general-purpose subagent (zoom_out, design_critic, implementation_readiness; Mode: REVIEW),
on the first draft of docs/designs/router-claude-order-nw-burst.md and the uncommitted worktree code.

## Verbatim review

**Verdict: FAIL.** Blocking findings: B1 test suite red, B2 founder requirement not met in production, B3 burst rule race, B4 rollout preconditions unstated. Router-level logic otherwise matches the design; the Mythos guarantee holds.

### BLOCKING

**B1. The branch fails 47 tests that pass on main: old account-order assumptions left in two test files.**
- `tests/factory/test_model_call_maxima.py`: 30 pass on base in 22 s. On the branch, 42 fail (counting subtests) and the run takes 15 min. Line 227–228 still expects the first Claude lease to be `claude-factory-token-2`. The ProtocolTests worker fixtures (~918, ~1093) give the worker only the small login, never eligible now, so calls wait instead of running (e.g. `test_runtime_close_mid_response_retains_hold_once`).
- `tests/factory/test_durable_call_budget.py:46`: fixture sets `capacities={'claude-factory-token-2': 2}`, so `claude-token` defaults to 1 seat; concurrent calls now raise `ProviderWait` (e.g. `test_parallel_runtime_denial_never_enters_transport`).
- The design's Tests section lists only `test_model_router.py`; the brief asked to check every place encoding the old order, tests included.

**B2. The founder's "the refused call retries on a floor seat" is not met in production.**
- With `UNBUG_PROVIDER_WAIT=1` and an engine, an NW rate failure has `final_usage_known=False`; `go_quota_moves_on` covers only NW `quota`/`credit` (`model_runtime.py:403-409`); so `router_deferred` is True and the case parks until `retry_at('rate')`, now + 900 s.
- Every burst 429 still costs that case step its in-flight CLI call plus a 15-minute park; bursting makes these more frequent.
- Minimal fix: one word in `model_runtime.py:409`, `reason in ('quota', 'credit', 'rate')` for `NW_ROUTES`; `budget.py:1456` already counts `rate` among refusals whose steps are bounded. Outside the stated "model_router.py only" scope: widen scope or get written sign-off.

**B3. The burst-or-floor decision uses lease count when the worker reports the 429, not concurrency when it happened.**
- `occupied(route['pool']) > floor` at observe time (`model_router.py:704-705`) ignores peers finishing between the provider's 429 and the observe. OpenCode retries 429s internally first (`budget.py:1363-1365`), and the worker writes its receipt before observing.
- Example: 4 held, NW refuses the 4th, a peer finishes meanwhile, observe sees 3 → pool blocked 900 s, doubling. Clustered refusals likewise: with 6 held, the 4th refusal observed lands on the floor path.
- Pick a rule: (a) while `burst_until > now`, a refusal on a lease admitted before the cooldown only extends it; or (b) accept the race with sign-off and a counter. Add a test for a done finish between the 429 and the observe.

**B4. Rollout preconditions are unstated.**
- `capacities['claude-token']` must be at least the old small-account cap, else it defaults to 1 seat.
- Workers must hold the `claude-token` secret, else `credential_expiring` waits until claude-token is blocked. Design must say so and require checking it. (`tests/integration/worker_delivery_edge.py:89-90` still models a small-login-only worker.)
- The live stopgap `operator_hold` row on `claude-factory-token-2` becomes harmful after deploy; rollout should clear it or let it expire.
- Rollout steps missing: drained restart with `burst_capacities` in the same restart; check `status` shows 6 seats; worker side of `_account_order`.

### NIT
- N1. `'mythos' in route` is case-sensitive while the route regex allows upper case; use `.lower()`. Guarantee otherwise holds (every lease path goes through `routes()`; old workers validate by set membership; Mythos unpriced on main).
- N2. `burst_capacities` accepts any pool name; a typo is silently ignored. Consider requiring a known pool.
- N3. A real NW quota exhaustion above the floor takes up to (burst − floor) extra refused calls before the pool blocks; the design should say so.
- N4. The refused call's retry is a new request id, so it joins the back of the FIFO queue; "retries on a floor seat" overstates it.
- N5. No metric for whether 6 seats beat 3; the 300 s cooldown is a guess.
- N6. Old workers/routers are safe (observed details: finish-before-observe on old workers is conservative; extra `burst_until` field ignored; `guard.router_clear` ignores it; `capacity` RPC has no production callers).
- N7. "Deletes: nothing" is right; observe-before-finish ordering is real (`model_runtime.py:722-729`).

## Response (elephant)
- B1 fixed: the worker fixtures in `test_model_call_maxima.py`, `test_model_runtime.py` and `test_durable_call_budget.py` give the worker `claude-token`; line 227 expects `claude-token`. All three files pass. `worker_delivery_edge.py` tests secret delivery by name, not routing order; left as is.
- B2 fixed: `go_quota_moves_on` now moves NW `rate` on (one word, worker side, new launches only); `test_neuralwatt_runtime` updated. Scope widening recorded in the design and the report.
- B3 fixed with a different rule than (a): every RPC samples each burst pool and stamps `above_floor_at` while it holds more than its floor; a refusal within 300 s of that is the burst's. Covers both the peer-finish race and clustered refusals. New test `test_a_peer_finishing_before_the_observe_still_counts_as_the_burst` (fails under the old count-at-observe rule, checked by mutation), which also shows a refusal after a whole window at the floor blocks.
- B4 fixed: preconditions checked read-only on the VM (`claude-token: 100` in capacities; workers get both Claude logins) and rollout steps, including the `operator_hold` row, written into the design.
- N1 fixed (`.lower()`), N2 fixed (pool must be an approved account), N3 written as a known ceiling (now bounded by one window), N4 wording now says capacity wait FIFO, N5 recorded as a ponytail note on the constant. N6, N7 no action.
