# Diff review 1: independent-worker-retirement

- Reviewer: a fresh goldfish, run as a local `claude -p` process (Claude Code
  2.1.318) with read-only tools (`Read`, `Grep`, `Glob`, `git show`,
  `git diff`, `git log`). It had no conversation history.
- Personas: `zoom_out` and `implementation_readiness`, both in
  `Mode: REVIEW`, with `implementation-readiness-standard.md`.
- Subject: `git diff origin/factory-simplify...8ea2e8f -- bin tests`, against
  `docs/designs/independent-worker-retirement.md`.
- Verdict: **PASS**, with no blocking findings and 9 nits.

The review output is reproduced verbatim below, followed by the elephant's
dispositions.

---

## Verbatim review

## Zoom-Out (Skeptical Architect), Mode: REVIEW

The change goes after the root cause, which is serial retirement in `guard_wait` and in the exit pass. It doesn't patch around it. It adds no new retirement path: `guard_retire`, `factory_ttl_retire` and `factory_auto_resume` are untouched, and two inline loops become start/reap pairs. The new pieces are small and each one has a job:
- a task list held in a shell variable;
- token-named status files;
- one trap helper (`guard_signal_traps`), which `guard_init` now reuses;
- two pattern-match predicates.

There is nothing to reuse in the shell layer. `processes.py` is Python and doesn't fit a sourced POSIX guard. I found no YAGNI in the code. The token's epoch part is justified by PID reuse across controller restarts, and the `ttl`/`retire` kinds match the only two old call shapes. The diff is about 130 lines against the design's "about 60". The difference is mostly comments and the two predicates, and nothing in it is speculative.

Scope is sound. Auto-resume stays inline, and the setup-failure and failed-`guard_new` retirements in `factory/launch.sh:667,798` stay synchronous, both as the design states. Leaving row 16 open is correct:
- the reserve-versus-sealing half is untouched;
- the tests use authored transports and cards;
- `docs/ENGINEERING.md:94` closes a row only with a real-artifact test.

The fixture timing (`monitor.json`: 57600/55800/1800) and the id `bx_d6dzvjbc` (`created.json`) are real. They don't make the transport real, and the test docstring says so (`tests/bench/test-independent-retirement.py:7`).

## Implementation Readiness (Tech Lead), Mode: REVIEW

I checked the code against each design point:

- **Start, `bin/boat-launch-guards.sh:178-206`.**
  - The counter is bumped, then the token is built as `epoch.$$.counter`.
  - Older `$state/$id.retirement-exit.*` files are removed before the fork.
  - The deferring traps are installed only when `guard_exiting != 1`.
  - The task runs `trap - 0`, then the kind work with `|| gr_s=$?`, then writes the status as tmp + `mv`.
  - The `id:pid:token` entry is recorded right after `&`. The traps are then restored with `guard_signal_traps`, and a deferred signal leads to `exit "$gr_signal"`.
  - Matches the design.
- **`ttl` dispatch, `:192-196` and `:375`.** It is used only on the numeric-reply TTL-margin branch. Stall and unreachable-or-TTL use `retire` (`retire_kind` is reset at `:348`). Matches.
- **Reap, `:211-232`.**
  - Without `block`, a task is skipped only if it has no exit file and `kill -0` succeeds. Otherwise the reaper runs `wait || :` and reads only the exact token.
  - A missing or invalid status is logged and fails the reap. `.retired` is touched in every case, the file is removed, and the entry is dropped.
  - `guard_retiring` is reassigned only after the loop, so a signal mid-reap leaves every entry visible to `guard_exit`. The worst case is a spurious "ended without a status" log line.
- **`guard_wait`.**
  - Each pass starts with a reap (`:321`).
  - The in-flight skip comes before the `.retired`/`.deleted` checks in the first loop (`:325`) and is the first check in the classification loop (`:346`).
  - Both return points also require an empty `guard_retiring` (`:337`, `:392`).
  - Phase 2 runs before the `once` return (`:387-391`).
  - All four former inline sites are now starts, and their status bookkeeping matches the design's table.
- **`guard_exit`, `:253-265`.**
  - The kill loop skips recorded task pids. The `:pid:` match can't hit an id or token, because neither contains `:`.
  - It then sets `guard_exiting=1` and runs `reap block`, which is logged only, before `guard_ids resolve`.
  - The exit pass starts one task per id, and `reap block || guard_cleanup_error` keeps the old `cleanup_failed` meaning.
- **POSIX, `set -eu`.** Every new non-final command is in an `if`, `||` or `&&` context. Every variable is initialised when the guard is sourced. dash clears the "tested" context for `&` subshells, but the only command in the task that can fail is wrapped in `|| gr_s=$?`, so behaviour is the same in dash and `bash --posix`. Calling `guard_wait` bare under `set -e` (`bin/exam-launch:134`) behaves as before.
- **Name collisions.**
  - No caller uses `gr_*`, `retire_kind`, `guard_deferred`, `guard_retiring`, `guard_exiting`, `guard_task_*` or `guard_signal_traps`. I searched `factory/launch.sh`, `bin/exam-launch` and `tools/run-gate-smoke.sh`.
  - `factory_auto_resume` overwrites `now`, but it now runs after the classification loop, so nothing later reads the clobbered value.
  - The existing clash of exam's `tries` with `guard_retire`'s `tries` is now confined to a subshell. That is an improvement, not a regression.
  - No caller reads `files`, `dest`, `collect_status`, `retire_id` or `retire_status` after a retirement, so moving `guard_retire` into a subshell loses no state.
- **Behaviour by launch type.**
  - Single-worker launches and exams are the same, except that `guard_wait` can return up to one `poll` later. The worker is already deleted by then, and the design states this lag.
  - Batch operations still bind `N=1`, and `factory_auto_resume` still returns 1 for them.
  - Gate smoke never calls `guard_wait`. Its exit pass is now a single task that is joined, and its watchdog is still killed first.
  - Resume launches (`UNBUG_RESUME_LAUNCH=1`) are unchanged: `monitor.sh` defines none of the new names, and stale status files are removed at start.
- **Tests.** The barriers are file-based and bounded, so they don't depend on timing. The `sleep` calls in the signal tests only make negative checks easier to pass, so they can't cause flakes. Each failing-on-base assertion matches a claimed property.
  - Scenario 1 (overlap barrier), scenario 2 (later-due peer) and the two-phase scenario (`resume-saw`) would genuinely fail on the base guard.
  - So would the `once` ordering, task death (the helper kills the base launcher shell), TERM join (`collect-start` count 1) and Ctrl-C (two `collect-end` lines).
  - Auto-resume-zero and the real-collector scenario would pass on the base guard. That is expected for regression checks.

I could not run anything, so the 11/11 result and the regression-file results are the elephant's report, not mine. Under the command limit I could only read the code and tests, and I found no reason in them to doubt those results.

## Findings

1. **NIT** `bin/boat-launch-guards.sh:338-342`: the design says all three per-worker loops skip in-flight ids ("the probe-wait loop" by name). The probe-wait loop has no explicit skip. It relies on in-flight ids never getting a `.pid` file in the current pass, which holds within one controller. The exception is a stale `.pid` left by a dead controller for an id that gets a `.deletion-attempted` task on resume. There, `wait <stale pid>` could in principle block on a reused pid that now belongs to a live child. The base code has nearly the same exposure and the odds are negligible. A one-line `guard_retire_running "$wait_id" && continue` would match the design text.
2. **NIT** `tests/bench/test-independent-retirement.py:30`: `WAIT = 20`, but the design says the scenario 1 and scenario 3 barriers are "bounded at 60 s". This doesn't affect correctness, but the design and the test disagree.
3. **NIT** `tests/bench/test-independent-retirement.py:340-361`: the TERM-during-auto-resume scenario doesn't assert `events.count('collect-start ' + REAL_ID) == 1`. Killing the task and re-collecting in the exit pass would also give `collect-end … 0` and both deletes. So this test doesn't prove "`guard_exit` joins the peer task". `test_term_joins_in_flight_retirement_then_exit_pass` (`:317`) does prove it.
4. **NIT** `tests/bench/test-independent-retirement.py:197,208,211-217`: scenario 1 uses `ttl_collect()`, which has no `mkdir "$EV/$1.collecting"` lock, so `assertNoOverlap` at `:208` checks nothing there.
5. **NIT** `tests/bench/test-independent-retirement.py:363-394`: the "collects two workers concurrently" scenario never asserts that the collections overlapped, and it would pass on the base guard. The design asks only for "both verified and deleted", so the code conforms, but the test name claims more than it checks.
6. **NIT** `tests/bench/test-independent-retirement.py:287-301`: design scenario 4 asks for "not probed … again". Only the collection count is asserted. The probe calls are logged in `ev/calls` but never checked.
7. **NIT** `tests/bench/test-independent-retirement.py` (whole file): no test covers the rule that unreachable-or-TTL-margin uses `retire`, with no attestation. Only the positive `ttl` path is tested (`:206`). The code is right at `:375-384`.
8. **NIT**: the elephant reports "8 of its 9 behaviour scenarios" failing on the base guard. I count 10 behaviour tests (11 minus `test_fixture_timing`). Of those, auto-resume-zero and the real-collector scenario should pass on the base guard, so "8 of 10" fits the file. The mutation record should be corrected.
9. **NIT** `docs/murphy-register.md:28`: row 16's `Where` column cites `bin/boat-launch-guards.sh:302`, and that line number has moved with this diff. Leaving the row open with no edit is correct (`docs/ENGINEERING.md:94`). The line reference can be refreshed when the row is next touched.

**Verdict: PASS**, with no blocking findings.

---

## Dispositions (elephant)

There were no blocking findings. The nits were handled in the commit that
follows `8ea2e8f`; the new file has 12 tests and all pass under dash and
`bash --posix`.

| # | Disposition |
|---|---|
| 1 | **Adopted.** The probe-wait loop now skips in-flight ids explicitly (`! guard_retire_running "$wait_id" \|\| continue`), as the design says. |
| 2 | **Adopted.** The design's barrier bound is corrected to 20 s, matching `WAIT = 20`. |
| 3 | **Adopted.** The TERM-during-auto-resume test now asserts exactly one `collect-start` for the peer, so it proves the join (no kill and redo). |
| 4 | **Adopted.** `ttl_collect()` now takes the `mkdir` overlap lock, so `assertNoOverlap` is meaningful in scenario 1. |
| 5 | **Adopted.** Renamed to `test_real_collector_under_parallel_retirement_tasks`, with a comment that overlap is not asserted (integration only). |
| 6 | **Adopted.** The task-death test asserts that the worker was probed exactly once, from the `calls` log. |
| 7 | **Adopted.** Added `test_unreachable_ttl_margin_retires_without_attestation`: a failing probe for a TTL-due worker is retired with no `factory_ttl_retire`. |
| 8 | **Accepted; the record is corrected.** The base-guard mutation run fails 8 of 10 behaviour tests in both shells: `once` (error), Ctrl-C, inline auto-resume two-phase, later-due peer, simultaneous overlap, task death, TERM during resume, and TERM join. Auto-resume-zero and the real collector pass on base, as expected for regression checks. That run was made at `8ea2e8f`, before the new unreachable test, which on base would pass (the base guard also only attests on the numeric branch). |
| 9 | **Not adopted on this branch.** The row-16 evidence line number (`bin/boat-launch-guards.sh:302`) is stale. `docs/murphy-register.md` is also changed by the owned `claude/practice4-release-prep` branch, so this branch does not edit it, to avoid a conflict. It should be refreshed when the row is next touched at merge. |
