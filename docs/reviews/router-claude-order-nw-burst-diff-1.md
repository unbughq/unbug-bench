# Diff review 1: router Claude order + Neuralwatt burst on 29c1fa13 (goldfish)

Reviewer: fresh general-purpose subagent (zoom_out, implementation_readiness; Mode: REVIEW), given the diff
19b404be..29c1fa13, the design, design review 1 and the founder's requests.

## Verbatim review

**Verdict: PASS** (no blocking findings; fix the NIT 1 and NIT 2 design wording before the founder sign-off)

**Verified**
- Touched tests pass: test_neuralwatt_routes 14, test_model_router 53, test_neuralwatt_runtime 8, test_model_call_maxima 30, test_durable_call_budget 43, test_model_runtime 11; also test_router_capacity 10, test_router_delivery 5, test_provider_routes 5.
- "No burst key behaves exactly as today" holds: base 19b404be and head on the same 400-step random sequence from the real 2026-11-19 health fixture with `capacities={'neuralwatt-key': 3}` and no burst key (acquire, observe rate/quota/credit/outage, done/interrupted finishes, time jumps): every acquire answer and every `status.health` snapshot byte-identical; no new health rows.
- Gate identity unchanged: `gate_state.model_science()` hashes the same on base and head (67de849c…). No top-level *.md, calibration.py, gate_state.py or claims.py touched.
- Mythos guarantee holds: every lease path goes through `routes()`; a `claude/…mythos…` route returns only claude-token (`model_router.py:186`); Mythos is unpriced so not leasable today; the test patches a synthetic maximum.
- Claude order (`model_router.py:186`, `:535-540`): claude-token first; small account eligible only while claude-token has an unexpired rate/quota block; expired blocks are zeroed at the top of the RPC. Remaining old-order references are fine (ACCOUNTS big first; label map is a mapping; `model_runtime.py:679` symmetric; other tests use the small login only as a label and pass).
- Burst mechanics: sampling runs before the operation, so the refusing lease is counted; the worker observes before it finishes (`model_runtime.py:722-729`); `_start` follows acquire before any provider request, so a fourth lease is stamped before it can be refused; expired leases are cleared before sampling; `dict(old, burst_until=…)` keeps an existing block; the floor path's fresh dict dropping the new fields is harmless; `guard.router_clear` (`guard.py:705`) and the healthy-observe reset ignore the new fields; the FIFO `older` check only sees seats through `free()`.
- Compatibility: old router ignores `burst_capacities` and the extra fields; old workers validate by set membership so accept the new order; old workers still defer NW rate; new workers on an old router get a rate wait and park after 60 s as today.
- Money of NW rate moving on: each refusal's unseen tail is booked as open_steps × nw_request_worst (`budget.py:1452-1458`, `:433-437`); each retry reserves within the case's funding; per-refusal booking equals the old deferral path.
- Mutations: no sampling — killed (3); count at observe time — killed by `test_a_peer_finishing…`; `free()` ignores cooldown — killed (3); window doubled — killed; Mythos guard removed — killed; `eligible()` always true — killed (8); old `_account_order` — killed; runtime rate not moving on — killed only by the predicate unit test; sampling over `capacities` — survives, no effect with valid config; burst path without the reason check — **survives** (NIT 3); without `not lasting(key, old)` — **survives** (NIT 3).

**BLOCKING**: None.

**NIT**
1. The known ceiling is understated and refusals are not free. A call whose refusal repeats every time (`tpm_uncached_request_too_large`, classed rate) retries on a floor seat, the cooldown ends, peers burst again, `above_floor_at` is fresh, and it takes the burst path again; the pool never blocks (simulated: 5 consecutive refusals, none blocked). A moved-on call restarts its CLI (`model_runtime.py:848`), re-spending the charged prefix; same for any mid-session burst 429 on a long writer session. Bounded by role duration and invocation funding inside the case's $50; before, the same call looped through 15-60 min parks and blocked the pool for everyone. Design should say so plainly; consider a Murphy row.
2. "The refused call retries on a floor seat" holds only when no later lane in the chain is open: with NW full, acquire leases the next open lane (OpenRouter twin, or `opencode/deepseek-v4.1-flash-free`). Tests never exercise this (OpenRouter credit-blocked in the fixture). Production is fine only while non-MiniMax OpenRouter routes stay disabled and `opencode-free` stays 0; name that dependency.
3. Two test gaps: no test pins "a credit above the floor still blocks" (`model_router.py:710-711`); `not lasting(key, old)` can never be true for NW and is redundant since `dict(old, …)` keeps a block — delete it or say why.
4. The `refuse()` helper's classification check is decorative (`test_neuralwatt_routes.py:144-149`): it classifies a synthetic string then observes with the passed reason. Use the real `concurrent_budget_exceeded` body in `fixtures/neuralwatt-smoke-20261119.json` (`errors.concurrent`), or drop the assertion.
5. `burst_capacities` accepts any approved account (`model_router.py:455-458`); a burst on claude-token would turn a Claude quota into a 300 s cooldown. Restrict to neuralwatt-key or state the intent.
6. A refusal at or below the floor within 300 s of being above it takes the burst path, deviating from the founder's literal wording; the design explains why; make sure the founder hears it plainly.
7. The worker side of "rate moves on" is only unit-tested on the predicate (`test_neuralwatt_runtime.py:110`); acceptable given its size.
8. Rollout is safe only with both Claude logins on every worker (an old worker without the small login's secret still offers it); keep it as a hard rollout step.

Zoom-out: small for what it does (one config key, one constant, a two-line sampling loop, one observe branch, `occupied()` factored out); no speculative abstraction; the design reads as an implementation plan. Murphy rows named but unnumbered because the register isn't on main — acceptable.

## Response (elephant)
- NIT 1: design "Known ceiling" rewritten plainly; Murphy row `new-nw-burst-2` added (open).
- NIT 2: design names the `disabled_routes` / `opencode-free: 0` dependency.
- NIT 3: added `test_spent_credit_above_the_floor_still_blocks` (the reason-check mutation now fails); deleted the redundant `not lasting(key, old)`.
- NIT 4: `refuse()` now classifies the real `concurrent_budget_exceeded` body from `neuralwatt-smoke-20261119.json` and observes its reason (`rate`) unless a test passes another.
- NIT 5: intent stated in the design (Neuralwatt only); not restricted in code.
- NIT 6: deviation written in the design and in the report to the founder.
- NIT 7, 8: no change; NIT 8 is rollout precondition in the design.
