**PASS.** This is the final design round (2 of 2), read-only, on worktree `t3-21bef30c` at HEAD `74bb733`. No blocker or major is left open. The four round-1 findings (B1, M1–M3) and nits 5–7 are fixed in the design. Three new nits are below; none blocks implementation.

I read the three persona files, `docs/ENGINEERING.md`, the heilmeier, implementation-readiness and zoom-out standards, the design and the round-1 review with its disposition. I checked the design against the code in `factory/batch_holder.py`, `factory/batch_service.py`, `factory/batch_money.py`, `factory/key_holder.py`, `factory/practice.py` (`active`), `tests/factory/test_batch_holder.py`, `tests/factory/test_batch_service.py`, `tests/run.py` and commit `89934c9`.

## Round-1 findings, checked against the code

**B1 (repeated archive hashing) is fixed.**
- **Successor skip:** the cheap scan skips a source whose successor `operation_id(policy, job, generation)` already exists (design lines 33–35). This is the same check `schedule_waits` makes at `batch_holder.py:486`.
- **Retirement skip:** the scan also skips a source that has a `retirements/<case>/<generation>.json` marker, including a symlinked one (line 35). That marker is the only lasting result of `retire_legacy` (`batch_service.py:301-325`).
- **One hash per attempt:** the helper runs before plan's `_snapshot`, and plan reuses the card the helper returns (lines 74–77). The only hash is `_source` → `_entry` → `_snapshot` (`batch_holder.py:137-166`).
- **Cheap refusals don't hash:** the helper checks export, deadline, incidents, the aggregate bound and overrun first (steps 1–4). The snapshot hash only happens at step 5.
- **60-second retry map catches every failure:** `MoneyWait` is a subclass of `ValueError` (`batch_money.py:15`), so the caught exception list covers money refusals.
- **Every end state is skipped later:** a planned result sets facts, a legacy retirement leaves a marker, and a consumed source has a successor. So each candidate costs one hash in total, or at most one hash per 60 seconds while it keeps being refused.

**M1 (existing wait test) is fixed.**
- With `diagnosis_policy` disabled, the new scan returns before it reads any operations, so `_snapshot.assert_not_called()` at `test_batch_holder.py:898` still holds.
- `diagnosis_enabled` is only read at `batch_service.py:337` and in the manifest check (`batch_money.py:57`). The wait and reserve path never reads it.
- Re-freezing before the wait is created matches the existing pattern (`test_batch_service.py:96`).
- Both tick tests named in the design are real tests (`test_batch_holder.py:462` and `:486`).

**M2 (midterm queue result) is fixed.**
- `HolderTests.output()` writes a known total, and `input()` sets `diagnosis_state={}`, so `retire_legacy` returns False.
- With `pending={'schema_version': 1, 'status': 'pending', 'replacement_eligible': False}` and the default `exhausted=True, work=True`, `_facts` accepts the projection. `_replacement` is False, and `_enqueue` writes exactly one row: `resume/<case>/<generation>` with reason `exhaustion` (`batch_service.py:288-290`).
- Turning `replacement_policy` off is redundant but harmless. The design labels the projection honestly as an API double.

**M3 (lock-depth test) is fixed.**
- `batch_holder` calls `money.locked` and `batch_service` calls `batch_money.locked`. Both are the same module attribute, so one `patch.object(batch_money, 'locked', …)` wraps every call.
- Checking the depth before calling the real lock turns a nested lock into an assertion failure instead of a suite hang.
- `_source`, `_entry`, `_config`, `_operations`, `load_locked` and `practice.active` take no money lock.

**Round-1 nits 5–7 are fixed.**
- **Shared `_post` prefix:** `_current_operation` takes the same arguments as `_post`, and `_post` keeps its input-source check (lines 49–52). On a collected, ACKed source that has not advanced, `row.sources[-1] == op.source_generation` and `row.authority == op.authority` both hold, because `sources` only grows in `advance_locked` (`batch_money.py:369`). So the prefix fits a planning source.
- **`root` parameter:** now in the helper signature (line 55).
- **Helper borrowing:** the design names the `locals().update` pattern from `test_batch_holder.py:855` (line 115).

**Scope is clean.** The change adds the caller and the planning metadata only. It does not drain the queue, activate anything, change admission, or touch Boat work. No Murphy row closes, which is correct. Every Heilmeier question is answered.

## New nits (optional)

1. **Merge step not written down.**
   - **Where:** lines 159–161.
   - **Evidence:** the design never says to merge `89934c9`, and that commit is not an ancestor of HEAD. HEAD's `tests/run.py` has no lock, so "without lockf" is already true.
   - **Fix:** add "merge `89934c9` into the branch before the handback full suite", so the slot-pool runner and the new `ENGINEERING.md` step 4 are what actually run.
2. **Patching the clock is global.**
   - **Where:** lines 140–143.
   - **Evidence:** `batch_holder` imports the `time` module itself, so patching `holder.time.monotonic` patches `time.monotonic` everywhere, including `key_holder`'s waits.
   - **Fix:** say to patch it only around the tick calls, or move the deadline read into a small module-level function and patch that.
3. **Local import not named.**
   - **Where:** lines 44 and 55.
   - **Evidence:** plan, in `batch_service`, calls `_planning_source` in `batch_holder`, which imports `batch_service` at the top.
   - **Fix:** say to use a function-local `from batch_holder import _planning_source`, as `_load` already does at `batch_service.py:98`.

## Checks I skipped
- I ran no tests, network calls, models or workers, made no edits, wrote no record and delegated nothing.
- I did not run the real `diagnosis` predicates on the e15450 card. The design labels its projection as an API double.
- I did not try the merge of `89934c9` for conflicts. Its diff against HEAD touches 19 files under `factory/` and `tests/factory/`.
- I did not quantify archive sizes or lock-hold time. The design bounds them by count, not by measurement.
- I did not review the imported-only path; the design leaves it out of scope.

## Elephant disposition

PASS accepted. All three optional nits accepted: merge parallel-tests before tests,
clock patch limited to tick calls, and function-local holder import in plan.
Implementation follows the reviewed scope; no row closure.

