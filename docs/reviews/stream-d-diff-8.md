**Verdict: PASS.** `84cf56c..512eee4` is an exact, justified test migration. It keeps the original assertions and hides no regression. I found no blocking findings and no nits that need action.

**Method**
- I read `zoom_out.md`, `implementation_readiness.md`, the readiness standard and `docs/ENGINEERING.md`. I did not read `docs/designs/stream-d.md` end to end, only the 8-line addition in this diff.
- I read the full diff (18+/2-, three files) and the production helpers `calibration.compatible_identity`, `compatible_panel` and `run.calibration_identity`. I also read `factory/invalid-runs-compat.json` and the smoke preflight test body.
- I confirmed with `git diff --stat` that `5bc8224..512eee4` does not touch `factory/calibration.py`, `factory/invalid-runs-compat.json` or `factory/gate_state.py`. I saw no frozen-artifact paths in the diff's file list.
- I ran a throwaway probe in the scratchpad that subclasses the real test setup, with no edits and no git writes.
- I reran the focused tests: `test_invalid_runs` and `test_gate_smoke` give 41 tests OK. I did not run or check the full suite.

**Findings**
1. **Cause is exactly as described.** The live identity differs from C's pinned `current_*` policy on one name only: `runner/calibrate`. Live is `9a84cd60…`, pinned is `49660ac1…`, base is `006fed7a…`. D's `run.py` changes (`prepare_dispatch`, the `owner_channel` kwargs, `parent_call_name`) altered `calibrate`'s source. Every other pinned runner and file entry still matches, and there are no top-level identity differences.
2. **The migration assertions keep their meaning.**
   - The test now builds C's pinned current inventory from the policy file, not from live source. So `assertTrue(compatible_identity(old, current))` still proves the pinned base→current migration succeeds only there.
   - The seed-change and `bin/bench.py` negatives still run against `current` and still refuse.
   - The panel assertions are unchanged.
3. **The new `assertFalse(compatible_identity(old, live))` refuses for the right reason.**
   - Patching live's `runner/calibrate` to the pinned value flips the result to True (`old->patched-live True`).
   - So the refusal comes from the `calibrate` hash and nothing else.
   - Production correctly refuses D's source, and the test now locks that in. This also shows the helper has no hole that lets live source inherit C's grant.
4. **The smoke test's mutation is valid.** `case_budget_boundary(c, requested,` occurs once in current `model_runtime.py:293`. D changed that call to add `lease_id=...`, which is why the old literal stopped matching. The test still asserts `assertNotEqual(invalid, original)`, so a future silent no-op replace fails loudly. It still asserts the preallocation preflight rejects the hash mismatch, plus the unrelated-edit, null-hash, `run.py` and all-names cases.
5. **The design note is accurate and scoped.** It says production pins and captured artifacts are unchanged and that D's scientific migration is still pending. No Murphy closure is claimed, and the elephant–goldfish flow in `ENGINEERING.md` allows skipping a design for a fix under 20 lines.

**Residual, not blocking**
- Until D adds its own pinned migration, C-era calibration attempts are quarantined by the live runtime. That is intended and documented as pending. It is runtime behaviour in the other review's scope, not this diff.
- The new `assertFalse` does not name `runner/calibrate` as the cause. I confirmed that cause by probe, and it is not worth a test change.

## Elephant response and fixed/rejected ledger

- PASS accepted. No blocking finding or nit needs a fix; no finding rejected.
- This narrow review covers only 84cf56c..512eee4. Fresh review7 covers the runtime implementation and full design/contracts. Full-suite validation remains pending.
- No Murphy row closure claimed; the scientific migration remains a later obligation.

## Full-suite validation

`uv run --with numpy --with scipy python -B tests/run.py` completed with
136 test scripts, 0 failed, on the runtime/source-test tree at 512eee4
(5dc7750 adds this review only). Log: /tmp/stream-d-increment-2-verified-suite.log.
The first run had six failed scripts; four legacy adapter failures and the two
exact source-test migrations are fixed above. Runtime goldfish7 remains required.
