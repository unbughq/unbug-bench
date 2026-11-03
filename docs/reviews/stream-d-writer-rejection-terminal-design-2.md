**Verdict: PASS.** This is design round 2 of 2 for `docs/designs/stream-d-writer-rejection-terminal.md` at `3c426c0`, using Mode: REVIEW with the zoom_out, design_critic and implementation_readiness personas, against `heilmeier-standard.md` and `implementation-readiness-standard.md`. Both round-1 blockers are fixed and no new blocker came up. I made no edits and no calls.

## Blocker fixes, checked against the code

**B1 (which directories cause a refusal): fixed.**
- **Leftover staging directories are ignored.** `Records.save` stages in `mkdtemp(prefix='.stage-', dir=self.root)` (`extension_package.py:187`). A SIGKILL skips the `finally`, so a `.stage-*` directory can be left behind. The design ignores every dot-prefixed directory (lines 47–48), which covers it.
- **The refusal set is exact.** It is the subdirectory names (or symlinks) in `extensions.stages()` other than the candidate (lines 44–46).
  - `stages()` = `stress` plus `GATES` without G12 (`extensions.py:38`). That includes G1/G15/G3/G4/G5, so a second candidate also refuses.
  - `saved-cheats` is not in `stages()`; the "more than one candidate" rule covers it.
  - Nothing else writes into the package root: the only writers are `save`'s rename and `observe_gate`'s rmtree, and neither runs on a rejection path.
- **The other crash leftovers are harmless.**
  - The terminal's own staging uses a system TemporaryDirectory.
  - A `_save_case` leftover `.snapshot-*` sits beside `outcome/` and is never read by `_verify_case`.
- **The exam is named:** a candidate next to a leftover `.stage-x/record.json` completes, and a real conflicting stage directory refuses (lines 166–167).

**B2 (exact card changes in `stop()`): fixed.**
- **Removed or emptied:**
  - `gates` and `gate_results` become `{}`;
  - `failed_gate`, `failed_detail`, `infrastructure_gate` and `early_gates` are popped;
  - `c.early` and `early_hash` are removed;
  - `stress_review` is set to `not_run` / `writer_rejection`.
- **`failed_detail`** is a deep copy of the retained `info` for every stage.
- **`failed_gate`** is the actual stage for G1/G15/G3/G4/G5. It is absent for saved-cheats, which `_held_stage` turns into `unknown` (`diagnosis.py:248`); `unknown` is a normal value there.
- **Kept:** `builder_rounds` and the money and diagnosis fields.
- **Raise:** `extension_incomplete`, which `_trigger` accepts once the outcome is committed (`diagnosis.py:55`).
- **Exam:** asserts these values and absences on both fresh completion and replay, starting from stale state.

## Other checks

- **Receipt windows** match `run.py`:
  - Completed window: written at `:383` with `next_phase G1`.
  - Validated window: written at `:1534/1540` and `:1556`, with `validation_problems` equal to the retained problems.
  - Exhaustion fields: written at `:1646`. A modern run always sets `stop_reason` to `rounds_exhausted`; `budget_exhausted` is set only on the non-modern path at `:1494`. So "both absent, or True with `rounds_exhausted`" is exact.
- **Generation simplification holds.**
  - Nothing between the outcome rename and the resumed `complete` changes `attack-state.json`. So the marker, record, support and case tree are byte-identical, and `_save_case` → `_verify_case` accepts the existing target (`extensions.py:178`).
  - `extensions.complete` then commits the history row once.
  - `verified` never calls `writer_receipt`. That call would return None once the history row is no longer active.
- **Routing is sound.**
  - `apply(comparison_route=True)` skips the pending stop.
  - Main then goes `admit_extension` → `entry` → `subsequent_entry`, and the `verified` check raises `retired_no_progress` before `writer_request`, `current_pair` or `Evaluator`.
  - Generic `progress()` returns `pending` for the all-unreached outcome, as the design says, and the non-opted-in guard is kept.
- **The legacy hold is preserved.** With no record, the selector returns False. `write_and_attack` → `rounds_exhausted` → the second `complete` returns False → `stress()` refuses with `extension_execution_pending`.
- **The marker names don't collide** with `unchanged_outcome` or `public.verified`. Every evidence path passes `validate_snapshot`'s rule against paths starting with `case/`.
- **The named items exist:** the worker manifest entry, the nonempty G1 predicate (fixing `extension_package.py:250`), and the scope of the existing tests.
- **No fake score or paid reroll:** nothing invents a stress, G6 or pass score, and there is no paid reroll.
- **Heilmeier:** the objective is in plain language, and cost, timeline, risks and the midterm/final exams are all present.
- **Merge order:** `merge/land11` exists and must merge before implementation, as the design states.

## Optional findings (none blocking)

1. **Nit, readiness.** `test_package_version_drift_keeps_existing_handoff_label` (`test_stream_d_writer_g1.py:171`) calls `held()`. Once `held()` is updated, the test silently starts expecting completion under version drift. That is the intended new behaviour (line 180), but the test should be named and renamed. Also, `test_legacy_validated_receipt_is_not_reconstructed` must keep an explicit `execution_pending` assertion rather than the updated helper.
2. **Nit.** The pre-`writer_receipt` read should also require `round == row.round`. Otherwise an attack-state equal to `previous` (an earlier extension's validated writer receipt) passes the check and lets the recovery write happen. This state can't be reached without tampering. In `package.run`, `complete_unchanged` already calls `writer_receipt` first anyway, so the "no recovery write" claim really holds only for the explicit refusal cases. The exam assertions remain valid.
3. **Nit.** "In package.run before the ordinary stress path" should say exactly where: next to `unchanged_outcome` and `public.verified` at the top of `run`. If the check sits below the `records.completed` block, `stress()` refuses `extension_outcome_changed` first.
4. **Deferred M2, accepted.** The direct helper replay branches remain, but package entry now always reaches them second.

## Writer disposition

PASS accepted. Both blockers independently verified fixed. Optional nits incorporated: name the version-drift test rename and explicit legacy hold; require row round in the pre-authentication read, with the limited no-write claim; place terminal replay alongside the top-level unchanged/public checks. Existing direct helper replay remains as accepted. Land11 is still pending at approval time; no implementation starts before its merge.

