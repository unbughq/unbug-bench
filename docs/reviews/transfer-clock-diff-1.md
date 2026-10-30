# Diff review: Freeze boat-call deadline clock in transfer tests (`592823d`)

Reviewer: fresh goldfish, OpenCode `openrouter/~deepseek/deepseek-pro-latest`, read-only.
**Personas:** zoom_out, implementation_readiness
**Mode:** REVIEW (change skipped the design under the ≤20-line, obvious-cause exception → reviewed against the commit message)

## Verdict: PASS

## Root cause (Q1) — confirmed correct

Production collection never forces a 2-second bound. `factory/collect.sh` (line 19) uses `BOAT_COMMAND_TIMEOUT_SECONDS=${COLLECT_PAUSE_SECONDS:-1200}` for the pause probe, and every other `boat ssh` / `transfer.py` call runs `bin/boat-call` with its default `120` (`bin/boat-call:19`, `processes.deadline`). `factory/transfer.py` sets no override and reads the default via `CALL`. Only the test's `patch.dict` set `BOAT_COMMAND_TIMEOUT_SECONDS=2`, and that bound wraps the *entire* `python3 -c` chain (boat-call + fake transport + three interpreters). On a loaded host the startup chain can exceed 2 s and exit 124. So this is a harness artifact, not a production-deadline defect. The claimed cause is accurate.

## Determinism (Q2) — sound

- The seam is lifted verbatim from `tests/bench/test-launch-guards.py` (lines 325–330): same `count('import processes\n') == 1` guard, same `import launch_guard_clock; launch_guard_clock.install(processes)` injection into a *copied* boat-call, so production `bin/boat-call` is untouched.
- `launch_guard_clock` patches `processes.time` (a `SimpleNamespace`), and `processes.py` reads `time.monotonic()` only through the module attribute, so the freeze propagates to `deadline`/`run`/`shell`. Real `time.monotonic_ns()` used in the event filename is the stdlib clock — unaffected (comment at line 26 confirms the intent).
- The fake transport now advances the clock by writing `FAKE_COMMAND_CLOCK` via an atomic `.tmp`-then-`replace`, so the event is never observed half-written. Before the write, `monotonic()` returns the frozen `start`, so `remaining` stays positive and the `run()` poll loop never fires on real time; the moment the event carries `3.0` (= `BOAT_COMMAND_TIMEOUT_SECONDS + 1`), `remaining` goes negative, `TimeoutExpired` is raised deterministically.
- `<pid>-<nanos>` in the event name makes each boat-call invocation independent; no cross-invocation race.
- The `once` path cannot hang: after writing the event it calls `signal.pause()`, but boat-call's `run` `finally` block runs `kill_tree` + `process.wait(timeout=2)` and reaps it. The test file passed clean in 26.8 s for all 5 tests with no stall. It also cannot pass vacuously: the event advanced to 3.0 vs a 2.0 deadline, which is strictly past the bound.

The only residual real-time exposures are the two `subprocess.run(..., timeout=60)` hang guards in `test_uncertain_pause_retains_worker...`. Those run a stub `boat` script (not the clock-seamed boat-call) and complete in well under a second, so 60 s is ample even on a loaded host. This is a nit, not a flake risk.

## Coverage (Q3) — real timeout+kill path and all assertions retained

- `test_timeout_partial_retries_without_promoting_short_bytes` still exercises the true path: `once` makes the first `f.seek(0)` emit `partial`, advance the clock, and `pause()`; the **real** boat-call owner (its `deadline`/`run`/`kill_tree`) detects the expiry, kills the child, prints the exact production message "boat-call: command timed out; remote outcome may be unknown", and returns 124; `transfer.remote` raises `CalledProcessError(124)`; the retry (flag unlinked) fetches real bytes. The `metadata()` call does not contain `f.seek(`, so it does not consume the `once` flag prematurely.
- Every original assertion is intact: dest bytes == data, `f.seek(0)` recorded in offsets, 16-byte `.part` preserved on failure then resumed at `f.seek(16)`, corruption/mutation never replaces a good archive, work retained on uncertain pause, no-chunks for already-verified. The diff adds no assertion removals and one new guard (`count('import processes\n') == 1`) that fails loudly if the seam ever drifts.

## Blockers

None.

## Nits

1. **`10 → 60` real-time hang guard is a magic-sanitized hard cap.** It's fine, but it converts a hard symptom (sub-second script hitting 10 s under load) from "should never fire" to "should never fire, with margin". No action required.
2. **The `once`/`always` branch is now chain-coupled to two env vars** (`FAKE_COMMAND_CLOCK`, `BOAT_COMMAND_TIMEOUT_SECONDS`) that only the seam sets. `always` is not exercised in this file, so a future caller using `mode='always'` without the seam would crash on `KeyError` rather than pause. Pre-existing shape, not introduced here.
3. **Copy-set maintenance:** the test now pins `bin/boat-call` + `bin/processes.py` + `tests/bench/launch_guard_clock.py` in the temp dir under one `self.assert` seam guard, mirroring `test-launch-guards.py`. If `boat-call`'s import layout changes, that assert triggers — acceptable.

## Files read

- `docs/ENGINEERING.md`
- `git show 592823d` (stat + message), `git diff 0dfad44..592823d`
- `tests/factory/test_transfer.py`
- `bin/boat-call`, `bin/processes.py`, `tests/bench/launch_guard_clock.py`
- `factory/transfer.py`, `factory/collect.sh`
- `tests/bench/test-launch-guards.py`
- `tools/egm/agents/{zoom_out,implementation_readiness}.md`, `tools/egm/document_standards/{zoom-out,implementation-readiness}-standard.md`

Test run: `uv run --with numpy --with scipy python -B tests/factory/test_transfer.py` → `Ran 5 tests in 26.780s` → `OK`.

## Writer disposition

No blockers. Nits 1–3 are accepted as written; no change made. Nit 2 is moot within this file: the `always` mode is never set by any test.
