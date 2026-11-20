# Design review 1: neuralwatt-first (goldfish)

Scope: `docs/designs/neuralwatt-routes.md` §"Neuralwatt first (2026-11-20)" (lines 327-563), checked against the code on `feat/neuralwatt-first` (b8cec463) and its fixtures. Lenses applied: zoom_out, design_critic, implementation_readiness.

Claims that check out:
- DeepSeek maximum: $1.572865 (2 × 0.786432 + 0.000001).
- One request's real worst case: $0.177, which is below `nw_request_worst`.
- The 11-20 record has `deepseek-v4.1-flash` at 0.15 / 0.015 / 0.6, `max_model_len` 1048560 and `max_output_tokens` 393216.
- MiniMax and Muse are not served.
- `disabled_routes` matches by prefix (`model_router.py:446`).
- The old worker's `_admit` raises `invalid lease response` before it calls `finish` (`model_router.py:880-885`).
- MiMo and GLM `price_source` strings stay byte-identical.
- The wall stays intact: `ungated_lanes`, `bounded_route` and `enforce` are all keyed on `NW_ROUTES`.

1. **BLOCKING: the off switch, and the deploy order, bring back the cae763 loop for new-release workers.**
   - **The claim is wrong.** The design (line 428) says new workers are safe because they know the lane. With the switch on, they are exposed: a new-release worker offers `neuralwatt-key`, and its `CHAINS` contain `neuralwatt/deepseek-v4.1-flash`, but the router never leases that lane.
   - **Why that loops.**
     - `ordinary_retry.answer` builds `approved` from the worker's own chain (`factory/ordinary_retry.py:136-140`), so that lane is never spent and `exhausted()` never comes true.
     - `await_lease`'s `exhausted` is false for the same reason (`model_router.py:958`).
     - With every other lane spent or excluded, the router's `choices` is empty, so it answers `outage` with a 900 s wait (`model_router.py:563-568`).
   - **This was already caught and fixed once.** It is the exact shape of diff-3's B1 (`docs/reviews/neuralwatt-routes-diff-3.md:5`), and `offered_accounts()`'s docstring warns about it (`model_runtime.py:70-75`). The original rollout avoided it by ordering steps "key first, lane last".
   - **Who it hits.** DeepSeek is the stress_tester (attacker) on every live case, and the real request fixture is a stress_tester call. The window covers:
     - from deploy step 1 (`source-current`) to the router restart (old router chains);
     - then the whole time the switch is on, which is days, until the 3dfdde3c batches retire.
   - **Fix:**
     - Preferred: add the protocol flag now and delete the off switch, its second restart and new-neuralwatt-3's operator step.
       - Add one optional acquire field, e.g. `nw_chain: 2`, to the allowed set at `model_router.py:507`.
       - In `choices`, drop `neuralwatt/deepseek-v4.1-flash` when the field is absent.
       - `_admit` sends the field.
       - That is about 3 lines in the acquire path. Coordinate it with the router-retry change as a small merge rather than avoiding it.
     - If the switch stays: add a test showing this does not loop. Use a new-release DeepSeek stress `ordinary_retry` on the real 3dfdde3c request, with the switch on and every other lane spent, and show it reaches `exhausted()` or a bounded park. The current code says it won't.

2. **BLOCKING: the design says list price "is only the reservation bound", but it is also what each step books.**
   - The design says this at line 355. In fact every NW step books `max(OpenCode cost, go_step_cost)` as real case money (`factory/budget.py:1410-1413`). After this change, `runtime_prices` / `go_step_cost` return Neuralwatt's own list.
   - **Effect on case money.** DeepSeek on Neuralwatt books more than it booked on OpenRouter for the same tokens:
     - uncached input: 1.07×;
     - output: 1.43×;
     - cache reads: 3.57× (0.015 against 0.0042).
   - Under the real 11-19 state (OpenRouter credit-blocked), DeepSeek fell to the free lane, which booked $0. It now books list.
   - **Fix:**
     - Correct the text.
     - State the effect on case money, e.g. re-price the 7-day DeepSeek token mix behind the $12.37 at Neuralwatt list.
     - Record that the founder's "Neuralwatt anyway" covers case money booked at list, not only the provider's price. Reconciliation stays out of scope, but the over-count is then a known cost.

3. **NIT: `service_tier == "standard"` does not rule out speed lanes.**
   - In the 11-20 record, `deepseek-v4.1-flash-speed` also has `service_tier: "standard"` and the same 0.15 / 0.015 / 0.6, even though the statement says speed lanes are priced above list. So line 390 and the test at line 531 prove nothing about lane choice.
   - **Fix:** assert that the provider-block model id equals the record's base id, with no `-speed` or `-flex` suffix. Keep `service_tier` only as a secondary check.

4. **NIT: two existing tests assume every Neuralwatt route has the same price as its twin.**
   - `test_neuralwatt_routes.py:100-111` asserts `runtime_prices(route) == runtime_prices(twin)` and the `twin=` source for every `NW_TWINS` entry.
   - `:115-125` looks up every `NW_TWINS` name in the 11-19 record, which holds only mimo and glm, so DeepSeek would fail with a KeyError.
   - **Fix:** the design should say both loops run over `NW_TWINS.keys() - NW_OWN_PRICES.keys()`.

5. **NIT: the wall test misses a real walled DeepSeek role.**
   - The real card `e15450-collected-card.json` has `easy_calibrator: opencode/deepseek-v4.1-flash-free`, so DeepSeek does reach a walled role. The inventory says "attacker, builder" only.
   - **Fix:**
     - Add a walled DeepSeek acquire, with `ungated_lanes` excluded, to the wall test.
     - Option A's $/day should count any live walled DeepSeek calibrators.

6. **NIT: there is no real DeepSeek step through OpenCode.**
   - The 11-20 smoke was direct, not through OpenCode, and was not saved. DeepSeek reasons by default ("high").
   - **Fix:**
     - Save that smoke as a fixture.
     - Before removing the switch, capture one OpenCode step with the factory config, as the 11-19 run did for MiMo and GLM, and confirm it carries non-zero tokens including reasoning.

7. **NIT: costs and seat behaviour are understated.**
   - Add DeepSeek's $0.786 per-request tail and pre-stop to "Known costs, recorded" (line 258 lists only MiMo and GLM).
   - The Seats section leaves out two things:
     - When the Neuralwatt seats are full, DeepSeek and GLM spill to their free lanes, because of chain order (`model_router.py:540-547`).
     - Spill of MiMo, GLM and DeepSeek onto OpenRouter drains the $10 that Option A's three-week estimate keeps for walled roles.
   - "Concurrency not measured": it can be measured read-only from the router ledger's `leases` table. Do that before relying on 3 seats.
   - "About 45% of list" has no source. Lines 23-24 say 20% and 27% below list.

**Verdict: FAIL** (2 blocking)

## Elephant response (2026-11-20)

Both blocking findings are fixed in the design, and nothing is rejected.

**B1.** The off switch is gone. Its replacement is a general version of the suggested flag:
- `_admit` sends `chain`, the caller's own chain.
- The router offers only lanes the caller `knows`, both in `choices` and in the queue-ahead check. Without the second, a waiting 3dfdde3c DeepSeek request queued ahead of every newer Neuralwatt request.
- A caller with no chain is never offered `LATE_ROUTES`.
- There is no second restart. The deploy order puts the router first, because an old router refuses the field.
- Tests use the real 3dfdde3c request. Removing either `knows` filter makes them fail.

**B2.** The text is corrected. On the real 7-day OpenRouter DeepSeek mix, case money booked at Neuralwatt list is $4.91, against $2.73 at the OpenRouter pin. That over-count is now recorded as covered by the founder's "Neuralwatt anyway".

**Nits:**
- N3: the provider-block ids are checked to carry no `-speed` or `-flex` suffix.
- N4: both loops now run over `NW_TWINS` minus `NW_OWN_PRICES`.
- N5: there is a walled DeepSeek wall test, and the inventory notes the walled DeepSeek role.
- N6, partly done: the smoke stays in the operator scratchpad, because no test reads it.
  - The OpenCode capture is not done. It would mean copying the key onto a live case's box.
  - It is replaced by a first-hour check after deploy.
- N7:
  - the DeepSeek tail is added to "Known costs";
  - concurrency is measured: 3 seats cover about 96% of the time;
  - the spill to free lanes and onto OpenRouter is described;
  - the 45% figure is attributed to the operator's measurement.
