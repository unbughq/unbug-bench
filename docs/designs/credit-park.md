# Credit park

Founder ruling, 15 November: when a model runs out of credit mid-run, "checkpoint the case and cleanly
stop. Don't lose any progress." It resumes where it was once credit is back.

## Before

A provider 402 and the router's own pre-check refusal both end the step `router:credit`. The engine slept
900 s on the same worker and retried, forever. After a 402 the router's credit block never expired, so
every case on the pool looped until a manual DB edit. After a pre-check refusal no block was written, so
cases retried blind every 15 minutes. The attempt's spend was booked as waste.

## After

- **Router** (`model_router.py`). A short balance (paid_reserve) or a 402 (observe) blocks the paid pool
  `openrouter-key` for credit. `Store.lift_credit`, run every reconcile pass, reads the balance and lifts
  the block once it pays one request of the dearest gated route on top of the holds in flight. It never
  lifts inside a 402's backoff (15, 30, 60 minutes). After three refusals in a row it stops: the guard
  alerts "credit refused 3x despite balance: check key limit", and the operator runs
  `model_router.py --config <cfg> --lift-credit`. A credit block on any other pool has no readable
  balance, so it expires on its backoff. A Go seat wait wins over the paid pool's credit wait.
- **Engine** (`engine.py`, patch `credit_park`). A `router:credit` stop settles with no waste: its snapshot
  keeps every passed gate. If the paid pool is blocked, the case releases its worker and parks as
  `waiting_for_credit`. After its backoff it polls `model_router.credit_ready` every `wake_poll_s` until
  the block is lifted and the router's books fund one request of the step's dearest model. It then
  clears its `router:credit` reason and retries once. The retry is uncounted and never diagnosed. A
  refusal with no block (the ceiling, an unreadable balance) keeps the old short sleep on its worker.

## Limits

- **Herd.** Cases that poll in the same `wake_poll_s` window all see the same balance. Only the first
  paid_reserve raises the holds in flight, so more cases can wake than one lift pays for. Each extra one
  is refused at its first request and parks again: one attempt each, not a loop.
- **Stale balance.** `credit_ready` reads the balance from the last lift pass or the last paid request,
  not a live one.
- **Refusal count.** The count of refusals is the pool's failure count, which also counts its 429s
  since the last finished call.

## Deploy

The router reads the new rules only after a restart. Restart it drained (no model calls in flight).
