# Design review 2: neuralwatt-first (goldfish)

Scope: the "Neuralwatt first (2026-11-20)" section of `docs/designs/neuralwatt-routes.md` (from line 327), checked against `git diff 3dfdde3c -- factory tests` on `feat/neuralwatt-first` (4d739f80). I applied the `zoom_out`, `design_critic` and `implementation_readiness` lenses. I ran `test_neuralwatt_routes.py` (10 tests), `test_neuralwatt_runtime.py` (8) and `test_model_router.py` (49), and all of them pass.

**Round 1 blocking findings**

- **B1 is resolved.**
  - `_admit` sends `chain=chain(model)` (`model_router.py:889`).
  - The router filters by `knows()` in two places: in `choices` (`:540`) and in the queue-ahead check (`:567`).
  - A 3dfdde3c caller sends no chain, so it is never offered `LATE_ROUTES`. Its own `ordinary_retry` `approved` set is Go, OpenRouter and free, so the router leases everything it counts, and it has no loop.
  - A new caller gets every lane in its chain, and no `disabled_routes` entry is used.
  - The wall is not weakened. `chain` only narrows the router's own `_routes()`, and `excluded_lanes` and `ungated_lanes` are unchanged. The walled DeepSeek and GLM test passes.
  - The 3dfdde3c CHAINS differ from this branch only in DeepSeek's chain, so `LATE_ROUTES = {NW DeepSeek}` is complete.
- **B2 is resolved.**
  - The text now says that the list price is what each step books (`budget.py:1410-1413`).
  - $4.91 against $2.73 checks out: 6.8M uncached input, 149.7M cached and 2.75M completion tokens, priced at each list.

**Findings**

1. **BLOCKING: the preferred rollback (step 5) hard-stops cases, and it contradicts the runbook's own rule.**
   - **Where:** `neuralwatt-routes.md:644` says "prefer moving those batches back with `plumbing_release`" (back to 3dfdde3c).
   - **The rule it breaks:** the runbook already says "A case that ran an NW call is never moved below this release" (`:254`).
   - **What fails:** the DeepSeek stress_tester runs through `ordinary_retry.answer` (`stress_progress.py:10`).
     - A malformed answer on the NW DeepSeek lane adds `neuralwatt/deepseek-v4.1-flash` to `spent_routes` in `ordinary-retries/*/state.json` (`ordinary_retry.py:193`).
     - 3dfdde3c checks `spent_routes ⊆ routes(model, ACCOUNTS)` against its own CHAINS, which lack that lane (`ordinary_retry.py:131-133` at 3dfdde3c).
     - So after the move back, the next `answer()` raises `ordinary_retry_state_invalid`. That is a pit stop.
     - Also on the move back: the ledger rows' `open_steps` tail for that route is no longer in `NW_ROUTES` (`budget.py:433`), so the whole bound gets booked.
   - **Fix (text only):** rewrite step 5.
     - A batch that ran this release is never moved back to 3dfdde3c.
     - The loop-free rollback is to withdraw the key ("Rollout runbook" rollback steps 1-4). `offered_accounts()` then drops every NW lane from `approved`, and `spent_routes` is still checked against `ACCOUNTS`.
     - A DeepSeek-only rollback is a fix-forward release.
     - `disabled_routes` alone stays emergency-only, with its known B1 loop.

2. **NIT: DeepSeek does not "spill to its free lane" while Go is on quota.**
   - **Where:** `:556` (Seats) and `:364` ("On 11-19 … DeepSeek fell to its free lane and booked $0").
   - **Why it is wrong:** `opencode/deepseek-v4.1-flash-free` runs on the Go account pools (`ACCOUNT_FREE_ROUTES`). So in the design's own scenario (both Go plans on quota), that lane is blocked too. The design's own test shows that under the real 11-19 health, a keyless DeepSeek acquire gets `('wait', 'credit')`, not the free lane (`test_neuralwatt_routes.py`, `test_offered_key_gets_the_neuralwatt_lane…`).
   - **Fix:** say that DeepSeek waits for a Neuralwatt seat (`capacity`) or for OpenRouter credit. Note that the attacker on every live case now competes with MiMo for the 3 seats. That is still strictly better than parking on credit.

3. **NIT: stale "twin's list price" comments.**
   - **Where:** `budget.py:434` and `:1411`, `token_prices.py:67` and `:105`, `model_call_gate.py:833-836`.
   - **Fix:** say "its list price (the twin's, or `NW_OWN_PRICES`)", as the updated `model_runtime.py` comment already does.

4. **NIT: the deploy check does not test what the deploy order exists for.**
   - **Where:** step 2 (`:628`) asserts CHAINS and ACCOUNTS only.
   - **The risk:** a bad merge with the router-retry change could drop `'chain'` from the allowed-fields set (`model_router.py:528`). Every new worker would then get `invalid admission fields`, which means `router_unavailable` parks.
   - **Fix:**
     - Run `test_neuralwatt_routes.py` on the merged tree before `unbug install`.
     - Add `and hasattr(m, 'knows')` to the check.
     - Add one line to the rollback: the router is never downgraded below this release while a worker on this release is live.

5. **NIT: the router test helper now models only legacy callers.**
   - `test_model_router.py`'s `acquire()` sends no chain, so all 49 router tests exercise the chainless path.
   - The parallel router-retry change will edit that path with only legacy-path coverage there.
   - **Fix:** give the helper a `chain=True` default, as `test_neuralwatt_routes.py` does, and keep the one DeepSeek legacy assertion explicit.

**Verdict: FAIL** (1 blocking)

## Elephant response (2026-11-20)

Everything is fixed as specified, and nothing is rejected.

- **B1.** Deploy step 5 is rewritten. It now says:
  - never move a batch back to 3dfdde3c, with the `spent_routes` and `open_steps` reasons;
  - never downgrade the router while a worker on this release is live;
  - the loop-free rollback is withdrawing the key (runbook step 6, rollback steps 1-4);
  - a DeepSeek-only rollback is a fix-forward release;
  - `disabled_routes` is for emergencies only.
- **N2.** The 11-19 text and the Seats text are corrected. DeepSeek waits for a seat or for OpenRouter credit, and only GLM spills to an anonymous free lane.
- **N3.** The comments are updated in `budget.py`, `token_prices.py` and `model_call_gate.py`.
- **N4.** Deploy step 1 now runs `test_neuralwatt_routes.py` on the merged tree before `unbug install`, and the step 2 check includes `hasattr(m, 'knows')`.
- **N5.** The `test_model_router.py` helper sends the chain by default. The DeepSeek legacy assertion passes `chain=False` explicitly, and all 49 tests pass.
