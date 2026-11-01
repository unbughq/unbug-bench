**Verdict: BLOCK.** All the round-3 fixes you listed hold up against the code. One new blocker remains: the forked child can't tell the parent when a model-call attempt should not be published as infrastructure waste. That signal is lost.

This was a read-only review of `t3/stream-d-gates` at HEAD 5762ab0. I read `docs/ENGINEERING.md`, the `zoom_out`, `design_critic` and `implementation_readiness` personas, both standards, the design and review 3. I then checked them against `gate_attempt.py`, `run_validity.retry`, `recovery.py`, `restart.py`, `diagnosis.py`, `diagnosis_dispatch.py`, `extension_compare.py`, `extension_package.py`, `factory_waste.py`, `exam_responder.py`, `budget.reserve_invocation`, `model_runtime.py`, `run.py` main and finalize, and the existing tests. I made no edits, model calls or git changes, and started no subagents.

## Round-3 fixes, checked against the code

- **B1, parent-owned attempts (fixed).**
  - **Retries stay in one launch.** `run_validity.retry` loops inside the same process. It counts every `Exception` that isn't the `interruption` type and persists the count in the journal. So child death, IPC failure or a setup failure inside the parent's stage `invoke` is retried once, then becomes `InfrastructureExhausted`. `gate_attempt.execute` turns that into a crashed outcome (`gate_attempt.py:36-41`).
  - **Stage exhaustion doesn't use up a pair attempt.** Stage exhaustion raises `BudgetError`, and `snapshot` re-raises any `BudgetError` that isn't the stress `freshness_unresolved` (`extension_compare.py:201-203`). The pair-level `retry`, with `interruption=BudgetError`, then clears its `running` flag without consuming an attempt (`run_validity.py:90-94`).
  - **Diagnosis gets queued.** main records `exhaustion_occurred`, and `record_exhaustion` replaces the completed state because this is a new exhaustion. `infrastructure_exhausted`, `stress_validation_exhausted` and `freshness_evidence_unavailable` are all in `_trigger` (`diagnosis.py:52-53`).
- **Terminal proof is checked before the pair journal (fixed).** Of compare's `'pending'` exits, only lines 285-288 (retained scored pair fails verification) is permanent. The producer now catches it before the journal and raises `extension_snapshot_changed`. The other pending exits are:
  - lines 270-271, 281-283 and 303-308 (`_Changed`, drift);
  - line 256 (outcome is `None`).

  Each of these maps to a table row or to the eligibility check.
- **Error routes cover every pending source (fixed).** `retain_comparison`'s `extension_comparison_pending` (`extensions.py:508-511`) can't be reached once the snapshot hashes and versions are equal.
- **The `runner_error:comparison_in_progress` checkpoint is restartable (fixed).**
  - It matches `RETRY`'s `runner_error:.*`, and `ledger_agrees` accepts any `runner_error:` stop (`recovery.py:251`).
  - Removing `infrastructure_gate` and `failed_gate` is what lets `require_restart_stop` pass.
  - On relaunch, `_dispatch → replay → apply` returns 0 again (`diagnosis_dispatch.py:238-256`).
  - `queued_inputs` still verifies on relaunch. It checks the frozen `card.json` and `diagnosis_state.stop`, which `CARRY` keeps, not the rewritten live stop.
- **Reservation collection works.** Ledger rows hold every `_FIELDS` key (`budget.py:166-171`). `record_reservation` takes the parent's contextvar scope, so collecting new lease IDs in the parent's `finally` works.
- **M1, live `c` (fixed).** Lines 63-67 and 283 are explicit.
- **M2, bounded thread wait (fixed).** Lines 133-137 give a 30 s limit, and a refusal is counted. Only daemon threads exist (`model_call_gate`, router renew, `exam_responder`), and nothing in the runner keeps a thread alive, so the precondition can be met.
- **M3, deferred (accepted).** The design opens Murphy row `new-stream-d-current-comparison-1` and makes no claim about where a factory-bug resume returns.
- **Scope holds.** Activation stays off, limits and validators are unchanged, and no Murphy row is closed.

## Blocking finding

**B1. The child loses the parent's "do not publish this as waste" signal.** *(design_critic and readiness; §4 lazy fork, §6 lines 332-342)*
- **Where it happens.** The child is forked lazily inside the first stage `invoke`, which runs inside the parent's factory-waste scope. The child therefore inherits a copy of `factory_waste._attempt`, still pointing at that first stage's `Attempt`.
- **The G10 path.** G10's owner channel calls `scope.mark_unpublishable('owner_drain_timeout')` and then raises `InvalidInfra` (`exam_responder.py:222-245`). In the child, that mark lands on the copy only.
  - The parent's real scope then sees `InvalidInfra` and publishes a `factory-failures` invalid-infra proof (`factory_waste.py:57-75`).
  - The current code deliberately suppresses that proof.
  - Result: comparison work whose cleanup didn't finish can be attributed to the infra-waste line.
- **If the child really had no scope** ("the child opens no factory-waste scope"), `exam_responder` takes its unscoped branch instead. That branch never raises on an incomplete drain, so the safety check would be weakened.
- **Fix:** right after fork, the child installs a forwarding scope:
  - `mark_unpublishable(reason)` sends that reason as an effect;
  - the parent applies it to the active `Attempt` before `publish`;
  - `record_reservation` does nothing in the child, because the parent collects from the ledger.
- **Test:** an authored G10 owner-drain timeout in the child produces no `factory-failures` or `factory-replays` file, and still counts as an invalid-infra attempt.

## Major (should fix; not blocking)

**M1. An existing test conflicts with the design, and no disposition is given.**
- `test_stream_d_entry.py:291-295` (`test_history_refuses_without_snapshot_or_evaluation`) expects `^extension_comparison_pending$` when history exists.
- The design deletes that refusal and forbids catching `subsequent_entry` errors. A malformed history row would then raise something else.
- **Fix:** state the replacement, so this isn't silently weakened. Keep the assertion that "no snapshot or evaluation happens on invalid history", and name the label expected now (for example `extension_history_invalid`).

**M2. "Remove the temporary status/terminal_stop" is ambiguous (line 575).**
- `apply` sets `status='stopped'` and `terminal_stop='extension_comparison_pending'` (`STOPS`, `diagnosis_dispatch.py:30,232`).
- First entry admits with those values in place, and `package.run` clears them on success (`extension_package.py:322-324`).
- **Fix:** restore the exact pre-producer values rather than popping the keys, so subsequent entry and first entry hand the writer the same card. Say this explicitly.

**M3. A dead child's reservations aren't reconciled before the in-launch retry.**
- A pending ledger row from a killed child still counts against the cap (`budget.py:178-182`) until it is reconciled. The retry could then stop spuriously on `money_wait`.
- **Fix:** after cleanup and before the retry, the parent calls `reconcile_reservations(accounting_work, c.ledger)`. Test it.

**M4. The pair-level row doesn't name raised exceptions or the `publish` callback.**
- `retry` counts any non-`BudgetError` `Exception` that compare raises, such as a `ValueError` from `validate_snapshot` or a diagnostic `RuntimeError`. The table mentions only pending returns.
- **Fix:** add a row: "any other exception escaping compare counts as a pair attempt". Also say what the pair `publish` callback does (no-op, or operational events only).

## Nits

- **Pair journal identity.** The pair journal needs the pinned version vector before `compare` builds its workspaces. State that the producer computes it with `extension_compare._versions` on a workspace built from the owner's args and models. This works because `scientific_version` ignores case content (`gate_state.py:207-211`).
- **Misleading diagnosis label.** Pair exhaustion is reported as `stress_validation_exhausted` even when stress never ran. Put `scope: pair` in the comparison-diagnostics index so the diagnosis reviewer isn't misled.
- **Original failure fields are lost.** After the in-progress marker, an evidence-stop card has lost its original `failed_gate`, `failed_detail` and `infrastructure_gate`. Either say that this is intended, or keep them under the diagnosis-input copy.

## Heilmeier and readiness

- **Heilmeier:** all answered. Objective at lines 475-477; current state at 17-22; risks at 24-28; cost and timeline at 459-470; midterm and final exams at 469-470.
- **Readiness:** phases, file list and exams are explicit. Only B1 and M1-M4 leave design choices to the implementer.
- **Zoom-out:** reusing `gate_attempt` and the in-process retry removed the child exhaustion messaging. No new subsystem is added.

**Result: BLOCK** (B1 only). Fixing B1 needs a short addition to the design: the forwarding scope, plus one exam.

## Writer disposition

Accepted B1 and M1–M4. Add a child forwarding waste scope with parent acknowledgement, preserve the owner-drain safety signal, reconcile dead-child reservations before retry, specify exact card restoration and pair callbacks, and explicitly update only the superseded history-refusal test while retaining its no-evaluation assertion. Fresh review follows.
