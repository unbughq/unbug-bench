# Credit-parked cases wake by themselves (2026-11-20)

Founder, 2026-11-20 ~10:40 UTC: "Let's fix them".

## Problem

- A step that stops `router:credit` parks (`_Case.wait_for_credit`): it naps for its own backoff, then polls
  `credit_ready_step()` every `wake_poll_s`.
- `model_router.credit_ready` is True only when the paid pool (`openrouter-key`) has no credit block. That block
  is `lasting`: it lifts only on `lift_credit`, which needs a top-up above a $5 margin, or on an operator force
  lift.
- The founder will not top up OpenRouter. Most traffic now goes to Neuralwatt first, and a call that parked while
  Neuralwatt was busy, blocked or excluded could now take that lane. Instead the case stays parked for hours:
  1108c sat 80+ minutes on 11-20.

## Change

- `model_router.credit_ready(path, now=None)` is now ready when either:
  - there is no credit block, as before; or
  - the block's `observed_at` (when the router last saw a 402 or a short balance on the pool) is at least
    `CREDIT_RECHECK_S = 1800` old.
- `wait_for_credit` is unchanged. After its own backoff, the case wakes once the block has gone 30 minutes without
  a fresh refusal, and retries once.
  - If the router still refuses the route, the case parks again. Whether a fresh refusal restarts the 30 minutes
    depends on where the refusal comes from:
    - A 402, or a short balance at the gate, restarts the 30 minutes.
    - A refusal at lease time does not. That case naps for its wait's own backoff, which is 900 s or the block's
      end.
  - The retry is a PROVIDER_LIMIT, which `policy.decide` always SLEEPs. So it is never counted or diagnosed, and
    it is booked as now: not waste under `credit_park`.
- Router lift semantics are unchanged: `lift_credit`, `lasting`, the backoff, the cap and the margin.
- The DBOS workflow is unchanged. It makes the same step calls in the same order, so no replay diverges.
  `credit_ready_step` is a recorded step, and its answer is read live only on new calls.
- Why 30 minutes:
  - A parked case has released its worker, so each retry may create one. On 8 November, 15-minute waits by five
    cases spent the campaign's whole creation allowance, so the cadence stays at two retries an hour per parked
    case.
  - The cost of one poll is unchanged: one read-only SQLite row every `wake_poll_s`.
  - ponytail: there is one cadence for every parked case, whatever its chain. Add a per-chain readiness check if
    the retries bite.

## What it deletes

Nothing. The "top-up only" wake becomes "top-up, or 30 quiet minutes".

## Tests

- `tests/factory/test_router_paid_spend.py::PaidTests.test_a_parked_case_retries_once_the_block_has_seen_no_refusal_for_thirty_minutes`,
  on the real router `Store`:
  - A short balance at the gate blocks the pool: not ready at +0 or +1799, ready at +1800.
  - A provider 402 on a call in flight 1000 s later restarts the clock.
  - With no top-up, `lift_credit` still answers `short_by`, the pool still refuses new leases (`credit`), and the
    case is ready to retry.
- `tests/factory/test_durable_engine.py::CreditPark.test_a_parked_case_wakes_without_a_top_up_and_a_refused_retry_parks_again_uncounted`,
  through the real engine, DBOS and the real router books (balance $0.20, never topped up). Actions set
  `CREDIT_RECHECK_S` to 0 ("30 quiet minutes have passed") while the case is parked and to 1800 while the block is
  fresh:
  - Two `router:credit` stops with an infra allowance of 0 park twice without a worker.
  - The case wakes with no top-up and seals, with no diagnosis and 0 waste.
- The existing CreditPark tests (park until a top-up, the lift wake, no block, the pre-patch path) still pass. They
  run within seconds of their block, so inside the 30 minutes.
- Failing first: with `credit_ready` reverted, the router test errors (no `CREDIT_RECHECK_S`) and the engine test
  never wakes.

## Gate identity and verdict code

- `credit_ready` is read only by the controller (`durable/runtime._credit_ready`). It is not a gate-identity input,
  since only `model_router.family` is, and `myident.py` prints identical JSON.
- `model_router.py` is in `VERDICT_CODE`, so main's `verdict_code_pins.model` is recomputed after this commit,
  together with the diagnosis change.
- It reaches running cases with a controller restart. A worker never calls it.

## Murphy row

- `new-credit-park-wake-1`: "A case parked on `router:credit` waits for a top-up that will not come, though its
  chain's Neuralwatt lane could serve it (1108c, 80+ min, 11-20)." Closed by the two tests above.
