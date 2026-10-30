# Transfer test clock flake

Base: `0dfad44`. Source fix: `592823d`. Only `tests/factory/test_transfer.py` changed.

## Cause

The test set `BOAT_COMMAND_TIMEOUT_SECONDS=2` for every real `bin/boat-call`.
Each remote call starts three interpreters: boat-call, the fake transport and
`python3 -c`. On a loaded host, that chain can exceed 2 s on wall time, so the
metadata hash call exits 124. The 2 s bound existed only so the fake's `once`
mode, which sleeps 10 s, would time out.

Production is not affected. `factory/collect.sh` and `factory/transfer.py`
use the boat-call default of 120 s per call, which is per 8 MiB chunk and per
remote hash. Nothing in production sets a short bound for collection. Unloaded
calls measured 0.26 s median and 0.73 s maximum at load 14. Production is
unchanged.

## Reproduction

The probe below adds a 2.5 s delay before each remote hash, standing in for a
slow interpreter start. It runs the test file with that patch applied:

`slow_hash_probe.py`, which inserts `time.sleep(2.5)` before the hash command.

- Before the fix: 5 errors, all `CalledProcessError ... exit status 124` from `metadata()`.
- After the fix: all 5 tests pass. The `once` test still prints the real
  "boat-call: command timed out" message.

## Fix

The fix reuses `tests/bench/launch_guard_clock.py` on a copied boat-call, the
same seam as `test-launch-guards.py`, so the deadline clock is frozen. Only
the fake's `once` event moves it past the bound. The fake then calls
`signal.pause()`, and the real process owner kills it and returns 124. The
`collect.sh` hang guards go from 10 s to 60 s.

## Validation

Three CPU burners and the full suite ran in the background while
`tests/factory/test_transfer.py` ran five times in a row. Load figures are
1-minute, 5-minute and 15-minute averages. Earlier probe burners were still
draining, so load was well above the reported 10 to 15.

| run | rc | load at start (1m 5m 15m) | seconds | suite alive |
|---|---|---|---|---|
| 1 | 0 | 97.04 90.63 52.25 | 24.46 | yes |
| 2 | 0 | 72.01 85.15 51.38 | 26.27 | yes |
| 3 | 0 | 58.23 80.87 51.02 | 28.04 | yes |
| 4 | 0 | 41.37 75.07 49.79 | 29.00 | yes |
| 5 | 0 | 33.64 69.79 48.74 | 26.26 | yes |

The concurrent suite, at load 70 to 97, reported 155 scripts and 1 failure. The
failure was `tests/bench/test-launch-guards.py`, which this branch does not
touch. Its own 60 s wall-time guard around a whole synthetic launcher run
(`stall` scenario, line 477) expired. That is the same class of bug in a
different test and is not fixed here. Suite log sha256:
`8732982c22c12e4cf40adb9cf11c2404160269e80188fdf6df282e9ff37ddc61`.

The standalone full suite at `592823d` (load 8.9 falling to 6.9) reported
**155 test scripts run; 0 failed.** Log sha256:
`4a6d67cf72a2d579fa6b6c269569d762ec343ac75ad23ae8d68110f9a97154bc`.

## Review

A fresh DeepSeek goldfish diff review passed with no blockers:
`docs/reviews/transfer-clock-diff-1.md`. No Murphy row is closed, and no rule
in section 4 or any security property changes.
