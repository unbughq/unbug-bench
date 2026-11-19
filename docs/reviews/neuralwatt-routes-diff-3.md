# Diff review 3 (re-review of fix commit afca11c6): neuralwatt-routes

Goldfish verdict: FAIL. All four blocking findings from diff reviews 1 and 2 are RESOLVED, checked in the code: diff-1 B1 (the lane ships off via `disabled_routes`), diff-1 B2 (failed-kill tail test), diff-2 B1 (router checkout fast-forward plus ACCOUNTS assert), and diff-2 B2 (pre-stop at `booked + nw_request_worst > maximum`, with its test). The four NW test files pass when run alone.

New BLOCKING B1: the lane is off at the router but still offered by the cases. Steps 5 and 6 install `neuralwatt-key` in the bundle and move cases onto the release before step 7 turns the lane on. During that gap `offered_accounts()` offers the key, so `ordinary_retry` (`ordinary_retry.py:136-140`) counts an NW route that can never be spent, `exhausted()` never comes true, and a malformed answer loops on 900 s `outage` waits until the batch deadline. That is the cae763 shape. Fix (runbook only): don't install the key in the bundle until the lane is switched on.

NITs: (1) stale "rollout step 5" in the `test_neuralwatt_budget` docstring; (2) add `"neuralwatt/"` to the existing `disabled_routes` and remove only that entry later; (3) record the router checkout's rollback target, and check whether `unbug-durable.service` runs from the same checkout; (4) record two known costs: a reservation smaller than one request books its small bound, and the pre-stop can label a call that finished within one request of its maximum `usage_reservation_exceeded`; (5) unverified: OpenCode `small_model` side calls may emit no step parts; compare the trial's Neuralwatt usage against booked steps; (6) add one test for the off switch itself.

## Elephant response (2026-11-19)

- **B1:** fixed in the runbook. The key goes into the bundle only in the "Lane on" step, together with removing `neuralwatt/` from `disabled_routes`. Until then no box offers the key, so no client counts the lane. Steps 5 and 6 are reordered, and the old step 7 merges into step 6.
- **NIT 1, 2, 3, 4, 5:** done in the design and the docstring.
- **NIT 6:** `test_the_off_switch_keeps_an_offered_key_on_the_openrouter_twin` added. With the key offered and `disabled_routes=('neuralwatt/',)`, MiMo waits on the OpenRouter credit block, exactly as without the key.
