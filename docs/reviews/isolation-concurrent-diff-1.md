# Concurrent launcher isolation — diff review 1

Reviewer: claudeAgent / claude-opus-5-5. Mode: REVIEW.
Reviewed commit: 1637dadd02c4b243e0046decbc425a2b42b2ca90, base c32e884.
Fresh read-only zoom_out and implementation_readiness review.

**Verdict: blocked by one finding.** The fix and the evidence hold up. One record defect has to be fixed before merge, and it is a one-line change.

## Blocker

**1. The new Murphy row is not part of the register table** (`docs/murphy-register.md`, the added lines at the end of the file)
- The diff adds an empty line before the `new-isolation-concurrent-1` row.
- In Markdown a blank line ends a table. This row shows up as a loose line of pipe-separated text, not as a row of the register.
- ENGINEERING.md §2 says the register is the record of every failure and how it closed. The row that records this fault and its closing test isn't in the table, so the record is broken.
- **Fix:** delete the blank line so the row comes straight after `new-router-account2-1`.

## Checks that passed

**Root cause.** The evidence supports it.
- `shell-inheritance.json` shows that running in the background (`&`) alone makes Python start with SIGINT ignored. In the foreground it does not.
- `ignored-evidence.json`: three narrowed copies reached both `polled` and `signal-sent`. They kept calling the fake transport (118, 118 and 119 calls) and deleted nothing. So the watchdog did send the signal and the launcher ignored it.
- That matches `bin/boat-launch-guards.sh:17` (`trap 'exit 130' INT`). Under POSIX, a non-interactive shell cannot trap a signal that was already ignored when it started.
- Countercase: three foreground copies of the unmodified code passed in 354.8–356.3 s. This is consistent with no shared state between the suites.

**The regression test exercises the real failure.** At `tests/bench/test-launch-guards.py:470-484`:
- The parent sets SIGINT to ignored around `Popen` and restores it in `finally`. The child inherits the ignored signal, because `subprocess` only restores SIGPIPE, SIGXFZ and SIGXFSZ.
- The wrapper resets SIGINT to default and then execs the real `/bin/sh factory/launch.sh` or `bin/exam-launch`. Foreground runs now hit the background-job condition too.
- Without the reset this is exactly the baseline hang.
- **Still asserted:**
  - both 16384-line drains;
  - `polled` and `signal-sent`;
  - exit code `128 + sig` for SIGINT and SIGTERM (line 734);
  - collect before delete, and `deleted` for each VM;
  - the 900 s guard, which still kills the process group with SIGKILL.
- SIGTERM runs skip the ignore step (`if sig` is true for both, but resetting only INT leaves TERM unchanged), so they are unaffected.

**Production and limits unchanged.**
- `git diff c32e884..1637dad` touches only `tests/bench/test-launch-guards.py`, the Murphy register, the report and the evidence folder.
- No changes under `factory/` or `bin/`.
- `HANG_GUARD_SECONDS`, `BOAT_*` timeouts and stall minutes are all unchanged.

**Validation record.** I re-hashed every committed `.log.gz` against its JSON entry; all 22 match.
- **Three background baseline hangs:** exit 1 at 1235.49, 1235.56 and 1235.89 s. Each log shows `TimeoutExpired ... launch.sh 1 --source port ... timed out after 900 seconds`, and the logged command is the old wrapper without the reset.
- **Fixed runs:** 15/15 exit 0 across rounds 1–5, three copies per round. Each round's durations cluster tightly, which fits all three copies starting together.
- **Full suite:** "156 test scripts run; 0 failed", exit 0, source `03914ce`.

**Murphy row is justified.**
- The fault was seen in a real three-worktree run.
- The row follows the `new-<topic>-<n>` naming rule, and severity "Medium / validation hang" fits.
- The closing test uses the real launcher, so it meets ENGINEERING.md §2.

**Simplicity.** The fix is one statement in the wrapper plus a scoped ignore/restore around `Popen`. It adds no helpers or new mechanism, and the under-20-lines exception applies.

**Clear enough to act on.** The commit message and the report together say what was changed, where and why, and how to reproduce it. Nothing is left for a reader to decide.

## Optional nits
- `proof.json` doesn't record which commit the `fixed-*` worktrees were at. Only `full-suite.json` names `03914ce`. Adding the SHA would make the 15 passes provable on their own.
- The `log` and `worktree` paths in the evidence JSON point at an `/var/folders/...` directory that won't last. The committed `.gz` files plus their SHA-256 values are the durable record; the report could say so.
- The report says no production state was shared, which is true. It could add one line on scope: a launcher started in the background or under `nohup` in production would also ignore SIGINT. That is harmless today because nothing in production sends SIGINT, but it is worth knowing if a supervisor ever stops launchers with INT instead of TERM.

## Implementation response

Accepted and fixed the sole blocker: removed the blank line before
`new-isolation-concurrent-1`, so it is contiguous with the register table.
Verified the preceding line is the existing router row. No blocking finding
was rejected or remains open.

Added the full tested source SHA to every proof record, and clarified that
the committed compressed logs and hashes are the durable evidence. Added a
scope note about normal production shell signal inheritance without claiming
any production cancellation behavior changed.

Clarification of the review's SIGTERM sentence: both signal cases deliberately
inherit ignored SIGINT and reset it in the child; SIGTERM's own disposition
is unchanged. The report above is preserved verbatim.

These post-review changes are records only. The tested source remains
03914ce694db034836c46266ec46c984aee0483b. No additional delegate was started for
the one-line documentation fix, as instructed. Validation remains 15/15
concurrent copies and 156 full-suite scripts with zero failures.

