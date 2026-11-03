# Parallel offline suite, no shared lock

**Status:** founder direction, 2026-11-03: "We can't have people waiting for 5 hours to run tests." The pass cache was dropped on the founder's instruction (relayed from thread 796b18cd) after review found that it could reuse stale passes.

## Problem
- `tests/run.py` ran its 184 scripts one at a time, taking about 45 minutes, and each script already ran in its own process.
- To stop several suites from overloading the host, every stream took a host-wide `lockf` before running.
- That turned overload into a queue. On 2026-11-03, streams waited up to 6 hours, about 15 stream-hours in total, and a 12-core Mac ran one test at a time.

## Change
1. **Parallel scripts.** `tests/run.py` runs scripts concurrently: `-j N` or `TEST_JOBS`, defaulting to the CPU count. Each script stays its own process with the same command, cwd and env, and gets stdin `/dev/null`. Output is buffered per script and printed in script order. The exit code and the final `N run; M failed` line are unchanged. An interrupt cancels any scripts still queued.
2. **Host-wide cap instead of a lock.** Before it starts, a script must hold one of `TEST_SLOTS` (default: CPU count) `flock` files in `/tmp/unbug-test-slots`. Every suite on the host shares that pool, so total concurrency stays bounded however many suites run, and suites interleave script by script. `flock` releases when the process exits, so a killed suite never leaks a slot.
3. **Process** (`docs/ENGINEERING.md` step 4):
   - Builders run only the test files they touch while working.
   - They run one full suite on the exact head they hand back.
   - The parent runs one full suite on the merged tree, skipping it only if that tree is byte-identical to the tested one (checked with `git rev-parse <commit>^{tree}`).
   - No `lockf`.

## Deletes
- The shared `/tmp/unbug-suite.lock` convention and its queue rules.

## Not done, and why
- **Pass cache.** Removed. A whole-tree key misses env vars, installed binaries and ignored files. Some tests also exit 0 while deferring a check when a binary is missing (for example `tests/bench/test_refusal.py:165`, "permission check deferred"), so such a pass would be reused once the binary appears. Nearly all the speedup comes from parallelism anyway.
- **pytest-testmon or other coverage-based selection.** 96 of the 184 scripts start subprocesses, and 84 drive `bin/` or shell. Coverage can't see those dependencies, so selection would silently skip affected tests.

## Risks
- **Timing-sensitive tests can flake under full load.** For example: the isolation outer-caller heartbeat test, `test_control_resume`, and the controller-deadline tests. These fail loudly; they don't pass falsely. Check with `-j 1`, and fix the test rather than serialising the suite.
- **Shared fixed paths, ports or Docker names would collide.** The review grep found none in the offline suites. `harbor/keyswap`'s fixed paths are Docker-only, and fixed ports live under `tests/live/`, which the runner does not select.

## Tests
`tests/tools/test_run_slots.py` checks two things:
- two runners sharing one pool never exceed its cap (negative control: with the slot made a no-op, peak > cap);
- a killed holder frees its slot.

## Murphy rows
None closed or added. This is test infrastructure and has no factory failure mode.
