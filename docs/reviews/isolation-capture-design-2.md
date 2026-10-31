# Design review 2: `docs/designs/isolation-capture.md`. Verdict: **PASS**

There are no blockers. The revised design fixes B1, the replay-corruption problem from the first review. One Major and four Nits remain, and none of them blocks.

**Scope.** I worked read-only in worktree `t3-c3a8faa6` at 022ee5b; the design file is untracked. I read:
- the three persona files, `heilmeier-standard.md` and `implementation-readiness-standard.md`;
- `docs/ENGINEERING.md` and Murphy row `new-isolation-outer-wall-2`;
- review 1, `bin/boat-call`, `bin/processes.py` and the six call sites;
- `tests/factory/test_isolation_outer_callers.py` and the `isolation-timeouts` fixtures.

I spawned no subagents, made no paid calls, edited nothing and pushed nothing.

---

## B1: fixed

**The new reading method (lines 22–25, 33–34) is safe.** The design now pins it down:
- take the file size with `os.fstat` after `processes.run` and its cleanup have returned;
- read that many bytes with `os.pread` at explicit offsets;
- never use seek/read, and never touch the shared file position.

Boat no longer moves the shared position, so a writer that keeps appending always writes past the snapshot. The bytes Boat replays therefore stay intact. Short reads continue from the next offset, and hitting the end of the file early fails closed with 125. That also covers an escaped process that truncates the file.

**The tests (lines 66–73) cover both sides.**
- **Real-process test:** a still-running escaped child appends whitespace to both streams. The test checks that each replay starts with the exact saved artifact bytes, followed only by whitespace. Per your instruction, it does not require an exact length for the appended part.
- **Focused offset test:** a real temporary file has its shared position at the end of the file. The test forces small `pread` chunks and asserts that the position never moves. This catches a `seek(0); read(n)` implementation every time, whereas the real-process test only catches it when the timing happens to line up.

Both halves of the fix are tested. Trailing whitespace is safe for every caller:
- `json.loads` accepts trailing whitespace (`key_holder:668`, `batch_holder:720`, `coordinator_inventory:140/167`, `batch_status:63`);
- `ttl_continuation:88` calls `.strip()`.

## Earlier findings (M1, N1–N4): all resolved
- **M1 (Heilmeier gaps):** the plain-language objective and the key-holder impact are on lines 5–7. Risks, including disk growth in `TMPDIR` on the control VM, are on lines 42–46. Timeline and cost are on line 83.
- **N1 (inherited opt-in):** `BOAT_CAPTURE_OUTPUT` is removed from the transport environment (lines 40–41).
- **N2 (edge cases):** 125 wins over a nonzero exit, and on oversize neither captured stream is emitted (lines 31–33). The temp files are opened inside `processes.deadline` and closed after cleanup. On timeout or cancellation, partial diagnostics are discarded (lines 36–40).
- **N3 (version check):** an escaped `--version` writer is stated to end in 124 at the deadline (lines 27–29). That matches the `capture_output` path through `processes.run:104`.
- **N4 (ambiguous test phrase):** the TTL test checks stdout at `check_output` and stderr at the outer harness (lines 65–66).

## Heilmeier check
Every question is answered:
- **Objective** (5–7) and **current state** (9–13);
- **new approach** (18–29) and **impact** (5–6);
- **risks** (42–46) and **cost**, which is $0 (83);
- **timeline**, one local cycle (83), and **exams**: tests, full suite, design and diff reviews (54–78).

## Readiness check
The design names its files: the six call sites, `bin/boat-call` and the existing test file. It specifies every exit code (0, nonzero passed through, 124, 125, 143). The phases are design, implementation with the full suite, then diff review. Two small choices are left to the implementer; see N-a and N-b.

## Simplicity check
- It adds no new module, subprocess or timer, and uses only the standard library (`TemporaryFile`, `fstat`, `pread`).
- The opt-in keeps default streaming for `transfer.py`, `statement_round` and shell callers. This matches the Murphy row's explicit acceptance of the transport risk.
- Replacing the expected-hang test with a test that the caller returns is an honest deletion.
- It does not over-claim: there is no claim of descendant death, remote completion, Item 8 readiness or billing bounds.

---

## Findings

**M-a: Major (not blocking): integrity rests on one assumption, which the design should state.**
`pread` protects the replay only from Boat's own position changes. An escaped process that seeks or uses `pwrite` could still overwrite earlier bytes. The old pipe design trusted descendants the same way, since they could inject output before end-of-file, so this is not a regression. Lines 42–46 should still say that only ordinary appending writers are assumed.

**N-a: Nit: there is no saved stderr artifact.**
The design says "both saved-artifact streams" (line 67), but the fixtures contain no stderr artifact. The design should say the stderr prefix is the transport's stderr: empty in the current fake CLI, or a named saved byte string. Otherwise the implementer has to make that up.

**N-b: Nit: the write order in the test must be fixed.**
The fake CLI must write and flush the saved artifact before it starts the whitespace writer. If it doesn't, whitespace can land in front of the artifact and the byte-exact prefix check becomes flaky. One clause in the test paragraph is enough.

**N-c: Nit: how small reads are forced is unspecified.**
"Force small positional-read chunks" (line 72) does not say whether that means a chunk-size parameter on the snapshot helper or patching `os.pread`. Either works. The helper also needs to be callable from tests, and `bin/boat-call` has no `.py` extension, so it must be loaded with something like `SourceFileLoader` or `runpy`. Naming one approach would remove the guess.

**N-d: Nit: formatting and the Murphy closure.**
Line 24 is far longer than its neighbours. Line 82 should also name the test file as the "Closed by" entry for `new-isolation-outer-wall-2`, as ENGINEERING.md section 2 requires.

---

**Result: PASS.** No blocker is left. M-a and N-a to N-d are optional, but fixing N-a and N-b before implementation would keep the real-process test reliable.

## Elephant resolution

No blockers. Accepted M-a and all nits: clarify trusted append-only writers, synthetic stderr marker, flush before spawning, runpy plus patched pread, and explicit closure test path.
