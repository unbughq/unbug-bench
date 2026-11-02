**Verdict: PASS** for diff review round 1 of 2, `b75c9b4..caba7e6`, reviewed with the zoom_out and implementation_readiness personas, Mode: REVIEW. No blocking finding is open. I made no edits, started no workers or subagents, and made no paid calls.

## Evidence checked
- **Suite record:** `head` is caba7e6 and `tree` is 43ebc77cbe160802146b999992dea1fa4e3a6768, which matches `git rev-parse caba7e6^{tree}`. The log's SHA-256 is 87f8ab62…0fc47, matching the record. The log ends "179 test scripts run; 0 failed", and it includes `test_stream_d_writer_early.py` with 11 tests OK. The recorded command is the required locked command.
- **HEAD ffe4b47:** it changes only docs and suite evidence. There is no diff under `factory/`, `tests/` or `bin/` between caba7e6 and HEAD.
- **Focused test:** I re-ran `tests/factory/test_stream_d_writer_early.py` offline. 11 tests pass.
- **Existing tests:** no existing test file changed. The only test change is the new file.

## Scope checks (all sound)
- **Optional defaults:**
  - `write_and_attack(writer_early=None)` falls back to `early_checks` at both sites (`run.py:1537`, `run.py:1553`), and dry-run skipping is unchanged.
  - `on_rejection=None` passes straight through `run.early_checks` (`run.py:961`).
  - The other callers (`run.py:1680` and the existing tests) use the old path.
- **Publication outside the retry:** the callback runs after `gate_attempt.execute` returns and after `problems` is built (`gate_pipeline.py:100`). Exceptions skip it. The save-OSError test proves G15 runs only once.
- **Stale saved-cheat summary:** the entry is popped right before `saved_cheat_check` (`gate_pipeline.py:103`). The summary is a deep copy and can be None. Replay removes the marker when the summary is None. The test seeds `ok:True`, then hits a real CaseProblem raised inside `cheat_runs`.
- **Private namespace and version:**
  - `saved-cheats` has its own version digest (G6 scientific version plus `early_cheat_check` source).
  - Its `inputs.json` comes from the G6 inputs plus `kind` and `sample_source`.
  - It is written under `saved-cheats/`. No G6 record, G6 cache or `c.early['G6']` is created, and the test asserts all three.
- **Package-entry replay before G1:**
  - It sits after `complete_unchanged` and `public.complete`, before `public.capture` (`extension_package.py:500-504`).
  - It refuses when an early record sits next to a G1 record, or when more than one early record exists.
  - The receipt check requires actor writer, phase completed or validated, `repair_pending is False`, and output equal to the current `case_hash`.
  - Only `extension_comparison_pending` is mapped to `extension_execution_pending`; every other refusal propagates.
  - In the kill-after-save test, G1, the early checks, setup and the checkpoint all raise if called. The record and the receipt stay byte-identical, the receipt stays `completed`, and the writer runs once.
- **No fabricated passes:** a record with `ok` true refuses. Replay restores only `{'ok': False, 'minutes': 0}` or the retained summary. It does not set `c.early` or a G1 pass, and it clears `early_hash`.
- **Worker-count validation on a copied context:** `probe` gets deep-copied args and card, and live args are never changed (the test asserts they stay 2). The test uses the real `scientific_version`; the only mock of it is in a different class, `PackageRecordTests`. With 2 workers, `bin/factory_pool.py` enters the inputs, so if the recorded count weren't applied, the direct `replay_writer_early()` call at test line 173 would raise. That makes it a real regression check.
- **Refusal cases:** missing, tampered and symlinked support, case drift, version drift (held), a record changed to pass, empty feedback, `bench_workers=True`, and an extra G1 or G15 record are all covered. Pending-shaped returns and exceptions from the sample (InvalidInfra, TimeoutError, BudgetError) publish nothing.
- **Real artifacts:** G4 and G5 run on the real `invalid-runs-real.json.gz` executions, and saved cheats are judged for real over the saved reference execution. The writer, G1, G15, G3 and checkpoint transport are labelled as authored controls.
- **Merged routes:** G1, public-match and blocking-stress keep their paths unchanged. Their existing assertions are untouched, and the full suite passed.
- **Out of scope, as briefed:** no Murphy row closes, and nothing changes in activation, limits, attribution, schema or the normal gate versions.

## Optional findings (not blocking)
1. **Major, optional: the receipt-authentication branch has no test of its own.**
   - Where: `factory/extension_package.py:263-267`.
   - Problem: if that check were deleted, every test would still pass. The only refusal that reaches it is the case-drift exam, and `load`'s `case_sha256` check would refuse that case anyway.
   - Suggested fix: add one refusal exam on a valid G5 record with a receipt that has `repair_pending: True`, or `phase` other than completed or validated. Expect `extension_snapshot_changed` and no G1 or early call.
   - Why not blocking: the design's exam list doesn't name this case, and the code itself is correct.
2. **Nit: `writer_receipt` can write before it refuses.**
   - Where: `extension_package.py:263`.
   - If `current == previous`, `writer_receipt` writes `attack-state.json` with the intent receipt (`extensions.py:341-343`) before the phase check refuses. A legitimate record can't exist in that state, but it is a write on a path that is meant to refuse. Accept this, or document it.
3. **Nit: a G3 record's replay count comes from the card.**
   - Where: `extension_package.py:99-102`, together with line 279.
   - For a G3 record, `load` overwrites `probe.args.bench_workers` with the card's `bench_workers_effective`, so the recorded `writer_observation.bench_workers` is ignored, and replay refuses if the card lacks that value.
   - This can't happen today, because real G3 returns True or raises (`run.py:2468`). Note it for the terminal slice.
4. **Nit: the replay branch at the start of `writer_early` can't be reached after the entry check.**
   - Where: `extension_package.py:294`.
   - Round 2 already accepted keeping it.

Next-slice obligations remain open, as briefed: stricter receipt consistency at terminal time (`next_phase`, `validation_problems ==` retained feedback, exhausted/`rounds_exhausted`), terminal completion and progress, and irrelevant-edit rerolls.

## Writer disposition

PASS accepted; no blocking finding remains. Per parent instruction, hand back immediately after PASS. Optional receipt-authentication test and stricter terminal receipt consistency are carried to the terminal/progress slice. The existing writer_receipt reconstruction side effect on an illegitimate state is accepted for this capture-only slice. G3 rejection cannot occur with the real gate today; its worker-count caveat is recorded for terminal work. The shared replay helper stays as accepted in design round 2. No production changes after reviewed caba7e6; no Murphy rows close.

