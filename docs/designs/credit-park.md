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
  `openrouter-key` for credit. A 429 or quota on a call in flight only lengthens it. `Store.lift_credit`,
  run every reconcile pass, lifts it once the balance read pays the holds in flight, one request of the
  dearest gated route and a fixed $5 margin (`LIFT_MARGIN_USD`): settling holds cannot free that much,
  so a lift means a top-up. It never lifts inside a 402's backoff (15, 30, 60 minutes). After three 402s,
  each after a lift with no call finishing done between them, it stops: the guard alerts "credit refused
  3x despite balance: check key limit", and the operator runs `model_router.py --config <cfg>
  --lift-credit` with `OPENROUTER_API_KEY` set; it prints `lifted` or why not (`no_block`,
  `balance_unreadable`, `short_by $X`). 402s while blocked, low-balance refusals and 429s never count.
  A credit block on any other pool has no readable balance, so it expires on its backoff. A Go seat
  wait wins over the paid pool's credit wait.
- **Worker** (`classify.py`). Only the paid pool's credit stop is `router:credit`. Another pool's 402
  (OpenCode) is that provider's limit (`router:opencode_limit`) and keeps its short backoff.
- **Engine** (`engine.py`, patch `credit_park`). A `router:credit` stop settles with no waste: its snapshot
  keeps every passed gate. If the paid pool is blocked, the case releases its worker and parks as
  `waiting_for_credit`. After its backoff it polls `model_router.credit_ready` every `wake_poll_s` until
  the block is lifted; it checks only the block. It then clears its `router:credit` reason and retries
  once. The retry is uncounted and never diagnosed. A refusal with no block (the ceiling, an unreadable
  balance, unreadable router books) keeps the old short sleep on its worker. The guard excludes a parked
  case from its "no progress" alert, as it does `held_for_release`.

## Limits

- **Herd.** A lift wakes every parked case, whatever its step costs. Each one the balance cannot fund is
  refused at its first request and parks again: one attempt each, not a loop, since the next lift needs
  another top-up. (An earlier version also compared the balance with the step's dearest call, Claude
  routes included; a small top-up then lifted the block and woke no one, for good.)
- **Margin.** With less than $5 over the dearest call the block stays until a top-up or `--lift-credit`.

## Patch name

The patch stays `credit_park`. The first version with it (cea82524) was never deployed: the VM ran
6109d786, then d3504089, so no recorded workflow has its step shape.

## Deploy

Restart the router first, drained (no model calls in flight), then the controller. A controller on the
new engine with the old router would park on blocks that never lift.
