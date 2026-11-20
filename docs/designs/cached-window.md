# Cached prompt tokens in the model-call gate's window

Closes Murphy row `new-cached-window-1` (recorded in `fix/diagnosis-continue-cb5e26`,
`docs/designs/diagnosis-continue.md`): "the model-call gate prices cached prompt tokens at the full
input rate, so a long cached session hits `model_call_cap` far below its real cost".

## Problem

- The worker gate (`model_call_gate.Allowance`) counts each OpenRouter request with
  `token_prices.openrouter_gate_cost`. That prices every prompt token at the full input rate, though
  OpenRouter reports `prompt_tokens_details.cached_tokens` and its own charge (`usage.cost`, always
  asked for: `openrouter_body` sets `usage.include`).
- The lease's input-token cap is `max_usd / input price`, and the gate counts whole prompt tokens
  against it, so it binds at the same point.
- The router's paid ledger (`model_router._paid_charge`) and the case ledger (OpenCode's step cost at
  `runtime_prices`, which has the cache-read rate) already price cache reads correctly. Go and
  Neuralwatt steps (`go_step_cost`) do too, and have no input-token check. Claude's gate prices cache
  reads at their rate and its input cap is at the cheapest rate. Only the OpenRouter gate is wrong.

## Measured (router `factory.sqlite3` on the control VM, 13-20 November)

- 735 OpenRouter leases with paid requests. Summed over them, the gate counted $647.66 where the
  router booked $119.21 from OpenRouter's own charges. This is an in-call count, not booked money.
- Four leases, replayed at the full rate, leave no room for one more request (`model_call_cap`); all
  four ended `interrupted`:

  | lease | when (UTC) | role, model | window | gate counted | billed | cached | with this change |
  |---|---|---|---|---|---|---|---|
  | 412ba567 | 11-19 19:03 | cb5e26 diagnosis 1-1, MiMo | $12.50 | $12.05 | $2.40 | 74% of 27.6M | $3.19, fits |
  | a14a21d1 | 11-15 15:59 | reviewer2, GLM | $2.09 | $2.06 | $0.99 | 98% | $1.27, fits |
  | 1d921598 | 11-19 18:22 | cb5e26 G10 easy calibrator, GLM | $1.26 | $1.09 | $0.05 | 97% | $0.92, fits at that point |
  | e11c7bb2 | 11-19 18:29 | cb5e26 G10 easy calibrator, GLM | $1.26 | $1.24 | $0.05 | 97% | $1.09, still cut |

- The cut calls' real spend was $3.49 ($2.40 of it the diagnosis). The larger loss is the work: the
  diagnosis was cut, and cb5e26's G10 went to diagnosis.
- **Not this row:** the G10 easy calibrator's second cut (e11c7bb2) is driven by six requests whose
  stream ended without usage. The gate holds each one's whole worst case ($0.17 of a $1.26 window,
  $1.04 together; the router later settled them by generation id at cents). This change does not
  fit them and must not. That is a separate failure for its own row.

## Change

- `token_prices.openrouter_gate_cost`: when the usage carries OpenRouter's own charge, price
  `cached_tokens` at the route's pinned cache-read rate, and never below that charge:
  `max(full - cached * (input - cache_read), cost)`. Without `cost` it stays at the full rate.
- `openrouter_cached_tokens(usage)`: the cached count the gate discounts, `0` without `cost`, `None`
  (invalid usage, the request keeps its hold) when the details are malformed or exceed the prompt.
- `model_call_gate.Allowance.amount`: a discounted cached token counts against the input-token cap as
  `cache_read / input` of a token (rounded up), the same scaling as its cost. The lease, its maximum,
  `price_source`, request holds and the router are unchanged, so leases in flight stay valid.

## Money safety

- Each validated request is booked at least at OpenRouter's own charge for it, and at most at the full
  rate (a charge above the full rate is still invalid, as before). Requests without usage keep their
  whole hold. So the gate's settled plus held amount still bounds real spend.
- A serving endpoint whose cache read costs more than the pin (the `cheaper` endpoints were checked on
  input and output price only) is covered by the charge floor, which is why no discount is given
  without `cost`.
- The input cap stays redundant with the money cap: counted inputs times the input price never exceed
  the counted cost.

## Gate identity

- Touches only `factory/token_prices.py` and `factory/model_call_gate.py`. Neither is in
  `gate_state.STAGE_DEPENDENCIES`, `runner_inputs` (which hashes `run.py` source only) or
  `model_science` (`model_router.family`, `model_runtime.model_effort`), and neither
  `calibration.py` nor `exam_responder.py` imports them. No sealed fingerprint moves.

## Deletes

Nothing.

## Tests

`tests/factory/test_cached_window.py`, on the router's recorded usage of the four leases
(`tests/factory/fixtures/cached-window-leases-20261119.json.gz`, token counts and charges only):

- every recorded request is priced between its bill and the full rate, and at the full rate without
  `cost`;
- the cb5e26 diagnosis replay reproduces the row ($12.05, 27.6M, 74%, $2.40) and now fits with room
  for another request, settled at no less than its bill;
- the GLM reviewer2 lease fits;
- the easy calibrator lease with six usage-less requests is still cut.

## Deploy

Worker-side code (`token_prices.py`, `model_call_gate.py`): reaches new launches through the normal
plumbing deploy. No router or controller restart.
