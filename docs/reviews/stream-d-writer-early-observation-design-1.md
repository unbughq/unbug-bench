**Verdict: BLOCK.** Round 1 of 2 for `docs/designs/stream-d-writer-early-observation.md` at b84304b. There are two concrete blockers, and both have small fixes. The overall shape is sound and kept small: one failure-only record, a callback that runs after the retry step, no G6 namespace and no pass records. I made no file changes.

## Blockers

**B1. The saved-cheats `summary` can be a leftover from an earlier round** (lines 26–29, 80–82)
- `early_cheat_check` (`factory/run.py:1837-1853`) writes `c.card['early_gates']['saved_cheats']` only after `cheat_runs` succeeds. If `cheat_runs` raises a CaseProblem, it returns `[str(error)]` without touching that entry.
- Nothing ever clears `early_gates.saved_cheats`. A grep over `factory/` finds only the write at line 1851, so the live card keeps whatever an earlier round wrote.
- So the claim that "summary may be None when early_cheat_check returned a CaseProblem" is wrong whenever an earlier round recorded a summary. The record would store a stale summary, such as `{'ok': True, 'checked': n}`, next to `ok: False`. Replay would then restore that stale entry (line 82), and the terminal step that reads these records next would get a contradiction.
- Fix: decide on one line. Either `GatePipeline.early_checks` pops `early_gates['saved_cheats']` right before it calls `saved_cheat_check`, or the summary is captured only when this call wrote it. Add the stale-summary-plus-CaseProblem case to the tests (line 117).

**B2. On replay, G1 runs again, and the design doesn't say what should happen** (lines 79–86, 111–113)
- After a crash between saving the record and writing the validated receipt, the receipt still says `phase == 'completed'`. That sends the resume through `resume_writer_validation` (`run.py:1283`, `1551-1553`), which calls `writer_g1` before `writer_early`.
- G1 passed the first time, so there is no G1 record and `r.g1(c)` runs live: the full `contract.inspect` with its retry journal and `sh` calls.
- That leaves two problems:
  - The exam at line 111 says "every early evaluator … forbidden". It is unclear whether G1 counts. If it does, the design fails its own test. The G1 precedent forbids G1 on replay (`test_stream_d_writer_g1.py:85-98`).
  - A plumbing change that touches only G1's dependencies can make the rerun G1 fail. That saves a G1 rejection record next to the existing G5 or saved-cheats record. `writer_early` is never reached, so its "at most one record" check never sees the pair, and the round ends up with two rejection observations.
- Fix: the design must pick one behaviour. Either:
  - (a) allow the G1 rerun as an authored control, and make `writer_g1` refuse to save a G1 record while an early-stage record exists; or
  - (b) have the package check for early records before G1 and skip the G1 call when one exists, with a stated reason why that is safe.

  Then make the replay exam say exactly whether G1 is allowed or forbidden.

## Optional majors

**M1. Drop the copied-context, two-pass load and `writer_observation.bench_workers`** (lines 49–50, 69–77, 114–115). An equally correct version is much smaller.
- `gate_state.scientific_version` already removes `bench_workers` and `concurrent_roles` from the settings it hashes (`gate_state.py`, end of `scientific_version`). The saved-cheats version is built from `scientific_version(c,'G6')` plus `source_inputs`, so it is also independent of the worker count.
- G3's worker cut therefore cannot cause version drift for G15, G4, G5 or saved-cheats.
- The only thing the copy protects against is `Records.load('G3')` changing the live `args.bench_workers` (`extension_package.py:99-102`). That needs a G3 rejection record, which the design itself says doesn't normally happen. Even then, replay ends in the hold and does no bench work.
- Simpler version: call `self.load(stage)` once with the version check, and keep only `writer_observation = {'feedback': problems}`. The "workers 1 vs 2" test (line 114) still passes and becomes a regression check for that fact.

**M2. Simplify the gate marker restore** (line 81). `early_gates` is excluded from what the record saves, so restoring it explicitly is right. But a record saved this way already contains the real `minutes` value in `info`'s neighbourhood. Either keep `{'ok': False, 'minutes': 0}` and state that it is a replay marker, or drop the marker entirely, since this slice claims no progress. Just choose one and record why.

## Nits

- Line 18: `lambda c: records.writer_early(c)` can simply be `records.writer_early`.
- Line 27: `'runs_each': 1` in `detail` repeats what `summary` already holds whenever `summary` is present.
- Line 44: the wording "False-compatible info under comparison._pending" should just say "`ok is False` and `not comparison._pending(ok, info)`", as in `writer_g1`.

## Checked and found sound

- **Retry ownership:** the callback runs after `gate_attempt.execute` returns (`gate_pipeline.py:84-99`), so saving cannot retry a paid gate, and exceptions skip it.
- **Saved-cheats vs G6:**
  - `Records.version` and `inputs` would raise KeyError on `'saved-cheats'` without the special case. The design covers both places.
  - `sources()` has no roots for this stage, and the inventory baseline still picks up the cheat-run outputs.
  - Nothing is written under `G6`, the gate cache or `c.early`.
- **Identity, version drift and the handoff to `extension_execution_pending`:** consistent with `Records.load` and `package.run` (`extension_package.py:445`).
- **Test material:** `invalid-runs-real.json.gz`, `suffix-case` and the checkpoint patch transport (`test_extension_compare.py:29,58,83`) all exist. Using real `verdicts` over saved reference runs, with the cheat guard as a labelled control, matches the `test_invalid_runs` precedent and judges an actual sample. G15 and G3 as authored controls are acceptable because they are labelled as such.
- **Murphy rows:** the design supports rows 9 and 13 and closes none. That is consistent: there are no claims about terminal outcome or progress.
- **Heilmeier standard:** cost, timeline and the midterm/final exams are all present.

Once B1 and B2 are fixed and M1 is taken, this is a PASS candidate for round 2. Land10 has to merge before implementation starts.

## Writer disposition for round 2

B1 accepted: clear saved_cheats immediately before invoking the sample. B2 accepted via option (b): verify/replay an early observation at package entry before write_and_attack/G1, then raise the existing execution-pending hold without changing the writer receipt or inventing a G1 pass. M1's simplification is not adopted: dependency_files excludes bin/factory_pool.py when workers == 1 (gate_state.py:113), so scientific_version still changes through the dependency inventory despite removing the numeric setting. Round 2 must independently review this optional finding disposition. M2 documents minutes=0 as a replay marker; all nits are incorporated.
