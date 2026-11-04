# Diff review 2: independent-worker-retirement

- Reviewer: a fresh goldfish, run as a local `claude -p` process (Claude Code
  2.1.318) with read-only tools (`Read`, `Grep`, `Glob`, `git show`,
  `git diff`, `git log`). It had no conversation history.
- Personas: `zoom_out` and `implementation_readiness`, both in
  `Mode: REVIEW`, with `implementation-readiness-standard.md`.
- Subject: `git diff origin/factory-simplify...390834e -- bin tests`, against
  `docs/designs/independent-worker-retirement.md`. The reviewer was also
  given diff review 1.
- Verdict: **PASS**, with no blocking findings and 7 nits.

The review output is reproduced verbatim below, followed by the elephant's
dispositions.

---

## Verbatim review

## Zoom-Out (Skeptical Architect), Mode: REVIEW

The change fixes the root cause. Retirement is no longer serial in `guard_wait`'s classification loop or in `guard_exit`'s exit pass; each worker's retirement now runs as a start/reap pair. It adds no new retirement path: `guard_retire`, `factory_ttl_retire` and `factory_auto_resume` are byte-identical. The new pieces are small:
- a space-separated `id:pid:token` list;
- two `case` predicates;
- a trap helper, which `guard_init` now reuses (`bin/boat-launch-guards.sh:11-14,25`);
- a deferred list for inline auto-resume.

I found nothing speculative:
- The token's epoch part is there because a restarted controller can reuse a dead controller's pid.
- The two kinds, `ttl` and `retire`, match the two old call shapes.
- Phase 2 is the smallest change that stops a same-pass peer from queueing behind auto-resume while keeping auto-resume's signal semantics.

There is nothing to reuse: the guard is sourced POSIX sh, and the repo has no shell job-management helper. A search outside docs and tests finds the `gr_*`, `guard_retiring`, `guard_deferred`, `guard_exiting`, `guard_task_*` and `retire_kind` names only in the guard. So the design's "about 60 lines" against an actual ~130 is comments and predicates, not scope creep.

What stays out of scope is stated honestly:
- the setup-failure and failed-`guard_new` inline retirements at `factory/launch.sh:667,798`;
- inline auto-resume;
- the reserve-versus-sealing bound.

Keeping row 16 open is correct, for three reasons:
- Its remedy names three things (`docs/murphy-register.md:28`), and only "independent retirement task" is addressed.
- Every transport and card in the test is authored, and the docstring says so (`tests/bench/test-independent-retirement.py:7`).
- `docs/ENGINEERING.md:94` closes a row only with a real-artifact test.

## Implementation Readiness (Tech Lead), Mode: REVIEW

**Design conformance.** I checked each design step against the code and all of them match:
- **Start (`:178-206`):**
  - The counter is bumped and the token is `epoch.$$.N`.
  - The glob `rm` runs before the fork.
  - The deferring traps are installed only when `guard_exiting != 1`.
  - The task runs `trap - 0`, then the work under `|| gr_s=$?`, then writes its status as tmp + `mv`.
  - The entry is recorded straight after `&`, then the traps are restored and any deferred signal is re-raised with `exit`.
  - Every command in the deferral window is a builtin except the fork. `gr_signal` is reset before the traps are installed.
- **`ttl` dispatch:** only the numeric TTL-margin branch sets `retire_kind=ttl` (`:376`), and it is reset per worker (`:349`).
- **Reap (`:211-232`):** a task counts as finished when its exit file exists, `kill -0` fails, or `block` is passed. The reaper then runs `wait || :` and reads only its exact token. An empty or non-numeric status is logged as a failure. `.retired` is always touched. `guard_retiring` is reassigned only after the loop, so a signal mid-reap leaves every entry visible to `guard_exit`. The worst case is a duplicate "ended without a status" log line, which is logged only.
- **`guard_wait`:**
  - Each pass starts with a reap.
  - All three loops skip in-flight ids. In the first loop the skip comes before the `.retired`/`.deleted` checks.
  - Both return points also require no active tasks (`:337,393`).
  - Phase 2 runs before the `once` return.
  - All four former inline sites are now starts, and their status bookkeeping matches the design's table.
- **`guard_exit`:**
  - The kill loop skips recorded task pids. `:pid:` can't match an id or token, because neither contains a colon.
  - It then sets `guard_exiting=1` and joins the tasks before `guard_ids resolve`; failures from that join are logged only.
  - The exit pass starts a task per id, and `reap block || guard_cleanup_error` keeps the meaning of `cleanup_failed`. `guard_cleanup_error` is idempotent, so calling it once instead of once per id is equivalent.

**POSIX and `set -eu`:**
- Every new function is safe when called bare under `-e`. `guard_retire_start`'s last command is an `if` or `[ ] || exit`, so it returns 0. The predicates are called only from `if`, `!` or `||` contexts.
- `[!\ ]` and `*" $1:"*` behave the same in dash and bash.
- Every global is initialised when the guard is sourced, which is before `guard_init`, so it also holds on the `UNBUG_RESUME_LAUNCH` early return.
- The task gets SIG_IGN for INT, since it is async with job control off. Caught TERM is reset to default. `bin/boat-call:45` installs its own handlers, so the claimed Ctrl-C behaviour holds.

**Callers:**
- `factory/launch.sh`, `bin/exam-launch` and `tools/run-gate-smoke.sh` have no bare `wait`, no INT/TERM trap of their own on the main shell after `guard_init`, and no reads of `dest`, `files`, `collect_status`, `retire_id` or `tries` after a retirement.
- Hooks that now run in a subshell (`factory_ttl_retire`, `factory_ttl_retired`, `collect_vm`) communicate only through files.
- `boat_lifecycle.delete_receipt` only reads the spend file and writes per-worker evidence. `hcloud-park` is per-id.

**Behaviour by launch type:**
- **Single-worker launches and exams:** the same, except `guard_wait` returns up to one `poll` after the deletion (stated in the design).
- **Batch operations:** still `N=1`, and auto-resume still returns 1.
- **Gate smoke:** retires inline itself and kills its watchdog. Its exit pass is now one task that is joined.
- **Resume (`UNBUG_RESUME_LAUNCH=1`):** unchanged apart from stale-token cleanup.

**Previous review's adopted nits.** All seven are really implemented:

| Nit | Where |
|---|---|
| 1 | `:339` |
| 2 | design `:421,439` |
| 3 | test `:383` |
| 4 | test `:220` |
| 5 | test `:387-388` |
| 6 | test `:320-321` |
| 7 | test `:227-238` |

Not adopting 9 is reasonable.

**Tests.** The barriers are file-based and bounded. I checked ordering in the once, later-due, two-phase, TERM and INT tests, and none is timing-dependent:
- The later-due peer's first probe always runs before A's task can change its reply.
- If TERM lands inside the deferral window, the test outcome is the same.
- The trap after the auto-resume stub runs before `resume-after` in both shells.

The real proofs are the overlap barrier, `resume-saw`, the single `collect-start` counts and the two `collect-end` lines. Each of them fails on the base guard, which fits the elephant's count of 8 failures among the 11 behaviour tests. I could not run anything, so that count, the 12/12 result and the regression results are the elephant's report, not mine.

## Findings

1. **NIT** `tests/bench/test-independent-retirement.py` (whole file), against `bin/boat-launch-guards.sh:321,265`: no test makes a reaped failure the only source of a non-zero result.
   - Every failing-task test uses a TTL-due worker, where `wait_status=1` is already set at `:384`.
   - So deleting `|| wait_status=1` at `:321` would pass the suite. So would replacing `|| guard_cleanup_error` at `:265` with `|| :`.
   - One DONE (`label=exam`) worker whose collection fails 3 times, with `guard_wait` returning 1, would cover the first. The same worker kept at exit, with `cleanup_failed=true`, would cover the second.
   - The code itself is correct.
2. **NIT** `tests/bench/test-independent-retirement.py:335`: `assertNotIn('collect-end bx_row16a 0', …)` can never fail, because the helper blocks on `release` until line 336. Its comment, "still running, not killed", claims more than it checks. The real proof of the join is `:340`, where `collect-start` appears exactly once.
3. **NIT** `tests/bench/test-independent-retirement.py:227-238`: the unreachable-without-attestation test has one worker. So it doesn't check that `retire_kind` is reset per worker at `bin/boat-launch-guards.sh:349`. A TTL-numeric worker sorted before an unreachable one would cover that. The code is correct.
4. **NIT** `docs/designs/independent-worker-retirement.md:445-447` against test `:75`: the design says the stub finds the task pid with `sh -c 'echo $PPID'`. The test uses `os.getppid()` from the helper, which is equivalent because the helper's parent is the task subshell. Also, the stale-file check (test `:313`) passes because start removes the file before the fork (`bin/boat-launch-guards.sh:184`). It doesn't show that token naming alone would ignore a stale file. The design text should match the test.
5. **NIT** `docs/reviews/independent-worker-retirement-diff-1.md` (dispositions, row 8): the only mutation record is from `8ea2e8f`, with 10 behaviour tests. The design requires the manual base-guard run to be "recorded in the diff review" (`:424-427`). The HEAD result the elephant reports now (8 failing of 11 behaviour tests, with the unreachable test passing on base) should be recorded in this review's dispositions.
6. **NIT** `bin/boat-launch-guards.sh:393-394`: when the only thing left is an in-flight task, the loop still sleeps a full `poll` (120 s by default) before reaping. For exams and single-worker launches, `guard_wait` returns up to 120 s later than before. No paid VM is involved, because the worker is already deleted, and the design states the lag. Waiting on the task pid when nothing else is pending would remove it, but that isn't necessary now.
7. **NIT** `docs/murphy-register.md:28`: the row's `:302` evidence reference is stale; this repeats nit 9 of diff review 1. Leaving the row open with no edit is correct under `docs/ENGINEERING.md:94`. Refresh the line reference when the row is next touched.

**Verdict: PASS** (no blocking findings).

---

## Dispositions (elephant)

There were no blocking findings. Nits 1–5 were adopted in tests and design
text only. `bin/boat-launch-guards.sh` is byte-identical to the reviewed
`390834e`. The new file has 13 tests, and all pass under dash and
`bash --posix`.

| # | Disposition |
|---|---|
| 1 | **Adopted.** Added `test_reaped_failure_alone_sets_status_and_cleanup_failure`: a DONE exam worker whose collection always fails. Its reaped failure alone makes `guard_wait` return 1, and its failed exit-pass retry makes the launcher exit 1 with "unfinished launch evidence retained". I checked that the test catches both mutations the review named, using single-mutation copies of the guard: dropping `\|\| wait_status=1` on the per-pass reap fails it (2 errors), and replacing the exit pass's `\|\| guard_cleanup_error` with `\|\| :` fails it (2 failures). |
| 2 | **Adopted.** Removed the vacuous "still running" assertion. The join is proved by the single `collect-start` count. |
| 3 | **Adopted.** The unreachable test now has a numeric TTL-margin worker (`a-ttl`, which attests) sorted before the unreachable worker (which does not), so the per-worker `retire_kind` reset is covered. |
| 4 | **Adopted.** The design now describes the `os.getppid()` kill, and says the stale-file check is shown through its removal before the fork, while token-only ignoring is argued. |
| 5 | **Adopted.** Final base-guard mutation record, using the final test file and `GUARD=` the `origin/factory-simplify` guard. In both shells, 8 of 12 behaviour tests fail: once (error), Ctrl-C, two-phase auto-resume, later-due peer, simultaneous overlap barrier, task death, TERM during auto-resume, and TERM join. Four pass on base, as expected for regression and behaviour-preserving checks: auto-resume-zero, real collector, unreachable without attestation, and reaped-failure (the base's synchronous retirement also returns 1 there). Result: 13 tests, 14 failures plus 2 errors, in 594 s. |
| 6 | **Not adopted.** Reap lag of up to one `poll` after the last deletion is stated in the design, and no VM is alive during it. |
| 7 | **Not adopted,** as for diff review 1, nit 9. `docs/murphy-register.md` is also changed by the owned practice4 branch. |

A third diff review was not run. The guard code is unchanged since this
review's subject, and the later changes are test assertions and design
wording that this review asked for.
