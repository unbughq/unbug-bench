**PASS**

I re-reviewed only `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-ded79ec5`, `bbe20af..af0819f` (HEAD), read-only. I made no edits and no saves.

**What changed and why it's correct**
- **`bin/unbug`**: `sys.dont_write_bytecode = True` is now set right after `import sys`, before `pathlib` or `batch_status` load. There is no `factory/__pycache__/batch_status*` after my test run. The only file in `bin/__pycache__/` is `bench_judging…pyc` from 00:12, which comes from older bench runs, not from this command.
- **`factory/batch_status.py:196`**: the lock is now taken as `LOCK_SH | LOCK_NB`. When the writer holds the lock, the read raises `BlockingIOError`. That is a kind of `OSError`, so `main` (`:232`) catches it and prints `Batch unreadable / Needs attention: unreadable` and exits 1. Status can no longer hang forever. The lock is still opened through `_regular`, so status never creates it and never calls `batch_money.locked`.
- **Dead `card_unreadable` branch**: removed, and `grep` finds no remaining uses in `factory`, `tests` or `bin`. Unreadable cards still show up correctly, because the read failure at `:217-218` sets the row to `unreadable`, which adds the `unreadable` action at `:109`.
- **`docs/designs/status.md`**: the design now says what the code does (nonblocking lock; busy or missing lock means unreadable). Design and code don't disagree.
- **Two new tests**:
  - `test_busy_writer_lock_refuses_immediately` takes the writer's exclusive lock for real.
  - `test_real_entrypoint_does_not_write_import_bytecode` runs the real `bin/unbug` file with the bytecode env vars stripped.

  Both test the actual behaviour, not a mock of it.
- **Original brief**: all other files are unchanged from the diff9 PASS. That includes the snapshot-pinned cards, calls shown as a plain count N with no denominator or threshold, the future lifecycle formatter tests, and the unchanged real-card classifier.

**Test evidence**
- `cd tests/factory && python3 -B -m unittest test_batch_status` ran 12 tests: all OK in 0.189s.
- Running it from the repo root gives an `ImportError` instead. That's only how the fixture imports are set up, not a code problem.

**Blockers:** none.

**Not yet evidence:** the full suite (`/tmp/unbug-b-stream-status-tests.log`) is still running. Process 7969 has been on `tests/bench/test-launch-guards.py` since 04:10. The log has no failures so far and hasn't reached the status tests. The corrections were committed at 04:16:15, after the suite started, so it may be running the code from before the fix. To count as evidence, that log has to finish green on HEAD `af0819f`, or be re-run on it.

---

Elephant resolution: PASS accepted, no blockers or rejected findings. Full-suite
completion remains required; the status script has not run in that suite yet,
so it will execute the final committed status code/tests. Both corrected paths
already pass their direct regressions on af0819f. Record the completed suite
and final source/test hashes in the increment report. No VM changes, spending,
production lifecycle hookup or Murphy closures.

