**Verdict: PASS. No blocking findings.**

I reviewed `git diff 15e16b5..46ec5ef` against only the "Loaded launch-guard regression (2026-10-30)" section of `docs/designs/isolation-timeouts.md`. I used `zoom_out`, `implementation_readiness` and the implementation-readiness standard, and followed `docs/ENGINEERING.md` §1–§4. I wrote no files and did not run the suite or call Boat.

**Diagnosis vs. diff:** the diff follows the design. Production code is untouched: the only changed files are `tests/bench/test-launch-guards.py`, the new `tests/bench/launch_guard_clock.py`, the design doc and the reproducer. The `bin/boat-call` seam is added only in the temp copy, after asserting `import processes\n` appears exactly once. Only `processes.time` is replaced, and `processes.py` only uses `time.monotonic` (lines 20, 42, 43, 94, 108). So `subprocess` timeouts and `process.wait(timeout=2)` keep the real clock. The clock is installed at import, before `main()` builds `env` from `os.environ`, so `FAKE_COMMAND_CLOCK` reaches the transport.

**Contract checks:**
- **Clock per call:** each event name uses the boat-call's pid plus a nanosecond timestamp. The event file is published atomically (`.tmp` then `replace`), and the fake waits for its own `.observed` file. The background watchdog probes in `guard_wait` (`bin/boat-launch-guards.sh:298`) therefore can't advance each other's clocks.
- **Timeout amounts:** setup-timeout and hang advance by command timeout + 1. Restore advances 1 s, which is above 0.5 and below 3. The unreachable test dropped its override.
- **Watchdog marker:** `.boat-launch-start` appears in the `python3 -c` command only in the two watchdog probes (`factory/launch.sh:445`, `bin/exam-launch:123`). Its other uses (`launch.sh:605,755`, `exam-launch:116`) are `exec` payloads. The `shlex.split` assertion would catch any change in the probe's shape.
- **Prepended time patch:** both probes start with plain `import … time`, with no `from __future__`, so prepending `time.time = lambda: now` is safe. Re-importing `time` returns the patched module.
- **Stall timing:** stale/mixed see age 10, above the stall limit of 2 s (from 0.02 min). Progress sees age 0 on every poll, against a limit of 1 s. Resetting the parent directory's mtime blocks a false pass from the directory scan.
- **Retention:** retention requires an `exec`, a `polled` marker on every worker, and a "collect failed / KEEPING" message. Hang also requires both the watchdog timeout event and the `hashlib` collector event. The setup-timeout countercase checks no `exec`, exactly one statement-transfer event, a timeout message and a delete. Together these cover both sides of the original misdiagnosis.
- **Signal test:** the signal goes to `launcher.pid`, which the `exec` prelude keeps equal to the launcher's PID. More than 64 KiB is pushed through both stdout and stderr, and exact counts prove both were fully drained. The old 30 s readiness deadline is gone, leaving one 60 s outer budget with a kill-group cleanup. The existing `code == 128 + sig` check is kept (`test-launch-guards.py:721`).
- **Murphy register:** no rows are closed or added, which fits a test-only fault.

**Focused check** (in the scratchpad, using the real `bin/processes.py` plus `launch_guard_clock.install`):
- With the clock frozen, a 1.5 s real child finished under a 1 s deadline (took 1.59 s).
- An advance event made the run raise `TimeoutExpired` after 0.28 s, and the paused child was killed with no leftover process.

**Nits (optional):**
1. The stderr assertion `== 16384` assumes stall mode runs `exec` exactly once. That's deterministic today, but a future auto-resume path in stall mode would double the count and fail with a misleading "not drained" message. `>= 16384` would avoid that.
2. With every boat-call frozen, a real hang during setup is now caught only by the 60 s outer budget, not the command deadline. This is intended by the design ("one outer hang-detection budget"), but it should be stated plainly as a known limit.
3. Real host-clock exposure remains in the 1 s cutoff on the unreachable path (`date +%s`) and in TTL logic. The design accepts this, and each wait is bounded by real sleeps far below 60 s.

**Validation limits:**
- **Five loaded runs:** not finished. At review time only `/tmp/isolation-e-loaded-1.log` exists, its last line is the "Ctrl-C and TERM" PASS with no final line yet, and `/tmp/isolation-e-five.json` doesn't exist.
- **Full suite:** `/tmp/isolation-e-full-suite.log` has reached `== tests/bench/test-launch-guards.py ==` and isn't finished.
- **Reproducer:** I did not re-run it. Your logs exist, but I didn't independently confirm that both cases are red against the old harness.
- **Overall:** the PASS covers the code only. A merge still needs all five loaded runs green and the same-SHA full suite passing.

## Author response

No blocking findings or rejected findings. Keep the exact output count: this
scenario deliberately launches one runner; an unexpected restart should fail.
Known limits: freezing command clocks makes an unrelated setup hang depend on
the outer 60-second harness budget. Host UTC TTL and unreachable cutoffs still
use real time. These are test-harness limits, not changed production policies.
Final validation is now complete on the unchanged reviewed source `46ec5ef`:
five consecutive loaded passes and a fresh full suite, 148 scripts / 0 failed.
The reviewer correctly did not claim unfinished checks passed at review time.
Exact durations, source and log hashes, and reproduction commands are recorded
in [the evidence report](../reports/isolation-timeouts-loaded.md) and its JSON.
