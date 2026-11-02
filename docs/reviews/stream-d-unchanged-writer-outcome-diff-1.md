**PASS** on round 1 of the diff review. Nothing blocking and no majors; there are three optional nits.

I reviewed `6599e95..HEAD`. The production code is the one commit `f00b673`, and everything after it is reports and docs. I read it against `docs/ENGINEERING.md`, the zoom_out and implementation_readiness personas, the implementation-readiness standard, the design including its "Parent-approved after round 2" section, both design reviews and the report.

## The parent-approved rules are implemented as written
- **Both writer-loop checks** (`factory/run.py:1364-1366` and `:1523-1525`) still require `case_hash` equality. They then require `repair_requested OR (extension is not None AND full tree == entry.case_sha256)`. For non-extension runs nothing changes: the `extension is not None` test comes first, so the import of `extensions` that only extension runs make is never reached.
- **Package entry** (`factory/extension_package.py:350-357`): if the receipt qualifies but the full tree differs, the code returns False and goes on to `write_and_attack`.
  - With no repair requested, it reaches G1, early checks and stress. Two tests cover this: `test_freshness_only_no_repair_keeps_g1_and_stress_route` and `test_completed_freshness_only_no_repair_falls_through_package_entry`.
  - With a repair requested, the writer loop raises `unchanged_repair`, and then `after_stop` gives `extension_snapshot_changed` with history still open (`test_freshness_only_repair_keeps_evidence_stop_and_open_history`).
- **N3 (unreached frontier):** the card gets no `failed_gate`, so `_held_stage` returns `'unknown'`. `UnknownDiagnosisTests` runs this through the real finalizer, the restore receipt, `queued_inputs` and `validate_result`.
- **N4 (all-pass entry):** refused both before completion (`:357`) and when the proof is read back (`:338`), tested by `test_all_pass_entry_is_refused`.
- **Next diagnosis:**
  - `apply` → `comparison_pair` on identical entry and outcome gives `no_progress`, never pending.
  - `admit_extension` → `subsequent_entry` then hits `unchanged_outcome` (`:575`) before `current_pair` or `Evaluator`, so it raises `retired_no_progress` even after version drift.
  - The ordinary progress rule, snapshot schema and `scientific_version` are not changed.
- **Saving the outcome:** the proof is written with `atomic_json` in a system temp directory. `extensions.complete(evidence_root=...)` only passes that directory through to the existing `_save_case`, which keeps its copy-and-rename before the history write. Retrying after the rename reuses the same bytes, and the rename-before-history test checks this.
- **Replay** (`run` `:407-409`, `completed_route` `:396`): it checks the proof by its fixed path and the receipt hash against the retained case copy. It never calls `writer_receipt`, writer, stress, gates or money, and replay is tested with all of those patched to fail.
- **Scope:** no existing test assertions changed, and no Murphy rows are closed.

## Checks I ran
- **New tests:** I re-ran `tests/factory/test_stream_d_unchanged.py` and all 15 tests passed in 43s.
- **Suite record:** the passing record matches HEAD `3def7d9`, tree `6a148b01…`, and log sha256 `db1e2363…`. Between `f00b673` and `3def7d9` no files under `factory/` or `tests/` changed. HEAD adds only docs and the record.
- **First full run:** it had 1 failed script, and it is correctly kept as a failure record, not counted as a pass.

## Nits (optional)
- **N-a:** `factory/extension_package.py:345`: the separate `except BudgetError: refuse()` could join the tuple above it. The behaviour is the same either way.
- **N-b:** in `tests/factory/test_stream_d_unchanged.py:213-216`, tampering `output_sha256` only checks that `complete_unchanged` returns False. The actual refusal comes later, from `write_and_attack` as `writer_output_changed`, and nothing tests that end to end. Optional.
- **N-c:** the version-drift test calls `admit_extension` directly, not through `apply`. The `comparison_pair` step in `apply` makes no paid calls, so nothing is missed. Optional.

I made no edits, live or paid calls, or subagents.

## Writer disposition

Accepted PASS. No blockers or majors; optional N-a through N-c remain recorded above. No production or test changes follow review. Full suite: 173 scripts / 0 failures at 3def7d9, production code f00b673. No Murphy rows close; activation remains off. This increment is complete for handback, with no further slice started.

