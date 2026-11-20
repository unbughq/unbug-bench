# Credit-parked cases wake by themselves (2026-11-20)

Founder, 2026-11-20 ~10:40 UTC: "Let's fix them".

## Problem

- A step that stops `router:credit` parks (`_Case.wait_for_credit`): it releases its worker, naps for its own
  backoff, then polls `credit_ready_step()` every `wake_poll_s`.
- `model_router.credit_ready` is True only when the paid pool (`openrouter-key`) has no credit block. That block
  is `lasting`: it lifts only on `lift_credit`, which needs a top-up above a $5 margin, or on an operator force
  lift.
- The founder will not top up OpenRouter. Most traffic now goes to Neuralwatt first, and a call that parked while
  Neuralwatt was busy, blocked or excluded could now take that lane. Instead the case stays parked for hours:
  1108c sat 80+ minutes on 11-20.

## Change

- `_Case.wait_for_credit`, under a new DBOS patch `credit_park_recheck`: the wake loop ends when the block lifts,
  as before, or after `Timing.credit_recheck_s` (1800 s) of polling, whichever comes first. The case then retries
  once.
- `model_router.credit_ready` is unchanged, and so is the SLEEP branch that calls it before parking. A retry the
  router still refuses with `router:credit` finds the block there and parks again, releasing its worker. Each
  park gives at most one retry, wherever the refusal came from (a 402, a short balance at the gate, or a refusal
  at lease time).
- The retry is a PROVIDER_LIMIT, which `policy.decide` always SLEEPs. So it is never counted or diagnosed, and
  under `credit_park` it is booked as the case's spend, not waste.
- Router lift semantics are unchanged: `lift_credit`, `lasting`, the backoff, the cap and the margin.
- Replay: a park that had already polled before the patch has `credit_ready_step` recorded at the patch's
  position, so `DBOS.patch` answers False there and it keeps the unbounded wait, as recorded. A case parked at
  deploy (1108c) therefore still waits for a lift; one still in its first backoff nap, and every later park, wakes
  by itself.
- Why 30 minutes:
  - A parked case has released its worker, so each retry creates one. On 8 November, 15-minute waits by five
    cases spent the campaign's whole creation allowance. 30 minutes keeps it under two creations an hour per
    parked case.
  - Each case's own park sets its clock, so cases parked on one block wake staggered, not together.
  - The poll cost is unchanged: one read-only SQLite row every `wake_poll_s` (300 s).
  - ponytail: one cadence for every parked case, whatever its chain. Add a per-chain readiness check if the
    retries bite.

## What it deletes

Nothing. The "top-up only" wake becomes "top-up, or 30 minutes parked".

## Tests

- `tests/factory/test_durable_engine.py::CreditPark.test_a_parked_case_wakes_without_a_top_up_and_a_refused_retry_parks_again_uncounted`,
  through the real engine, DBOS and the real router books. The balance is $0.20, never topped up, so the block
  stays the whole time and `credit_ready` stays False. `credit_recheck_s` is 1 s.
  - Two `router:credit` stops with an infra allowance of 0 park twice. Each park releases its worker before its
    one retry starts.
  - The case seals with no diagnosis and 0 waste.
  - With the patch disabled (a recorded park), there is no retry until a top-up lifts the block.
- The existing CreditPark tests (park until a top-up, the lift wake, no block, the pre-patch path) still pass.
  They use the 1800 s default, so their parks end on the lift.
- Failing first: with `wait_for_credit` reverted, the new test never wakes (the block never lifts).
- Real-artifact gap: the second refusal is a scripted `router:credit` stop, not a lease-time refusal by the real
  router. The engine parks on the real router books either way, which is what the test proves.

## Gate identity and verdict code

- Only `durable/engine.py` changes (controller side). It is neither a gate-identity input nor in `VERDICT_CODE`,
  and `myident.py` prints identical JSON.
- It reaches running cases with a controller restart. A worker never calls it.

## Murphy row

- `new-credit-park-wake-1`: "A case parked on `router:credit` waits for a top-up that will not come, though its
  chain's Neuralwatt lane could serve it (1108c, 80+ min, 11-20)." Closed by the engine test above.
