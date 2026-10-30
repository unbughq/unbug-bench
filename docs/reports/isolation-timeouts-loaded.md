# Launch-guard load diagnosis and validation

Source under test: `46ec5efca31a1722085a82dd90d78312fbf39aa5`, based on
`15e16b5`. Final evidence updates change documentation only.

## Diagnosis

The reported timeout/deletion failure is a test phase error. The supplied
`merge-held-suite.log` shows statement installation timing out before runner
execution, followed by successful empty collection and worker deletion. The
test used a global one-second command timeout but asserted that its requested
`unreachable`/`hang` mode had already reached a running worker. A scheduler
delay could invalidate that assumption. The new countercase proves a pre-run
timeout may retire a verified-empty worker; the live-worker cases require
observed execution, watchdog arrival and failed collection before asserting
no deletion, orphan reporting and an unfinished spend record.

The signal harness waited up to 30 seconds for preparation and a watchdog
marker while neither output pipe was drained. Enough setup output prevents
that event indefinitely. Under load we reproduced the exact `launcher never
polled` assertion using output backpressure. The historical stall reports
alone do not distinguish slow preparation from a full pipe; both assumptions
are removed. Signal delivery now happens at the watchdog event while the
harness drains both pipes continuously.

No production file changes and no new Murphy row: the reproduced faults are
in test timing and phase assumptions. Existing open production rows remain
open. This does not claim every possible launcher failure is ruled out.
The supplied trace also contains a local `kill_tree` PermissionError. Our
phase reproduction reaches the same no-delete assertion with a clean timeout
124 and no cleanup exception, so that exception is not necessary to this
failure. This patch does not claim to diagnose or fix that separate cleanup
observation.

## Reproduce the baseline failures

From the repository root:

```sh
rtk proxy python3 docs/reports/isolation-timeouts-reproduce.py phase
rtk proxy python3 docs/reports/isolation-timeouts-reproduce.py signal
```

The committed reproducer loads the old test directly from `15e16b5`, selects
the affected scenario in memory, starts three `python3 -c 'while True: pass'`
processes and runs the test at nice +10. It stops and joins the burners in
`finally`. Its only transport changes are a 1.5-second delay before the actual
statement extraction (`phase`) or 16,384 diagnostic lines before execution
(`signal`). It returns zero only after observing the expected old assertion.
Both commands reproduced their intended failures. Logs:
`/tmp/isolation-e-reproduce-phase-final.log` and
`/tmp/isolation-e-reproduce-signal-final.log`.

An unmodified focused old-harness run under three burners also passed in
67.4 seconds. That is consistent with a load-sensitive test race, not evidence
that it cannot fail. The new harness's preliminary full-script loaded run
passed in 351.1 seconds. Neither run is counted in the required five-pass
sequence below.

## Required validation

**Five consecutive complete launch-guard runs passed:** 388.87, 373.47,
360.09, 342.33 and 328.33 seconds, each exit 0. Results are recorded in
`/tmp/isolation-e-five.json` and `/tmp/isolation-e-loaded-{1..5}.log`.
All used three continuous CPU burners and
`nice -n 10 python3 -u -B tests/bench/test-launch-guards.py`. The driver checks
all burners are alive before/after each run, stops on any failure and verifies
both test source hashes remain unchanged across the sequence. It completed
successfully and terminated/joined all three burners. No source changed during
the sequence.

The fresh full suite uses:

```sh
rtk proxy uv run --with numpy --with scipy python -B tests/run.py
```

Its log and terminal result are `/tmp/isolation-e-full-suite.log` and
`/tmp/isolation-e-full-suite.json`. It completed on the same source SHA while
the loaded sequence ran: **148 scripts, 0 failed; exit 0; 960.71 seconds**.
The checked source hashes, five individual log hashes, full-suite result/hash
and both baseline reproduction log hashes are retained in
[`isolation-timeouts-loaded.json`](isolation-timeouts-loaded.json).

## Review

Design review 4 requested precise clock and phase contracts; all findings were
addressed. Design review 5 approved the implementation contract. Fresh diff
review 3 (Claude Opus 5.5, independent of the Codex writer) passed with no
blockers and independently exercised the clock helper with real child
processes. The reviewer correctly noted validation was still pending at review
time; all required checks subsequently passed on the unchanged reviewed source.
Reviews are preserved verbatim under `docs/reviews/`, including
[`isolation-timeouts-diff-3.md`](../reviews/isolation-timeouts-diff-3.md).

All provider activity used the fake transport, with temporary synthetic keys
and fixtures. No real Boat calls, merge, push or deployment.
