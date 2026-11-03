# Practice startup repair, diff review round 2 of 2

**Verdict: PASS.** No blockers or majors are open. Both round-1 findings are fixed, and the tests for them fail when I put the old behaviour back. There are three optional nits.

**Scope.** I read the worktree only, at `t3/batch-service-control-vm`, HEAD `9ebce99`, and reviewed it against `docs/designs/practice-startup-error.md` (parent-approved), design reviews 1 and 2, and `docs/reviews/practice-startup-error-diff-1.md`. I used the zoom_out and implementation_readiness personas with `implementation-readiness-standard.md`.
- **Commits reviewed:** `0ee9831`, `3f9a841`, and the startup-specific effect of merge `3804bba`, plus `6785aa7`, `b7f6a97` and `9ebce99`.
- **Out of scope:** the upstream containment, Stream D and parallel-runner content, and Boat settlement `0292abc`.
- **What I did not do:** no edits to the worktree, no git changes, no Docker, network, provider or model calls, no delegates and no full suite. The worktree is still clean at `9ebce99`.
- **What I ran:** the `Diagnostics` tests offline, in a throwaway `git archive` copy that I deleted afterwards. No Docker test was run.

## Round-1 findings

**B1 (case output reached the public card): fixed.**
- `factory/run.py:2840` now stores only `type(error).__name__` in `early_probe.skipped`.
- The new test `test_early_probe_keeps_real_command_output_out_of_public_card` runs a real `sh(check=True)` failure through the real `early_probe`. It asserts that the card holds exactly `'RuntimeError'`, that neither the private SQL text nor the conflict text is in the card JSON, and that both are in `logs/commands.log`.
- **Mutation check:** I put back `f"{type(error).__name__}: {error}"[:200]` and the test fails, because the card then shows `'RuntimeError: python3.14: exit 1\nPRIVATE_CASE_SQL: …'`.
- Nothing in production reads the `skipped` text. A grep finds it only in tests.

**M1 (nothing protected the forced `check=True`): fixed.**
- The mode-test stub now calls `execute(args, cwd=root, timeout=3600)` with no `check`, which matches the real fresh path in `bin/factory_pool.py:61-66`.
- **Mutation check:** I changed the adapter at `run.py:3414` to `lambda cmd, **kw: sh(c, cmd, **kw)`. All 8 mode subtests then fail:
  - ordinary, resume, audit-fairness, late-gate-rehearsal, statement-only and extension reach `pick_models`, giving `runner_error:AssertionError`;
  - dry-run gives `FileNotFoundError`;
  - rehearse-only gives `AttributeError`.

  The real code passes all 3 `Diagnostics` tests.

**N1 (project constant could drift from the compose file): fixed.** The Docker exam now asserts `name: <COMPOSE_PROJECT>` against `projects/medusa/compose.yaml`. This check runs before the Docker skip, so it applies on every machine.

**N3, N5 and N6:** recorded in the report. **N2 and N4:** still open and optional, as the design allows.

## Startup changes in the merged tree

- **Merge `3804bba` left the startup code alone.** Its `factory/run.py` changes are limited to `early_checks`/`writer_early`. It changed none of `sh`, `command_error_tail`, the adapter, the handler's `error_evidence` or `early_probe`. It did not touch `bin/bench.py`, `bin/factory_pool.py` or `tests/factory/test_practice_startup.py`.
- **Murphy register:** the merge changed only the `new-isolation-settlement-1` row. Both practice-startup rows came through unchanged.
- **Final tree matches the design:**
  - `prepare_factory_main` (`bench.py:360-374`) force-removes the four `{COMPOSE_PROJECT}-*-1` names, suppressing `RuntimeError`, then runs `down -v`, then `setup()`.
  - `run.main` calls `prepare(1, fresh=True, execute=<check-forcing adapter>)` with `previous_slots` left at its default, before model selection.
  - The handler card's `error_evidence` is the constant `logs/runner.log`.

## The two changed test assertions

- **`test_calibration_attempts.py:190` and `test_parallel.py:134`** now check for exactly `'BudgetError'` instead of `'provider_limit' in skipped`. This follows directly from the type-only card.
- **The behaviour checks are all still there:**
  - the receipt is absent;
  - the label is `None` when `want` is false;
  - the attempt is not counted as a completed failure.
- **One lost detail:** the assertion no longer pins *which* `BudgetError` was swallowed. Only `provider_wait` and `model_call_cap` are re-raised, so any other `BudgetError` would also pass (see Nit 2).

## Suite provenance

| Record | Commit | Tree | Result | Hashes |
|---|---|---|---|---|
| `20261103T182159Z-a587d574` | `b7f6a97` | `7bf03e4…` ✓ | exit 0, `186 test scripts run; 0 failed.`, qualifying | log ✓, compressed log ✓ |
| `20261103T173952Z-41fc1c40` | `6785aa7` | `a2bfa52…` ✓ | 1 failed, non-qualifying | ✓ |
| `20261103T155412Z-339ea1a0` | `0ee9831` | `e0988c1…` ✓ | exit 143 (interrupted), non-qualifying | ✓ |

- **Qualifying run:** `test_practice_startup.py` printed `REAL DOCKER: conflict, mounted-volume freshness and repeated seed SQL passed` and reports `Ran 4 tests in 35.457s … OK`. That section shows no skip, so the Docker exam really ran.
- **`9ebce99` adds only records:** its diff against `b7f6a97` is the JSON, the log and the report.
- **Failed run at `6785aa7`:** the only failure is `FAILED: tests/factory/test_parallel.py`, on the old `'provider_limit' in …skipped` assertion. That is the line `b7f6a97` updated.
- **A traceback that is not a failure:** a `BrokenPipeError` traceback in `test_model_call_maxima` comes from the TLS test server, and that file reports OK.

## Murphy closures

**`new-practice-startup-1`: closure holds.** The `RealDocker` exam does all of the following:
- It uses a unique project, `unbug-startup-test-<uuid>`, with `COMPOSE` and `COMPOSE_PROJECT` patched together. Images must already be cached (`--pull never`, `--no-build`), and it skips only when the Docker binary is missing.
- It sets up an unlabelled fixed-name Postgres that mounts the labelled project volume, holding a marker file, `bench_checker` and `medusa_seed`.
- It proves the real `already in use` conflict, and that `down -v` alone keeps the volume.
- It runs the real `factory_pool.prepare` and the real `prepare_factory_main` under the real lock, which `LOCK_NB` confirms is held. After preparation the marker is gone, both `CREATE` statements succeed and the unrelated sentinel survives. This repeats for G3.
- **Cleanup:** the `finally` block removes only that project's container, sentinel and volume, plus `compose -p <project> down -v`. The default and shared project is never touched.

**`new-practice-startup-2`: closure holds, and is now complete.**
- The `Closed by` field now also names the `early_probe` test.
- Between them, the tests cover public-card confidentiality on both the top-level handler path and the `early_probe` path.
- Mutation checks above show both paths would catch a regression.
- I found no other path from this diff to the public card; round 1 already checked the other catchers.

## Blockers
None.

## Majors
None.

## Nits (optional)
1. **Nit, `run.py:2840`:** a non-command reason for skipping the probe, such as `BudgetError('provider_limit:<model>')`, is now dropped completely. Command failures still keep their output in `commands.log`, but this reason is written nowhere. Logging it to `runner.log` with one line would keep it private and still diagnosable. The approved design accepts type-only, so this does not block.
2. **Nit, `test_calibration_attempts.py:190` and `test_parallel.py:134`:** the exact `'BudgetError'` check no longer proves the swallowed error was `provider_limit`. The rest of each test still covers the behaviour.
3. **Nit:** N2 (empty tail when one final line exceeds 4096 bytes) and N4 (`SCANNER_SOURCE` read by position) from round 1 are still open, as allowed.

**PASS.** Merging this needs no handback. The parent's merged-tree suite rule still applies, and Boat settlement `0292abc` still needs its own separate review.

## Writer disposition

PASS accepted. B1 and M1 fixed and independently mutation-checked by Claude.
Optional nits remain open. No further startup runtime changes. Parent-required
merge of cache-free parallel-tests and exact-head suite follow this review.

