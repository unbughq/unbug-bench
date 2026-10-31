**Verdict: FAIL. One blocker is open, and it can be fixed with a few lines of design text.**

The design gets the root problem right and fixes it the simple way. The blocker is that deleting the outer timers introduces a new way for a caller to hang, and the design doesn't mention it. There are also four Major gaps and some nits. I reviewed `docs/designs/isolation-item8-prereqs.md` at `3a9948d` against the three personas (Mode: REVIEW), the Heilmeier and implementation-readiness standards, `docs/ENGINEERING.md`, the six call sites, `bin/boat-call`, `bin/processes.py`, the Murphy row, Item 8 in `stream-d.md`, the existing tests and the saved fixtures. I made no edits, paid calls, pushes or merges.

## What I checked and found accurate

- **The six call sites and their limits match the code.**
  - `key_holder.py:665`: 25 s, unchecked.
  - `batch_holder.py:717`: 25 s, checked.
  - `coordinator_inventory.py:135` and `:160`: 25 s each, unchecked, with an injectable `run`.
  - `batch_status.py:60`: 30 s, checked, and it already passes `BOAT_COMMAND_TIMEOUT_SECONDS`.
  - `ttl_continuation.py:87`: 120 s, via `check_output`.
- **The root cause is correct.** On timeout, `subprocess.run` sends SIGKILL to `boat-call`, so its cleanup never runs. `processes.run` starts the Boat child in a new session, so that child survives.
- **No caller loses error handling.** I checked each one: timeouts now come back as exit 124, which turns into `CalledProcessError` or the existing nonzero refusal. `batch_holder`'s handler at line 748 already catches `CalledProcessError`.
- **`UNBUG_PROCESS_DEADLINE` is already honoured.** `boat-call` copies `os.environ`, and `processes.envelope` takes the earlier of that deadline and the command limit.
- **Removing the timer is the simplest root fix.** `transfer.py:30` already calls `boat-call` this way, with no outer timer. No new helper is needed.
- **The design has every section `ENGINEERING.md` requires:** problem, change, deletion, tests and the Murphy row.

## Blockers

**B1. Without a timer, a caller can now wait forever, and the design doesn't say so.** (Design critic; "Change and deletion", lines 24–31)
- All six callers capture output through pipes. `boat-call` doesn't capture the Boat process's output, so Boat and anything it starts write straight into the caller's pipe.
- If a descendant escapes `kill_tree`, it keeps that pipe open. For example, a process could detach before the `ps` snapshot, or be forked after it.
- Without `timeout=`, `subprocess.run` keeps reading until the pipe closes, which may be never. Today, a timed-out run kills the child and then only calls `process.wait()`, so the caller always returns.
- The design lists escaped descendants as out of scope. What it misses is that this change turns them from a stray process into a caller that never returns.
- That matters most in `key_holder`: its serve loop (`key_holder.py:561–575`) is single-threaded and also runs `batch_tick`. One hung inventory call would stall every holder request and batch dispatch. That is a human pit stop, which goes against the first target property in `ENGINEERING.md` §3.
- **Fix (either one):**
  - (a) Send the child's output to a temporary file (`stdout=tempfile.TemporaryFile()`) instead of a pipe. The caller then waits only for `boat-call` itself to exit. This needs only the standard library and no new helper, but the design must say that capture now goes through a file.
  - (b) State this new failure mode explicitly and add a `new-isolation-outer-wall-2` Murphy row for an escaped pipe holder wedging a caller that has no timer. Name `key_holder` as the most exposed caller, and justify accepting the risk the way the `transfer.py` precedent does.

## Major

**M1. The longer worst-case wait isn't checked against the callers' own time limits.** (Design critic; lines 26–30)
- A launch client waits 60 s on its socket (`key_holder.py:281`), and a timed-out launch is treated as uncertain and never retried (`:823`).
- Previously the inventory call was capped at 25 s. Now the cap is 25 s plus the cleanup time `boat-call` adds after its deadline, which can be about 64 s.
- `kill_tree` also runs its `ps` probe on every successful call, not just on timeouts.
- On the slow host this row is about, the holder can therefore go on to launch after the client has already recorded "uncertain".
- **Fix:** add one sentence on how each caller's surrounding limit relates to the new worst case: the `key_holder` 60 s socket timeout, the coordinator tick deadline and the TTL `bounds['deadline']`. Either accept each gap with a reason or lower that caller's limit.

**M2. The list of call sites is incomplete, and the design doesn't say what it leaves out.** (Zoom-out; lines 5–7)
- Other Python callers of `boat-call` still have outer timeouts that kill it with SIGKILL:
  - `tools/public-qualification/finish.py:56` (`timeout=remaining`, deletion status);
  - `tools/factory_dashboard.py:74` `run_json`, at 45 s, which `tools/factory_board.py:135` also uses.
- `finish.py` matters most, because Item 8's B/E work verifies cleanup from creation through deletion.
- `tools/boat_readiness.py` is already safe, because it uses `terminate`.
- **Fix:** say in one line that these are excluded and why (operator or display tools, owned by a later increment), or bring them into scope.

**M3. Several implementation decisions are left to the implementer.** (Readiness; "Tests and evidence")
- **New test file:** no path is given. That path is what goes into the Murphy row's "Closed by" column.
- **Existing tests that must change:** none are listed. `tests/factory/test_coordinator_inventory.py:108` asserts `kwargs["timeout"] == 25`, so it will fail and needs to assert the new environment variable instead.
- **Suite log:** the design says only "a unique committed path". It should name a concrete location, such as `docs/reports/isolation-item8-prereqs-suite-<stamp>.log`.
- **Per-site change:** spell out the exact edit for each of the six sites. Most are "drop `timeout=`, add `env={**os.environ, 'BOAT_COMMAND_TIMEOUT_SECONDS': '<n>'}`". `batch_status` only needs `timeout=` deleted.

**M4. The Heilmeier answers are thin.** (Design critic, Heilmeier standard)
- The objective is full of jargon ("Murphy new-isolation-outer-wall-1", "A/D", "B/E").
- Impact, Cost and Timeline are not stated.
- One plain line each would fix this. For example, Impact: "a timed-out provider query can no longer leave a stray Boat process on the control host." Cost: "local only, $0." Timeline: "one increment."
- This is not a blocker, given how small the change is.

## Nits

- **N1. The overrun description is slightly too high.** Cleanup after the version check runs inside the same deadline. If that cleanup reaches the deadline, the command isn't started at all. So the time past the deadline is at most one cleanup pass plus the drain, not two (lines 27–28).
- **N2. Test the real functions where that's cheap.** `batch_status._boat`, the default `remote` in `ttl_continuation`, and `coordinator_inventory.tick` with `run=subprocess.run` can all be called directly. Keep the code-extraction approach only for the two holder sites that are buried in large functions; it breaks more easily when the source changes.
- **N3. Say cleanup runs on every call.** `kill_tree` runs on success too, so the `ps` cost applies to every call, not only timeouts. One clause would make the latency trade clear.
- **N4. Add one test for B1.** A descendant that detaches before the snapshot and keeps stdout open would show whether the chosen B1 fix works, or show the accepted risk if (b) is chosen.

## Rows the design closes

Closing only `new-isolation-outer-wall-1`, using real-process tests that run against the saved fixtures in `tests/factory/fixtures/isolation-timeouts/` (`boat-version.json`, `list.json`, `created.json`, `launch.json`), is appropriate. The design correctly leaves Item 8's settlement and live rows open and keeps diagnosis disabled.

To pass, fix B1 (option a or b) and answer M1–M4 in the design, then get another fresh design review.

---
Implementation response: B1 accepted using option (b), a visible remaining risk
and open Murphy row; M1–M4 and N1–N4 incorporated into the revised design.
No implementation yet. A fresh reviewer must accept the revision.
