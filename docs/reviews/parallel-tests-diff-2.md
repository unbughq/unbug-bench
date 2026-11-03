**BLOCK**

1. **Blocker: a script is judged finished at pipe EOF, not at its exit** (`tests/run.py:39-40`). With `stdout=PIPE`, `subprocess.run` waits for every descendant that inherited stdout. Repro: a script that does `Popen(["sleep","8"])` and then `exit 1` makes `run()` return after 8.1 s. The serial runner returned at exit. `test_isolation_timeouts.py:75-80` and `test_isolation_outer_callers.py:97-100` spawn daemons that ignore SIGTERM. If containment regresses, a loud FAILED becomes an endless hang that holds a host slot and never prints the counts line. Fix: `with tempfile.TemporaryFile() as out: subprocess.run(..., stdout=out, stderr=STDOUT); out.seek(0); output = out.read()`. Add a leaked-grandchild case to `test_run_slots.py`.

2. **Minor: an interrupt still runs scripts that are waiting for a slot** (`run.py:25-34`, `:70`). `cancel_futures` skips only futures that haven't started. Threads polling in `machine_slot`, which is common when other suites hold the slots, still take a slot and run a full script, and they never get the SIGINT. Fix: set a `threading.Event` in `finally`, and return early from the slot loop and `run()` when it is set.

3. **Nit:** `TEST_SLOTS` of 0 or less loops forever (`run.py:17,26`). Use `max(1, ...)`.

4. **Nit: fixed checkout path.** `tests/bench/test_gate_setup.py:140,152` call `factory_pool.prepare(fresh=True)` with the real `RESULTS`, so they take `results/.bench.lock` with `LOCK_NB` (`bin/factory_pool.py:41-43`). This is safe within one suite. Two unqueued suites in one checkout can make it flake. Fix: patch `RESULTS` to a temporary directory.

5. **Nit: `ENGINEERING.md` step 4 doesn't fully match the design.**
   - It credits "one per CPU" for removing the lock. The real reason is the host-wide `TEST_SLOTS` pool.
   - It leaves out the design's `git rev-parse <commit>^{tree}` check.
   - Old designs (`stream-d-*.md`, `request-only-stress-retirement.md:163`) still prescribe `lockf /tmp/unbug-suite.lock`. Add "do not wrap the suite in lockf".

6. **Nit:** with stderr merged and stdout block-buffered, prints and tracebacks appear out of order in each script's log. `tests/README.md` omits `TEST_SLOTS` and `TEST_SLOT_DIR`.

7. **Cache: fully removed** from the code, flags, tests and docs. 57 stale markers in `~/.cache/unbug-tests` were written today by a runner from before 74dc5c7 in another worktree. They are harmless; delete them after landing.

8. **Verified correct:**
   - argv, cwd and env are unchanged, and stdin is `/dev/null`.
   - The exit code and the counts line are unchanged.
   - `flock` conflicts across threads and is released on exception or kill.
   - `close_fds` stops children inheriting slots.
   - No nested runner.
   - `test_run_slots.py` passes.
   - No colliding ports, paths or container names offline. Keyswap's `/tmp/key.pem` and `:443` are Docker-only.

## Disposition (parent-approved after round 2)
- 1 fixed: output goes to a temp file, so a script is judged at its exit. New test `test_leaked_child_does_not_hold_the_script_open` fails on 74dc5c7 (about 8 s) and passes now.
- 2 fixed: a `STOP` event is set on exit, so threads waiting for a slot give up and report 130. New test `test_interrupt_releases_slot_waiters`.
- 3 fixed: `TEST_SLOTS` floored at 1.
- 5 fixed in `ENGINEERING.md` step 4: slot pool, "do not wrap in lockf", tree check. Old design docs are historical and left unchanged; step 4 governs.
- 6: `tests/README.md` now documents `TEST_SLOTS` and `TEST_SLOT_DIR`. Interleaving within one script's log is left as it is.
- 4 not fixed: `test_gate_setup` can flake only when two suites run in one checkout, which the process never does.
- 7: stale `~/.cache/unbug-tests` markers will be deleted after landing.
