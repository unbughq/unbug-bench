# cached-window diff review 2

Goldfish: fresh general-purpose subagent (Claude), personas zoom_out + implementation_readiness, Mode: REVIEW.
Reviewed: `git diff origin/main...fix/cached-window` at 3938f25c, against docs/designs/cached-window.md and
docs/reviews/cached-window-diff-1.md.

## Review (verbatim)

Verdict: PASS

The fix holds up, and the earlier review's blocking finding is really fixed. I checked it by running the tests and by temporarily mutating the code. I then restored the files with `git checkout`, and `git status` is clean.

**What I verified**
- **The test proves the row.**
  - With `token_prices.py` and `model_call_gate.py` put back to `origin/main`, 4 of the 5 tests fail.
  - With only the input-cap scaling taken out (`model_call_gate.py:224`), 2 fail: the cb5e26 diagnosis replay and the GLM replay.
  - With only the charge floor taken out (`token_prices.py:138`), 1 fails: `test_a_bill_above_the_pinned_cache_rate_is_the_price`. That was review 1's blocking finding (finding 1), and it is fixed.
  - With the branch as it is, all 5 pass. The neighbouring `test_router_cheap_maxima` (10 tests) and `test_model_call_maxima` (30 tests) also pass.
- **The fixture looks real.** It has router-only fields (`charge_nano`, `cost_details.upstream_*`, `is_byok`, `cache_write_tokens`). Its lease caps and `price_source` strings match the pins, and it records where it came from. Nothing in it is produced by the code under test.
- **Money safety holds.**
  - Each request is booked at `max(discounted, cost)`. The existing check that rejects a charge above the full rate is kept, so the price sits between the bill and the full rate.
  - With no `cost` there is no discount (`openrouter_cached_tokens` returns 0). Request holds don't change, because `worst_request` carries no `cost`.
  - `_gate_bound` (settled plus held) still bounds real spend.
  - The router's `_paid_charge` already books `cost` alone, so the gate is now at least as conservative as the router's own ledger.
  - All five pinned OpenRouter routes have a non-zero cache-read price, so no route falls into the "no cache price" case.
- **The parser behaves the same.** A null, non-dict, bool, negative or too-large `cached_tokens` is still rejected, now through `openrouter_cached_tokens`. Review 1's finding 2 (the duplicate check) is fixed.
- **Gate identity is untouched.** `gate_state.py`, `calibration.py` and `exam_responder.py` don't reference either changed file.
- Review 1's finding 3 (design wording) is fixed. Finding 4 is fixed: 1d921598 is now replayed in `test_glm_windows_no_longer_cut`.

**Findings**

1. **NIT: the cache-discount pricing is worked out in two places.** `factory/model_call_gate.py:221-224`
   - `Allowance.amount` reloads the route's prices and calls `openrouter_cached_tokens` again, just to rescale the input count. `token_prices.openrouter_gate_cost` does the same pricing for the cost.
   - If one is changed without the other, cost and input count could drift apart.
   - Fix: give `token_prices` one helper that returns `(cost, counted_input)` (or have `openrouter_gate_cost` return both), and have the gate use only that.

2. **NIT: the money floor assumes `usage.cost` is the whole charge.** `factory/token_prices.py:117-122`
   - For a BYOK request, OpenRouter's `cost` is only its own fee. The floor would then not cover an upstream endpoint that charges more than the pin for cache reads.
   - It doesn't happen today: every recorded request has `is_byok: false`, and there is one paid key.
   - Fix: in `openrouter_cached_tokens`, return 0 when `usage.get('is_byok')` is true, or at least note in the docstring that the floor assumes a non-BYOK key.

3. **NIT (process): the row can't be closed on this branch.** `docs/ENGINEERING.md` and `docs/murphy-register.md` don't exist in this worktree. Murphy row `new-cached-window-1` lives on `fix/diagnosis-continue-cb5e26`, so the merge has to close it there, with this test as its evidence.

## Resolution (elephant)

PASS; no blocking finding. Nits left open so the reviewed head is the one that ships:
1. Not applied: the two callers share `openrouter_cached_tokens`; a combined return would change
   `openrouter_gate_cost`'s signature for the router probe and tests. Follow-up if the pricing changes again.
2. Not applied, recorded: the factory has one OpenRouter key and it is not BYOK (`is_byok: false` on every
   recorded request); the router's own `_paid_charge` already books `cost` alone on the same assumption.
   If a BYOK key is ever added, discount only when `is_byok` is false.
3. Noted in the PR: close `new-cached-window-1` with `tests/factory/test_cached_window.py` when the
   diagnosis-continue branch's register text lands.
