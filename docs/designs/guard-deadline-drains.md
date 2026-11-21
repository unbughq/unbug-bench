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

**The cleanup timer still cuts at once.** `control/campaign/unbug-case-campaign-deadline.timer` runs
`campaign_guard.py --cleanup`, and `run` treats `cleanup` as an immediate `deadline` hard stop. This change
leaves that alone. The operator must keep that timer disabled, or set it at or after the drain ceiling
(`deadline + GATES_DEADLINE_S + CHECKPOINT_GRACE_S`). On the live VM its `OnCalendar` was 2026-11-15 06:00 UTC.
It has fired and has no next run, so it cannot cut today's drain.

## Known gaps (goldfish NITs, not changed here)

- **No SEAL during the drain.** The controller's `assess` refuses every worker acquire after the deadline. A
  case whose GATES step finishes in the drain therefore cannot start its SEAL step. The drain saves the gate
  results, but sealing still needs a raised deadline.
- **The ceiling is a little short.** A GATES attempt started just before the deadline can run until
  `deadline + deadline_s`. The engine then polls for `POLL_GRACE_S` (900 s) and the result still has to
  transfer. The ceiling is `deadline + GATES_DEADLINE_S + CHECKPOINT_GRACE_S` (600 s), so it is shorter than
  `deadline_s + POLL_GRACE_S + transfer time`. A step that uses its whole deadline can still be cut at the end.
- **Long renewals just before the deadline.** The TTL now covers the drain, so renewals just before the
  deadline are 7200 s, not the time left plus the grace. If the guard dies, a worker can outlive the deadline
  by up to 2 h.
- **Compute past the approval (needs founder OK).** `compute_bound` still counts each running slot for
  `wall_seconds + grace`, not the drain. A drain can therefore take compute past `approved_infrastructure_usd`
  by up to `max_running_sandboxes × GATES_DEADLINE_S × rate`. I did not change the formula, because that could
  make the live request stop `compute_bound` or be refused at controller start. The `worker_rate` backstop
  (real spend past the bound) does not help here. On the live campaign (`max_running_sandboxes` 26,
  `wall_seconds` 86400) it cannot fire within a 12 h drain.
- **No Boat-breach test during the drain.** Money is tested during the drain
  (`test_money_still_hard_stops_during_the_drain`). Boat count, allowance and rate breaches during the drain
  run through the same `_breach` call but have no test of their own.

## Murphy rows

The register is not on main. The new row, to be numbered at merge:
- `new-guard-deadline-drain-1`: the guard hard-stops at the deadline and deletes workers under running steps,
  so cases freeze mid-gates. Closed by
  `test_durable_guard.test_a_step_in_flight_drains_past_the_deadline_renewed`,
  `test_the_ttl_covers_the_drain_and_its_grace`, `test_an_unanswering_or_down_controller_drains_until_the_ceiling`
  and `test_money_still_hard_stops_during_the_drain` (all four fail on the old code).
  `test_deadline_with_nothing_in_flight_is_a_hard_stop` and
  `test_the_drain_ceiling_is_a_hard_stop_with_steps_still_in_flight` pin the two ends.

## ARCHITECTURE.md left unchanged on purpose

Root `*.md` files are G8/G9 dependencies (`factory/gate_state.py` `DEPENDENCIES`). Editing ARCHITECTURE.md's
guard paragraph re-keyed G8 and G9 on every case moved to the new plumbing, so the edit was reverted
to its 0b204264 bytes. Its guard paragraph still says the deadline is a hard stop; this note supersedes it:
the deadline stops new work, not a running step; the guard keeps renewing until no step is in flight, or
`GATES_DEADLINE_S` past the deadline.
