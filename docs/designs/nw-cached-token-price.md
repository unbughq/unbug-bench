# Neuralwatt cached tokens at their list cache rate

**What broke (cae763-h6, G10, 2026-11-20 19:57 and 11-21 01:52 UTC).** The easy calibrator on `neuralwatt/glm-5.3-flash`
stopped `model_call_cap` twice. The gate priced every cached prompt token at the full input rate ($0.15/M), because
Neuralwatt's usage has no `cost` field. Tries were ~98% cached: about $1.10 counted against a $1.09 window for about
$0.25 at Neuralwatt's list. The diagnosis called the case close_to_passing and the engine retired it with 13 gates passed.

**Fix.** `openrouter_cached_tokens(usage, route)` also counts cached tokens on a Neuralwatt route, and
`openrouter_gate_cost` prices them at the profile's cache rate there.
- Neuralwatt's list cache rates are the pins (GLM $0.03, MiMo $0.0036, DeepSeek $0.015; price record 2026-11-20).
- Its pricing page says no standard request costs more than its listed price, so the count is never below the bill.
- OpenRouter routes are unchanged: without `usage.cost` they still get no cache discount.
- Requests that end without usage still keep their whole hold (`test_unknown_request_holds_still_bound_the_easy_calibrator`).

## Murphy rows

The register is not on main. The new row, to be numbered at merge:
- `new-nw-cached-price-1`: the gate counts Neuralwatt's cached tokens at the full input price, so cache-heavy
  walled calibrators stop `model_call_cap` at a quarter of their window. Closed by
  `test_cached_window.test_neuralwatt_cached_tokens_at_its_list_cache_rate` (fails on the old code).
