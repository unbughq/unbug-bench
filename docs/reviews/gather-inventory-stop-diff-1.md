# Diff review 1: gather inventory stop on a0d2b67a (goldfish)

Reviewer: fresh read-only subagent (Claude Sonnet; the writer is Claude Opus, the same model family, since no other family was available in this session). Personas: `zoom_out`, `implementation_readiness`, Mode: REVIEW. The change skipped the design step, so this review was against the commit messages and the 1bb2ad-h9 crash report.

**PASS.** The change fixes the crash, gate identity is unchanged, and the deletions are safe. I found no blocking problems. The items below are non-blocking, and finding 1 needs an ops step before the live check.

## What I checked

- **Gate identity.** I extracted base 3dfdde3c and the head into scratch copies. For every gate in `DEPENDENCIES` and `STAGE_DEPENDENCIES`, I ran `gate_state.source_inputs` against each tree's `factory/run.py`, and I hashed every file listed in `STAGE_DEPENDENCIES`.
  - The 16 gates' source-input maps are identical.
  - All 245 listed files are identical.
  - `seal`, `wipe` and `_run_artifacts` are in `SIDE_EFFECTS`, so rewiring them and the new `gather_bench_results` body stay out of every gate hash.
  - No gate references `gather_bench_results`.
  - `bin/bench.py`, `calibration.py`, `gate_state.py` and `claims.py` are untouched.
- **Regression test.**
  - On the head, `test_live_slot_fixture.py` passes (5 tests).
  - I copied the new test file into the base tree and ran it there. It fails for the right reason on the gather subtest: `docker compose -f …/runs/…/inventory_sources/marketplace/compose.yaml stop marketplace` → "no such file or directory".
  - The seal subtest fails on the base with "False is not true" instead (the compose file is never moved, because `RunArtifacts.seal` is patched out). That is still a fail-before, but it is not the crash.
- **Other tests, all exit 0 on the head:**
  - `test_parallel`
  - `test_resume`
  - `test_sealed_audit`
  - `test_g11_review`
  - `test_isolation_timeouts` (21 tests)

## Does it fix the crash?

Yes.
- The stop runs before any move, and only when the saved `compose` argv names a file about to move.
- Paths are compared as `f.resolve()` strings against bench's stored paths. `bench.ROOT` is resolved, so this is correct, and the macOS `/var` symlink case passes in the test.
- Slot 0 and `factory-slots/N` are both covered. `worker_env(0)` gives `UNBUG_FACTORY_SLOT=0`, which bench treats as slot zero.
- Stopping at gather time is safe for the bench. Services are only used inside a checkpoint process (`bench.py:622`, `:770`). Every `_reset`, `prepare_factory_*` and `retire_*` stops and restarts them anyway.
- `run.seal` now gathers through the same function, so the old seal path is covered in one place. `engine_seal` and `retained_paths` already called `gather_bench_results`.

## Deletions

- The only callers of `RunArtifacts.wipe`, `run.wipe` and `result_dirs_since` were the deleted code and the deleted tests.
- I searched `control/`, `tools/`, `bin/`, `factory/` and `tests/`. Only comments and `SIDE_EFFECTS` mention "wipe".
- `slot_state.always_kept` is a strict subset of `is_state`: `LOCK` is in `FILES`, and `SEED_IDS` is matched for slots. Dropping it does not start gathering the lock or seed IDs.
- `factory_slots` and `pilot_wall` still exist in `run.py` and have other uses. Only the `RunArtifacts` fields went.

## Findings

1. **Non-blocking: boxes already wedged are not healed.**
   - `factory/run.py:3922-3926` stops a service only if the compose file is in this gather's `moving` set.
   - A box that already hit 1bb2ad-h9 has a stale `.inventory-services.json` pointing at a file already moved. The next gather will not match it, so G3 on that box keeps crashing.
   - Deploying needs a one-off removal of those state files, or the fix should be documented as forward-only. Add this to the "live check" note in the register.

2. **Non-blocking: a failed stop only logs.**
   - If the stop fails (daemon down, timeout), `run.py:3927-3929` logs it and the files move anyway, which leaves the same wedge.
   - This is the right trade for not losing the snapshot, and the commit message says so. It should be known that there is no second line of defence.
   - `log()` (`run.py:174`) needs `c.work/logs` to exist. A context without it would raise inside the `except` and abort the gather. This is fine in real runs.

3. **Non-blocking: the committed register is a stub.**
   - The branch adds `docs/murphy-register.md` as a new file with a header and one row (a0d2b67a).
   - The real register (about 101 lines, with the other rows) and `docs/ENGINEERING.md` exist only as untracked files in the main checkout. They are absent from base 3dfdde3c and from this worktree.
   - Merging a tracked stub over the untracked real file will either collide or fork the register. The row text should go into the real register instead.

4. **Non-blocking (nit): the test copies bin/checkpoint's freeze steps instead of running them.**
   - The `probe` snippet at `test_live_slot_fixture.py:~176-190` replicates the copytree and `scenario.json` rewrite from `bench.py:~855-865`, then writes the state file itself.
   - If bench changes how it freezes or saves state, this test will not notice. Real bench code and the real S13 marketplace project are otherwise used.
   - It does not exercise the failed-stop path (finding 2), a non-matching state, or the Docker shim beyond the missing `-f` check.
   - The seal subtest patches `RunArtifacts.seal` to a no-op. That is fine now that it no longer moves files.

5. **Non-blocking (nit): `run.seal` now gathers outside `RunArtifacts.seal`'s 600 s `processes.deadline`.** Each `stop_tester_services` has its own 600 s timeout, so the worst case is longer than before. This is unlikely in practice.

6. **Non-blocking (nit): stale leftovers.**
   - `scorecard_text` (`run.py:3142`) still prints `wipe: <card.get('wipe')>`, which is now always `null`.
   - `"wipe"` stays in `gate_state.SIDE_EFFECTS`. It is harmless and cannot be touched under the constraints.
   - `bin/factory_pool.py:95` and `tests/factory/test_inventory_ports.py:162` still mention "seal/wipe's scope".

## Other paths with the same bug

I found none still open. Every mover of `results/` evidence goes through `results_since` and `gather_bench_results`. Only the bench's own state files are left behind, and nothing else deletes compose files under `results/runs`.

## Elephant response (2026-11-20)

PASS. What I fixed and what I left:

1. **Fixed by documenting it.** The register row now says the fix is forward-only: a box that is already wedged needs its stale `.inventory-services.json` removed once, or a fresh box. This is in the hand-back as an ops step for the coordinator. The code does not heal it, because that would mean deleting bench state for compose files this step never moved.
2. **Left as is.** The snapshot outranks the stop. Every engine context makes `logs/` (`run.py` context setup), so `log()` is safe there.
3. **Fixed (4b7b5eac).** I removed the tracked stub and appended the row to the real register, the untracked `docs/murphy-register.md` in the main checkout, which now has 102 lines.
4. **Left as is.** Running the real `bin/checkpoint` needs Docker and a seeded shop. The test uses the real bench code and the real S13 service, and it copies the freeze steps from `bench.py` line for line.
5. **Left as is.** This is unlikely, and every stop already has its own timeout.
6. **Partly fixed.**
   - Fixed: the `test_inventory_ports.py` comment.
   - Left: `bin/factory_pool.py` is in MEASURE, so editing even a comment would change every bench gate's identity.
   - Left: `gate_state.py` must not be edited.
   - Left: `scorecard_text`'s `wipe:` field is cosmetic and is shown in saved scorecard fixtures.

After the review, the branch also gained 4b7b5eac (the stub removal) and this record, plus the comment fix. None of these touches code paths that the tests or gates run.
