Checks are done; writing up the review now.

# Diff review: `t3/isolation-item8-prereqs` (f829df7..5324e21) against `docs/designs/isolation-item8-prereqs.md`

**Personas:** zoom_out and implementation_readiness, in Mode: REVIEW, using `implementation-readiness-standard.md`.
**Reviewer:** fresh read-only goldfish. I made no edits, paid calls, pushes or merges, and started no agents.

## Verdict: **PASS.** There are no blocking findings, and three optional nits.

## What I checked myself

**The six call-site edits match the design's per-site list exactly.**
- `key_holder.py:665`, `batch_holder.py:717` and `coordinator_inventory.py:136` and `:162` each drop `timeout=25` and add `env={**os.environ, 'BOAT_COMMAND_TIMEOUT_SECONDS': '25'}`. `coordinator_inventory` gains `import os`. `key_holder` and `batch_holder` already imported it.
- `batch_status.py:60` only loses its `timeout=`. Its owner env was already there.
- `ttl_continuation.py:88` drops `timeout=120`, sets the env to `'120'` and adds `import os`.
- The argv, the check/capture/text/stdin flags and the error handling are all unchanged.
- `bin/boat-call` reads `BOAT_COMMAND_TIMEOUT_SECONDS` (line 19) and returns 124 on timeout.
- `processes.py:39–45` still takes the earlier of the inherited `UNBUG_PROCESS_DEADLINE` and the command limit, so the inherited deadline is preserved.
- No other factory call wraps `boat-call` with an outer `timeout=`.

**The tests use real artifacts and real processes.**
- The fixtures in `tests/factory/fixtures/isolation-timeouts/` were committed on 2026-10-29 (c04f5ff), before this branch. Their README says they are read-only copies from a real launch, so the code under test did not generate them.
- The tests run the real `boat-call` and `processes.py`. The transport is named `boat`, so pinned version discovery really runs: the test asserts `['--version']` appears in the call log.
- The heartbeat child is a real process in its own session that ignores SIGTERM. A real slow `ps` wrapper delays cleanup.
- The tests pull the production call expressions out by AST, sorted by line number. I checked that the index-to-site mapping matches the source: each file has only the expected `boat-call` calls, and coordinator index 0 is the ssh call at :136 while index 1 is the list call at :162.
- Each site gets checked four ways: no `timeout` keyword, the owner limit is 25/30/120, the inherited deadline passes through, and two real runs (saved output on success, nonzero exit 9 on failure).
- Timeout runs return 124 only after the heartbeat stops, with elapsed time ≥ 3 s against a 2 s deadline.
- SIGTERM cancellation returns 143 after cleanup.
- The escaped-pipe test shows the owner has exited while the caller is still blocked on its pipe, then kills the escaped child and confirms the caller is released. That is an honest demonstration of the open row.
- `batch_status._boat` and `ttl_continuation.request_retirement` are also called as whole functions.
- `test_coordinator_inventory.py:108` now checks the env value and that no `timeout` keyword is passed.
- **I reran the file myself:** `test_isolation_outer_callers.py` ran 5 tests, OK, in 44.5 s. Timings were 5.10–5.15 s per site and 3.25 s for SIGTERM. The working tree was still clean afterwards.

**Murphy register.**
- `new-isolation-outer-wall-1` is closed in the fix commit a42c520, as §2 requires. Its `Closed by` names the test, the six sites and both exclusions (the escaped-pipe case and the operator/display tools).
- `new-isolation-outer-wall-2` is added as **open**, rated High, with a `new-` id. Its fix column says it must be resolved before Item 8 activation and must not be used to infer worker absence or deletion.
- `stream-d.md` Item 8 now lists outer-wall-2 as an activation blocker.
- No settlement row or live-infrastructure row was closed.
- So B1 option (b) is implemented as tracked and is not claimed as fixed.

**Full suite.**
- The committed log `docs/reports/isolation-item8-prereqs-suite-20261031T131629Z-3cf32eef.log` shows `159 test scripts run; 0 failed`, `SUITE_EXIT_CODE=0` and `ELAPSED_SECONDS=1186.917`.
- It includes `test_isolation_outer_callers.py` (5 OK, with LOCAL_TIMING lines) and `test_coordinator_inventory.py`.
- The log's timestamp, 13:16:29Z, equals a42c520's commit time. The only later commit adds the docs and the log, so the suite ran on the final code.
- The report presents the timings as observations, not bounds, and makes no claim about billing or remote outcomes.

## Blockers

None.

## Nits (optional)

1. **The timing test can't fail on the old code; only the static check guards against regression.**
   - **Where:** `tests/factory/test_isolation_outer_callers.py`, `test_six_callers_wait_for_slow_cleanup_after_inherited_deadline`.
   - **Why:** cleanup finishes in about 5 s, well inside the deleted 25/30/120 s timers. That run would have passed before the fix too.
   - **What actually guards it:** the AST assertion that no `timeout` keyword is present, plus the env lookup, which fails if the env argument is missing. Both look at the real production expressions, so a regression is still caught, and the row's own wording ("prove timed-out real child cleanup under a slow probe") is met.
   - **Suggestion:** say this in the report or the row, so nobody later reads the timing runs as proof that an outer timer kills the owner. A test that does fail on the old code would need cleanup longer than 25 s. That isn't worth the suite time now.
2. **The scope note leaves out `restore_bundle.py`.**
   - **Where:** design lines 96–100 and the report's "Scope" section.
   - **What:** `factory/restore_bundle.py:115` and `:120` call raw `boat info` and `boat list` with `timeout=60`. They bypass `boat-call` entirely: no version pin and no cleanup step.
   - **Why it's only a nit:** this is not the outer-wall-1 mechanism, since there's no Boat owner to kill early. The design also already says the closure "does not certify every caller". Still, it's an absence/deletion query, so it's worth naming next to `finish.py` for the deletion-qualification work.
3. **The suite log doesn't record which commit it ran.**
   - **Where:** the suite log header.
   - **Why it matters:** I could only tie the log to a42c520 by matching timestamps.
   - **Suggestion:** for future suite logs, print `git rev-parse HEAD` and the clean or dirty state at the top of the log.

## Zoom-out

The diff deletes six competing timers and adds no new helper, module or transport. The only new file is the test, and it reuses the saved fixtures, `boat-call` and `processes.py` instead of building its own. The design limits are carried through honestly: outer-wall-2 is open, Item 8 is not ready, no live launch is authorized and diagnosis stays disabled. I found no YAGNI or reinvention problems.

## Implementation readiness

Every per-site instruction in the design maps one-to-one onto the diff, with nothing left for the implementer to decide. The design's test plan was carried out in full: six-site contract coverage, whole-function status and TTL calls, the coordinator assertion update, SIGTERM, the escaped-pipe demonstration, a separate hang guard (`GUARD=300`), a unique committed log path and a summary report.

**Result: PASS. No blockers, and nits 1–3 are optional.**

---
Implementation response: PASS accepted; no blockers to fix. Nits 1 and 2
addressed in the report as evidence/scope clarifications only. Nit 3 accepted
for future log headers; the original log is retained unmodified, with its
reviewer-verified implementation commit binding recorded in the report.
