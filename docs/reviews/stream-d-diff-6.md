# Stream D diff review 6: increment 2, runtime and pending-unit integration

**Verdict: NOTPASS.** There are two blocking findings. Both are wiring bugs inside the present scope, and both reproduce against the committed code at 9c1f610.

**What I reviewed.** The committed diff `5bc8224..9c1f610` and the files it touches. I read both persona files and the implementation-readiness standard first, then `docs/ENGINEERING.md`, Murphy rows 8–13, 15, 21, 35 and 39, and `docs/designs/stream-d.md` including the Increment 2 scope. I also read `job_authority.py` and the router paths the diff depends on (`await_lease`, `finish`, `running`, the `Store` RPC).

**What I did not do.** I did not read interfaces.md §§2/3/5/7, router.md, invalid-runs.md, B §8 or prior reviews 1–5, so I did not re-test the earlier accounting assumptions. I made no edits and ran no launches. I ran only `tests/factory/test_stream_d_runtime.py` (12 tests, all pass) and three throwaway repros that import the real modules. The repros are outside the repo:
- `/private/tmp/claude-501/-Users-bugsincode--t3-worktrees-unbug-bench-t3-21bef30c/a1feaf29-881b-4305-a4cf-ab48ec70737b/scratchpad/repro1.py`
- `.../scratchpad/repro2.py`
- `.../scratchpad/repro3.py`

Run each with `uv run --with numpy --with scipy python -B <path>`.

`docs/designs/stream-d.md` showed as modified (uncommitted) in the working tree. I reviewed only the committed version.

## Blocking findings

### B1. A wrapper-admitted call interrupted before its reservation exists makes provider-wait settlement fail permanently

**Where:** `factory/model_runtime.py`, `ModelRuntime._call`. The reservation is created inside `with model_router.running(...)`, after `renew_once()` and the credential read. `factory/budget.py:_settle_leaf` raises `usage_reservation_missing` when a receipt names a lease with no reservation row.

**Failure.**
1. A call that goes through the wrapper only (G10 tester, owner, dedup, G2, G8/G9, reviewers) gets a lease.
2. Something fails before `reserve_invocation`. Two real triggers:
   - a router blip on `renew_once()` at lease start;
   - the credential file disappearing between admission and the in-call read.
3. The failure is handled as a provider failure, so `_call` writes a receipt for that lease. The receipt has `final_usage_known: true` and no events.
4. The call raises ProviderWait carrying `lease_id` and `call_id`, so `write_provider_wait` records `evidence: interrupted` with that lease.
5. On resume, `settle(record)` loads that receipt and finds no reservation for the lease. It raises `usage_reservation_missing`.
6. `resume_provider_wait` fails on every resume. `provider_wait.json` stays live, so `await_lease` refuses with `provider_wait_unsettled`. The case is permanently wedged.

This is exactly the "denied before work must book $0 and resume" case in design lines 163–168 and 194–198, on the one path the tests don't cover.

**Reproductions.**
- `repro1.py`: `renew` raises RouterUnavailable once, then `run.model_call` is called, then `write_provider_wait`, then `resume_provider_wait`. Output: `reservations []`, then `RESUME FAILED BudgetError usage_reservation_missing`.
- `repro2.py`: the credential file is removed after admission. Output: `reservations None`, `RESUME FAILED BudgetError usage_reservation_missing`, `live wait still present True`.

**Why the tests miss it.** The wait-chain test uses `pending_call`, which reserves before the wrapper runs. The owner-denial test uses a null-lease record. Nothing exercises a lease-bearing wait from a call that never reserved.

**Fix direction.** Either reserve before `running()`/renew, or make `_settle_leaf` treat a missing reservation as $0 only when the receipt shows `not invoked`, `events == []` and `final_usage_known`. A missing reservation with unknown or invoked usage must still fail closed.

### B2. A binding change between a validated writer and its stress review spends a second writer round

**Where:** `factory/run.py`, `write_and_attack`, the `modern_writer_unit and not awaiting_stress` branch.

**Failure.**
1. A schema-v2 writer receipt is saved with `phase=validated` and `awaiting_stress=True`. The unit is validated but the stress review hasn't started.
2. The worker stops. Any release roll that changes `attack_binding` follows: source, bench, prompt or models. Design §3 says plumbing rolls onto running cases at the next checkpoint.
3. `awaiting_stress` is now false, because it requires `receipt['binding'] == attack_binding(c)`.
4. The modern writer branch then sets `start_round = n + 1` and `skip_writer = False`. It re-enters the writer loop and runs another writer round.
5. The legacy behaviour was a release re-review of round n with no writer call. The new branch also carries the saved `findings_report` and `input_problems` into that round.

This costs a paid writer round, up to the $15 range per the design's cost evidence, and increments `builder_rounds`. It also spends the round counter on a plumbing change. That breaks "relaunches consume no writer rounds" and "plumbing updates roll onto running cases".

**Reproduction.** `repro3.py` kills at `case_budget_boundary` after the receipt shows `validated`/`awaiting_stress`, then resumes with `attack_binding['prompt']` changed. Output:
- `SAVED {'round': 1, 'phase': 'validated', 'awaiting_stress': True, ...} builder_rounds 1`
- `CALLS ['builder-1', 'builder-2', 'attacker-2'] builder_rounds 2`

The trailing `stress_review_unresolved` error comes from my mock writing the wrong report filename. The `builder-2` call is the defect.

**Fix direction.** A validated writer unit with a stale binding should route to a stress re-review of round n. The saved rereview mechanism already does this: `rereview_round = n`, `skip_writer = True`. It should not start round n+1.

## Non-blocking findings

- **N1, over-charge for CLIs that never started.** `invoked` is set to `True` before `_invoke`, and any exception between that point and `run_budgeted` starting the process leaves `final_usage_known` false. Examples are `sh`/`sudo` setup in `_hand_to`, and the expiry check at the top of `_run_budgeted`. The reservation is then charged at its full maximum at the next reconcile, and no later receipt can lower it. This errs on the safe side and the design accepts conservative charging for unmatched reservations. But the design says a call that never started a CLI releases at $0, and here that isn't true. Consider setting the invoked state only once the process exists, or marking pre-start failures as known-zero.
- **N2, unexplained price multipliers.** `token_prices.invocation_maximum` multiplies rates by 2 (Codex input), 1.5 (Codex output) and 2.2 (Claude). The design says D uses no guessed multipliers. Document or remove them before E/A qualify bounds. `PAID_PRICES` also duplicates the pinned overrides at `model_runtime.py:156-161`. Reuse one source.
- **N3, repeated crash re-reviews.** A crashed pending stress review has `continuing_review` true regardless of whether it was a provider continuation. It reuses `operation_id` and `review_attempt` and does not increment `rereviews`. That is fine for money, but crash re-reviews are indistinguishable from continuations in the counters. Modern work also has no re-review cap, which the design intends.
- **N4, ordering of the ordinary-threshold check.** The writer's "spent + next maximum > ordinary limit" check runs after `await_lease`, because the maximum needs the lease route. A case that should go to diagnosis can therefore first end in a provider wait. This is harmless but worth stating in the design.
- **N5, stale design text.** Design lines 235–236 say the owner server is a non-threading `HTTPServer`. The code and the Increment 2 text say `ThreadingHTTPServer` with a non-blocking `owner_lock`. Reconcile the two.
- **N6, zero-headroom edge.** `require_case_budget` uses `>=` against other reservations while `reserve_invocation` uses `>`. A free route (maximum 0) is refused at exactly zero headroom. This is conservative and consistent enough.

## Areas checked with no defect found

- **Owner denial and interruption joins.** The owner bypass is gated on a program-set marker, a parent name in `active_model_calls` and a matching pending reservation. The owner runs without the dispatch lock but with an independent reservation. The three HTTP tests pass: done, denied (tester cancelled, one record, second settle adds $0), and interrupted (both leases settled once).
- **Lock boundaries.**
  - The factory path always passes `concurrent=True`, so short ledger transactions are used.
  - `reserve_invocation`, `complete_invocation` and `reconcile_reservations` don't nest inside a `transaction()`.
  - Reconcile excludes live leases and live call names.
  - The RLock is held through the checkpoint, and `prepare_dispatch` pre-shares the router lists.
- **Unknown usage.** The streaming accountant stamps `invocation_id` and `lease_id` on events and on `unpriced_invocations`. `_settle_leaf` removes only the matching entry. With the flag off, an unknown interrupted receipt does not force deferral, and the next admission fails closed with `money_wait` until crash reconciliation. Reservations are always taken from a fresh `for_case`.
- **Deadline expiry.** `run_budgeted` clamps the timeout to the absolute deadline and reports `retired_batch_bound`, not `timeout`. The codex/claude stop-first path includes that label. `for_case` then refuses permanently once the card carries the terminal stop. `reserve_invocation` rechecks the deadline.
- **Callback order.** `on_complete` runs after the router finish and the usage receipt, before the automatic checkpoint. The writer completion receipt is saved before G1 and resumes validation without a second writer. The stress completion receipt carries the report hash and review binding. The null-lease denied wait does not write a receipt. A pre-reservation lease failure inside `pending_call` is released at $0.

## Test adequacy

**What is covered:**
- the streaming accountant on the captured >$5 ledger;
- a denied wait changing nothing;
- missing, stale and expired authority;
- unknown route bounds;
- deadline interrupt;
- the ordinary threshold ($44 + $12);
- writer completion → checkpoint → validation resume;
- the three-wait chain for writer and stress;
- the flag-off path;
- three owner HTTP protocol cases.

**What is not covered:**
- the wrapper-path wait with a lease and no reservation (B1);
- binding change at a validated writer (B2);
- real kills between settle, pending reset and archive. The chain test calls `resume_provider_wait` repeatedly but never kills between those writes;
- the stress subtest of the wait chain uses a free route (maximum 0), so it checks no gap arithmetic and only proves the path;
- the committed-total refusal in a running `pending_call`;
- forged or mismatched `provider_continuation` archives;
- two-thread contention on `dispatch`;
- the pre-process-failure overcharge (N1).

Authored outputs, envelopes, bounds and the job config are appropriately labelled as authored. The tests use real saved bytes, make no real-crash or B/E qualification claim, and claim no row closure. That is consistent with the design.

## Obligations carried forward (not blockers)

- Diagnosis, extensions and stage snapshots.
- Legacy receipt and import migration.
- Removal of stale allowances and caps, plus scientific binding migration.
- B's installer and ack integration, and B's contract for `money_wait`/`retired_batch_bound` labels. Nothing outside `budget.py`/`job_authority.py` consumes those two labels yet.
- The legacy `not modern` branches remain until the cap-migration increment, which is acceptable only while they stay unreachable for authenticated jobs.
- Real crash and capped-call closure exams for rows 10, 21, 35 and 39.

## Readiness note

The readiness standard asks for zero implementer decisions. Increment 2 leaves two undecided in the design text. First, what a wrapper-admitted lease that dies before reserving must book. Second, what a stale binding at a validated writer unit must resume. Both decisions need to be written into the design before these fixes.

## Elephant response and fixed/rejected ledger

- B1 fixed: reservation now precedes initial renewal/credential re-read. An unreserved receipt can book zero only with explicit denied/final-known status, no IDs/events/unidentified usage, and a zero delta. Renewal-blip, credential-loss and malformed-zero regressions pass.
- B2 fixed: a validated writer awaiting stress keeps round n across changed bindings and re-reviews stress at n. A real callback-boundary interruption followed by an authored prompt-binding change produces builder-1 then attacker-1, with builder_rounds still 1.
- Full-suite finding fixed: parent_call_name is confined to authenticated factory jobs. The unchanged legacy calibration, attempts, delivery and recovery checks pass.
- N1 fixed with the actual Popen-success callback, so setup failures release at zero. N2 fixed by documenting the existing receipt tariff factors and sharing the paid-price table. N5 fixed by correcting the original owner-server paragraph. N3/N4 are documented; N6 remains an optional conservative edge.
- No finding rejected. All 16 runtime tests pass; full-suite validation remains required. No Murphy row is claimed closed.
- This reviewer explicitly did not read several required contract/design files. The next fresh goldfish is required to read all named inputs before assessing the fixed increment.
