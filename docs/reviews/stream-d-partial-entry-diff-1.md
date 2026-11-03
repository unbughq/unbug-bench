**Verdict: PASS** (diff review, round 1 of 2). There are no blocking findings, and I made no edits. The worktree was clean before and after my test run.

## What I checked

**Scope**
- 15e50cb..e70949c changes only `factory/extension_package.py` (+45/−4), `tests/factory/test_stream_d_entry.py` and docs.
- The upstream merge 502b15b..e70949c touches only `stress()` in `extension_package.py` (upstream E's O5b retirement). That path is used for extension rows, not by `entry` or `entry_prefix`.
- 502b15b..7fe3fbc has no changes under `factory`, `tests` or `bin`.
- 7dbdc58 is an ancestor of HEAD.

**`entry` in the final merged file (`factory/extension_package.py:685-731`)**
- **Pointer:** its schema, UUID4, round and case-hash checks are unchanged.
- **closed.json:** a marker that exists or is a symlink is validated exactly as before. A malformed, mismatched or symlinked marker refuses. A missing marker is allowed.
- **G3 workers:** `records.load('G3')` restores workers on the copied owner (deep-copied args/card/models). Only then does `comparison._versions(workspace(owner, r))` pin the versions.
- **`comparison.snapshot`:** its API is untouched. The `versions=` keyword already existed.
- **Missing-record normalisation:** at the missing record, `pending` must equal `[hole]` and both hashes must be null. Only then does that row change to unreached, and `validate_snapshot` runs again. With no missing record, any pending row still refuses.
- **Refusal labels:** every refusal raises `extension_snapshot_changed` or `extension_comparison_pending`. Both are in `EVIDENCE_STOPS`, so both map to `^extension_comparison_pending$`.

**`entry_prefix` (`factory/extension_package.py:655-682`)**
- **Order:** it walks `extensions.stages()` in runner order with stress first.
- **Corrupt records:** `Records.load` returns None only when the file is absent and is not a symlink. Every other problem refuses, so a corrupt record is never treated as missing.
- **Records past the frontier:** any record after a retained failure or after the missing record refuses.
- **Case-copy coverage:** each record's `support/case` tree must equal the support entries under that prefix exactly.
  - The hash formats match: `tree` and `gate_state.digest` both use sha256 over the bytes.
  - The tree must also equal the live case tree once `freshness.jsonl` is left out.
- **Freshness:** live freshness must equal the copy in retained G2, G8 and G9, and in the last retained record. When stress is the only record, it is the last record, so its freshness must match live.
- **Stress:** it must be the first retained record and `ok is True`.
- **Checkpoint labels:** at or after the missing record, `'pass'` or `'fail'` refuses; `'invalid-infra'` does not. The labels come from `checkpoint_card` when present, otherwise the live card, and are only read.
- **Staging leftovers:** `.stage-*` temp directories are never stage names, so they are ignored.

**Tests**
- **Midterm test:** `test_real_partial_prefix_never_evaluates_and_preserves_caller` runs on real G4/G5 saved executions, interrupted with `money_wait` at G5 and no closed.json.
  - It forbids `check`, `checkpoint`, `g3`, `retained_answer` and `budget_boundary`.
  - It asserts that repeated entry gives an identical snapshot, and that caller args, card, models and file bytes are unchanged.
- **Missing record vs. corrupt proof:**
  - Pass or fail labels at G4/G5 refuse, `invalid-infra` gives frontier G4, and a later record refuses.
  - A missing G3 is unreached and live workers stay 2; a corrupt G3 refuses.
- **G2 freshness top-up:** the closed capture, the G5 interruption and the G2 append-then-crash case all behave as designed, and a freshness change after the stop refuses.
- **The three formerly-held tests change exactly as design item 7 says:**
  - removing closed.json gives the same snapshot, and the new malformed, mismatched and symlink marker cases refuse;
  - the infrastructure test gives frontier 1 and asserts `invalid-infra` and `exhausted`, and the real diagnosis → propose → verify path passes;
  - the old-traversal test resets gates and gets frontier G1, then G4.
- **Existing holds still refuse:** capture-error and after-rename holds still refuse, because of the fail label or a later record.
- **Untouched assertions:** no route, attribution or retry test file is in the diff. In the entry file, only the hunks the design names changed.

**Suite record**
- The JSON gives head 502b15b2ecd2a2cd08f88e70eed57ce015d29a76. That commit's tree is 8e06c2b83f85fff25bfe4ac803c22539ff034bcf, which matches the record.
- The log's sha256 is 51f5ff86f813d618061630127848014713e568450ed663a25672f38e2a4376d4, which matches.
- The log ends with "182 test scripts run; 0 failed." followed by `exit 0`.
- In that run, the entry file passed 19 tests in 44.965s.
- The timeout scope is `after_lock_acquisition`: 7200 s on the runner's `proc.wait`, with no `-t`. Run time was 2916.3 s and queue time 5083.7 s.
- I ran `tests/factory/test_stream_d_entry.py` alone: 19 tests passed in 46.6 s.

**Murphy rows:** none closed, as the design states.

## Optional findings (not blocking)

1. **A valid closed.json combined with a missing record is admitted as unreached** (`extension_package.py:700-707`). A closed marker means the observation finished, so a missing record under it can only come from loss or tampering. Card labels catch this in practice, because a finished traversal labels every stage it reached. Refusing when `close_path` exists and `hole is not None` would be a one-line extra guard. The design permits the current behaviour.
2. **Design test 2 is only partly exercised.** It asks for the infrastructure stop at the same point as test 1 (after a real G4 pass). The infrastructure test stops at G1 instead, and it does not assert "no writer until pending_call". The label and marker logic it checks is the same either way.
3. **A non-dict `gates` value would escape the refusal mapping** (`extension_package.py:681`). If `card['gates']` were present but not a dict, `card.get('gates', {}).get` raises AttributeError, which `entry` does not map to `extension_comparison_pending`. It only matters for a malformed card.
4. **Design item 4 is only partly covered.**
   - The diff adds no explicit "changed round" refusal test; the bad pointer is covered only by `'{}'`.
   - The item 4 refusal tests don't forbid evaluator calls, unlike test 1.

## Writer disposition

PASS accepted. No blocking fixes are required. Optional findings 1–4 remain recorded as non-blocking follow-ups; no production or test changes are made after review. Handing back immediately as requested by the parent. No additional review round.

