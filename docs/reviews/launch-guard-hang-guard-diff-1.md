# Diff review: Replace launch guard wall limits with a generous hang guard (`dc8adb5`)

Reviewer: fresh goldfish, OpenCode `openrouter/~deepseek/deepseek-pro-latest`, read-only.
**Mode:** REVIEW (change skipped the design under the ≤20-line, obvious-cause exception → reviewed against the commit message).

## Verdict: PASS

## 1. Root cause — the 60 s limit was a harness safety net, not a production deadline

Confirmed. The stall run's real-time bounds break down as follows:

- **The 60 s `proc.communicate(timeout=60)` (old line ~474) wrapped the *entire* synthetic launcher run** — ~30 sequential fake `boat exec` calls, each spawning several interpreters, plus the fake's own `FAKE` script. That is a test-harness `communicate` guard, not a deadline any production code depends on.
- **No individual step in the stall path waits on a real wall deadline.** Each `boat exec "$id" --detach …` (`factory/launch.sh:774`, `bin/exam-launch:116`) runs through `bin/boat-call` → `processes.run` → `processes.deadline` (`bin/boat-call:19,30`, `bin/processes.py:19`). In the test, `BOAT_COMMAND_TIMEOUT_SECONDS=2` is set (`test-launch-guards.py:442`), but the injected seam (`tests/bench/launch_guard_clock.py:13-27`) replaces `processes.time.monotonic` with a frozen clock that **only advances when a transport event is written** (the fake's `advance()` at `FAKE` lines 35-41). So `processes.deadline`'s 2 s, and `processes.envelope`'s 120 s fallback (`processes.py:43`), never elapse in wall time — the stall step's monotonic stays pinned until the fake advances it.
- **The other production bounds are likewise event-driven or far larger than anything the test exercises**: `stall_seconds` (from `BOAT_STALL_MINUTES`, default 45 min → `guard_init` in `boat-launch-guards.sh:21-30`), `BOAT_UNREACHABLE_SECONDS` (default 600), `retire_at`/TTL margin, and the per-step `BOAT_NEW/PIN/IMAGE/RESTORE_TIMEOUT` overrides (all ≥300 s). None of these is what the 60 s cap protected.
- Therefore the growth under load is real wall time across all fake calls/scrambled interpreters evenly, with no production deadline to "miss". A slow control VM legitimately needs minutes for this synthetic workload. The commit message's claim ("the 60 s communicate limit was a harness safety net that a loaded host or the full suite could exceed") is accurate.

One caveat worth stating for the record: **`guard_delete_receipt` is *not* under the seam.** It is a plain-Python heredoc (`boat-launch-guards.sh:101-169`) using stdlib `time.monotonic()` directly, and its `subprocess.run(..., timeout=remaining+5)` is a real wall-clock bound. That is the one genuine real-time deadline in the whole file, and it is the one the change deliberately keeps short (see Q2).

## 2. Replacement correctness — assertions hold, no mode hangs or passes vacuously

- **900 s (`HANG_GUARD_SECONDS`)** now guards both the launcher `communicate` (line 481) and the deletion-receipt `subprocess.run` (line 409). The stall run measures ~39 s alone at load ~220 and ~60 s at load 70–97; 900 s is roughly 15× headroom and, per the commit's own framing, a "should never fire" hang detector, not a deadline. Correct class of change.
- **`BOAT_DELETION_TIMEOUT_SECONDS=3` now set only for `deletion-incomplete`** (line 412). Traced through every mode in the `deletion-*` loop (lines 390-431):
  - `finish` — fake returns `status:'completed'`/`stage:'completed'`/`completedAt` ISO string on the *first* `deletion status` query, so `guard_delete_receipt` saves `deletion-completion.json` and breaks immediately. `completion.exists() == (mode=='finish')` holds; `returncode == 0` holds.
  - `deletion-wrong-worker` / `-wrong-operation` / `-wrong-kind` — the fake mutates `targetId`/`id`/`kind`, so `identity()` raises `ValueError('operation identity mismatch')` on the first query. Fail-fast, independent of the timeout value.
  - `deletion-wrong-stage` — fake returns `status:'completed'` + `stage:'deleting'`, triggering `ValueError('completion stage mismatch')` in the first loop iteration.
  - `deletion-no-timestamp` — `completedAt:None` → `ValueError('missing completion timestamp')` on first iteration.
  - `deletion-unavailable` — fake `sys.exit(1)` → `query()` raises `ValueError('command failed')` on the first `delete` (or first status) call.
  - `deletion-incomplete` — the *only* mode where `status` stays `'processing'`/`stage:'deleting'`/`completedAt:None`, so the loop must actually sit until the deadline fires to prove "bounded polling + manual reconciliation" (`verification FAILED`, `returncode != 0`). This is correctly the one mode that keeps the short 3 s.

  Result: **no non-incomplete mode loops** — all terminate on the first query regardless of the 60 s default — and **no mode can hang or pass vacuously**. `deletion-incomplete` is the only designed-to-timeout mode and it retains the reachable deadline. The 60 s production default for the others only matters if a fake regression made one return `processing` forever; that would now take 60 s instead of 3 s to fail, but still fails. No added suite wall time, since all other modes complete in one query.

## 3. Remaining real-time bounds that could flake under load

There are essentially none left at the wall-clock level, which is the point of the change. Concretely:

- **`timeout=HANG_GUARD_SECONDS` (lines 409, 481)** — the only two wall-clock bounds remaining. Both 900 s; not flake risks.
- **`BOAT_DELETION_TIMEOUT_SECONDS=3` (`deletion-incomplete`)** — the sole short real-time deadline still under test. It times something *out*, not in: under load it just polls fewer times before `TimeoutError` → `verification FAILED`, so it is deterministic and unflakeable. (This is also the one spot the frozen seam does not cover, so it is genuinely wall-clock — see Q1 caveat.)
- **FAKE `advance()` spin, `while not event.with_suffix('.observed').exists(): time.sleep(.01)` (FAKE, line 41)** — an *unbounded* wait with no timeout. If the observation never arrives (e.g., a seam regression), this subprocess hangs until the 900 s `communicate`/`subprocess.run` guard kills its group. It is now bound only by 900 s rather than the old 60 s, so a real seam bug would surface as a 15-minute stall instead of a 1-minute one. This is the only construct that *loosened* meaningfully, and it is a designed-never-to-fire guard, not a deadline.
- **All other short values are event-driven, not wall-clock:** `BOAT_COMMAND_TIMEOUT_SECONDS=2`, `BOAT_POLL_SECONDS=0.1/0.4`, `BOAT_STALL_MINUTES=0.02`, `BOAT_COLLECT_RETRY_SECONDS=0`, `BOAT_UNREACHABLE_SECONDS=1` (`run()` env, lines 441-443; watchdogs at lines 689-698) resolve through the frozen `processes.time`, so host load does not affect them.

No additional bounds needed to be included with the 900 s treatment; the file already threads the truly-required short deadline (`deletion-incomplete`) separately, and everything else is frozen-clock or fail-fast.

## 4. Blockers and nits

### Blockers

None.

### Nits

1. **900 s converts a fast failure into a slow failure on a real regression.** `HANG_GUARD_SECONDS` is a designed-never-to-fire cap; if some future edit makes the launcher genuinely hang (not just slow), both the launcher test and the deletion-receipt test now sit for 15 minutes before failing, and `tests/run.py` inherits that per affected case. This is the correct trade (a flake under load is worse than a slow failure on a true regression), but it is a deliberate property, not an accident — same shape as the accepted nit in `transfer-clock-diff-1.md` (nit #1, "10 → 60 … with margin"). No action required.
2. **The inline comment slightly under-scopes the remaining real deadline.** The comment at lines 411 says "Only the never-completing operation should reach the deadline," which is accurate, but the block comment at lines 27-28 ("phases are event-driven … a loaded host may legitimately need minutes") does not mention that `BOAT_DELETION_TIMEOUT_SECONDS=3` *remains* a genuine wall-clock deadline under test, untouched by the seam. Minor; a reader who only reads the top comment could wrongly conclude the whole file is now wall-clock-free.
3. **`HANG_GUARD_SECONDS` magnitude is an unexplained magic number.** 900 is reasonable and shared cleanly across both sites, but it is not derived from anything (e.g., `n` × per-step budget). Acceptable for a hang guard; noted only because the constant sits just below the repo's own "obvious cause" bar.

## Files read

- `docs/ENGINEERING.md`
- `git show dc8adb5`
- `tests/bench/test-launch-guards.py` (full file)
- `tests/bench/launch_guard_clock.py`
- `bin/boat-call`, `bin/processes.py`, `bin/boat-launch-guards.sh`
- `factory/launch.sh`, `bin/exam-launch`
- `docs/reviews/transfer-clock-diff-1.md` (precedent)

*No test run performed — read-only review, per instruction (a loaded suite run is in progress in this checkout).*

## Implementation response

Accepted the review; no blocking findings. Retain the generous hang guard. The subsequent process cleanup change and deletion guard adjustment require a fresh combined diff review.
