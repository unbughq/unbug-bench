**Verdict: PASS, no blockers, within the scope the parent approved.**

I reviewed `b75c9b4..2e20d31` read-only and paid most attention to the changes after `94211b6`. I ran no tests and wrote nothing. `factory-simplify` is still `b75c9b4`, and that commit is already part of HEAD.

## What I checked myself

- **Scope:** Only two production files change: `factory/diagnosis.py` (+57) and `factory/diagnosis_dispatch.py` (+6/−1). Neither has changed since `9cd1a66`. The commits after round 1 touch only tests and docs.
  - `run.py`/`main` are unchanged, so there is no previous-card override.
  - There is no new router, counter, money path or retry reset, and diagnosis is still not enabled.
  - Murphy row `new-stream-d-current-comparison-1` is still `open`.
  - The item-8 checklist line in `docs/designs/stream-d.md` matches the required wording exactly.
- **Saving the decision:**
  - `retain_extension_resume` runs only in `apply`'s enabled close_to_passing branch, after `writer_receipt`/`completed_route` and before the scorecard is written and the integer returned.
  - An identical record is left alone, a new valid decision replaces it, and a malformed record refuses with `extension_resume_target_invalid`.
- **Freezing it with the next diagnosis:** `extension-resume.json` is added to `_write_input_tree`'s names.
  - When an existing diagnosis is replayed, `queued_inputs` compares the saved manifest against its own frozen inventory, not against live `work/`.
  - So the record that `apply` writes later cannot invalidate the original decision's manifest when it is replayed.
- **Admission order:**
  - The three-resume retirement check runs first.
  - `_extension_resume_state` then runs on both new and reused admissions, before any append.
  - Read, parse and `BudgetError` failures inside it become `FactoryBugHeldWait('extension_resume_target_invalid')`, which `run.py:3419` turns into a `factory_bug_held` stop with that reason.
- **Restore:** The original decision is put back in the same `atomic_json` write that clears the hold, and `factory_bug_resume_count` is kept.
  - `_dispatch` returns False unless the restored state is completed close_to_passing.
  - Otherwise it rebases `previous` and falls through the existing prepare, lock, reconcile, queued-inputs, journal, replay and apply steps.
- **The Major 1 fix is real:**
  - `test_completed_successor_uses_existing_completed_route:215-225` calls the real `_extension_resume_state` with no patching of `extensions.read`.
  - It runs after real `admit_active_control(1)` and `extensions.complete(...)`, so the history is non-empty and completed.
  - It asserts that the original decision comes back and that `self.c.card` is unchanged.
  - It then removes the live record, asserts the held refusal, restores the record, and runs the existing completed-route check.
  - The positive assertion can only pass if the real history, ledger and snapshot checks and `_state` against that full history all succeed.
- **The other round-1 items:**
  - Nit 2: the assertion that proved nothing is deleted.
  - Nit 4: the design now says that during replay this refusal happens after the `completed_route` side effects and is a plain stop, not a hold. A plain `BudgetError` becomes a `terminal_stop` label, and that label is not in `_trigger`'s list, so it cannot start a new diagnosis.
  - Nit 3 is deferred; behaviour is the same today.
- **Suite records:** The cancelled-run JSON has `cancelled: true`, `suite_started: false`, `verdict: null` and exit −15, and its log is 0 bytes.
  - The report keeps the `9cd1a66` run at 179 scripts with 1 unrelated failure. It is not relabelled as 179/0.
  - The parent's decision is quoted word for word in the report and the design.

## Findings (none blocking)

1. **Nit: the new failure check doesn't test the "history but no record anywhere" case with real history.**
   - **Evidence:** In the negative check at `:221-224` the frozen copy is still there. So it fails because the live and frozen bytes differ (the live file is missing). It would pass even if the "real history means refuse" check were broken.
   - The case with no live record, no frozen record and real non-empty history is still covered only by the patched `extensions.read` in `test_frozen_record_mismatch_and_missing_post_extension_target_refuse`.
   - This is exactly what round 1 asked for, and it is the realistic failure.
   - **Optional fix:** also unlink the frozen copy before the `assertRaises`, then restore both.
2. **Nit, carried over (deferred):** `diagnosis_dispatch.py:314`. `state` points at `c.card['diagnosis_state']`, not at `previous`'s copy as the design says. Behaviour is the same today.
3. **Doc nit:** the report still says "Final diff review round 2 is pending". Update it when you save this record.

## Delivery

- The parent's merge suite is the gate, by the parent's recorded decision.
- This lane needs no further full suite.
- There is no claim about `subsequent_entry`, pair-attempts, or archive and restore of retained artifacts; that remains item 8.

**PASS, no blockers.**

## Elephant disposition

Final PASS accepted; no blocker remains within the parent-approved focused scope. Round-1 Major 1 is independently verified fixed. Optional missing-both-records real-history coverage and the state-copy nit are deferred; no code or test change follows this review. Update the report's pending line. Parent merge suite remains the gate; the lane's locked run stays recorded as 179 scripts / 1 known isolation flake, with its passing targeted recheck and explicitly cancelled queued repeat. No further suite or review is started. No Murphy row is closed; the full retained-artifact chain remains on item 8. Production source remains unchanged since 9cd1a66.
