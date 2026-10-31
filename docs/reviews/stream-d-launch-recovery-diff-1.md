**Goldfish diff review: `stream-d-launch-recovery`, range 8a395f5..528d9ad**

Mode: REVIEW. Personas: `zoom_out` and `implementation_readiness`. Standard: `implementation-readiness-standard.md`. The change has a design (step 2 was not skipped), so I reviewed the diff against `docs/designs/stream-d-launch-recovery.md`.

**Verdict: PASS.** No blocking or major findings. Four nits, all optional.

### What I checked
- **Production change.** The only production change is five lines in `factory/diagnosis_dispatch.py:233-237` (`apply`). They sit after the stopped-card update and immediately before `scorecard.json` is published, which is where design-review nit 2 asked for them. The call is gated on `close_to_passing` and on `extensions.active(c)` not being `None`. Factory bug, retire, and close-to-passing with no active row all keep their old routes unchanged. No config, module, flag, file format or money path was added. The selector is reused, not re-implemented, so there are no zoom-out findings.
- **Order of checks before repair.** `apply` is reached in two ways: from `replay`, after the `decision.json` shape, `input_sha256` and retained-answer checks; and from `_dispatch`/`invoke`, after the journal and raw-answer checks. Both paths run inside `c.model_dispatch_lock`, after job authority, provider waits, `reconcile_reservations`, the pending-reservation guard, `extensions.read` and `queued_inputs`. So no receipt can be repaired before the diagnosis is verified. `test_launcher_corrupt_diagnosis_refuses_before_writer_recovery` patches `writer_receipt` to fail if called, and stops at `diagnosis_input_invalid`. The patch works because `apply` looks up `extensions.writer_receipt` when it runs.
- **Error routing.** The new call is not wrapped in `verify()`.
  - `dispatch()` only converts `InputVerificationError` and two named `BudgetError`s into `diagnosis_input_invalid`.
  - So `extension_reservation_mismatch` re-raises as itself, and `PermissionError` (and EIO) propagate as infrastructure errors. `_writer_json` only maps ELOOP, ENOTDIR, ENXIO and EISDIR to a mismatch.
  - Both cases are pinned by tests: the missing-intent test and the permission test.
- **Crash and receipt ordering.**
  - `writer_receipt` writes `attack-state.json` and then sets `c.card['builder_rounds']` in memory. The scorecard is written after that.
  - A crash between the receipt write and the scorecard write leaves `current == intent`. On the next launch the preserve branch runs: frozen fields, binding and phase all match, so nothing is rewritten.
  - Idempotence is shown by `test_main_recovers_admitted_writer_before_ordinary_launch_twice`. That test runs `run.main` twice in a subprocess with Compose, model selection, build, repair and pilots forbidden. It checks byte equality for history, writers, snapshots and diagnosis, and checks that reservations are unchanged.
  - Every replay ends in `stop()`, so a recovered pending receipt never reaches the ordinary writer path.
- **Test producers.** `admit_active_control` now uses a real `pending_call`, interrupted when it publishes `attack-state.json`, so the intent comes from the real producer. This resolves design-review nit 3.
- **Evidence.**
  - The suite record's `base_commit` (4e0da83) is HEAD's parent. 4e0da83 has the same tree as 8a395f5 (the diff between them is empty).
  - The log ends with "158 test scripts run; 0 failed." and contains `test_stream_d_dispatch.py`: 52 tests, OK.
  - I re-ran `tests/factory/test_stream_d_dispatch.py` on HEAD: 52 tests, OK.
- **Mutation check.** I ran this in a throwaway `git archive` copy, not the worktree. With `extensions.writer_receipt(c)` removed, 3 of the new tests fail (main twice, missing intent, permission). So the tests really guard the call.
- **Murphy rows.** The diff touches no row. Claiming zero rows is correct: row 9 still needs the package, and lane 1 owns row 13.

### Nits
1. **Nit — the "before scorecard" order isn't pinned by a test.** Scope: design §Change ("before publishing scorecard so repaired builder_rounds is durable with the stop") and `diagnosis_dispatch.py:233-238`. In my copy I moved the call to after `atomic_json(... 'scorecard.json' ...)`, and all 52 tests still passed. `main` republishes the card when the stop is raised, and the next replay repairs it anyway, so nothing is unsafe. But the claimed ordering has no test. Either add one assertion on `work/scorecard.json` `builder_rounds` after `dispatch.dispatch`, or drop the "durable with the stop" wording.
2. **Nit — the same-round stress branch leaves `builder_rounds` behind.** Scope: `extensions.writer_receipt`, where the stress branch returns `None` before `c.card['builder_rounds'] = row['round']`. In `test_launcher_preserves_finished_writer_and_stress_receipts`, the emulated public count (round − 1) is therefore still published on the stress branch. The design says this branch grants nothing, so this is acceptable for now. Package routing in item 8 should own fixing it.
3. **Nit — some receipts in the preservation test are hand-made.** The completed and validated phases are set by hand on top of a real `complete_writer` receipt, and the stress receipts are minimal hand-built dicts. The stress branch only looks at `actor` and `round`, so this proves the bytes are preserved but not what real stress receipts look like. That's fine for this increment, but it falls short of the "real artifacts" bar for row 9 later.
4. **Nit — process records.**
   - The design grew from the 72 lines review 2 saw to 95 lines with the addendum. The addendum only applies review 2's accepted nits, so no re-review is required.
   - The suite record says "uncommitted … implementation" but has no hash of the tested working tree, so it can't prove the committed bytes are the ones that ran. My targeted re-run on HEAD covers the changed file.

No blocking finding is open, so this may merge. I edited nothing in the worktree (the mutation copy was in a temp directory and has been deleted), and I did not delegate, push or run the full suite.

## Writer response

PASS accepted; no blocking finding needs adjudication. Optional nit 1 is deferred: current insertion follows the design and the review confirms replay remains safe; the next package tests should pin publication ordering explicitly. Nit 2 belongs to item 7 package routing before item 8, not to stress authorization in this recovery-only increment. Nit 3 is retained as the stated authored-control limitation; no Murphy row closure is claimed. Nit 4 is acknowledged: the full suite ran the unchanged implementation/tests later committed in 528d9ad; the reviewer independently reran the committed dispatch tests. Future suite records should capture the tested tree hash at start. No production/test edits followed the full suite or diff review; only review records and their trailing whitespace changed.
