# Design review 2: independent-worker-retirement

- Reviewer: a fresh goldfish, run as a local `claude -p` process (Claude Code
  2.1.318) with read-only tools. It had no conversation history.
- Personas: `zoom_out`, `design_critic` and `implementation_readiness`, all in
  `Mode: REVIEW`.
- Standards: `heilmeier-standard.md` and
  `implementation-readiness-standard.md`.
- Subject: `docs/designs/independent-worker-retirement.md` at commit
  `27d7443` (revision 2). The reviewer was also given design review 1 and its
  dispositions.
- Verdict: **FAIL**, with 2 blocking findings and 11 nits.

The review output is reproduced verbatim below, followed by the elephant's
dispositions.

---

## Verbatim review

I couldn't run dash or bash here because shell execution needed approval. The shell-behaviour points below come from POSIX, dash and bash semantics, checked against the repo source.

# Goldfish design review: `docs/designs/independent-worker-retirement.md` (revision 2)

All three personas ran in Mode: REVIEW. Standards: `heilmeier-standard.md`, `implementation-readiness-standard.md`, plus the zoom-out audit vectors.

## 1. Zoom Out (Skeptical Architect)

**Root problem and scope.** The scope is right. Row 16's Fix column names "an independent retirement task" per worker, and this design does that and nothing more. It keeps `guard_retire`, `factory_ttl_retire` and `factory_auto_resume` unchanged, and it leaves the seal-versus-reserve half open with clear reasons. Moving `factory_ttl_retire` and `factory_auto_resume` into the task was needed to make "the poll loop only probes, classifies, starts and reaps" true. That resolves blocking finding 4 from review 1.

**Reuse.** No new helper duplicates existing code. The per-worker locks it relies on already exist: `command_fence`/`delete_receipt` lock `<id>.deletion.lock` (`boat_lifecycle.py:466,677,695`), `transfer.py` takes a per-filename `flock`, and `ttl_continuation` locks per case. `--restore` and batch operations force `N=1` (`launch.sh:62,202`), so two workers in one launch never collect the same case name. That supports the "distinct cases" claim more strongly than the timestamp-plus-random argument the design gives.

**Altitude.** The sh fragments in §`guard_retire_start` are justified here: this change is mostly about shell semantics.

**Gap at the scope boundary.** Moving `factory_auto_resume` into a background task changes how a stop request interacts with a resume. The design analyses signals only for collection (see Design Critic, finding 1).

## 2. Design Critic

**POSIX sh under `set -eu`:**
- An async list `( … ) &` never triggers errexit in the parent.
- `<work> || gr_s=$?` keeps errexit off inside the work, as at today's call sites.
- `trap - 0` in the task is redundant but harmless.
- An `&` child with job control off ignores SIGINT and resets caught traps to their defaults, so the task's TERM is at default. Exit-pass tasks inherit `trap '' INT TERM`.
- All of this is correct for both dash and `bash --posix`.

**Signal-deferral window (review-1 blocking 2).** This is closed. A signal between `&` and recording `id:pid:token` only sets `gr_signal`. The entry is recorded before `exit "$gr_signal"` runs `guard_exit`, and step 1 then skips the recorded task. Restoring hard-coded `exit 130`/`exit 143` matches every current caller: all reach `guard_wait` only after `guard_init`, and `run-gate-smoke.sh` never calls `guard_wait`. It is still brittle (nit). `gr_signal` and `guard_exiting` must be initialised for `set -u` (nit).

**Reaping and liveness (review-1 blocking 1).**
- The file-or-`kill -0` test is sound: a zombie answers `kill -0` until dash or bash reaps it, and a later pass catches it.
- **New problem:** a task that dies without a status file is never marked `.retired`, so it is re-probed and respawned. The design itself names deterministic causes: a `set -u` abort in the retirement path, and ENOSPC on the status write. Disk-full is realistic, since archives of about 500 MiB land in `$root/sealed`.
- In those cases, every poll starts a new task that dies the same way. The final non-`once` `guard_wait` never returns, and the launcher never reaches its exit pass, orphan check or spend finish.
- Today, the same shell-fatal error kills the main shell, and the exit pass runs. ENOSPC during collection makes `guard_retire` return 1, the worker is marked `.retired` and kept, and the launcher still finishes.
- So the fix for review-1 blocking 1 swaps a hang for an unbounded respawn loop. Respawns need a bound: for example, the second missing-status death for an id marks it `.retired` with failure and leaves it to the exit pass and the TTL backstop.

**Ctrl-C and TERM for `done` tasks (`factory_auto_resume`).** §Signals analyses only collection and claims "the outcome is the same as today". That is false for the `done` kind.

*Today:* `factory_auto_resume` runs inline. dash and bash run the pending `exit 130`/`exit 143` trap between commands. So a Ctrl-C or TERM aborts the resume before any `|| { touch .keep; … }` handler runs, and the exit pass then collects and deletes the worker.

*New, Ctrl-C:* the task's shell ignores SIGINT, but its `boat-call` children catch it and fail. That runs the handlers today's trap skips:
- the restart-lock probe: `|| { touch .keep; return 1; }` (`launch.sh:520`);
- the `statement_round.py` handoff (`:568`);
- `account_handoff apply` (`:614`);
- `boat exec --detach` (`:641`).

Each of these writes `.keep`, so `guard_retire` and the exit pass refuse deletion. The VM is kept until TTL as "KEEPING VM … uncertain", which is a founder pit stop. Today it would have been collected and deleted.

*New, TERM to the launcher only:* the task keeps running. It can reach `boat exec --detach … run.py --resume` (`:625`) and start new paid model work after a stop was requested. It also removes `.collected` (`:624`), so the exit pass must pause the fresh run again and wait for it to seal. If that seal does not fit the pause wait, collection fails three times and the worker is kept.

Scenario 5 covers only a blocked collection. The design must either have `done` tasks honour a stop, for example a `$state/stopping` marker that the INT/TERM path writes and that the task checks before `factory_auto_resume`, or state and accept the new behaviour. Either way it needs a test.

**Concurrency for distinct workers.**
- These claims hold: subshell-local variables; per-file transfer locks with SHA-gated replacement; `collection.py` checking only names it listed itself; per-worker fence and deletion lock; atomic `ids` replacement, which `command_fence` reads.
- The claim that `factory_auto_resume`'s side effects "are all state files keyed by worker id" is inaccurate. `statement_round.py --same-worker-handoff` reads and reserves in the shared `$admission_root/sealed/statement-registry`. That registry is protected by `Registry`'s `flock`, apart from a lock-free read of an atomically written file, so it is probably safe. It belongs in the audit, and no scenario runs two real auto-resumes at once (nit).
- "Only one task per id can exist at a time" holds within one controller. Orphans of a SIGKILLed controller can overlap the new controller, as today's single orphan can (nit: qualify the claim).
- N simultaneous chunk transfers share host bandwidth under a 120 s-per-8 MiB chunk bound. This is not examined (nit).

**Replay safety.** Holds. The `.deleted`, `.collected` and `.retiring.json` markers make an exit-pass `guard_retire` a no-op or a refusal. Token-named status files mean a stale or orphan status is never read.

**Does the test plan prove the claim?**
- Scenario 1 proves overlap with the real guard and real fixture timing (`monitor.json` 57600/55800, `bx_d6dzvjbc` from `created.json`).
- Scenarios 4 and 5 cover the liveness and signal paths for collection only. No scenario covers a deterministic missing status, a `done` task under a signal, or `once` overlapping `guard_new` (requested in review 1).
- The base-guard mutation check is manual.
- Scenario 6's card is authored. That is acceptable because the row stays open, but it should say it does not count towards closing the row.

**Heilmeier.** Objectives, state of the art, approach, impact, risk and cost are present. Timeline is missing (nit).

## 3. Implementation Readiness

These points still need fixing before an implementer can work without making choices:
- **Where the in-flight skip goes.** It must come before the `.retired`/`.deleted` checks at `boat-launch-guards.sh:236-237`. Otherwise a task that just deleted its worker drops `pending`, and the early `return` at `:248` returns with tasks still in flight. The returns at `:248` and `:298` must also check that `guard_retiring` is empty. The design states the invariant but not these two placements.
- **When old status files are removed.** "Start removes older `$state/$id.retirement-exit.*` files" has no position in the numbered steps. It must run before the fork. Run after it, the glob can delete the new task's own status, and the reaper then counts the task as dead.
- **The `done` kind.** It should be written out, as `if … factory_auto_resume …; then write resumed; else guard_retire || gr_s=$?; fi`, together with the stop check from finding 1.
- **The respawn bound** (finding 2) is a design decision the implementer must not invent.
- **Out-of-scope list.** It should also name the synchronous `guard_retire` after a `guard_new` failure (`launch.sh:667`).
- **Phasing.** A single change is fine for this size. The regression list is complete and includes `bin/exam-launch`, whose `collect_vm` globals become task-local.

## Findings

1. **BLOCKING.** Moving `factory_auto_resume` into the task changes stop behaviour, and the design does not analyse it.
   - Ctrl-C makes the in-flight `boat-call`s fail inside a shell that ignores SIGINT, so the resume's `.keep` handlers run (`launch.sh:520,568,614,641`). The VM is kept until TTL with a founder pit stop. Today the trap exits first, and the worker is collected and deleted.
   - TERM to the launcher lets a resume go on to `boat exec --detach run.py --resume` (new paid work) and remove `.collected`, and the exit pass must then pause and re-collect it.
   - "The outcome is the same as today" is false here. Specify stop handling for `done` tasks (for example a stop marker checked before and inside the resume path, or skipping auto-resume once a stop is pending) and add a signal test for `done` tasks.
2. **BLOCKING.** Unbounded respawn. A task that ends with no status is never marked `.retired` and is restarted every poll. For deterministic causes the design itself lists (`set -u`, ENOSPC), the final `guard_wait` never returns, which is a new non-terminating launcher. Bound respawns per id (for example, after a second missing status, mark the worker `.retired` with failure) and test a task that always dies.
3. **NIT.** Specify that the in-flight skip comes before `:236-237`, and that the returns at `:248` and `:298` also require `guard_retiring` to be empty.
4. **NIT.** Put the stale-file removal before the fork, and initialise `gr_signal` and `guard_exiting` for `set -u`.
5. **NIT.** The trap restore is hard-coded. It is correct for current callers, but saving and restoring `$(trap)`, or a comment tying it to `guard_init`, would be safer.
6. **NIT.** The concurrency audit leaves out the shared statement registry and the shared `sealed/` cards that `factory_auto_resume` touches, and no test runs two real auto-resumes at once.
7. **NIT.** Qualify "only one task per id": orphans of a SIGKILLed controller can overlap, as today.
8. **NIT.** `kill -0` can be fooled by PID reuse over long batches. This is theoretical, but worth stating.
9. **NIT.** Automate or record the base-guard mutation check, and add the `once`/`guard_new` overlap test review 1 asked for.
10. **NIT.** Bandwidth and API contention from N parallel chunk transfers against the 120 s chunk bound is not examined.
11. **NIT.** List the synchronous retirement at `launch.sh:667` (after a `guard_new` failure) as out of scope too.
12. **NIT.** Heilmeier: add a timeline.
13. **NIT.** Say that scenario 6's authored card does not count as real-artifact evidence towards closing row 16.

**Verdict: FAIL.** Two blocking findings remain: stop behaviour for `done` tasks, and the unbounded respawn of tasks that die without a status.

---

## Dispositions (elephant)

Both blocking findings were accepted and fixed in design revision 3. No
blocking finding was rejected.

| # | Kind | Disposition |
|---|---|---|
| 1 | BLOCKING | **Fixed, by reverting that part of the scope.** `factory_auto_resume` stays inline in the main shell, exactly as today, so its stop semantics are unchanged byte for byte: Ctrl-C and TERM still run the launcher trap between its commands. Only retirement (`factory_ttl_retire` plus `guard_retire`) runs in tasks. The bound that inline auto-resume still adds to peers is stated under Out of scope: no pause wait, because DONE already exists, so it is a sealed-checkpoint transfer plus a few bounded SSH calls. The stop behaviour of `factory_ttl_retire` inside a task is analysed: with a TERM, the only extra effect is a `queued_policy_required` queue record, which needs a separate admitted launch. |
| 2 | BLOCKING | **Fixed.** Respawns are bounded. The first statusless death respawns (the worker is not `.retired`). A second death for the same id in the same controller marks it `.retired`, the same as a failed retirement today. In `block` (exit) mode, a missing status never respawns. Added a test for a task that always dies. |
| 3 | NIT | **Fixed.** The in-flight skip comes before the `.retired`/`.deleted` checks, and both return points require an empty `guard_retiring`. |
| 4 | NIT | **Fixed.** Stale-file removal happens before the fork, and the variables are initialised for `set -u`. |
| 5 | NIT | **Adopted as a comment.** The restored traps are tied to `guard_init`. Saving `$(trap)` was not adopted: `eval` of `trap` output is quoting-sensitive across dash and bash, and every caller uses `guard_init`'s traps. |
| 6 | NIT | **Moot.** Auto-resume stays inline, so no concurrent auto-resumes occur. |
| 7 | NIT | **Fixed.** "One task per id" is qualified to one controller, with orphan overlap stated. |
| 8 | NIT | **Fixed.** PID reuse is stated: the effect is a delayed reap, never a wrong status. |
| 9 | NIT | **Partly adopted.** The base-guard mutation check is recorded in the diff review and the PR. The once/`guard_new` overlap test was not added; the reasons are stated in the design (atomic `ids` replace, and the task-side reader needs only its own id). |
| 10 | NIT | **Fixed.** Bandwidth contention is stated: it costs retries, never integrity, and live impact is unmeasured. |
| 11 | NIT | **Fixed.** The `guard_retire` after a `guard_new` failure is listed as out of scope. |
| 12 | NIT | **Fixed.** Added a timeline. |
| 13 | NIT | **Fixed.** Scenario 6 is marked as not real-artifact evidence. |
