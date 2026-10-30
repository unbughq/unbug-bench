The diff checks out against the helper and the CPython `subprocess` wait path. Writing up the review now.

# Diff review: deployment readiness test clock (`820d0fb..HEAD`)

Reviewer: goldfish, read-only. Personas: `zoom_out` and `implementation_readiness`. Standards: `tools/egm/document_standards/zoom-out-standard.md` and `implementation-readiness-standard.md`. Mode: REVIEW. Design step 2 was skipped under the under-20-line exception, so this review is against commit `2629f74`'s message.

Files read: `tests/integration/test_qualified_deployment.py` (the `readiness_boundary` harness and the three sequence tests), `factory/launch.sh` (`qualified_readiness`, lines ~102–117), `tools/boat_readiness.py`, `docs/murphy-register.md`, `docs/ENGINEERING.md`.

## Verdict: PASS

No blocking findings.

## Does it fix the 59-vs-60 flake? Yes.

**Cause (confirmed).** The old harness replaced `time.monotonic` and `time.sleep` on the shared `time` module. `wait_ready` calls `proc.communicate(timeout=remaining)` on every poll.
- On POSIX, `Popen._wait(timeout)` waits for the child by calling `time.sleep(delay)` in a loop, with `delay` up to 0.05 s. It stops on `_time()`, which is `time.monotonic` captured when `subprocess` was imported, so it stays on real time.
- So while the child takes real time to be reaped, every poll-loop sleep pushed the fake readiness clock forward. Under CPU load that adds up across polls to seconds of fake time.
- That uses up the 600 s fake deadline early and ends the loop before poll 60. `test_actual_launcher_never_complete_times_out_before_mutation` then fails `attempts == 60`.
- The commit's reproduction (a one-shot 11 s sleep inside `Popen.wait` gives exactly 59) matches this: an extra 11 s on the clock moves the deadline in by more than one 10 s poll interval.

**The fix targets that cause.**
- The helper is still loaded from its pinned bytes; the hash check before the `exec` line is untouched.
- It is now loaded into a private namespace with `__name__ = 'readiness_fixture'`, so the module's `__main__` guard does not run.
- Only that namespace's `time` is rebound, to a `SimpleNamespace` providing `monotonic`, `sleep` and `time`.
- `main()` is then called explicitly. `wait_ready` looks up the global `time` when it is called, so it sees the fake clock. `subprocess` keeps the real module, so reaping no longer moves the fake clock.

**Coverage.**
- The shim covers everything the helper uses: `monotonic`, `sleep`, `time`. Any new `time.*` call in the helper would raise `AttributeError` and fail loudly rather than drift silently.
- `self.assertEqual(gate.count(entry), 1)` stops the patch from silently doing nothing if the launcher line changes.
- `namespace['subprocess'].time.sleep(.001)` plus the `clock[0] == before` assert is a direct runtime check that the specific leak is closed.
- Fake-clock arithmetic is unchanged: deadline is `min(requested_mono + 1380, clock0 + 600, …)`, which gives 600, so 60 sleeps of 10 s means 60 attempts. Both sequence tests are covered: the timeout test (60 attempts, refusal before mutation) and the folding-completion test (6 attempts). Their assertions are kept exactly.

## Is leaving production unchanged correct? Yes.

- In production the clock is real. Time spent reaping a child is real elapsed time and should count against the deadline.
- `wait_ready` is bounded by time (600 s, TTL, collection reserve), not by poll count. Nothing downstream reads `attempts` as a contract; it appears only in the receipt.
- A loaded VM making fewer polls before the same real deadline is the correct behaviour. The defect existed only in the test's fake clock.

## Zoom-out

- **Root cause, not symptom:** yes. The leak is fixed where it happens. The flake is not hidden by loosening `attempts == 60` or adding retries.
- **Placement:** test-only, inside the harness that created the problem. Production code and the pinned helper hash are untouched, which is correct.
- **Simplicity:** +15/−3 in one file, with no new helpers or dependencies.
- **Murphy register:** I agree no row is needed. This was a test-harness flake, not a failure seen in a real batch run, so the "new failure becomes a row" rule in ENGINEERING.md §2 does not apply. No row is claimed as closed, so there is no proof to check.

## Implementation readiness

- The commit message gives the cause, the mechanism, the reproduction, the scope (only the test harness changes) and the reason production is unchanged. Under the step 2 skip, nothing is left for an implementer to decide.
- The size and the obvious cause justify skipping the design.

## Non-blocking nits

1. **Base drift.** The branch is cut from `820d0fb`, but `factory-simplify` has moved on to `c450ce0` (another stream D merge). This diff only touches `test_qualified_deployment.py`. Confirm the merge applies cleanly and that the parent's full-suite run is on, or rebased onto, the current `factory-simplify` tip before merging.
2. **Probe weight.** The `subprocess.time.sleep(.001)` probe runs on every sequence-harness call and costs about 1 ms of real time. That is negligible and acceptable as a regression guard. It could become a comment instead, but keeping it is fine.
3. **Theoretical float hazard (existed before this change, not introduced by it).** The fake clock starts at real `time.monotonic()`. If `clock0 + 600` crosses a power of two and a rounding tie breaks differently from the step-by-step `+10` additions, the count could be off by one. This is extremely unlikely, and the old harness had the same exposure. Starting the fake clock at `0.0` would remove it, except that `requested_mono` comes from the shell's real clock, so the start must stay real. No action needed.

Fixes required before merge: none.
