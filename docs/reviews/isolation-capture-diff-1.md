# Diff review: `022ee5b..4c7658d` against `docs/designs/isolation-capture.md`. Verdict: **PASS**

There are no blockers. The `pread` fix for shared-file-position corruption is correct and tested from both sides, and I accept the closure of Murphy row `new-isolation-outer-wall-2`. Five nits remain, none blocking.

**Scope.** I worked read-only in worktree `t3-c3a8faa6` at HEAD `4c7658d`, and the tree is clean.
- I read both persona files (Mode: REVIEW), `implementation-readiness-standard.md`, `docs/ENGINEERING.md` and the design at `4c7658d`.
- I read the whole code diff, `bin/processes.py` (a dependency), the whole test file, the Murphy row, the report, both design reviews, and the suite log and JSON.
- I ran only two fast focused tests: the snapshot offset test and the oversize test. Both passed in 0.95 s.
- No subagents, no paid calls, no cloud workers, no edits, no push.

---

## Design conformance (implementation readiness)

| Design requirement | Diff | Status |
|---|---|---|
| Opt-in `BOAT_CAPTURE_OUTPUT=1` in the six per-call envs | `key_holder:666`, `batch_holder:719`, `coordinator_inventory:138/164`, `batch_status:62`, `ttl_continuation:89`; one keyword change each | ✔ |
| Private binary `TemporaryFile` stdout/stderr, inside `processes.deadline`, wrapping `processes.run` | `bin/boat-call:53-57` | ✔ |
| Wait for run plus cleanup exactly as before; no new subprocess or timer | `processes.run`'s `finally` (`kill_tree` plus close) runs before it returns, so `fstat` at `:58` comes after cleanup. No new process or timer. | ✔ |
| `fstat` snapshot, then `pread` at explicit offsets; never seek/read; never read to a moving EOF | `snapshot()` `:16-25` reads `pread(fd, min(64K, size-len), len(data))` and stops at the fixed `size` | ✔ |
| Short reads continue; premature EOF gives 125 | The loop resumes at `len(data)`; an empty chunk raises `OSError`, which `:65-67` turns into 125 | ✔ |
| 8 MiB per stream; oversize gives 125 with only the owner diagnostic; 125 overrides a nonzero exit | `:59-61` returns before anything is emitted, regardless of `result.returncode` | ✔ |
| Read both snapshots before emitting either | The list comprehension finishes both before `:68` | ✔ |
| 124 on timeout, 143 on SIGTERM, no drain of a failed capture | `TimeoutExpired` / `SystemExit` unwind through the `with`, so the files close and nothing is replayed | ✔ |
| Strip the opt-in from the transport env | `env.pop(...)` at `:40`; the fake CLI asserts the variable is absent | ✔ |
| Default streaming unchanged | `:71-73` unchanged | ✔ |
| No new module, manifest entry, retry or security boundary | Confirmed | ✔ |

I checked one point beyond the table. Under capture, the escaped descendant inherits only fds 0, 1 and 2: `DEVNULL` and the two anonymous files. It gets none of boat-call's outer pipes. `kill_tree`'s `ps` probe uses its own pipe with `stderr=DEVNULL`, and version discovery uses `processes.run`'s own pipes. So boat-call really is the only writer to the outer capture pipes, as the design says.

## The prior blocker: shared-position corruption

**Correct.** `os.pread` never changes the file position of the open-file description that boat-call shares with its descendants. An escaped writer that keeps appending therefore keeps writing at or after its own position, which is at least `size`. The replayed bytes `[0, size)` cannot be overwritten through boat-call's actions.

The design states its remaining trust assumption: an adversarial `pwrite`, seek or truncate by the transport is out of scope. A truncate fails closed through the premature-EOF path.

**Covered on both sides.**
- **Deterministic:** `test_snapshot_preserves_shared_offset_with_short_reads_and_growth` loads the real helper with `runpy` and patches `os.pread` to return chunks of at most 7 bytes. It appends 1 byte through the shared fd on every call. It then asserts:
  - the offset stays at or above `len(saved)` before each read;
  - the result is byte-exact;
  - `call_count > 1`;
  - the final `tell() == len(saved) + call_count`;
  - truncation raises.

  A `seek(0); read(n)` version fails this test for certain: `call_count` would be 0, and the offset would move backwards. I ran it and it passed.
- **Real processes:** in `escape-write` mode, a detached, reparented child writes `" "` to fd 1 and fd 2 every 2 ms. The artifact and diagnostic are flushed before that child is spawned, which resolves design-2 N-b. For each of the six production expressions, the test asserts:
  - an exact prefix of the saved `list.json` (or `12345`);
  - nothing but whitespace after the prefix;
  - strictly more bytes than the prefix, which proves the writer really overlapped;
  - the heartbeat still changing after the caller returns.

## Test claims against the evidence

- **The real-process regression is a regression test.** If capture regresses to inherited pipes, `invoke()`'s `subprocess.run(..., timeout=GUARD)` raises `TimeoutExpired` and the test errors instead of hanging forever. The test bodies are those six production expressions, extracted by AST and asserting opt-in plus deadline inheritance. The escape is a real separate session with ancestry delayed by the 3 s `ps` shim.
- **TTL boundary.** stdout and the exit code come through `check_output`, and stderr comes from the outer harness via the `data['stderr'] is None` fallback. This matches the design.
- **Nonzero.** `escape-failure` passes through 9 with both streams intact, through `CalledProcessError` for the `check=True` sites.
- **Oversize.** Both fds are tested. stdout is `b''`, stderr is exactly the owner diagnostic, and 125 overrides the command's exit 9.
- **Timeout and SIGTERM.** Six sites get 124 after slow owned cleanup, and SIGTERM under opt-in gives 143.
- **Log.** `shasum` of the `.log` matches the JSON's `log_sha256` (`fefb4b1f…cae4`). The focused section shows 8 tests passing, with 18 `LOCAL_TIMING` escape lines of about 3.3 s (6 sites × 3 modes), six timeout lines of about 5.1 s and SIGTERM at 3.25 s. The last line is `159 test scripts run; 0 failed.` The report's figures match. The log cannot prove which commit it ran on; I accept the JSON's base/branch record as the stated binding.

## Murphy closure: **accepted**

`new-isolation-outer-wall-2` is set to `closed` in the same commit as the fix. `Closed by` points at `tests/factory/test_isolation_outer_callers.py::…test_six_callers_return_while_escaped_descendant_holds_streams`. That test uses saved Boat artifacts, real escaped processes and all six metadata expressions. It does not over-claim: no descendant death, cancellation or deletion, matching the row's Fix column. It proves the row's failure mode, which is the caller waiting for EOF while an escaped descendant holds the stream.

## Findings

**N1: Nit (Murphy record).** `Closed by` names only the escape test. The design says the escape test and the offset test together "cover both halves". Listing `test_snapshot_preserves_shared_offset_with_short_reads_and_growth` as well would make the record complete.

**N2: Nit (behaviour worth one sentence).** The cap check uses `fstat` size after cleanup, and that size includes whatever an escaped writer appended. A chatty escaped descendant can therefore turn a small, successful query into 125. This fails closed, so it costs availability rather than correctness, and it is consistent with "if either snapshot exceeds the cap". A clause in the report would stop a later reader from treating such a 125 as real oversized metadata.

**N3: Nit (boundary).** The oversize test checks 8 MiB + 1 only. Nothing shows that exactly 8 MiB is accepted. The `>` comparison is obviously right, so this is optional.

**N4: Nit (zoom-out, tidiness).** The diagnostic hardcodes `'8 MiB'` next to `CAPTURE_LIMIT`. The capture branch also repeats the `processes.run` call instead of passing `stdout=/stderr=` into a single call. It reads fine either way, and no change is needed.

**N5: Nit (report).** `docs/reports/isolation-capture.md` points ahead to `docs/reviews/isolation-capture-diff-*.md`, which does not exist yet. Save this review there, as ENGINEERING.md requires, and add a `Reviewed-by:` trailer for design-1, design-2 and this diff review on the merge commit.

---

**Result: PASS.** There are no blockers, and the Murphy closure of `new-isolation-outer-wall-2` is accepted. N1 to N5 are optional.

## Elephant resolution

No blockers. Accepted N1: add the positional-read regression to Closed by. Accepted N2: clarify that escaped-writer bytes count toward the replay cap. N5: this file is the verbatim review record; no merge is authorized in this task. Optional N3 and N4 are left unchanged: the reviewed comparison and implementation are retained. No code or tests changed after the passing suite and review.
