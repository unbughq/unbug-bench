# Goldfish diff review 4: single launch path, round-3 nits and rebase onto stream E

Reviewer: fresh Claude subagent, persona implementation_readiness, Mode: REVIEW, read-only. Verbatim.

Review of `slice/single-path` at dd93822 (rebased onto 3f7521b): **PASS**, with one NIT and no BLOCKING findings. The full suite passes in a scratch worktree: 132 scripts, 0 failed.

The worktree was created detached at dd93822, because the `slice/single-path` branch is already checked out in a T3 worktree. It has been removed, and the main checkout is still on `factory-simplify` at 3f7521b.

## Findings

1. **NIT, `factory/batch.py:62`.** The release-input check covers `root`, but the qualification step tests a different copy of the code.
   - The commit-equals-HEAD and clean-tree checks (lines 55-61) run against `--root`.
   - The qualification script is found from `Path(__file__)`, so it runs against the checkout that `batch.py` is executed from. That includes the `launch.sh` it reads and the `restore_inventory` root it uses.
   - The two are the same when `batch.py` is run as `<root>/factory/batch.py`, which is how it is normally used. Running `/other/factory/batch.py build --root /repo` would check `/repo` but qualify `/other`'s working tree.
   - Fix: resolve the qualification path from `root`, or refuse when `root` is not `Path(__file__).parents[1]`.

## What I checked

**Nit fixes from round 3**
- **Nit 1, Git errors: fixed** (`batch.py:36-50`). `CalledProcessError` and `OSError` are caught; a missing `git` raises `FileNotFoundError`, which is an `OSError`. The code then falls back to `root/sealed`. The test (`test_batch_launch.py:155-161`) uses the real store with both errors. The no-inventory test now runs before `git init`, so the "outside a git repo" case is covered.
- **Nit 2, non-HEAD or dirty builds: fixed** (`batch.py:55-61`). Both are refused before qualification and before `mkdir`. The test covers non-HEAD, unstaged, staged and untracked changes, and asserts that no release directory is left. The earlier test that accepted a dirty source now asserts rejection, then rebuilds from a clean tree to the same digest.
- **Nit 3, inventory shape: fixed** (`test_restore_inventory.py:43-122`). The missing-key test uses `next(..., None)` and skips when nothing matches. The test that required more than 0 unwrapped archives is gone, and the over-500 MB check is now conditional. A new wrapped-only subset test runs against real data: 12 wrapped archives, 0 unwrapped, largest 355,936,660 bytes, which gives a 1,360 s timeout. The stream B hand-off row `new-single-path-1` follows the `new-<topic>-<n>` naming rule in `docs/ENGINEERING.md:92`.

**Rebase conflicts with stream E**
- `tests/tools/test_launch_manifest.py:80-81` keeps both E's `runner_supervisor.py` and the slice's `batch.py`.
- `docs/murphy-register.md` keeps E's closed row 52 and its evidence unchanged, then appends the new row.
- Tests changed to use E's process wrapper:
  - `test_resume.py` now patches `run_artifacts.processes.run`.
  - Its child test runs get `BENCH`, which `run_artifacts` needs to import `processes`.
  - `test_batch_launch.py:86-87` asserts that the batch launch command uses `runner_supervisor.py` and sets `FACTORY_RUNNER_SECONDS` and `FACTORY_RUNNER_GRACE_SECONDS`.

**Stream E's lifecycle and timeouts are unchanged**
- The slice removes no line E added to `launch.sh`, `run.py`, `run_artifacts.py` or `bin/`. In `bin/`, the slice only touches `qualified-release.py`, adding the `--batch-record` argument; `processes.py`, `boat-launch-guards.sh` and `runner_supervisor.py` are untouched.
- All of E's markers are still present in `launch.sh`:
  - the supervisor on both the fresh and resume paths (lines 596 and 741);
  - the runtime and grace bounds;
  - `STARTUP_FAILED` (line 434);
  - per-worker setup isolation, which retires only the failed worker (line 750).
- The slice's new restore transfer runs inside E's per-worker setup subshell and keeps its own size-scaled `BOAT_COMMAND_TIMEOUT_SECONDS`.
- The `run_artifacts.py` change only raises for batch cards when no case key can be produced. Legacy restores behave as before.

## Suite
`uv run --with numpy --with scipy python -B tests/run.py`: **132 test scripts run; 0 failed** (exit 0).
- The required inventory check ran against the real store: 43 checkpoints, 30 without case keys, 13 wrapped legacy. The largest is 527,987,760 bytes, which selects a 2,017 s timeout.
- The wrapped-only subset ran on 12 real checkpoints.

**PASS**

## Elephant resolution

**Nit, `batch.py:62`: deferred, as a known limitation.**

- **Option 1 tried:** resolving the qualification from `root`. This correctly refuses roots that have no real inventory. It breaks `test_batch_launch`, which builds from a temporary public copy on purpose.
- **Option 2 tried:** refusing when `root` is not the running checkout. This breaks the same test.

The misuse this nit guards against is running one checkout's `batch.py` with `--root` pointing at another. Nobody does that today: stream B's batch service runs `batch.py` from its own checkout. Revisit this in stream B's design if the service ever builds from a different root.
