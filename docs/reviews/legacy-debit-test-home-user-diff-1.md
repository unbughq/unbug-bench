# Diff review 1: legacy debit authored-I/O test under /home/user

Reviewer: fresh goldfish subagent (zoom_out + implementation_readiness, Mode: REVIEW).
Change skipped step 2 (small fix); reviewed against the commit message of 6d494a9.

## Review (verbatim)

**Verdict: PASS.** Nothing blocking. There are two nits. I made no edits, commits or pushes.

**Checks I ran**
- **Inside `/home/user/unbug-bench`:** the parent version of the test (2df5664) fails here with 2 errors, both authored-I/O tests. The new version passes all 7 tests. That confirms both the original bug and the fix.
- **Outside `/home/user`:** I ran it in a scratch worktree. All 7 pass with the new test, and all 7 still pass with the parent version. I have removed that worktree. `/tmp/ub-wt` in `git worktree list` was already there and is not mine.
- **Coverage of VM paths:** I listed everything `record_approved_debit` touches, including `settlement_workers` and `legacy_decision` (`factory/boat_lifecycle.py:127-150`, `:788-860`). Every synthetic path falls under one of the three roots at `tests/factory/test_boat_legacy_debit.py:84`:
  - the spend file
  - `state/` plus its `ids`, `new.N` and `monitor.sh`
  - `spend.with_suffix('.deletions')/<worker>/deletion-{request,completion}.json`, and the evidence directory's parent
- **Repo decision files:** these now go through the real filesystem for `regular`, `sha256` and `Path.resolve`. That is the intended fix, and it keeps the real hash-pinned artifacts as ENGINEERING.md section 4 asks.
- **Negative cases fail for the right reason:** I instrumented a scratch copy to print each `assertRaises(ValueError)` exception.
  - legacy: `invalid completion`
  - smoke: `invalid completion`, then `historical deletion hash mismatch`, `creation identity mismatch` and `historical envelope mismatch`

  Each one comes from the check its mutation targets, not from a path that was left unmapped. The positive `assertTrue` that follows proves the setup is otherwise valid.
- **Mapping is no weaker than before:**
  - The `Path.is_dir`, `Path.iterdir` and `regular` patches only send paths through `mapped()`. Paths outside the VM roots behave as they really are.
  - Temp-dir paths (`base.rglob`) are never under a VM root, even if TMPDIR is under `/home/user`. That case used to be at risk under the blanket mapping.
  - The test only writes through `mapped()`, so it cannot leak writes to the real filesystem.

**Nits (both existed before this commit and are not regressions)**
1. **`is_symlink` is not patched.**
   - Where: `test_boat_legacy_debit.py:110`, the `with patch.object(...)` line. It affects `factory/boat_lifecycle.py:130` (`state.is_symlink()`) and `:852` (`evidence.is_symlink() or evidence.parent.is_symlink()`).
   - Effect: these checks look at the real, unmapped VM paths, which normally don't exist, so they always return False. The symlink-rejection branches are never actually tested.
   - Failure scenario: inside a `/home/user/unbug-bench` checkout, `results/spend/` really exists (it currently holds `20261105T050730Z-6461-test.deletions`). If a real `results/spend/20261103T083635Z-242175-factory.deletions` symlink were ever present there, the test would fail spuriously, because it reads host state.
   - Possible fix: patch `Path.is_symlink` through `mapped()` as well. This is optional.
2. **The smoke `bad` completion with `id='wrong'` passes the hash check by file name, not by content.**
   - Where: the `digest` function at `test_boat_legacy_debit.py:104-106`.
   - Effect: in smoke mode it returns the decision hash for any file named `deletion-completion.json`, so this negative is caught by `completion()` rather than by the hash gate. It still fails for a valid reason, and the separate `'0'*64` case covers the hash gate.
   - Suggestion: a short comment saying this is deliberate would help. Not required.

**Zoom-out:** the change is minimal and aimed at the root cause: the mapping was keyed on a host prefix instead of the synthetic paths. It adds no new abstraction, and nothing in the repo already does this that it should have reused. The commit message matches the diff.

## Disposition

- Blocking findings: none.
- Nit 1 (unpatched `is_symlink`): not fixed. It predates this change and is out of scope for this fix.
- Nit 2 (name-based digest in smoke mode): not fixed. It predates this change, and the hash gate is covered by the separate `'0'*64` case.
- Note: `/tmp/ub-wt` was the elephant's own verification worktree, since removed.
