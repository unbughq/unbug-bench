# Design review 3: independent-worker-retirement

- Reviewer: a fresh goldfish, run as a local `claude -p` process (Claude Code
  2.1.318) with read-only tools. It had no conversation history.
- Personas: `zoom_out`, `design_critic` and `implementation_readiness`, all in
  `Mode: REVIEW`.
- Standards: `heilmeier-standard.md` and
  `implementation-readiness-standard.md`.
- Subject: `docs/designs/independent-worker-retirement.md` at commit
  `aa07f2d` (revision 3). The reviewer was also given design reviews 1–2.
- Verdict: **FAIL**, with 2 blocking findings and 8 nits.

The review output is reproduced verbatim below, followed by the elephant's
dispositions.

---

## Verbatim review

# Goldfish design review: `docs/designs/independent-worker-retirement.md` (revision 3)

All three personas ran in Mode: REVIEW, against the Heilmeier and Implementation Readiness standards, plus the zoom-out audit vectors. I could not run my dash / `bash --posix` experiments because shell execution needed approval, so the shell behaviour below comes from POSIX, dash and bash rules, checked against the repo source. I edited no repo files.

## 1. Zoom Out (Skeptical Architect)

**Root problem and scope.** The objective is clear. Murphy row 16's Fix column names "an independent retirement task" per worker, and this design does that one thing. It leaves the seal-versus-reserve half open with concrete reasons (the row-34 files, frozen `practice.TIMING`, no live proof). That is consistent with ENGINEERING.md §2. Putting `factory_auto_resume` back inline was the right reaction to review 2: it removes a whole class of stop-semantics risk at little cost.

**Reuse.** No new helper duplicates existing code. The per-worker isolation the design relies on is real:
- `<id>.deletion.lock` and per-worker evidence (`boat_lifecycle.py:466,677,713`);
- a per-name `flock` with SHA-gated `os.replace` (`transfer.py:63-98`);
- `results/ttl-retirements/<worker>.json` (`ttl_continuation.py:94`);
- `$dest/$id.runner-status.json` (`collect.sh:40-42`).

`guard_ids resolve` rebuilds `ids` from the `new.*` responses and replaces it atomically (`boat_lifecycle.py:209-222`). `_delete` only reads `ids` (`:706`). So the ids claim holds.

**YAGNI.** The only addition that looks speculative is the respawn machinery (`guard_task_deaths` plus re-probe). It exists to cover task deaths that are rare: SIGKILL/OOM, a `set -u` abort, ENOSPC. As finding 2 shows, it is also the part with the weakest semantics. Today a death like this simply ends in the exit pass. The simpler choice is to treat a statusless death as a failed retirement (touch `.retired`, exit pass and TTL as the backstop), or to respawn the same kind directly. Either is simpler than going back through classification.

**Altitude.** The shell fragments are justified, because this change is about shell semantics.

**Scope boundary.** Keeping auto-resume inline leaves one way back into the queueing the design exists to remove (finding 1). The design states this, but understates how large it can be.

## 2. Design Critic

**POSIX sh under `set -eu` (dash and `bash --posix`).**
- `( … ) &` never trips errexit in the parent.
- `<work> || gr_s=$?` turns errexit off inside the work, as at today's call sites.
- `printf … > tmp && mv` ends the subshell non-zero with no file on ENOSPC. That is the intended "no status" outcome.
- With job control off, an `&` child resets caught traps (so TERM is at its default) and ignores SIGINT. Exit-pass tasks inherit `trap '' INT TERM`.
- `gr_exit` and its `.tmp` are unique per token, and stale files are removed before the fork.

All of this is correct.

**Signal deferral.** The window between `&` and recording `id:pid:token` is closed: a signal there only sets `gr_signal`, the entry is recorded, then `exit "$gr_signal"` runs `guard_exit`, and step 1 skips the recorded pid. The `exit 130`/`exit 143` traps that step 6 restores match `guard_init:17-18`. All callers of `guard_wait` (`launch.sh:653,801,803`, `exam-launch:134`) run after `guard_init`. `run-gate-smoke.sh` never calls `guard_wait`, and its watchdog is a plain job that step 1 still kills. Skipping the juggling when `guard_exiting=1` is correct, because `guard_exit:169` already ignores INT and TERM. Review-1 blocking 2 is resolved.

**Reaping and liveness.**
- The finished test (file exists, or `kill -0` fails) is sound. A zombie answers `kill -0` until dash's next `dowait` (any foreground command) or bash's SIGCHLD handler reaps it, and `wait "$pid"` still returns the saved status afterwards.
- A task can wait up to one `poll` (120 s) before it is reaped. That is harmless.
- PID reuse: for a task that dies without a status, a reused pid held by a long-lived process delays the reap until that process exits. "Delayed" is the right word, and with today's `pid_max` it is negligible.

Review-1 blocking 1 is resolved. The respawn bound (2 per id per controller, never in `block` mode) ends the unbounded loop from review-2 blocking 2. But the respawn is not the replay the design says it is (finding 2).

**Replay safety: respawn goes through classification, not `guard_retire`.** The design says "a later poll probes the worker again, and `guard_retire` replays from its markers". In fact the worker goes back through the probe and the classification loop, and the original decision and kind are lost:
- **Stall or unreachable task that died after `collect.sh` paused the worker.** `run.py` has written DONE (`collect.sh:19-23`), so the re-probe returns DONE and takes the **inline `factory_auto_resume`** path, because `remaining > 60` before `retire_at`. Then:
  - if `.collected` is not set yet, it runs `collect_vm` **inline**, which blocks peers;
  - a single failure of the restart-lock SSH runs `touch .keep` (`launch.sh:520`). `guard_retire` then refuses deletion, and the VM is kept until TTL, which is a founder pit stop.
  - `restart.py` → `require_restart_stop` refuses `terminal_stop == 'paused'` (`recovery.py:205`), so in the common case no new paid work starts. But this path is not analysed or tested.
- **Unreachable worker that answers again, or a stall timer reset by the pause's writes.** The worker is classified as healthy and pending, and the retirement decision is silently dropped until the next trigger.
- **`ttl` task that dies after pausing.** The re-probe sees DONE, auto-resume returns 1 (`remaining ≤ 60`), and the respawn runs as `retire`, not `ttl`. Attestation is skipped.

**Inline auto-resume still queues peers.** Keeping `factory_auto_resume` inline does preserve today's stop semantics exactly:
- it runs in the main shell, with `guard_init`'s traps restored after every start, so a pending trap still runs between its commands;
- step 6 never leaves the deferring traps installed while it runs.

Review-2 blocking 1 is resolved. But the residual bound is not a bound. `ids` are sorted by name (`boat_lifecycle.py:209`), not by creation order, and workers are staggered by minutes. So within one pass, a DONE worker with `remaining > 60` can come before a peer that is already at its TTL margin. Its inline `collect_vm` transfers the whole sealed checkpoint at 120 s per 8 MiB chunk. For a ~500 MiB archive that is roughly 63 chunks, or up to about 2 h in the worst case, and the peer's `ttl` task starts only afterwards. That is row 16's queueing through a different door. "Typically minutes" in the Out-of-scope section is not the bound that review-1 finding 4 asked for, and the Impact line "the k-th worker's collection starts about at once" overclaims. A two-phase pass removes the same-pass case without touching stop semantics: start every due task first, then run the deferred inline auto-resumes.

**Ctrl-C latency.** Today, Ctrl-C kills the foreground `collect.sh` at once, and the exit pass makes up to 3 tries. Under the new design, the task's `collect.sh` ignores INT, so only the in-flight `boat-call` fails. The task then goes on with its remaining tries (each can include a pause of up to 1200 s), and `guard_exit` joins it before an exit pass that makes up to 3 more tries. For a worker that keeps failing, stop latency can be about twice today's. "The join can last as long as today's sequential pass" is not accurate for that case.

**Concurrency for distinct workers.** These claims hold: subshell-local variables; per-name transfer locks with SHA-gated replace; `collection.py` checking only the names it listed; the per-worker deletion lock and evidence directory; per-case `coordinator.locked`; batch and restore operations forced to N=1 (`launch.sh:62`); `ids` replaced atomically. One wording error: `bin/exam-launch`'s `collect_vm` does **not** use function-local variables. `files`, `collect_status` and `dest` are sh globals, and they are safe only because the task is a subshell.

**Token collision.** `gr_token=$$.$counter` resets with every controller. A restarted controller that happens to get the dead controller's pid, while that controller's orphan task still runs, would use the same token, and could read the orphan's late `mv` as its own status. This is very unlikely. Adding `$(date +%s)` to the token removes it.

**Heilmeier.** Objectives, state of the art, approach, impact, risk, cost, timeline and exams are all present. The impact statement needs the correction from finding 1.

**Does the test plan prove the claim?**
- Scenario 1 proves overlap with real fixture timing (`monitor.json` 57600/55800/1800; `bx_d6dzvjbc`).
- Scenarios 2, 4 and 5 cover isolation, liveness and the signal paths.
- Nothing covers:
  - a DONE worker's inline auto-resume ahead of a TTL-due peer in the same pass (finding 1);
  - a respawn whose re-probe shows DONE or healthy (finding 2);
  - a signal during inline auto-resume while tasks are in flight.
- Scenario 6's authored card is correctly marked as not counting towards closing the row.

## 3. Implementation Readiness

Mostly actionable: steps, encoding, variable prefixes, loop placements, return points and the status mapping table are all given. These gaps remain:
- **Kind on respawn.** It is not recorded, so the implementer cannot know what to replay (finding 2).
- **How the test drives `guard_init`.** There are two options: the resume path (`UNBUG_RESUME_LAUNCH=1` sourcing a `monitor.sh` written from `monitor.json`), or a fresh `guard_init`, which needs `boat-spend --check`. The fixture's `poll=120` must also be overridden without breaking the "real timing" claim. Neither is specified.
- **How a stub SIGKILLs its own task** (scenario 4). `$$` inside the task is the *controller's* pid, so the obvious stub would kill the launcher. The mechanism must be stated.
- **How INT reaches the process group** (scenario 5): `setsid` / `start_new_session` plus `killpg`.
- **How "never two concurrent collections" is observed** (for example a stub that holds an `flock` and fails if it is already held).
- **The mutation check is manual.** An env-selectable `GUARD=` path in the test, run in the diff review, is fine, but the expected failing assertion should be named.

Phasing: a single change, which is fine for about 60 lines. The regression list is complete.

## Findings

1. **BLOCKING.** Inline `factory_auto_resume` can still queue TTL-due peers within one pass. `ids` are sorted by name and creation is staggered, so a DONE worker with `remaining > 60` can come first and run a full sealed-checkpoint `collect_vm` inline. That is up to about 2 h worst case at 120 s per 8 MiB chunk, before a peer's `ttl` task starts. "Typically minutes" is not a bound, and the Impact claim overstates the benefit. Fix: run classification in two phases (start every due task first, then run the deferred inline auto-resumes; stop semantics are unchanged), add a test, or at minimum state the worst-case bound and narrow the Impact claim.
2. **BLOCKING.** The respawn after a first statusless death is not a replay from `guard_retire`'s markers. It goes back through the probe and classification and loses the original kind:
   - a stall or unreachable task that died after pausing re-enters as DONE, then inline auto-resume runs, which can mean an inline `collect_vm` and a `.keep` after a single SSH failure (`launch.sh:520`);
   - a healthy-looking re-probe drops the retirement;
   - a `ttl` death respawns as `retire`.

   Fix: record the kind in the in-flight entry and respawn that kind directly on the next pass. Or, simpler (YAGNI), treat a statusless death as a failed retirement and rely on the exit pass. Test either choice.
3. **NIT.** Ctrl-C latency: the task finishes its remaining tries before the exit pass makes up to 3 more, so a worker that keeps failing can take about twice today's time. Correct "as long as today's sequential pass".
4. **NIT.** Add a time or random component to `gr_token`, so a restarted controller that reuses the old controller's pid cannot collide with an orphan's token.
5. **NIT.** `bin/exam-launch`'s `collect_vm` uses sh globals (`files`, `collect_status`, `dest`), not function-local variables. They are safe only because the task is a subshell. Fix the wording.
6. **NIT.** Test harness specifics are missing:
   - how `guard_init` gets the fixture timing, and how `poll` is overridden;
   - how a stub SIGKILLs its own task (`$$` is the controller);
   - how INT reaches the process group (`setsid`/`killpg`);
   - how "never two concurrent collections" is detected.
7. **NIT.** Add a scenario: a signal during inline `factory_auto_resume` while peer tasks are in flight. Pass: the trap fires between the resume's commands, `guard_exit` joins the tasks, and the exit pass runs.
8. **NIT.** Say that reaping can lag up to one `poll`, and that `once`-mode tasks are reaped only by the next `guard_wait` call or in `guard_exit`.
9. **NIT.** On PID reuse, a statusless task's reap is delayed for as long as the reused pid's process lives. "Delayed" is correct; say it is bounded by that process's lifetime.
10. **NIT.** Name the assertion that the manual base-guard mutation check must fail on (scenario 1's overlap barrier), so the recorded result can be checked.

Review-1 blockers 1–4 and review-2 blocker 1 are resolved. The bound in review-2 blocker 2 is fixed, but finding 2 here shows its replay claim is wrong.

**Verdict: FAIL** (2 blocking: inline auto-resume still queues TTL-due peers with no real bound, and respawn re-classifies the worker instead of replaying its retirement).

---

## Dispositions (elephant)

Both blocking findings were accepted and fixed in design revision 4. No
blocking finding was rejected.

| # | Kind | Disposition |
|---|---|---|
| 1 | BLOCKING | **Fixed with the two-phase pass.** Every task due in the pass starts first, and then the deferred inline auto-resumes run. Stop semantics are unchanged, because auto-resume is still inline in the main shell. The remaining cross-pass bound is now stated as a worst case: about 63 chunks × 120 s for a ~500 MiB checkpoint, plus bounded SSH. The Impact claim is narrowed to same-pass peers, plus one `poll` and any in-pass auto-resumes. Added a two-phase test with a barrier, which is expected to fail on the base guard. |
| 2 | BLOCKING | **Fixed with the simpler option the review offered (YAGNI).** A statusless death is a failed retirement: `.retired`, failure status, the exit pass retries from markers, and the TTL is the backstop. Nothing is re-classified or respawned. The respawn machinery is removed. Scenario 4 asserts that the worker is not probed or collected again by `guard_wait`. |
| 3 | NIT | **Fixed.** Stop latency for a worker that keeps failing (up to about twice today's) is stated, with the N-worker improvement. |
| 4 | NIT | **Fixed.** The token includes `guard_task_epoch` (`date +%s`, taken when the guard is sourced). |
| 5 | NIT | **Fixed.** The `exam-launch` wording is corrected. |
| 6 | NIT | **Fixed.** The harness section covers the `guard_init` outputs, the `poll` override, the `$PPID` trick, `killpg`, and the `mkdir` overlap detector. |
| 7 | NIT | **Adopted.** Added the scenario of a signal during inline auto-resume with a peer task in flight. |
| 8 | NIT | **Fixed.** Reap lag of up to one `poll`, and when `once`-mode tasks are reaped, are stated. |
| 9 | NIT | **Fixed.** The PID-reuse delay is bounded by the lifetime of the reused pid's process. |
| 10 | NIT | **Fixed.** The expected failing assertions for the mutation check are named. |
