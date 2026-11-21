# The campaign deadline drains, it does not cut (2026-11-21)

**What broke (2026-11-21 06:10 UTC).** At `deadline_epoch` the guard (`guard.py` `run`) took the deadline as a
hard stop. It stopped `unbug-durable-case-campaign.service` and deleted every worker. Six cases froze mid-gates,
some with 15 of 17 gates passed. The engine already reads the batch deadline as "stops new cases, extensions and
held-resumes, not a running step", and the controller refuses every worker acquire after it (`assess`). Only
the guard cut running steps. Its TTL renewal also stopped at `deadline + checkpoint grace`.

**Fix (one condition, one TTL).**
- The early hard stop fires at `deadline_epoch + policy.GATES_DEADLINE_S` (12 h, the longest step deadline), not
  at the deadline. The wind-down then adds the usual checkpoint grace. So the drain ends by
  `deadline + 12 h + CHECKPOINT_GRACE_S` at the latest. That is finite and needs no new state.
- Between the deadline and that ceiling the pass runs as before: Boat breach checks, ledger and router money,
  case status, renewal. After the controller checks, a `deadline` hard stop fires as soon as an active
  controller answers `in_flight == 0`. Nothing new can start after the deadline, so 0 means the drain is done.
  An unknown answer (rpc failure, down or unknown service) never reads as 0. It drains on until the ceiling.
- A finished campaign (every case terminal, published) finishes as before. It is not also hard-stopped.
- The TTL is `min(WORKER_TTL_S, deadline + GATES_DEADLINE_S + grace - now)`, so it covers the drain.
- Every other hard stop (money, compute bound, worker count, allowance, rate, cleanup) is unchanged. They now
  also apply during the drain.

**Known gap (founder decision, not changed here).** `compute_bound` still counts each running slot for
`wall_seconds + grace`, not the drain. Changing the formula could make the live request stop `compute_bound`
or be refused at controller start. During the drain, live workers' real Boat spend past the bound is still a
`worker_rate` hard stop.

## Murphy rows

The register is not on main. The new row, to be numbered at merge:
- `new-guard-deadline-drain-1`: the guard hard-stops at the deadline and deletes workers under running steps,
  so cases freeze mid-gates. Closed by
  `test_durable_guard.test_a_step_in_flight_drains_past_the_deadline_renewed`,
  `test_the_ttl_covers_the_drain_and_its_grace`, `test_an_unanswering_or_down_controller_drains_until_the_ceiling`
  and `test_money_still_hard_stops_during_the_drain` (all four fail on the old code).
  `test_deadline_with_nothing_in_flight_is_a_hard_stop` and
  `test_the_drain_ceiling_is_a_hard_stop_with_steps_still_in_flight` pin the two ends.
