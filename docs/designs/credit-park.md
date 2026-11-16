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
  `openrouter-key` for credit and records the balance last read. `Store.lift_credit`, run every reconcile
  pass, lifts the block only after a top-up: the balance read must exceed the recorded one by more than
  one request of the dearest gated route, and pay that request on top of the holds in flight. Headroom
  from holds settling is not a top-up. It never lifts inside a 402's backoff (15, 30, 60 minutes). After
  three credit refusals (402s and short balances, counted apart from 429s) with no call finishing between
  them, it stops: the guard
  alerts "credit refused 3x despite balance: check key limit", and the operator runs
  `model_router.py --config <cfg> --lift-credit`. A credit block on any other pool has no readable
  balance, so it expires on its backoff. A Go seat wait wins over the paid pool's credit wait.
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
- **No top-up, no lift.** A block whose balance would pay once old holds age out stays until a top-up or
  `--lift-credit`. A 402 from the key's own limit with no top-up stays parked; the cards' "Top it up"
  reason is the alert.

## Patch name

The patch stays `credit_park`. The first version with it (cea82524) was never deployed: the VM ran
6109d786, then d3504089, so no recorded workflow has its step shape.

## Deploy

The router reads the new rules only after a restart. Restart it drained (no model calls in flight).
