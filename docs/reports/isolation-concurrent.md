# Concurrent launch-guard hang

Source base: `c32e884` (factory-simplify after stream A). Fix: `03914ce`.
Branch: `stream-e-concurrent-launch-isolation`.

## Cause and scope

The synthetic SIGINT case inherited an ignored SIGINT disposition when the
suite was started as a shell background job. Python preserves SIG_IGN at
startup and through exec. The startup-output wrapper therefore execed the
noninteractive launcher shell with INT ignored. That shell cannot install its
INT trap over an inherited ignored signal. The fake watchdog sent SIGINT once,
then the launcher continued polling a healthy synthetic worker until the
900-second test guard. Scheduling load and simultaneous suites were correlates;
no shared path, undrained pipe or cross-suite group kill was needed.

Three separate detached worktrees at c32e884 ran the existing signal case in
parallel, with only unrelated cases skipped. Their parent deliberately set
SIGINT to SIG_IGN before Popen, reproducing shell background-job inheritance.
All three reached `polled` and `signal-sent`, continued to 118/118/119 transport
calls, and had no deletion. SIGTERM then released them; their expected-130
assertions failed. With only the wrapper reset applied, the same three narrowed
cases and ignored parent passed in about nine seconds. This is a bounded
minimized reproduction; it did not wait for the 900-second guard.

Three complete unmodified copies were also run concurrently from separate
worktrees with SIGINT ignored. All three failed at the original 900-second
guard in the exact `launch.sh 1 --source port` startup-output case (total
script durations 1235.49, 1235.56 and 1235.89 seconds). Three complete
unmodified copies with ordinary SIGINT inheritance instead passed in
354.8–356.3 seconds. A direct `/bin/sh` foreground/background probe confirmed
that `&` alone changes Python entry SIGINT from enabled to ignored.

The fix resets SIGINT to SIG_DFL in the Python child before exec. The test
explicitly sets SIG_IGN around Popen and restores the parent disposition in
finally, so foreground runs also exercise the regression. The real launcher,
16384-line stdout/stderr pressure, watchdog-triggered signals, exact exit codes,
collection-before-delete checks and 900-second guard are preserved. Production
files are unchanged. Murphy row `new-isolation-concurrent-1` records the fault.

This obvious fix is under 20 lines and skips design review under ENGINEERING.md
section 1; the commit message is the diff-review specification.

## Validation

All copies run `python3 -u -B tests/bench/test-launch-guards.py` in distinct
worktrees. The full background baseline and fixed batches inherit SIG_IGN from
the parent before exec. Each fixed batch starts three copies together, joins
all three, and starts the next batch only if all passed. Unique raw logs and
JSON are under `/var/folders/wy/9m9k8zxx55dbm7_s_xqfmc7c0000gn/T/stream-e-concurrency-p_ft6fes`.

Full-suite command: `uv run --with numpy --with scipy python -B tests/run.py`.
Result on source `03914ce`: **156 test scripts, 0 failed**, exit 0, 1163.42 seconds.
The suite ran concurrently with the repetition batches. Its unique raw log is
`full-suite-03914ce.log` under the directory above; the committed compressed copy
and SHA-256 are in `isolation-concurrent-evidence/`.

Five consecutive batches of three concurrent complete copies passed: **15/15**,
all exit 0. Each batch joined before the next started. Per-copy durations and
log SHA-256 values are in `isolation-concurrent-evidence/proof.json`; every
complete output is committed alongside it as `.log.gz`. No limit was raised.
All six temporary validation worktrees were removed after their runs finished.
Only test harness and records changed; no production change, merge or push.

Reproduction method: create three detached worktrees at the source commit, set
`signal.signal(signal.SIGINT, signal.SIG_IGN)` in the driver, and launch one
`subprocess.run(["python3", "-u", "-B", "tests/bench/test-launch-guards.py"],
cwd=worktree, stdout=unique_log, stderr=subprocess.STDOUT, start_new_session=True)`
per worktree concurrently. For the fixed proof, join all three and repeat five
times. The unmodified foreground countercase omits the SIG_IGN assignment.
The ordinary shell equivalent of that inherited state is `command & wait`.

