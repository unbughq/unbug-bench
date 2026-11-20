# cached-window diff review 1

Goldfish: fresh general-purpose subagent (Claude), personas zoom_out + implementation_readiness, Mode: REVIEW.
Reviewed: `git diff origin/main...fix/cached-window` at 9b113fd6, against docs/designs/cached-window.md.

## Review (verbatim)

Verdict: FAIL

The fix works and is safe, but one test gap blocks: nothing tests the money-safety floor.

What I checked:
- **Test proves the row.** I ran `test_cached_window.py` against three variants:
  - Both halves of the fix: passes.
  - Neither half: 3 of 4 tests fail.
  - Only the cost discount, without the input-cap scaling: 2 fail. On the cb5e26 diagnosis replay, counted input stays at 27,635,463 tokens against the test's limit of 9,211,821 (a third of the prompt tokens).
  - Only the input-cap scaling, without the discount: 3 fail.

  So the test catches the row and needs both changes.
- **The fixture looks real.** It carries router fields (`charge_nano`, `cost_details`, `is_byok`, `cache_write_tokens`), and its lease caps and price sources match the leases. Nothing in it comes from the code under test.
- **Money bound holds.** A request is booked at the higher of the discounted amount and OpenRouter's own charge. That is never below the bill and never above the full rate. Requests without usage keep their whole hold.
  - `request_hold` and `worst_request` carry no `cost`, so their amounts don't change.
  - `_gate_bound` takes settled plus held, so it still bounds real spend.
  - `_paid_charge` and the router maxima are untouched.
- **No change for callers.** The streaming parser now rejects malformed `prompt_tokens_details` inside `openrouter_gate_cost`. It rejected the same inputs before (null, non-dict, a bool or non-int count, more cached than prompt tokens), so the result is the same. `router_cheap_pin_probe` sets `cost` to the full rate, so it is unaffected.
- **Other tests pass:** `test_router_cheap_maxima` (10), `test_model_call_maxima` (30), `test_router_item8_profiles` (9).
- **Gate identity untouched.** Neither changed file is referenced from `gate_state.py`, `calibration.py` or `exam_responder.py`.

Findings:

1. **BLOCKING — nothing tests the charge floor.** `factory/token_prices.py:138`, `tests/factory/test_cached_window.py:37-44`
   - The floor (`max(..., Decimal(str(cost)))`) is the only thing that keeps the gate from pricing below the bill. That matters when the serving endpoint charges more for cache reads than the pin.
   - In the fixture it never binds: 0 of 251 recorded requests have a charge above the discounted amount. Every endpoint there billed below its pin. Deleting the floor still passes all four tests, so the assertion at line 44 proves nothing about it.
   - Fix: add a case built from a real recorded cached request.
     - Raise its `cost` to just below `full_rate`. Assert `openrouter_gate_cost` returns exactly that cost and that `Allowance.finish` settles it.
     - Raise `cost` above `full_rate`. Assert it returns `None` and the request keeps its hold.

2. **NIT — the parser re-checks something already checked.** `factory/model_call_gate.py:546`
   - `openrouter_gate_cost` now validates `prompt_tokens_details.cached_tokens` through `openrouter_cached_tokens`. The `('prompt_tokens_details', 'cached_tokens', ...)` entry in the parser's loop is now dead.
   - Fix: remove that entry and keep only the `completion_tokens_details` check, so the cached-token rule lives in one place.

3. **NIT — design claim is slightly overstated.** `docs/designs/cached-window.md:60`
   - The doc says "counted inputs times the input price never exceed the counted cost". Because of the `math.ceil` rounding, they can exceed it by just under one input token's price.
   - That is harmless (it only makes the input cap a hair stricter), but the claim is not exact. Fix: change the wording to "exceed it by less than one token's price".

4. **NIT — one table row is unbacked.** `docs/designs/cached-window.md`
   - The 1d921598 row ("$0.92, fits at that point") has no test.
   - Fix: add a one-line replay assert like the a14a21d1 one, or mark the row as not tested.

One flag: `docs/ENGINEERING.md` and `docs/murphy-register.md` do not exist in this worktree. The row is recorded on `fix/diagnosis-continue-cb5e26`, so closing it there has to be part of merging.

## Resolution (elephant)

1. Fixed: `test_a_bill_above_the_pinned_cache_rate_is_the_price` takes the most-cached real request of the
   cb5e26 diagnosis, sets its `cost` to 0.99x and 1.01x the full rate, and asserts the price is exactly
   that cost and settles (0.99x), or is None and keeps its whole hold (1.01x). Mutation check: with the
   floor removed this test fails.
2. Fixed: the parser's `prompt_tokens_details` entry removed; a comment points at `openrouter_cached_tokens`.
3. Fixed: design wording.
4. Fixed: `test_glm_windows_no_longer_cut` replays 1d921598 too.
Flag: noted for the merge; this branch has no register to close the row in, the PR says so.
