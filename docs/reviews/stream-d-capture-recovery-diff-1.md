**PASS.** Diff review round 1 of 2 for `5b28ed1..32235e9` found no blocking findings. I also checked the evidence/docs commit, HEAD `408a2ee`. It changes no production or test code.

I read the engineering rules, the zoom_out and implementation_readiness personas (Mode: REVIEW), the readiness standard, the design including its "Parent-approved after round 2" section, both design reviews and the report. I made no edits. The only thing I ran was three focused tests without the lock: the one-shot ACK test, the persistent-failure test and the invalid/pre-existing proof test. All three pass (3 tests, 11.6s).

## What the implementation does, against the brief
- **At most two publication attempts, evidence only.** `Records.save_observation` (`factory/extension_package.py:322-353`) never invokes a gate.
  - If the target is missing after a failure, it retries `save` once, so there are never more than two saves.
  - If the target exists after a failure, it verifies the record and calls `_sync_tree(target)`. A failed sync is verified and synced again on the second pass, without calling `save`.
  - It returns `True` only after a save or a sync has returned.
- **No gate rerun.** `invoke()` sits outside the capture try in `observe_gate`. All work after the gate returns is under `except Exception`, so `BaseException` still passes through, and the original tuple is always returned. The two destructive `rmtree` paths are gone. Pre-invoke handling still catches only `CAPTURE_ERRORS`, as accepted under O3.
- **Frozen inputs and pins.** `info` and `old_card` are deep-copied, and `case_hash` and `version` are pinned before the first attempt. Both are re-checked before each attempt. A pre-existing target, including a symlink, returns `False` without calling `save`.
- **JSON result equality.** Both sides are compared with `extensions.digest` of `{ok, info}`. NaN, or keys that can't be sorted, raise and return `False` before any save.
- **Copied G3 context.** Verification builds `probe = copy.copy(c)` with deep-copied `args` and `card`, the same pattern as `replay_writer_early`. So `load('G3')` writing `bench_workers` cannot touch live state.
- **Published proof is never changed.** A corrupt, mismatched or symlinked record leads to `False` and is never deleted or replaced.

## Exams, against the parent-approved spec
- **One-shot G1 test.** Only the first post-rename parent sync fails, and verification sync succeeds. The test asserts:
  - one save per stage;
  - each gate runs once;
  - the G1 bytes are unchanged;
  - `closed.json` is present;
  - the snapshot equals the baseline run with the same uuid.
- **Persistent failure test.** G1 runs once and its bytes are retained. Every later executed stage gets two saves and one execution, `closed.json` is absent, and entry stays pending.
- **Other exams present and matching the design:**
  - real G4/G5 copy retry;
  - stress ACK recovery with no extra stress validation;
  - RuntimeError from save and from verification;
  - JSON tuple/int-key normalisation with G3 isolation;
  - the eight refusal sub-cases (pre-existing, symlink, corrupt, different result, verification error, case drift, version drift, NaN);
  - a one-time kill after G4's rename, with frontier at G5, the prefix passing, no evaluator and no save.
- **Scope.** No changes to activation, limits, versions, schema or the Murphy register. Retired adapters are untouched. Absent or corrupt proof stays held for the final integration.

## Suite record
The record checks out against the repository:
- `head 32235e9…` and `tree 6fcd4d93…` match `git rev-parse`.
- The log's SHA-256 recomputes to `cf64192b…`.
- The log footer reads "182 test scripts run; 0 failed. / exit 0", and `test_stream_d_entry.py` ran 27 tests, all OK.
- The run used plain detached `lockf`, with the 7200s timeout counted from lock acquisition.

## Optional findings (non-blocking)
1. **The outer `except Exception` in `observe_gate` is untested on its own.** Every RuntimeError exam raises inside `save_observation`, which already catches it. A mutant that reverts `observe_gate` to `except CAPTURE_ERRORS` would likely still pass. One test that raises a RuntimeError from a post-invoke `case_hash` call, then asserts one execution and the original tuple, would pin it.
2. **The real G4/G5 exam has no baseline run.** It checks against the saved artifact, the live support digests and frontier G5. The design's wording is "same as baseline", so this proves the same property by a slightly different route.
3. **The stress ACK test doesn't count stress saves.** It doesn't assert exactly one `save('stress')`.
4. **`observe_stress` still catches only `CAPTURE_ERRORS` outside the helper.** It runs before the pipeline, so it cannot cause a gate rerun. This is out of scope and noted only.

## Writer disposition

PASS accepted. No blocking finding remains. Optional findings 1–4 are recorded as non-blocking follow-ups; no production or test changes are made after review. Handing back immediately under the parent's rule, with no additional review round. No Murphy rows close.

