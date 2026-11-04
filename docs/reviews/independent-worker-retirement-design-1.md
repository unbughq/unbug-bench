# Design review 1: independent-worker-retirement

- Reviewer: a fresh goldfish, run as a local `claude -p` process (Claude Code
  2.1.318) with read-only tools (`Read`, `Grep`, `Glob`, `git show`,
  `git diff`, `git log`). It had no conversation history.
- Personas: `zoom_out`, `design_critic` and `implementation_readiness`, all in
  `Mode: REVIEW`.
- Standards: `heilmeier-standard.md` and
  `implementation-readiness-standard.md`.
- Subject: `docs/designs/independent-worker-retirement.md` at commit
  `b35682e` (revision 1).
- Verdict: **FAIL**, with 4 blocking findings and 11 nits.

The review output is reproduced verbatim below, followed by the elephant's
dispositions.

---

## Verbatim review

# Goldfish design review: `docs/designs/independent-worker-retirement.md`

Mode: REVIEW, for all three personas. Standards used: Heilmeier, Implementation Readiness and Zoom-Out. I could not run dash in this session because the shell probes needed approval. The shell semantics below are therefore taken from the dash and POSIX rules and checked against the repo source.

---

## 1. Zoom Out (Skeptical Architect)

**Context sufficiency and root problem.** The objective is clear. Workers in one launch reach the TTL margin in the same poll, and the sequential `guard_retire` loops in `bin/boat-launch-guards.sh:240,263,271,294,178` let worker 1's pause and collection use up worker k's 1800 s reserve. Giving each worker its own background retirement fixes the queueing directly. It is the fix named in Murphy row 16's Fix column. Leaving the row open is consistent with `docs/ENGINEERING.md` §2.

**Simplicity and reuse.** The design is minimal. `guard_retire` is unchanged, there is no new retirement path, and the per-worker locks it relies on already exist (`boat_lifecycle.py:466,677,695`, `transfer.py:63-64`, `coordinator.locked` at `coordinator.py:217`). The `<id>.retirement-exit` file is justified: POSIX `wait` cannot poll without blocking, and `kill -0` cannot tell a zombie from a live task. I found no existing job-tracking helper to reuse.

**Root-problem gap.** Two inline paths in the poll loop still block it, and the design does not convert them:
- `factory_auto_resume` runs `collect_vm` synchronously on DONE (`factory/launch.sh:531`).
- `factory_ttl_retire` makes two SSH calls of up to 120 s each per worker before retirement starts (`ttl_continuation.py:87-99`, called at `boat-launch-guards.sh:284`).

So the headline claim, "The poll loop never blocks on a retirement", is false on the factory/Boat path. The out-of-scope reason given ("Each runs before any peer is due from the same creation step") applies at best to the setup-failure retire in `launch.sh`. It does not apply to `factory_auto_resume`, which runs inside `guard_wait` at any time.

**Altitude.** Writing the subshell one-liner into §Change 1 is acceptable for a shell-semantics design. It also exposes a defect: the literal `tmp` path (see finding 5).

## 2. Design Critic

**`set -eu` and the subshell.** `guard_retire "$id" || s=$?` correctly turns off errexit inside `guard_retire`, the same as the old call sites. `set -u` still applies, though, and so do the `echo`/`mv` after it. Any shell-fatal error, or a signal that kills the subshell, ends the task without writing `<id>.retirement-exit`.

**Trap inheritance.** dash, like POSIX, resets non-ignored traps in a subshell. The task therefore has EXIT cleared (`trap - 0` is belt and braces), TERM at its default (it dies), and INT hard-ignored, because dash's `forkchild` ignores SIGINT and SIGQUIT for `&` jobs when job control is off. Its stdin also becomes `/dev/null`. The design states the INT part and not the TERM part. Exit-pass tasks are started after `trap '' INT TERM` (`:169`), so they and their exec'd children inherit SIG_IGN for TERM. That matches today's behaviour, but the design should say so.

**Signal behaviour: the Ctrl-C claim is wrong.** `bin/boat-call:45` unconditionally installs Python handlers for SIGTERM and SIGINT, which override the inherited SIG_IGN. On Ctrl-C, SIGINT goes to the whole foreground process group, background tasks included. Each in-flight `boat-call`, including the pause SSH in `collect.sh:19` that is waiting up to 1050 s for DONE, raises `SystemExit(130)` and its deadline cleanup kills the child session group. `collect.sh` itself survives, because SIGINT is ignored on entry. Then:
1. `pause_status=1` (or UNFINISHED);
2. collection fails;
3. `guard_retire` retries 30 s later, up to three times;
4. if all three fail, the worker is KEPT.

So Ctrl-C does not "let an in-flight collection finish". Test 4 sends TERM to the launcher PID only, so it never covers this path.

**Reaping and liveness.** `guard_retire_reap` (non-block) reaps only ids whose exit file exists. A task that died without writing it (OOM, a stray TERM, a `set -u` abort, ENOSPC on the `echo`, or the race below) is never reaped. `guard_wait` "stays `pending` while any task is in flight", so it loops every `poll` seconds forever. That is a new hang, exactly the class of failure the Murphy register tracks. The fix: reap when the file exists **or** `kill -0 "$pid"` fails. dash reaps finished background children during later foreground `dowait`s, so `kill -0` then fails. Treat a missing status as a failure, and fall back to `wait`'s status.

**Concurrency: the guard_exit kill/join split has a race.** Today `guard_exit` kills every job in `jobs -p`. The comment at `:171` notes this covers "a signal between starting a probe and recording its PID". The design changes this to "kill only the other jobs", meaning jobs not in `guard_retiring`. A TERM or INT trap can run between `( … ) &` returning and the assignment that records `id:pid`, because dash runs pending traps between commands. That task then looks like a probe and gets `kill -TERM`. TERM is at its default in the subshell, so the subshell dies and its `collect.sh` is orphaned and keeps running. The exit pass then starts a second retirement of the same id at the same time, which is the very hazard §Change 4 says the design avoids. Fix the split the other way round: kill only PIDs recorded as probes or the poll `sleep`, and `wait` (join) every other job. Probes are bounded at 120 s, so joining an unrecorded probe is harmless.

**Replay safety.** The `.deleted`, `.collected` and `.retiring.json` markers make an exit-pass `guard_retire` on an already-finished worker a no-op, so that claim holds. Two smaller issues:
- Reap marks `.retired` even when there is no status (the task was killed). A restarted controller (`UNBUG_RESUME_LAUNCH`) then never probes that worker in `guard_wait`. Only its exit pass retries it.
- If a controller is SIGKILLed, its background tasks survive as orphans. A restarted controller can retire the same id alongside them, and an orphan's late `mv` can overwrite the new task's `.retirement-exit`. The single-orphan version of this already exists today, but the design's §Restart claims cover it without saying so.

**Is concurrent `guard_retire` safe?** I checked the claims against the code, and they hold for distinct workers:
- Shell variables are subshell-local.
- `transfer.py` takes a per-filename `LOCK_EX` and replaces only after a SHA match.
- `collection.py` verifies only the names its own collection listed.
- The deletion lock and evidence directory are per worker.
- `coordinator.locked` is per case (`ttl_continuation.py:264`).
- Case ids carry a timestamp plus 24 random bits (`run.py:3310`).
- `$state/ids` is replaced atomically by `guard_ids resolve` (`boat_lifecycle.py:217-221`), so a `_delete` read during a once-mode `guard_new` is safe.

All of this is proved by argument only. The tests stub `collect_vm`, so the shared `$root/sealed` destination is never exercised with real `collect.sh` under overlap.

**Heilmeier compliance.**
- Objectives, state of the art, the new approach and the main risk (the seal bound) are present.
- Cost and timeline are missing.
- Impact is not quantified. The seal can take about 2400 s against an 1800 s reserve, which is out of scope here, so how many cases does parallelism actually save?

## 3. Implementation Readiness

Several design choices are left to the implementer:
- **The `tmp` path.** `echo "$s" > tmp; mv tmp …` is relative to the working directory and shared by every concurrent task. The path must be given, e.g. `"$state/$id.retirement-exit.tmp"`.
- **The `guard_retiring` encoding.** Its format, how it is parsed, and how an entry is removed are unspecified. sh has no local variables, so the variable names inside `guard_retire_start` and `guard_retire_reap` must not reuse globals. `launch.sh` uses `$id`, and the guards use `wait_id`, `exit_id` and `probe_pid`.
- **How `guard_exit` tells retirement tasks from probes.** Unspecified, and it is where the race lives (finding 2).
- **`wait "$pid"` under `set -e`.** Its status must be explicitly ignored with `|| :`, and the design should say how reap failure combines into `wait_status`.
- **Stale replies.** The third loop of `guard_wait` (`:255-296`) must skip in-flight ids. Otherwise a stale `.ok`/`.reply` from an earlier pass (DONE) restarts retirement. The design says "neither probed nor started again" but not where that check goes.
- **Test 1's "run against the base guard".** No mechanism is given (for example `git show factory-simplify:bin/boat-launch-guards.sh` into a temp root), and the design does not say whether this is an automated assertion.
- **Timing values.** `monitor.json` holds floats (`"margin": 1800.0`, `"retire_at": 55800.0`), but the guards use shell integer arithmetic. The test must state the conversion.
- **Missing consumer.** `bin/exam-launch` also sources the guards (`collect_vm` at `:79`, `guard_wait` at `:134`) and is not listed as affected or in the regression set.
- **Test plan gaps.** No test covers:
  - a task that dies without an exit file;
  - SIGINT delivered to the process group;
  - the start/record signal race;
  - a once-mode task overlapping `guard_new`/`guard_ids resolve`;
  - an exit pass with two or more remaining ids running in parallel;
  - a stale `.retirement-exit` on resume.

Phasing is a single change, which is acceptable for its size.

---

## Findings

1. **BLOCKING.** Reap liveness: non-block reap waits only on the exit file. A task that dies without writing it leaves `guard_wait` pending forever, a new hang. Reap on file-exists **or** `kill -0` failure, count a missing status as failure, and test it.
2. **BLOCKING.** The `guard_exit` kill/join split races with the signal window between `( … ) &` and recording `id:pid` (the window `:171` already guards for probes). An unrecorded retirement task gets TERM-killed and orphans its `collect.sh`, and the exit pass then collects the same worker at the same time. Kill only recorded probe/`sleep` PIDs and join everything else, and specify that mechanism.
3. **BLOCKING.** The signal claim is false. `bin/boat-call:45` catches SIGINT and kills its child group, so Ctrl-C aborts every in-flight pause SSH or transfer in the background tasks. The result is failed collections, 30 s retries, and possibly KEEP. Correct the claim, decide the intended Ctrl-C behaviour, and add a test that sends INT to the process group (Test 4 only sends TERM to the shell).
4. **BLOCKING.** The headline invariant "the poll loop never blocks on a retirement" does not hold. `factory_auto_resume` runs `collect_vm` inline (`launch.sh:531`), and `factory_ttl_retire` makes up to 2×120 s of SSH per worker inline before the task starts. The out-of-scope reason given for `factory_auto_resume` is factually wrong. Either move these into the task, or correct the claim and state the bound they add to peers' reserves.
5. **NIT.** Give a per-id temp path inside `$state` for the status file. The literal `tmp` is shared and relative to the working directory.
6. **NIT.** Specify the `guard_retiring` format and parsing, unique global variable names in the new functions, `wait "$pid" || :`, and how reap status feeds `wait_status`.
7. **NIT.** Specify that the third `guard_wait` loop skips in-flight ids, so a stale `.ok`/`.reply` cannot start a second task.
8. **NIT.** Do not mark `.retired` for a task that ended without a status, so that a resumed controller probes it again.
9. **NIT.** The §Restart claims omit orphaned tasks from a SIGKILLed controller: they can run alongside the new controller, and a late `.retirement-exit` write can be taken as the new task's status.
10. **NIT.** The concurrency audit for real `collect.sh` (shared `$root/sealed`, transfer locks) is untested because `collect_vm` is stubbed. Consider one overlap test that runs real `collect.sh` over the authored `BOAT_CMD` transport.
11. **NIT.** Test details: convert the `monitor.json` floats to integers, give the mechanism for running against the base guard, and add an exit-pass test with two or more remaining ids.
12. **NIT.** Name `bin/exam-launch` as an affected consumer and cover it in the regression set.
13. **NIT.** Say explicitly that exit-pass tasks inherit SIG_IGN for TERM and INT (as today), and that `guard_exit`'s join can last about an hour, longer than systemd's default stop timeout (as today).
14. **NIT.** Heilmeier gaps: no cost, timeline or risk section, and the impact is not quantified given that the seal bound stays out of scope.
15. **NIT.** The out-of-scope reason for the synchronous setup-failure `guard_retire` in `launch.sh` is also imprecise, since earlier peers can already be DONE. The impact is low because a setup-failed worker has no `run.py` to pause.

**Verdict: FAIL.** There are four blocking findings: reap liveness, the kill/join signal race, the incorrect SIGINT claim with no INT test, and inline retirement work left in the poll loop.

---

## Dispositions (elephant)

All four blocking findings were accepted and fixed in design revision 2. No
blocking finding was rejected.

| # | Kind | Disposition |
|---|---|---|
| 1 | BLOCKING | **Fixed.** Reap now triggers when the token-named exit file exists **or** `kill -0` fails. dash records a finished child's status during later foreground commands; this was verified locally with dash (`kill -0` failed and `wait` still returned 7). A missing or invalid status is a failure, and the worker is not `.retired`, so it is probed again. Added test scenario 4: a task killed with SIGKILL. |
| 2 | BLOCKING | **Fixed, with a different mechanism.** A plain `wait` for all jobs would hang on the 2700 s watchdog job in `tools/run-gate-smoke.sh`. The design therefore keeps killing non-retirement jobs, and closes the window instead: `guard_retire_start` installs deferring traps (`gr_signal=130`/`143`) around the fork and the pid recording, then restores the traps and exits with the deferred status. Verified with dash: the flag was set and the pid was recorded. Added a signal-window test. |
| 3 | BLOCKING | **Fixed.** The claim was false and is corrected. Ctrl-C interrupts in-flight `boat-call` commands, as it interrupts today's foreground collection. `guard_retire`'s own retry then re-collects, and `guard_exit` joins the task. The intended behaviour is stated: an uncollected worker is never deleted, collection is retried, and a worker that still cannot be collected is kept. Added a test that sends INT to the process group. |
| 4 | BLOCKING | **Fixed.** `factory_ttl_retire` (`ttl` kind) and `factory_auto_resume` (`done` kind, outcome `resumed`) now run inside the task, so the poll loop only probes, classifies, starts and reaps. The out-of-scope text for the setup-failure retirement in `launch.sh` was corrected (see finding 15). |
| 5 | NIT | **Fixed.** The status file is `$state/$id.retirement-exit.$token`, written via `.tmp` and `mv`. |
| 6 | NIT | **Fixed.** `guard_retiring` holds `id:pid:token` entries. New-function variables use the `gr_` prefix, waits use `wait "$pid" \|\| :`, and how reaped failures map to `wait_status` is specified. |
| 7 | NIT | **Fixed.** All three per-worker loops skip in-flight ids. |
| 8 | NIT | **Adopted.** A task with no status does not get `.retired`. |
| 9 | NIT | **Fixed.** Token-named files mean an orphan task's late write is never read, and start removes older files. |
| 10 | NIT | **Adopted.** Added scenario 6: two workers collected concurrently by the real `collect.sh`, `transfer.py` and `collection.py` through an authored transport. |
| 11 | NIT | **Fixed.** Float-to-int conversion is stated, the manual base-guard mutation check is specified, and the exit pass with a remaining peer is covered in scenario 5. |
| 12 | NIT | **Fixed.** `bin/exam-launch` is in the audit, and `test-launch-guards.py` (which includes the exam paths) and `test_gate_smoke.py` are in the regression set. |
| 13 | NIT | **Fixed.** Inherited ignored signals and the join duration (as today) are stated. |
| 14 | NIT | **Fixed.** Added a "Cost, risk and impact" section. |
| 15 | NIT | **Fixed.** The setup-failure text is corrected: earlier peers can be due, and the impact is low. |
