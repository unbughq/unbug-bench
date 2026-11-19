# Diff review 9: neuralwatt item 8 confirm on 53396b51 (goldfish)

**PASS.** I found nothing blocking.

1. **`configured_model` is the right variable.** `_invoke` takes the lease's route (`model_runtime.py:634`), passes it as `configured_model=model` (`:938`), and builds `-m` from it (`:817`). For a reserved call, `budget.py:1044` rejects any run whose reservation route differs from `configured_model`, so on an NW lease it always equals `lease.route`, which is in `NW_ROUTES`. `provider_model` would also work, but its value is the same.
2. **Go and free lanes behave exactly as before item 8.** I compared `d329ae64` with `53396b51`. On a non-NW route `terminal` is now `False`, which is the default of the parameter added in c7fd7ccf. So `diagnostic` follows the same path it did at d329ae64. `provider_diagnostic` and the classifier are unchanged. I ran the tests on scratch copies of the code:
   - With the fix: 15/15 pass.
   - With c7fd7ccf's `budget.py` swapped in: the new Go test fails as expected (it gets `rate`/`account` on `opencode-go/mimo-v2.6-pro`). So the test does pin the narrowing.
3. **The doc text in item 8 is accurate.** The new "Neuralwatt lanes only" wording matches `budget.py:1367`. So do "OpenCode's own retries", the pool-keyed `rate` blocking the Go account, and the 900 to 3600 s block. "Go if its plan has quota, else the OpenRouter twin" fits the Go → NW → OpenRouter chain order (`neuralwatt-routes.md:40`, `token_prices.py:64`).

One non-blocking note: the narrowing still lets the rate allowance swallow a single Go 429. This is deliberate, and the elephant response already records it.

## Elephant response (2026-11-19)

PASS, nothing to change. The note on the Go allowance was already recorded in review 8.
