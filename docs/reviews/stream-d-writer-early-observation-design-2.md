**Verdict: PASS.** This is round 2 of 2 for `docs/designs/stream-d-writer-early-observation.md` at `8989180`, reviewed in REVIEW mode with the zoom_out, design_critic and implementation_readiness personas against both standards. No blocking finding is left open, and nothing needs to go to the parent. I made no edits and started no subagents or workers.

## Blockers from round 1: both fixed

**B1 (the saved-cheat summary could be left over from an earlier round): fixed.**
- `early_cheat_check` (`factory/run.py:1837-1853`) writes `early_gates.saved_cheats` only after `cheat_runs` succeeds. Clearing that entry just before `saved_cheat_check` (`gate_pipeline.py:101`) therefore makes `summary` either this call's result or `None`.
- The only other reader is `bin/gate-smoke:145`. It calls `run.early_cheat_check` directly, not through the pipeline, so the clearing doesn't affect it.
- Replay drops a leftover marker when `summary` is `None`.
- The test that seeds a stale `ok: True` summary and then hits a real CaseProblem proves this.

**B2 (G1 ran again on replay): fixed with option (b).**
- The lookup at package entry happens before `public.capture`/`write_and_attack`, so `resume_writer_validation` (`run.py:1283, 1551`) and `writer_g1` are never reached. The exam that forbids G1 and every early evaluator is now consistent with the design.
- The hold label matches today's fresh path. A fresh rejection ends with `attack_unresolved('rounds_exhausted')`. `package.run` swallows that, and `stress()` then refuses with `extension_execution_pending` because the receipt's actor is the writer (`extension_package.py:289-298`). The early raise at entry gives the same package-visible label.
- Receipt check: `complete_writer` (`run.py:383`) sets `phase='completed'`, `repair_pending=False` and `output_sha256=case_hash`. Every window in which a record can exist (completed, done→completed, or validated/exhausted) passes the stated checks.
- Calling `extensions.writer_receipt(c)` at entry adds no new side effect. `complete_unchanged` already calls it at the same point (`extension_package.py:366`). For a completed or validated receipt it only reads the ledger and sets `builder_rounds`; it rewrites `attack-state.json` only when `current == previous`, which can't happen in these phases. So the receipt stays byte-identical.
- If no record has been published yet, the run still takes the ordinary resume path (G1 live, then the early checks). That matches the "kill before publication" exam.

## M1 decision (not adopting the simplification): confirmed correct

- `scientific_version` removes the numeric `bench_workers` setting (`gate_state.py:211`). However, `inputs()` → `dependency_files()` without `include_pool` skips `bin/factory_pool.py` when `bench_workers == 1` (`gate_state.py:113`).
- `bin/factory_pool.py` is in `MEASURE` (`gate_state.py:24`), which G4, G5, G6 and G15 all depend on. So the version differs between one worker and more than one.
- G3 lowers the live `c.args.bench_workers` during the same early pass (`run.py:2451-2456`), before G4 and G5 save their records. At package entry no G3 has run, so the args still hold the requested count. Without the recorded count, a run that ended up at one worker but resumes asking for two would show false version drift.
- G15 runs before G3, so `bench_workers_effective` in the card can be missing or stale. That is why the count must come from the live args at save time, not from the card.
- The copied-context approach follows the `entry()` precedent (`extension_package.py:554-555`). It is the right size, and requiring the reduced-worker test to use the real `scientific_version` is necessary.

## Compatibility with already-accepted work

- **G1 capture:** a G1 record on its own still goes through `writer_g1`. A G1 record next to an early record is refused. Because the entry check now runs before G1, the two-records case from round 1 can't arise.
- **Lane 1 public-match capture:** the two can't conflict. `public.capture`/`_intent` need a `stress_tester` receipt (`extension_public_match.py:49`), and an early rejection never reaches stress. A `freshness_public_match` BudgetError is an exception, so it never triggers the callback.
- **Other stage records:** gate records in this root come only from `run_gates` after stress, and the entry branch requires no stress record. `observe_gate` writes to the separate `entry-records/` root.
- **Saved cheats vs G6:**
  - The design special-cases both places that would otherwise fail: `version()` and `inputs()` (via `STAGE_DEPENDENCIES` and the `KeyError`).
  - `saved-cheats` isn't in `REUSABLE`.
  - `early_gates` is in `EXCLUDED`, so restoring the marker explicitly is required.
  - No G6 pass/fail, cache or `c.early` entry is created.
- **Scope:** no change to terminal, progress, activation, allowance, attribution, snapshot or any existing gate version, and no Murphy row is closed. Rows 9 and 13 are supported but not closed, which is consistent.

## Readiness

There are zero implementer decisions on the paths that can actually happen. The file, the hooks (`writer_early`, `on_rejection`, `Records.replay_writer_early`), the record shape, label mapping, refusal set and exams are all specified. Heilmeier cost, timeline and midterm/final exams are all present. Land10 must merge before implementation starts.

## Optional findings (not blocking)

1. **Major, optional.** For a validated receipt, the entry check doesn't require `next_phase == 'writer'`, `exhausted`/`stop_reason == 'rounds_exhausted'`, or `validation_problems ==` the retained feedback. An inconsistent state (for example a receipt awaiting stress next to an early record) would be held as `extension_execution_pending` instead of refused as `extension_snapshot_changed`. Both outcomes are holds, so this slice scores nothing wrong. The next terminal increment, which "must accept these two authenticated publication windows", should add these checks if it trusts this authentication.
2. **Nit, simplification.** Once the entry check exists, the replay branch inside `writer_early` (line 143) can't be reached: any published record is found at entry first. If it ever did run, its feedback would flow into the validated/exhausted receipt rewrite. Consider making `writer_early` refuse if it finds a record rather than replay it, or rely on `Records.save`'s existing "target exists" refusal.
3. **Nit.** Lines 86-89 still say replay "ends in the existing writer exhaustion hold". The binding amendment (lines 152-157) replaces that with a direct raise at entry. One sentence saying the amendment overrides lines 81-89 would remove the ambiguity.
4. **Nit.** Say where the entry check sits relative to `complete_unchanged`/`public.complete`. Recommended: after both, immediately before `public.capture`. Both are mutually exclusive with an early rejection, so this only removes a judgement call.

## Writer disposition

PASS accepted. Optional receipt-consistency strengthening is explicitly assigned to terminal completion; this slice publishes no outcome. Keep the reviewed shared replay helper at both entry and writer_early (no extra refactor). Clarify the binding amendment's precedence and put the package entry check after complete_unchanged/public.complete, immediately before public.capture. Implementation awaits land10.
