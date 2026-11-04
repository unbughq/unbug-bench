# Design review 4: independent-worker-retirement

- Reviewer: a fresh goldfish, run as a local `claude -p` process (Claude Code
  2.1.318) with read-only tools. It had no conversation history.
- Personas: `zoom_out`, `design_critic` and `implementation_readiness`, all in
  `Mode: REVIEW`.
- Standards: `heilmeier-standard.md` and
  `implementation-readiness-standard.md`.
- Subject: `docs/designs/independent-worker-retirement.md` at commit
  `bca6248` (revision 4). The reviewer was also given design reviews 1–3.
- Verdict: **PASS**, with no blocking findings and 10 nits. The reviewer
  confirmed that every earlier blocking finding is resolved.

The review output is reproduced verbatim below, followed by the elephant's
dispositions.

---

## Verbatim review

# Goldfish design review: `docs/designs/independent-worker-retirement.md` (revision 4)

All three personas ran in Mode: REVIEW, against `heilmeier-standard.md` and `implementation-readiness-standard.md`, plus the zoom-out audit vectors. I read the design, the referenced code and design reviews 1–3. Running dash and `bash --posix` experiments needed approval, so I could not run them. The shell findings below rest on POSIX, dash and bash semantics, checked against the source. I edited no files.

## 1. Zoom Out (Skeptical Architect)

**Root problem and scope.** The objective is clear. The Fix column of Murphy row 16 asks for "an independent retirement task", and this revision does that. It leaves the larger half of the row open (seal time longer than the reserve) and says why: the row-34 files, the frozen `practice.TIMING`, and no live proof. That is honest and consistent with ENGINEERING.md §2. Keeping `factory_auto_resume` inline and replacing the respawn with "a statusless death is a failed retirement" both cut risk and code. The two-phase pass is the smallest change that removes same-pass queueing.

**Reuse.** No new helper duplicates an existing one. The per-worker isolation it relies on is real:
- `<id>.deletion.lock` and per-worker evidence (`factory/boat_lifecycle.py:466,677-703,712`);
- the per-filename `flock` with a SHA-gated `os.replace` (`factory/transfer.py:63-98`);
- `coordinator.locked` (`factory/ttl_continuation.py:182,264`);
- `command_fence`, which locks only the targeted worker (`factory/boat_lifecycle.py:438-477`).

**Simplification opportunity.** Step 6 (design :95-98) restores hard-coded copies of `guard_init`'s traps (`bin/boat-launch-guards.sh:17-18`) and relies on a comment to keep them in sync. The test harness copies them a third time (:369-370). One small `guard_signal_traps` function, called from `guard_init` and from step 6, removes that duplication and the drift risk at no cost (nit 1).

**Altitude.** The step lists and the table are detailed but appropriate for roughly 60 lines of signal-sensitive shell. I see no YAGNI violation.

## 2. Design Critic

**POSIX sh under `set -eu`.** These parts are correct:
- `( … ) &` never trips errexit in the parent.
- `<work> || gr_s=$?` suppresses errexit inside the work, as at today's `guard_retire … ||` call sites. `set -u` still aborts the subshell, and that gives the intended "no status file" case.
- `printf … > tmp && mv` is an AND-list, so a failed write ends the task with no file. That is also intended.
- With job control off, an `&` subshell resets caught traps (so TERM goes back to default) and ignores INT. This holds under both dash and bash.
- `bin/boat-call:43-45` installs its own SIGINT and SIGTERM handlers in Python. These work even though INT was ignored when the process started, so the description of Ctrl-C reaching the in-flight `boat-call` is correct.

**Signal-deferral traps.** The window between `&` and recording `id:pid:token` holds only builtins. A signal there sets `gr_signal`, the entry is recorded, and only then does `exit "$gr_signal"` run `guard_exit`, which skips the recorded pid. The traps restored in step 6 match `guard_init`. Every caller of `guard_wait` (`factory/launch.sh:653,801,803`, `bin/exam-launch:134`) runs after `guard_init`. `tools/run-gate-smoke.sh` never calls `guard_wait`, and its watchdog is an ordinary job that step 1 still kills. Review-1 blocking 2 is resolved.

**Reaping and liveness.** The test "file exists **or** `kill -0` fails" is sound:
- A zombie answers `kill -0` until it is reaped. dash reaps it during a later foreground `dowait`, and the guard runs many `cat` substitutions per pass. bash reaps it in its SIGCHLD handler.
- `wait "$pid"` still returns the saved status after the child is reaped.
- The worst cases are a reap lag of one `poll`, or a delay while a reused pid lives. The design states both correctly.

Review-1 blocking 1 is resolved.

**A statusless death counts as a failed retirement.** This settles review-3 blocking 2: nothing is re-classified, nothing loops, and the retirement kind is never lost. Two accuracy points remain:
- **Timing.** The statement (:136-138) that today's shell-fatal case leads to the exit pass "in the same way" is wrong on timing. Today, a fatal error in an inline `guard_retire` kills the launcher, and the exit pass runs **at once**. Now the dead task's worker is marked `.retired` and waits for the exit pass at the **end of the batch**. Peers can run until their own TTL margin, so a TTL-due worker whose task died may be erased before that pass reaches it. The trigger is rare: SIGKILL or OOM of a small `sh`, a `set -u` bug, or ENOSPC. The trade-off is acceptable, but it should be stated (nit 3).
- **Orphaned children.** If only the task subshell is SIGKILLed, its foreground `collect.sh` child survives as an orphan. The exit pass can then collect the same id at the same time. Integrity still holds (the per-file `flock`, SHA-gated replace and per-worker deletion lock), but "only one task per id exists at a time" (:149) holds for tasks, not for their children (nit 4).

**Two-phase pass and stop semantics.** These parts preserve today's behaviour:
- Auto-resume still runs in the main shell, with `guard_init`'s traps restored after every start. A pending trap therefore still fires between its commands.
- TERM during `boat exec --detach` still fires only after that foreground command, as today.
- Ctrl-C during the inline auto-resume's foreground `collect.sh` kills it (foreground, INT not ignored), as today.
- `factory_auto_resume` returns 1 at once unless `UNBUG_CLOUD=boat` (`factory/launch.sh:509`), so on the default Hetzner path the deferred list is always empty.

Review-3 blocking 1 is resolved for the same-pass case.

One record now differs from today. In-flight task failures joined in `guard_exit` feed `guard_cleanup_error` (:196-197). Today, an interrupted foreground retirement is never counted, and only the exit pass's result counts. Suppose a task's pause times out (the seal takes about 2400 s) and the exit pass then succeeds. `cleanup-status.json` now says `cleanup_failed:true` where today it says `false`, and `factory/restore_bundle.py:263` keys on that field. The double count is defensible for ttl-evidence failures, because `guard_retire`'s replay returns 0 once `.deleted` exists. It should be stated as a deliberate change (nit 5).

**Residual bounds.** The cross-pass bound in Out of scope (:315-318) understates the worst case. `transfer.py` retries every chunk `COLLECT_CHUNK_RETRIES=3` times (`factory/transfer.py:81-89,113`), each bounded at 120 s. The per-chunk worst case is therefore 360 s, and about 6.3 h for a ~500 MiB archive, not about 2 h. `metadata()` calls and an unbounded `flock` wait (`transfer.py:64`, if a sweeper holds the same name) come on top. The conclusion does not change, because either figure is far beyond the 1800 s reserve. The figure is still wrong (nit 2). The same retry means the Ctrl-C paragraph (:218-221) overstates the effect on a transfer. Ctrl-C usually costs one chunk retry inside `transfer.py`, not a failed `collect_vm`. A failed pause SSH does fail the attempt, through `pause_status` (`factory/collect.sh:23,63`) (nit 6).

**Concurrency of distinct workers.** I verified these claims:
- `command_fence` takes an SH lock on the targeted worker only.
- `_delete` uses a per-worker evidence directory and an ownership check against the atomically replaced `ids`.
- Each `transfer.py` lock is per filename.
- `collect.sh` temp files are per id (`$dest/$id.runner-status.json.tmp`).
- `hcloud-boat` keeps per-sid `known_hosts` and an append-only `record()`.
- `hcloud-park` takes one id.
- Batch, restore and `--restore` launches are forced to N=1.
- The inline auto-resume in phase 2 touches only `$state/$resume_id.*` and its own `sealed/<case>` card while peer tasks run.
- Globals in the main shell (`retire_id`, `tries`, `now`) are not shared with subshell tasks.
- The `files`, `collect_status` and `dest` globals in `bin/exam-launch` are safe because each task is a subshell (and exam is n=1).

I found no shared mutable state between tasks for distinct ids.

**Does the test plan prove the claim?**
- Scenario 1 (overlap barrier, real `monitor.json` timing of 57600/55800/1800 and id `bx_d6dzvjbc`), scenario 2 (later-due worker, isolated failure), scenario 3 (the two-phase barrier, which fails on the base guard) and scenario 4 (SIGKILL ends the wait, no re-probe) test the main claims and discriminate against the base guard.
- The **signal-window** test (:425-427) is not deterministic, which contradicts "Determinism" (:361-362). The window holds only builtins, so a signal sent "right after the task starts" from Python almost always lands after step 6. The test then passes whether or not the deferral exists, so it does not prove review-1 blocking 2's fix (nit 7).
- Scenario 5's INT case requires "A's pause SSH blocked inside `boat-call`". That holds only if A's collection goes through `bin/boat-call`, either the real `collect.sh` or a stub that calls it. The plan does not say which (nit 8).
- Scenario 6 is correctly marked as not real-artifact evidence. Row 16 rightly stays open.

**Heilmeier.** Objective, state of the art, approach, impact, risks, cost and exams are all answered. The timeline is "a single change" with no duration, which is weak but acceptable at this size. Impact (:338-346) is now honestly narrowed.

## 3. Implementation Readiness

The steps are mostly actionable: start and reap steps, token and file naming, loop placements, return conditions and the status table are all given. These remaining ambiguities would make the implementer choose:
- **The `ttl` kind on the unreachable branch.** The table says "`ttl` for the TTL margin, else `retire`". But the unreachable branch (`bin/boat-launch-guards.sh:289-291`) also fires on "TTL margin reached", and today `factory_ttl_retire` runs only in the numeric-reply branch (`:281-285`). Say explicitly that the unreachable branch is always `retire` (nit 9).
- **How the `ttl` kind is composed.** Give the exact form, for example `case $kind in ttl) if command -v factory_ttl_retire …; then factory_ttl_retire "$id" || echo …; fi; guard_retire "$id" ;; …`, inside the `|| gr_s=$?` context (nit 9).
- **Where phase 2 goes.** Phase 2 must run before the `[ "$wait_once" != once ] || return` at `:297`, and it needs a named variable for the deferred list (nit 10).
- **Where the join goes in `guard_exit`.** State whether the join runs before or after `guard_ids resolve` (`:177`) (nit 10).
- **Test harness.** The INT scenario's collection path (nit 8) and a deterministic seam or stated probabilistic loop for the signal window (nit 7).

Phasing as a single change is fine at this size. The regression list is complete.

**Earlier blocking findings:** review 1 (1–4), review 2 (1–2) and review 3 (1–2) are all resolved in revision 4, and I agree with how they were resolved.

## Findings

1. **NIT.** Add a shared `guard_signal_traps` helper, used by `guard_init` and by step 6 of `guard_retire_start` (design :95-98), in place of hard-coded copies tied together by a comment.
2. **NIT.** The cross-pass auto-resume bound (:315-318) ignores `transfer.py`'s 3 retries per chunk. The worst case is about 360 s per 8 MiB chunk (about 6.3 h for ~500 MiB), not about 2 h, plus `metadata()` calls and an unbounded `flock` wait. The conclusion is unchanged; the figure should be corrected.
3. **NIT.** On a statusless death, "the exit pass runs in the same way" (:136-138) is wrong on timing. Today the exit pass runs at once; now it waits until the batch ends, possibly after the dead worker's TTL. State this trade-off.
4. **NIT.** SIGKILL of only the task subshell orphans its `collect.sh`, which the exit pass can then overlap for the same id. Integrity holds through `flock`, SHA checks and the deletion lock, but say so next to the "one task per id" claim (:149-152).
5. **NIT.** Counting join failures through `guard_cleanup_error` (:196-197) changes `cleanup-status.json` relative to today: an interrupted retirement is now counted even when the exit pass succeeds (`factory/restore_bundle.py:263` reads this field). Declare it as intended, or log join failures and let the exit pass decide.
6. **NIT.** In the Ctrl-C paragraph (:218-221), an interrupted transfer chunk is retried inside `transfer.py`, so `collect_vm` does not necessarily fail. An interrupted pause SSH does fail it, through `pause_status`. Correct the wording.
7. **NIT.** The signal-window test (:425-427) cannot hit the builtin-only window deterministically, so it also passes without the deferral. Add a test seam, or run it as a stated probabilistic loop and do not count it as proof. Fix the "Determinism" claim.
8. **NIT.** Scenario 5 (INT) must say that A's collection runs through `bin/boat-call`, using the real `collect.sh` or a stub that invokes it, so that "pause SSH blocked inside `boat-call`" is actually exercised.
9. **NIT.** Say that the unreachable or TTL-margin branch starts `retire`, never `ttl`, and give the exact shell for the `ttl` kind dispatch.
10. **NIT.** Say that phase 2 runs before the `once` return, name the deferred-list variable, and give where the `guard_exit` join goes relative to `guard_ids resolve`.

**Verdict: PASS.** No blocking findings; every earlier blocking finding is resolved, and the 10 nits are optional.

---

## Dispositions (elephant)

There were no blocking findings. All 10 nits were adopted in the design text
before implementation (revision 4, final).

| # | Disposition |
|---|---|
| 1 | **Adopted.** A shared `guard_signal_traps` helper is called by both `guard_init` and `guard_retire_start`. |
| 2 | **Adopted.** The worst case is corrected to about 6.3 h: 360 s per chunk with `COLLECT_CHUNK_RETRIES=3`, plus `metadata()` calls and the `flock` wait. |
| 3 | **Adopted.** The timing trade-off for a statusless death is stated: the exit pass now runs at batch end, not at once. |
| 4 | **Adopted.** The orphaned `collect.sh` child case is stated next to the one-task-per-id claim. Integrity holds. |
| 5 | **Adopted.** Failures from the `guard_exit` join are logged only, and the exit pass's own result decides `cleanup_failed`, preserving today's `cleanup-status.json` semantics. |
| 6 | **Adopted.** Ctrl-C wording: an interrupted pause SSH fails the attempt, while an interrupted transfer chunk is usually retried inside `transfer.py`. |
| 7 | **Adopted.** The signal-window test is dropped as proof. The deferral is argued, checked with a dash experiment, and explicitly not counted as test proof. |
| 8 | **Adopted.** The INT stub calls the real `bin/boat-call ssh`. |
| 9 | **Adopted.** The exact `ttl` dispatch is given. The stall and unreachable branches use `retire`. |
| 10 | **Adopted.** Phase 2 (`guard_deferred`) runs before the `once` return, and the join runs before `guard_ids resolve`. |
