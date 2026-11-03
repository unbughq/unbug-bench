## Code verdict: PASS (round 2 of 2, `b80929a..6bd0515`)

The round-1 Major and both Nits are fixed. I found no new code findings. Production code in `factory/` is byte-identical between `3e35280` and `6bd0515`.

### Independent check of the fixes

1. **Major (guards that `batch_tick` could swallow): fixed.** `PlanningTests.tick()` in `tests/factory/test_batch_planning.py`:
   - `reserve` and `dispatch` are now plain `patch.object` mocks with no `side_effect`. Calling them doesn't raise, so `batch_tick`'s `except Exception` handlers can't hide a call.
   - Spawn is now the recorder `lambda op, action: spawned.append(...) or op`. Its arity matches the real call site, `spawn(operation, action)` at `key_holder.py:471`, so a call can't hit a TypeError that would then be swallowed.
   - `assertEqual(spawned, [])`, `reserve.assert_not_called()` and `dispatch.assert_not_called()` all run after the `with` block, outside `batch_tick`.
   - `holder` is the same `batch_holder` module object that `batch_tick` imports. Patching the module attribute therefore catches both external calls and any internal `reserve(...)`/`dispatch(...)` call that goes through the module global.
   - All three tick users get the guard, because they all call `self.tick()`. This follows the pattern in `test_batch_holder.py:477`.
2. **Lock-depth Nit: fixed.** The test now runs `self.scan()` first, so the real path is `plan_collections → plan` under the depth counter. It asserts `len(queue) == 1`, then makes the direct `service.plan(..., published_operation=...)` call, and asserts `maximum == 1`.
3. **Journal Nit: fixed.** The money/export/successor matrix captures the `journal.json` bytes after `before = self.protected()` and checks they are unchanged after the `_snapshot`-guarded scan. This matches the sibling proof-matrix test.

### New findings
- **Nit, optional (test, `test_lock_depth_never_exceeds_one`):** the direct `service.plan` return value isn't asserted, so the test proves the lock depth but not that re-authentication returned `planned`. Fix if wanted: `self.assertEqual(service.plan(...), 'planned')`, using the function's actual success value. This doesn't block.

### Scope
Only the caller and metadata change; drain comes next. There are no activation, admission, Boat, schema or grant changes. The design-2 midterm requirements are now observably asserted: no reserve, dispatch or spawn; unchanged money, operations, config and journal bytes; and lock depth 1.

### Delivery evidence (separate from the code verdict)
- **No 185/0 claim is supported.** The full suite at `3e35280` was 185 scripts with 1 failure: `test_control_resume.py`, 5 failures. That file, `control_resume.py` and `launch.sh` are untouched.
- **The suite predates the test fix.** It ran at `3e35280`, so its 11/11 planning result is for the old test file. Nothing committed shows the 11 fixed planning tests passing at `6bd0515`. The report only says "fixed in tests only". I accept the claim as stated but have not verified it; the elephant should record the focused planning run (command, head, exit code) with the final record.
- **First controller recheck:** exit 1, 24 tests, 9 failures. It is recorded honestly. I confirmed the cause:
  - `tests/run.py:65` sets `BENCH=ROOT`.
  - `runner_supervisor.py:12` resolves `bin/` through `BENCH`, falling back to `~/unbug-bench`.
  - The recheck JSON command has no `BENCH`.
  - The report's wording ("invocation mistake… not comparable") is accurate.
- **Corrected BENCH recheck: still running, not a pass.** When I read it at 18:34Z, the `…183244Z-c07827b6` log was 6 bytes (`......`) and there was no JSON yet. It has not passed so far. Under the parent's rule, the controller failures can be accepted as unrelated only after this recheck finishes and passes. The parent owns the merged suite.
- **Report:** it correctly says the final diff review is pending and makes no load-only claim. It notes that a load-average figure alone proves nothing.

### Skipped checks
- I ran nothing: no tests, suites or rechecks, no background processes, network or model calls. I made no edits or commits, delegated nothing, and read no secrets.
- I did not re-verify the production review from round 1, beyond confirming `factory/` is unchanged since `3e35280`.
- I read the personas (`tools/egm/agents/zoom_out.md`, `implementation_readiness.md`), the readiness standard header and the relevant ENGINEERING.md sections. I did not read the zoom-out standard document.
- The worktree's only untracked file is the pending recheck log. There are no production edits.

## Elephant disposition

Code PASS accepted. All round-1 findings independently verified fixed. Optional
return-value assertion deferred; no further source edit. Focused planning run
was BENCH=<own worktree> python3 -B tests/factory/test_batch_planning.py, native
session 93434, exit 0, 11 tests in 15.156s. It ran before commit 6bd0515 against
that exact test-file content (then uncommitted at 986d788). No production change.
Parent subsequently required runner 74dc5c7 (no pass cache); merged as 5ffb0c2.
The replacement handback full suite will include the fixed tests. No new review
round is needed for the separately reviewed runner merge or evidence records.
Corrected controller recheck and uncached handback suite are still pending.

