# Design review: `docs/designs/isolation-capture.md`. Verdict: **FAIL**

There is one blocker. The design does not say how Boat should read its captured output files, so the obvious implementation can replay corrupted output. Everything else is a nit or a non-blocking Major. Once the blocker is fixed, ENGINEERING.md requires another fresh design review.

I worked read-only in worktree `t3-c3a8faa6` at 022ee5b. The design file is untracked. I read the three reviewer agent files, both standards, `docs/ENGINEERING.md`, Murphy row `new-isolation-outer-wall-2`, `docs/designs/isolation-item8-prereqs.md`, `bin/boat-call`, `bin/processes.py`, the six call sites and `tests/factory/test_isolation_outer_callers.py`. I spawned no subagents, made no paid calls and edited nothing.

---

### B1 — Blocker: replaying the files can corrupt output if an escaped process keeps writing
**Lines 16–21.** `TemporaryFile` opens without `O_APPEND`. When the file is passed as the child's stdout/stderr, Boat and every descendant share one file position. That includes escaped descendants, which is the case this design targets.

The natural replay is `f.seek(0); f.read(n)`. That moves the shared position back to 0. A reparented writer that is still writing then overwrites the start of the real output while Boat is replaying it. "Snapshot size and replay only that many bytes" limits how much is read, not which bytes are read.

The consequences:
- Most likely, the JSON is garbled and the caller fails closed, so availability suffers.
- Worse, `key_holder` or `coordinator_inventory` could parse an inventory that looks valid but is wrong.

The proposed test (line 49: a writer "retaining both streams") only holds the files open. It never writes to them while Boat replays, so it would pass with the bug in place.

**Required fix:**
- State the mechanism: `os.fstat(fd).st_size`, then `os.pread(fd, …)` up to that size, never moving the shared position. Opening with `O_APPEND` is an alternative.
- Add a test case: the escaped child writes to both stdout and stderr in a loop, and the caller must get byte-exact saved artifacts while that child is still writing.

### M1 — Major (non-blocking): Heilmeier gaps
- **Objectives (lines 5–10)** are written entirely in jargon ("reparented transport descendant", "EOF", "inherited pipes"). The plain objective is missing. Something like: "a stray background process can freeze the key holder forever; make the six provider queries return anyway."
- **Impact** is not stated here. The single-threaded `key_holder` serve loop is the reason this matters, but that is only in `isolation-item8-prereqs.md` (lines 73–75).
- **Timeline** is absent.
- **Risks** are scattered through the text. The swap of pipe back-pressure for unbounded disk growth (lines 31–33) is the one trade-off, and it deserves one plain sentence about where the temp file lives (`TMPDIR` on the control VM).

### N1 — Nit: the opt-in is an environment variable that children inherit
`BOAT_CAPTURE_OUTPUT=1` will pass to the Boat CLI, adapter transports and any nested `boat-call`. The existing `--stdin` argument flag is the local precedent, and a `--capture` flag would not leak. If the variable stays, `boat-call` should remove it from the child's environment, and the design should say so.

### N2 — Nit: a few edge cases are left to the implementer
- **Oversize cap vs. a nonzero command exit code:** which wins, 125 or the command's own code? Both are nonzero, so all callers behave the same, but the design should say which.
- **Captured stderr on oversize:** is it emitted? Line 27 only rules out stdout.
- **Where the files are created and closed:** they should wrap `processes.run` inside `processes.deadline`. They should close after cleanup so that the 124 and 143 paths never replay. Line 30 implies this but doesn't place it.
- **Lost diagnostics:** on timeout or cancellation, the command's partial stderr is now discarded where it used to be streamed. That is acceptable, but it should be stated as a behaviour change.

### N3 — Nit: the version-check claim needs one more clause
Lines 22–23 are correct that `--version` never inherits the caller's pipes. But an escaped descendant of `boat --version` would make the `communicate` loop in `processes.run` wait until the command deadline and then return 124. That is bounded, but it fails rather than succeeds, and the design should say so.

### N4 — Nit: one ambiguous test phrase
`ttl_continuation` uses `check_output`, so its stderr is never captured by the caller. "Nonzero escaped command output" (line 52) should say which site checks what for `ttl_continuation`.

---

### Checks that pass
- **Scope:** the six sites and their `SITES` indices match the code (`key_holder:665`, `batch_holder:717`, `coordinator_inventory:136/162`, `batch_status:60`, `ttl_continuation:88`). None of them uses `--stdin`, so stdin is not an issue.
- **Waiting behaviour:** `processes.run` with file descriptors instead of pipes makes `communicate` wait only for the process, so the deadline and `kill_tree` cleanup are unchanged. No new subprocess or timer is added.
- **Deletion:** removing the expected-hang test is an honest deletion. Default streaming stays for `transfer.py`, `statement_round` and the shell callers, matching the row's "accepts transfer/statement_round risk explicitly". Lines 38–40 and 65–66 avoid over-claiming.
- **Murphy closure:** the scope is right: one row, closed by real-process tests on saved artifacts, with no claims about worker absence, deletion or billing. Cost $0 and the full-suite command match ENGINEERING.md.
- **Simplicity (zoom-out):** there is no new module, and stdlib `TemporaryFile` is the minimal fix. The 8 MiB cap is justified as the bound on replay memory.

**Result: FAIL.** Fix B1, and preferably M1 and N1–N2 in the same pass, then run a fresh design review before implementing.

## Elephant resolution

Accepted B1: specify positional reads and an actively writing escaped-process regression. Accepted M1 and N1–N4; the revised design records these clarifications. No finding rejected. Fresh review follows.
