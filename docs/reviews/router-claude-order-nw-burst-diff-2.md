# Diff review 2 (confirm): delta 29c1fa13..be4085c7 (goldfish)

Reviewer: fresh general-purpose subagent (zoom_out, implementation_readiness; Mode: REVIEW).

## Verbatim review

**What I checked**
- Tests: `tests/factory/test_neuralwatt_routes.py` passes 15 tests on a clean copy of be4085c7 (14 before plus the new credit test).
- Worktree untouched; mutations ran on a scratch copy, restored from git between runs.
- Scope: the delta touches the design, the review doc, one line of code in `factory/model_router.py:710`, and the test file. No top-level `*.md`, `calibration.py`, `gate_state.py` or `claims.py` changed.

**Nit by nit**
- NIT 3a (credit test): real. `test_spent_credit_above_the_floor_still_blocks` (`test_neuralwatt_routes.py:213-221`) holds 6 leases, observes `credit`, checks for a credit block with no `burst_until`. Mutation "drop `reason in ('rate', 'quota')`": killed by this test alone. "Add `'credit'` to that tuple": killed. "Drop `'quota'`": killed by the quota subtest at `:156`. The first two die with `KeyError: 'reason'` at `:219`, not an assertion failure (NIT A).
- NIT 3b (removing `not lasting(key, old)`): no behaviour change in any state production can reach. `lasting()` (`model_router.py:413-415`) is true only for `credential_expiring`, or `credit` on `PAID_POOL = 'openrouter-key'`. With burst configured only for `neuralwatt-key`, a credit row is never lasting. A `credential_expiring` row never lands on the NW pool: the runtime's missing-secret raise (`model_runtime.py:620-622`) happens before `invoked = True` (`:634`); the gate's `credential_expiring` (`model_call_gate.py:888, 919, 921`) has no `provider_failure`, reroutes via `call_failure_reason` (`durable/stop_registry.py:231`) as `per_call`, which is not observed (`model_runtime.py:726`); `budget.py:1148` is Codex only. Putting the clause back survives the whole file, as expected. Strictly at the RPC level not identical (NIT B), but matches the design line "A block already on the row is kept".
- NIT 4 (`refuse()` helper): real. It classifies the fixture's `errors.concurrent` message with status 429 and observes `failure['reason']` unless a test passes another. Mutation "a 429 is classified `quota`" in `budget.py:44` fails 3 tests. The status code decides, not the body; fine, the worker passes the status too.
- NIT 1: "Known ceiling" now says plainly a never-succeeding request keeps taking the burst path, bounded by role duration and funding; Murphy row `new-nw-burst-2` listed open. Addressed.
- NIT 2: design names the `disabled_routes` / `opencode-free: 0` dependency. Addressed.
- NIT 5: intent stated (Neuralwatt only); code unchanged. Acceptable.
- NIT 6: deviation written up in the design; telling the founder is the elephant's job.
- NITs 7 and 8: no change, as stated.

**BLOCKING**: None.

**NIT**
- A. The credit test catches the reason-check mutation through a `KeyError` at `:219` (`health['reason']`); `health.get('reason')` would give a readable failure. Cosmetic.
- B. Removing `not lasting(key, old)` is not identical at the RPC level: an NW row with `reason='credential_expiring'` (only via a hand-made observe) or `burst_capacities` misconfigured on `openrouter-key` while it holds a lasting credit block would now keep the row and add `burst_until` instead of replacing/extending. Neither happens in production; the new behaviour matches the design. Say "unreachable in production; a block on the row is kept" rather than "redundant".
- C. The comment at `:156` ("None: the real concurrency 429, classified `rate`") is enforced only indirectly; enough, no action.

Zoom-out: the delta is small and moves in the right direction; nothing speculative; no new problem.

**Verdict: PASS**

## Response (elephant)
- NIT A: cosmetic, not changed.
- NIT B: accepted wording: the removed clause is unreachable in production, and a block already on the row is kept.
- NIT C: no action.
