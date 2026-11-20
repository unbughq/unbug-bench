# Diff review 1: neuralwatt-first (goldfish)

## Scope
- I reviewed `git diff 3dfdde3c..HEAD -- factory tests` at f99ce6dc. It touches `factory/{token_prices,model_router,model_runtime,budget,model_call_gate}.py`, five test files and two new fixtures.
- I checked the code against the "Neuralwatt first (2026-11-20)" design section, design reviews 1-5 and `docs/ENGINEERING.md`.
- The work was read-only. Mutations ran only in copies under the scratchpad.
- Protected files are untouched: `calibration.py`, `gate_state.py`, `bin/claims.py`, and the files pinned by the sealed delivery contract (`run.py`, `gate_state.py`, `calibration.py`, `sealed_audit.py`, `prompts/pilot.md`, per `tests/factory/test_sealed_audit.py`).

## Tests run
- **On HEAD.** All pass: `test_neuralwatt_routes` (10), `test_neuralwatt_runtime` (8), `test_model_router` (49), `test_free_routes` (9), `test_model_runtime` (11).
- **Mutations.** Script: `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/35da1f8b-8fdf-431c-a84e-d725cb8c71d1/scratchpad/mutate.py`. I made 11 single-line mutations, and at least one test failed for every one:
  - removing `knows` from `choices`: caught by routes and router tests;
  - removing `knows` from the queue-ahead check: caught by routes;
  - emptying `LATE_ROUTES`: caught by routes and router;
  - `_admit` dropping `chain`: caught by routes;
  - `chain` removed from the allowed acquire fields: caught by routes and router;
  - `knows` ignoring the caller's chain: caught by routes;
  - turning off chain validation: caught by routes;
  - `runtime_prices`, `nw_request_worst` or `nw_maximum` falling back to the twin's price: caught by routes (plus runtime for `runtime_prices`);
  - the OpenCode provider cost reverting to the twin's price: caught by runtime.
- **Trial merge with `fix/router-retry`.** I ran `git merge-tree` and got one conflict. I resolved it by hand and ran `test_neuralwatt_routes`, `test_neuralwatt_runtime`, `test_model_router` (52), `test_free_routes`, `test_router_capacity` and `test_router_paid_spend` (60). All pass.

## What I verified
- **Money bounds.**
  - DeepSeek on Neuralwatt has a bound of $0.786432 per request and a maximum of $1.572865 over two windows. Both come from Neuralwatt's own list prices (0.15 / 0.015 / 0.6).
  - The bound holds even if OpenCode's `max_tokens` clamp is ignored: Neuralwatt's own limits (1048560 input at 0.15, 393216 output at 0.6) give $0.393.
  - The record lists no cache-write price, and the profile keeps `cache_write='0'`.
  - Booking (`go_step_cost`), OpenCode's step cost, the tail settle and the pre-stop all read the same profile, so nothing books below the bound.
  - The OpenCode `limit.output` stays at `OPENROUTER_OUTPUT` (32768), the same as the existing twins.
  - `_unfunded` still skips Neuralwatt routes, the same as for MiMo and GLM.
- **Old workers on 3dfdde3c.**
  - MiMo and GLM `nw_maximum` values are byte-identical to 3dfdde3c's (pinned as literals).
  - A caller that sends no chain is never offered `LATE_ROUTES`, in `choices` or in the queue-ahead check.
  - Tombstone payloads and old stored requests have no `chain` and are handled correctly.
  - Attempt ids are `uuid4` per admission (`model_router.py:987/1014`), so "attempt id changed" cannot fire across releases.
  - No old-worker path parses router `status` leases or `price_source`.
  - `ordinary_retry` checks `spent_routes` against set membership, not chain position, so the reordered DeepSeek chain is safe.
- **The isolation wall.**
  - `chain` can only remove lanes from what the router offers; it never adds one.
  - `ungated_lanes` and `bounded_route` cover every route in `NW_ROUTES`, so walled DeepSeek is excluded (tested).
  - `enforce` still refuses `user is not None` on Neuralwatt.
  - The diagnosis environment still never passes the Neuralwatt key.

## Findings

1. **NIT: a nearly spent case wastes a step on the DeepSeek Neuralwatt lane.**
   - **Where:**
     - `factory/model_runtime.py:568-572` sets the funding floor from `request_hold`, which is `None` (counted as 0) for Neuralwatt routes.
     - The router then leases the lane with the funded maximum below $0.786432.
     - `factory/budget.py:1117` then stops the call with `usage_reservation_exceeded` → `model_call_cap` as soon as booked + $0.786432 passes that maximum.
   - **What happens:** when the funding is below about $0.79, the call stops at its first step. The real worst case of one request is about $0.18, and OpenRouter's gated hold for the same model is about $0.16, so that lane would have run.
   - **Not new:** MiMo ($0.570) and GLM ($0.629) already behave this way, and the design chose this bound deliberately (N8). It only matters when a lineage is nearly out of money.
   - **Fix (follow-up):** exclude a Neuralwatt lane when the funding is below `nw_request_worst(route)`, so the call moves on to the next lane. For example, add it to `router_excluded` in the same block at `model_runtime.py:568`.

2. **NIT: merge hazard with `fix/router-retry`.**
   - The only conflict is at `factory/model_router.py:888-889` (`_admit`).
   - Resolve it as `capacity_protocol=2, chain=chain(model))`.
   - If the resolution keeps only one side:
     - dropping `chain` is caught by `test_the_admission_carries_the_callers_chain` (mutation M4);
     - dropping `capacity_protocol=2` is caught only by router-retry's own tests.
   - The resolved merge passes all six router and Neuralwatt test files.
   - The deploy step 1 check (`test_neuralwatt_routes` on the merged tree) also catches `chain` missing from the allowed fields (mutation M5).

3. **NIT: `_nw_profile` hard-codes `endpoint` and `source_date`.**
   - `factory/token_prices.py:84` sets `endpoint='standard', source_date='2026-11-20'` for every entry in `NW_OWN_PRICES`.
   - A second own-price route added later would get the wrong `source_date` in its `price_source`.
   - **Fix:** store the date in the `NW_OWN_PRICES` value, or add a one-line assert that the dict has a single entry. Not worth doing now.

4. **NIT: one router test now covers only the old-caller path.**
   - `tests/factory/test_model_router.py` (`test_real_paid_deepseek_ledger_is_explicit_and_not_rebooked`) now acquires with `chain=False`, so that test only exercises a 3dfdde3c caller.
   - The current-release path (Neuralwatt first) is covered in `test_neuralwatt_routes.py:80-95, 112`, so nothing is lost.
   - **Fix:** none needed. Optionally, also assert that the same acquire with `chain=True` gets `neuralwatt/deepseek-v4.1-flash`.

No blocking findings:
- money bounds hold for every route;
- the wall is not weakened;
- 3dfdde3c workers cannot be handed a lane they reject, or be queued behind one;
- the tests use real fixtures (11-19 router health, e15450 card, the real 3dfdde3c request, the 11-20 Neuralwatt catalog) and fail under every mutation of the new logic I tried.

**Verdict: PASS**

## Elephant response (2026-11-20)

PASS. No code changes in response.

- **N1.** Agreed that this is not new: MiMo and GLM already behave this way at $0.570 and $0.629, and the bound is the design's deliberate N8 choice. A funding-aware lane exclusion is a follow-up. It is not in this change, because it touches the `model_runtime` funding path, which is outside "routes, prices and chains".
- **N2.** The hand-back report names the `_admit` conflict and its resolution (`capacity_protocol=2, chain=chain(model)`), and deploy step 1 catches a merge that drops `chain`.
- **N3.** Left as is. There is one own-price route, and a second one would need its own price record and test anyway.
- **N4.** Already covered in `test_neuralwatt_routes.py`, as the review notes.
