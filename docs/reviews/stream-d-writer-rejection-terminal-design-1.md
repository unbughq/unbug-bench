**Verdict: BLOCK.** This is design review round 1 of 2 for `docs/designs/stream-d-writer-rejection-terminal.md` at `972e160`. I used Mode: REVIEW with the zoom_out, design_critic and implementation_readiness personas, against `heilmeier-standard.md` and `implementation-readiness-standard.md`. I made no edits, started no workers or subagents, and made no paid calls.

The overall approach is sound. Nothing gets a fake score: the outcome marks every stage unreached, at frontier 0. The stop is an explicit no-progress decision in `subsequent_entry` before `current_pair`/`Evaluator`, which follows the unchanged and public-match precedent. There is no paid reroll: `subsequent_entry` is the only caller of `compare`/`current_pair`. Two gaps need fixing before implementation.

## Blockers

**B1. Refusing on "other package gate directories" will turn a real crash into a permanent stop.**
- **Where:** design lines 41–43.
- **Problem:** `Records.save` stages its work in `mkdtemp(prefix='.stage-', dir=self.root)` (`extension_package.py:187`). A real SIGKILL during `save` skips the `finally` and leaves `.stage-*` in `extension-package/<id>/`.
- **What then happens:** on resume no record exists yet, so the normal route re-runs the local G1 and saves it. Now a valid candidate sits next to a leftover `.stage-*` directory. If the implementer reads the rule as "any other directory in the root", the selector refuses with `extension_snapshot_changed`. That refusal repeats on every resume, so it is a pit stop on exactly the crash path this slice is meant to fix. The patched-exception exams never leave the directory behind, so they would not catch it.
- **Fix:**
  - Define the refusal set exactly: subdirectories whose names are in `extensions.stages()` (other than the candidate), or `stress`.
  - Ignore dot-prefixed staging directories.
  - Add one exam: a candidate next to a leftover `.stage-x/record.json` completes normally.

**B2. The card changes `stop()` makes are not fully specified, so the implementer would have to choose them.**
- **Where:** design lines 121–125.
- **Problem:** two phrases are undefined, and both shape what the diagnosis call sees (`diagnosis_dispatch.py:24` passes `failed_detail` and `early_gates` to it):
  - "Stale early markers": it doesn't say which `early_gates` keys to remove, and whether `c.early` and `early_hash` are cleared too. Note that `complete` never restores the record's card projection.
  - "Private sample info/feedback" for saved cheats: it doesn't say whether this is the retained `info` (`sample`, `summary`, `writer_observation`) or only `writer_observation.feedback`.
  - The same question applies to G1/G15/G3/G4/G5: whether `failed_detail` is the retained `info` as-is, including `writer_observation`.
- **Fix:** list the exact keys to pop, plus the exact value of `failed_detail` for each stage. Recommended: `failed_detail` = the retained `info` deep-copied as-is for every stage. Pop `early_gates` entirely, plus `c.early` and `early_hash`. That way the diagnosis sees only the bytes in the immutable record, and the exam can assert equality with them.

## Checked and sound
- **Receipt windows** match `run.py`:
  - Completed: set by `complete_writer:383` with `next_phase G1`.
  - Validated, fresh path: `:1534/1540`; `awaiting_stress` is absent and `validation_problems` is the retained feedback.
  - Validated, resume path: `:1556`; `awaiting_stress` is False, so "no true awaiting_stress" is the right test.
  - Exhausted: `:1646`, which may not have been published yet.
  - Reading `attack-state.json` before calling `writer_receipt` removes the reconstruction write noted in diff-1 (nit 2).
- **Full-tree identity:** `Records.sources` keeps every file under `case/` (`:159`), and `case_hash` leaves out `freshness.jsonl` (`run.py:892`). So the extra `tree()` equality check is needed and is enough.
- **Routing:**
  - `apply(comparison_route=True)` skips the pending stop and returns 0 (`diagnosis_dispatch.py:242`). Main then calls `admit_extension` → `entry` → `subsequent_entry`, which raises before `writer_request` (`run.py:3401`).
  - Same-exhaustion replay goes through `completed_route`.
  - `_trigger` and `_held_stage` give `extension_incomplete` and G5 or `unknown` (`diagnosis.py:55, 244`).
- **Crash replay with a generation change:** the stored-generation branch is correct as written (but see M1).
- **Precedence of the stop markers:** `extension-terminal/<id>-writer-rejection.json` does not collide with the unchanged or public-match markers.

## Optional findings
1. **Major, simplification.** Drop `source_generation` from the marker and use the current generation at completion, as `complete_unchanged:451` does.
   - The marker bytes would then be identical across a generation change, so `_save_case`'s existing target-exists check covers a crash after rename. The whole branch at lines 89–96 ("if an outcome directory already exists… temporary row") can then be deleted.
   - `verified` would check that `row.outcome.source_generation` is a valid sha. `propose` already treats the generation as lineage that may change (`extensions.py:404`).
   - This follows "Delete before adding". The rename-crash exam still works and becomes trivially byte-identical.
2. **Major, delete.** Once `complete` runs at package entry, the replay branches in `writer_early` (`:294`) and `writer_g1` (`:242-246`) can never be reached. Every record is either completed or refused before `write_and_attack`. Replace each with a refusal or delete it (this repeats diff-1 nit 4).
3. **Nit, readiness.** "Worker inventory entry" means adding `factory/extension_writer_rejection.py` to the `expected_worker` set in `tests/tools/test_launch_manifest.py:83`. `worker_files` already picks up `factory/*.py`. Name the file.
4. **Nit, test scope.** In `test_stream_d_writer_g1.py`, the shared helpers `held()` and `rejected()` (the latter asserts `outcome is None`) need changing, not just "the package boundary". Name the tests that change: fresh, completed, done, kill-after-record, and `test_stream_d_writer_early.py:80`. Also state that `test_legacy_validated_receipt_is_not_reconstructed` stays held.
5. **Nit.** `writer_g1` saves any non-pending `ok False` result, even with empty `problems` (`:250`), and the flow then carries on to early checks and stress. With the "stress alongside candidate" refusal, that would block the ordinary blocking-stress outcome. Real `g1` makes this unlikely. Consider saving the G1 record only when `problems` is non-empty, the same rule the selector already applies.
6. **Nit, Heilmeier.** The objective (lines 5–8) is understandable but full of jargon. One plain sentence would satisfy the "no jargon" requirement: "a writer whose output failed a check should end its extension and be retired, not stay open forever."

The scope is respected: no activation, limit, attribution, schema or gate-version changes, and no Murphy row closes (rows 9 and 13 are supported only). The cost, timeline and midterm/final exams are present. `factory-simplify` (`b75c9b4`) is already the merge base. Land11 still has to merge before implementation.

## Writer disposition

B1 fixed: enumerate conflicting published stage directories, ignore dot-prefixed staging, and add leftover .stage-x exam. B2 fixed: exact card/attribute cleanup and deep-copied retained info for every stage. Adopt optional M1: remove source_generation from the marker and delete special orphan-outcome reconstruction; current generation is outcome lineage, immutable evidence stays identical. M2 deferred: retain existing shared direct helper replay contracts in this slice; package entry dominates them, and no new replay branch is added. Name worker inventory/test updates, require nonempty G1 problems for new rejection capture, and add the plain-language objective. Fresh round 2 must independently check both blocker fixes.

