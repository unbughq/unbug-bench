**Verdict: PASS.** I found no blockers or majors, and one nit. The text below is ready to save as `docs/reviews/stream-d-diff-26.md`.

---

# Stream D diff review 26

- **Reviewer:** fresh read-only goldfish, Mode REVIEW, using the `zoom_out` and `implementation_readiness` personas.
- **Range:** `dc7935f92cd589f5417edb25f9cb8df193a59e32..c0c2e28fc4f2ad5eb4990ba9185a9a2794a059f5` on `t3/stream-d-implementation`.
- **Change:** one commit, `tests/tools/test_launch_manifest.py`, +2/−0.

## Verdict: PASS

The change adds 4 paths to the hand-written worker-upload expectation:
- `factory/diagnosis_dispatch.py`
- `factory/diagnosis_task.py`
- `factory/prompts/diagnosis.md`
- `factory/prompts/diagnosis-repair.md`

## What I checked

- **The expectation is still independent.** `expected_worker` is still built from the historical real inventory, `/Users/bugsincode/Developer/unbug-bench-e15450-restore-14-20261029/build.json` `source_sha256`. The doc and cutover exclusions are unchanged, and the change only adds explicitly named literals. The test still compares exact sets in both places: `manifest.worker_files(ROOT)` and the tar member names of a really stamped bundle. Nothing in the expectation comes from `manifest.WORKER_GLOBS` or the code under test.
- **The additions are needed.** None of the 4 paths are in the historical `build.json`; I searched it and found no `diagnosis*` entries. So without listing them, the exact-set check has to fail. That matches the single failure recorded at `dc7935f`.
- **The additions are real shipped sources.** All 4 are tracked in git and fall under the existing `WORKER_GLOBS` (`factory/*.py`, `factory/prompts/*.md`). Neither glob nor manifest code changed in this range.
  - `diagnosis_dispatch.py` imports `diagnosis_task`.
  - `diagnosis_dispatch.py:119-120` reads both prompt templates from `source/factory/prompts/`.
  - So the worker needs all four at runtime.
- **Nothing extra is admitted.** The stray-file exclusion check (`factory/unlisted.age`) is unchanged. The only ignored entry under `factory/` is `__pycache__/`, which the globs don't match.
- **ENGINEERING step 2:** an obvious inventory correction under 20 lines may skip the design; this diff review covers step 5. No Murphy rows close and no activation changes, so there is no `Closed by` to check.

## Blockers

None.

## Majors

None.

## Nits

- `tests/tools/test_launch_manifest.py:83`: the line before the new ones is already long and mixes several entries per line. The new lines are fine. If this set is touched again, one path per line would make future inventory diffs easier to review. This is optional and not blocking.

## Validation boundary

- **Ran:** `python3 -m unittest tests.tools.test_launch_manifest` at `c0c2e28` in the worktree: 2 tests, OK.
- **Not run:** the full suite (it is being rerun separately) and launch guards.
- **Not reviewed:** the dispatcher implementation (`diagnosis_dispatch.py`, `diagnosis_task.py` and the prompt contents) beyond confirming they reference the prompt files. That code is covered by diff25, which is still running. This PASS does not mean the dispatcher is ready.
- **Excluded:** `.stream-d-next/`.
- **Merge:** this PASS covers only this 2-line expectation. Stream D should not merge until diff25 passes and the full suite rerun is green.

## Elephant response

Accepted. The optional formatting nit concerns unchanged lines and is deferred until that inventory is next changed. This PASS covers only the explicit four-file expectation; dispatcher diff25 and the full suite remain required. No Murphy row closes.
