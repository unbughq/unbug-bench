**Verdict: PASS.** I found no blocking or major problem in `docs/designs/stream-d-launch-recovery.md` (uncommitted, 72 lines). It can be built as written, and only nits are left.

I followed `ENGINEERING.md`, the three personas (`zoom_out`, `design_critic`, `implementation_readiness`) with `Mode: REVIEW`, and both named standards. The design does not skip step 2. I checked it against:
- `factory/diagnosis_dispatch.py`: `apply`, `replay`, `_dispatch`, `dispatch`
- `factory/extensions.py`: `active`, `writer_receipt`, `writer_continuation`, `retain_writer`, `admit`
- `factory/run.py`: `pending_call`, `provider_continuation`, the barrier in `Ctx`, and the `main` dispatch and exception handlers
- `factory/model_runtime.py` (`dispatch`), `factory/budget.py` (`reconcile_reservations`), `factory/diagnosis.py` (`require_model_work`, `record_exhaustion`), `factory/recovery.py` (`RETRY`), `factory/stress_progress.py` (`publication`)
- `tests/factory/test_stream_d_dispatch.py` and `tests/factory/test_stream_d_admission.py`

## Checks that hold
- **Where the call goes.** `apply` is the only place both stop paths meet: replay of a retained `decision.json` (via `replay`) and a fresh valid answer (via `_dispatch`). Both reach it only after job authority, the dispatch lock, settled provider waits and reservations, no pending reservations, `extensions.read`, frozen inputs, the journal and the decision/raw-answer checks. So a corrupt retained diagnosis refuses before any receipt is repaired, and a public label alone cannot trigger recovery. The design's claim is true.
- **Checking `extensions.active` first is justified, not redundant.** `writer_receipt` returns `None` on its own when no row is active, but it does so inside `model_runtime.dispatch`. That runs `require_model_work` and the stress-publication drain. The pre-check keeps today's no-active close-to-passing route exactly as it is. Keep it.
- **The lock is safe to take again.** `model_dispatch_lock` is an `RLock` (`model_runtime.py:48`), and `writer_receipt` is called while `_dispatch` already holds it.
- **A crash between history and the attack receipt is recoverable.**
  - `reconcile_reservations` settles the pending first reservation at full maximum but keeps the row.
  - `writer_continuation` checks the operation, call name and invocation, not the reservation's state.
  - So the retained intent still binds, and `_dispatch`'s `usage_reconciliation_pending` guard does not block it.
- **Repeating the launch is idempotent.** The first launch publishes the intent (`current == previous`). The second takes the preserve branch, the frozen fields match, the phase is `pending` and the binding is equal, so the file is unchanged.
- **Error routing matches the claims.**
  - A selector `BudgetError` is re-raised by `dispatch()`, and `main` sets `terminal_stop` to its label.
  - A raw `PermissionError` or EIO is not caught by `verify` or `dispatch()`. It becomes `runner_error:PermissionError`, which `recovery.RETRY` retries as infrastructure. This holds as long as the call is not wrapped in `verify()`, and the planned injection test pins that.
  - `record_exhaustion` returns early when an extension is active, so a mismatch stop cannot start another diagnosis.
- **The `run.main` subprocess reaches the new code with diagnosis off.** Replay of `decision.json` happens before the `DIAGNOSIS_ENABLED` check, so the flag can stay unchanged. Compose, model selection, build and repair (`run.sh`, `pick_models`, `build`, `validate_and_repair`) are already forbidden in the harness.
- **Scope matches the code.** There is no production caller of `pending_call(extension_proposal=…)`, and the design adds no new module, config, file format, flag or money path. It reuses the existing selector. Claiming no Murphy row is correct: row 9 needs package execution, and lane 1 owns row 13.

## Nits (optional)
1. **Stress-publication drain (lines 26–29, 33, 39).** Inside `model_runtime.dispatch`, a pending `stress-publication.json` runs the `Ctx` barrier, which checkpoints remotely and rewrites the marker. In unit contexts without a barrier, it raises `stress_publication_configuration_missing`. I see no way to reach this in this increment, because admission's own dispatch drains the marker before history can become active. Still, "recovery is model-free / bounded reads" and "same-round stress… leave bytes untouched" are not literally true in that state. Add one sentence saying the drain is the intended dispatch invariant.
2. **Exact insertion line (lines 18–21).** Say whether the call goes before or after `c.card.update(status='stopped', terminal_stop=...)`. Recommended: after it, immediately before `atomic_json(c.work / 'scorecard.json', ...)`. The outcome is the same either way, because `main` overwrites `terminal_stop` with the raised label.
3. **How the crash state is built in tests (lines 46–47, 50–51).** "Retain intent before history, matching pending_call" leaves it open whether the test hand-builds the receipt or drives the real producer. Prefer the real `pending_call` interruption already in `test_stream_d_admission.py` (`publication_failure` / `recover_publication`), or call `retain_writer` with the exact `pending_call` envelope. A hand-built receipt could drift from the producer, which is the frozen-field risk raised in nit 4 of the receipt-routing design review (`docs/reviews/stream-d-extension-receipt-routing-design-2.md`).
4. **"Reservations unchanged" (line 52).** The first launch settles the admitted reservation through `reconcile_reservations`, so "unchanged" can only mean unchanged across repeated launches. Two existing assertions also need changing:
   - The subprocess helper asserts that `invocation_reservations` is absent from `continuation_budget`.
   - It expects only `diagnosis_pending` or `runner_error:ValueError` as the stop.

   Name the new `fault` mode and the expected `extension_comparison_pending` and `builder_rounds` values.
5. **Missing intent is a terminal stop (line 35).** `extension_reservation_mismatch` is not in `RETRY`, so an older active row with missing intent strands the case until a human acts. This is acceptable only because no production active extensions exist yet. Say that, so the gap does not read as a pit stop accepted on purpose.
6. **"What it deletes" (line 37).** Nothing is deleted in code. `apply` simply never calls the selector today. Say "nothing deleted" plainly.
7. **Heilmeier gaps.**
   - The text is very dense with shorthand: "5813be ledger", "lane 1", "A/B/E", `pending_call`, "frozen inputs".
   - There is no timeline beyond "increment".
   - There is no explicit risks section.
   - Impact should say outright that no production path admits extensions yet, so the benefit is a tested recovery seam for item 8, not a live fix.

No blocking finding remains, so the design may move to implementation. I made no edits, did not delegate and pushed nothing. The review is not saved to `docs/reviews/`; the elephant should save it verbatim as the next numbered file.

## Writer response

Accepted all seven nits. The design addendum clarifies scope, dispatch publication, insertion, test producers and accounting. Implementation uses real pending_call interruption for active admission controls.

