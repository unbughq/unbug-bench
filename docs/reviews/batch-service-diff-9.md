I reviewed `3c7e586..HEAD` (one commit, `bbe20af`) in `t3-ded79ec5` as a read-only goldfish. I edited and saved nothing, made no cloud, model or crypto calls, and wrote one throwaway sweep script to my scratchpad, outside the repo.

**Verdict: PASS.** Nothing blocking is left open. The 10 focused tests pass when I run them myself. The full suite is not confirmed: `/tmp/unbug-b-stream-status-tests.log` had only reached the `tests/bench/test-launch-guards.py` header, so it was still running.

Verbatim review (save to `docs/reviews/status-diff-1.md` if you want it on record):

---

# Status diff review 1 — goldfish (zoom_out + implementation_readiness, Mode: REVIEW)

Design: `docs/designs/status.md` (passed as status-design-6, plus the status-design-5 elephant resolution). Diff: `3c7e586..bbe20af`. Files: `bin/unbug`, `factory/batch_status.py`, `tests/factory/test_batch_status.py`, and one line in `tests/tools/test_launch_manifest.py`.

## Verdict: PASS

No blocking findings. Nits below are optional.

## Checked against the design

- **Read-only claim: met** (apart from nit 1).
  - The lock is opened with `batch_service._regular`, which is `O_RDONLY|O_NOFOLLOW`, then held with `LOCK_SH`. `batch_money.locked` is never called.
  - A missing lock raises `OSError` and the lock is not created (tested). A missing control home is not created (tested).
  - A before/after byte comparison of the whole fixture root, home included, shows no writes.
  - There is no dispatch, no decryption, no VM install and no Murphy row closure.
- **Strict shared validator: met.** The journal goes only through `batch_service._load`, after an explicit `is_file()` check. A future field such as `worker_id` on an entry makes the whole batch unreadable (tested). There is no second parser.
- **Selection: met.**
  - Jobs are the manifest roots plus the `child_job` values of recorded derivations.
  - Each job uses its unique entry. With more than one entry and no pointer, the job is unreadable (tested).
  - The pointer must be a regular non-symlink file with exactly `{generation, manifest_sha256}`, it must resolve to `case/generation`, and its manifest sha must match.
  - A job with no entry is `not collected` and fires nothing.
  - Ordering uses `sorted(jobs)`, never mtime or dict order.
- **Snapshot-pinned card: met.**
  - `manifest.json` is read through `read_file`, pinned to `entry.manifest_sha256` with `O_NOFOLLOW`.
  - The schema, case, job, batch, generation and release are checked.
  - The card bytes are pinned by the manifest's sha, and the card's `case`, `sha256 == generation` and `batch_release_sha256` must match.
  - The archive is not re-hashed. There is no flat-card fallback (tested with a copy in `sealed/`).
- **Boat: met.**
  - There is one `list --json` per run, bounded at 30 s by both the subprocess timeout and `BOAT_COMMAND_TIMEOUT_SECONDS`.
  - The inventory needs `hasMore is False` and unique ids matching the id regex. Anything else gives `boat unreadable` with no `worker gone` (tested).
  - There is one `cat ~/sealed/<case>.progress.json` per running worker confirmed present, and the case regex blocks shell injection. This matches the existing `boat-call ssh <id> <cmd>` usage in `tools/factory_board.py`.
  - The production adapter never emits `running`, so in production each run makes exactly one list call.
- **Precedence and lifecycle: met.**
  - Running, pending and failed come only from authored normalized rows.
  - A running row uses live progress. Its card supplies only spend, rounds and calls; a card with `freshness_unresolved` on a running row gives no `needs ruling` (tested).
  - A running row with no `worker_id` is flagged `unreadable`, never `worker gone`.
  - If `pending_since` is absent, `launch stuck` never fires (tested).
- **Calls: met.** Absent shows `calls —`. A non-negative int (not bool) shows `calls N`. Anything else shows `calls ?` (tested with True, -1, 1.5, "100" and None). There is no denominator and no call threshold.
- **Classification: met.**
  - Sealed means G12 pass, a falsy `failed_gate`, and a stop of null or `complete`.
  - Rejected is never flagged, including with a stop reason and 99% spend (tested).
  - The known-stop list matches the design. `provider_limit:*` shows as plain words.
  - Freshness and stress stops give `needs ruling`. Any other stop gives `unknown stop` and `check case`, and the free-form text is not printed (tested).
- **Sanitizing: met.** Errors show as fixed labels. Stage and gate names print only if `public_progress._stage` accepts them, and numbers are formatted. No stderr or source text reaches the output.
- **Thresholds:** they are in one table at the top of the script. Rules covered: 5 h stage (oldest of several running stages), 30 min pending, 30 min relaunch overdue, 80% spend and rounds, and `top up / re-login`. The wallet rule is deferred, as the design says.
- **Real cards:** classification uses unmodified saved cards; binding tests use authored snapshots, and the test docstring says so.
  - I rendered all 58 cards in `invalid-runs-public-cards.json.gz`: no crash, 52 show "nothing needs you", and every flag comes from real near-limit, ruling or unknown-stop fields.
- **Tests:** 10 run, OK (`python -B tests/factory/test_batch_status.py`).

## Nits (optional)

1. **`bin/unbug` writes bytecode.** The shebang runs `python3` without `-B`, so a real run can write `factory/__pycache__/*.pyc` into the release tree. That is cosmetic, and nothing hashes that directory, but it contradicts "writes nothing". Fix: `sys.dont_write_bytecode = True` before the import.
2. **The shared lock wait has no limit.** `fcntl.flock(lock, LOCK_SH)` blocks for as long as a writer holds `LOCK_EX`. A writer that hangs would hang `unbug status` with no output. Consider `LOCK_NB` with a short retry deadline, falling back to `Batch unreadable`.
3. **Dead code.** `row.get('card_unreadable')` (line 109) is never set by anything. Delete it.
4. **The calls test card has no cap.** `test_real_calls_above_historical_cap` picks a card with calls = 489, but that card has no `max_total_calls`. The corpus does carry caps of 977, 1159, 2000 and 5000 on other cards. Picking a card whose calls exceed its own `max_total_calls` would literally prove line 169. The risk is low, since the renderer has no call logic.
5. **Optional real-card sweep.** The old-card check uses one card. A loop over the whole fixture corpus, asserting no exception and no flags on old cards, would cheaply guard the design's "no false flags" claim.
6. **`near limit` can flag sealed cases.** The rule also fires on sealed cases. That is allowed by the literal table, but a finished case at 85% spend is noise. Consider excluding `sealed` along with `rejected`.
7. **Intermediate directories are not checked for symlinks.** `current/` and `generations/<case>/` symlinks are followed, because only the final component uses `O_NOFOLLOW`. Content stays hash-pinned from the journal, so this is harmless.

## Not verified

- The full suite. The log was still running when I checked.

I made no edits.

---

Nits 1 and 2 are the two worth a few lines before merge. The others can wait.

---

## Elephant resolution

PASS accepted; no blockers rejected. Fix optional nits1/2/3 before merge:
disable bytecode before imports in bin/unbug, take the existing shared lock
nonblocking (busy means unreadable), and remove the unused card_unreadable path.
Add direct entrypoint/no-bytecode and held-lock refusal regressions. The other
optional suggestions remain as stated: current real legacy calls exceed the
historical300 default, all current threshold behavior follows the reviewed design,
and journal-pinned metadata stays authoritative through intermediate directories.
A fresh diff review checks these small corrections. Full suite pending.

