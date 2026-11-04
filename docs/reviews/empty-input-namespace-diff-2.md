# Diff review 2: empty-input-namespace

- **Goldfish:** a fresh local `claude -p` process with read-only tools (Read, Grep, Glob, git show/diff/log).
- **Personas:** zoom_out and implementation_readiness, `Mode: REVIEW`.
- **Standard:** implementation-readiness-standard.md.
- **Subject:** `git diff fbca505..3e6101c`, reviewed against the design and checked against the fixes recorded in diff-1.

## Review (verbatim)

I couldn't run any tests: running python needed approval I didn't have. Everything below comes from reading the code. The test results quoted in diff-1's disposition (10 OK on HEAD, 25 failures on base) are the author's report; I didn't reproduce them.

**Verdict: PASS**

**What holds up**
- **Error handling in `empty_input`** (`factory/batch_holder.py:235-245`):
  - The `os.scandir()` call and the iteration over its entries are both inside the `try`.
  - The `ValueError` raised inside the `with` block is not an `OSError`, so neither handler swallows it.
  - Any `OSError` other than `FileNotFoundError` becomes `ValueError`. In `dispatch` that ends terminally at `:1010`, never as `TEMPFAIL` at `:1005`.
- **Diff-1 N3 fix (dangling symlink) is correct.**
  - A dangling symlinked sealed directory refuses.
  - A missing sealed directory is still treated as absent, which `test_qualify_batch_inputs.py:81` relies on.
  - An `lstat` error other than `FileNotFoundError` refuses.
  - A sealed directory that is a valid symlink is followed and scanned.
- **Replay and the `dispatch_started` boundary are unchanged.**
  - Replay returns at `:322`, before `empty_input` at `:374`.
  - Both locked checks (`:950`, `:994`) run before `dispatch_started = True` at `:997`.
- **The wider namespace rule doesn't block a legitimate path.**
  - Batch collection writes to `UNBUG_LAUNCH_STATE/collected` (`collect.sh:9-11`), not `root/sealed`.
  - `restore_ledger` and `launch.sh` write `<case>.*` into `sealed/` only for restores, which carry a `source_generation`, or after dispatch has started.
  - The qualifier only reads, and its `<case>0` neighbour still passes.
- **Git env change is correct.**
  - `root.resolve().parent` still lets Git find `root/.git`, whether that is a gitfile or a directory.
  - Dropping `GIT_DIR`, `GIT_WORK_TREE` and `GIT_COMMON_DIR` covers every variable that changes what `--git-common-dir` reports.
- **Diff-1 M1 fix is correct.**
  - The no-write check uses `git ls-files` for this checkout's tracked files only.
  - `.part` partials are excluded.
  - Discovery runs once.
- **Leaving the Murphy row open is correct.** `ENGINEERING.md` §2 closes a row only with a real-artifact test that proves it. Retained case names contain uppercase `T`/`Z`, and `check_manifest` allows only `[a-z0-9-]`, so no manifest can produce them. `HolderWiringTests` uses an authored name and says so.

**Major (non-blocking)**

- **M1. The second-locked-check test passes even if the second check never runs.** `tests/factory/test_empty_input_real_namespace.py:193-201`
  - `observe` appends to `calls` only after `original()` returns.
  - So `len(calls) == 1` holds both when the second `empty_input` raised and when dispatch failed with a `ValueError` somewhere between the two checks.
  - Either way, `assert_terminal` passes.
  - **Fix:** append before calling `original`, assert `len(calls) == 2`, and assert that the second call raised. For example, wrap it and record the exception.

**Nits**

- **N1.** `tests/factory/test_empty_input_real_namespace.py:66-71`: test 1 copies files from the shared `sealed/` when run from the main checkout.
  - There, `ROOT/sealed` is the live collection directory.
  - `transfer.py` can replace a `*.progress.json` or `*.scorecard.*` file by rename between `copyfile` and `digest(original)`, so the hash comparison can fail at random.
  - **Fix:** read the bytes once, write them, and compare the copy with those bytes. Or limit the enumeration to `git ls-files sealed`, as test 2 now does.
- **N2.** `tests/factory/test_empty_input_real_namespace.py:207-212`: the dangling-symlink test checks only that `reserve()` raised `request_refused`. It doesn't show that `empty_input` was the source.
  - **Fix:** also call `holder.empty_input(self.h.root, self.h.directory, self.case)` directly and assert it refuses, as the `NotADirectoryError` test does at `:219`.
- **N3.** `tests/factory/test_empty_input_real_namespace.py:162-163`: the docstring says "real retained ledger bytes", but `json.dumps(ledger)` re-serializes a parsed card field. Only the name matters to the guard, so nothing is wrong functionally.
  - **Fix:** change the wording to "real ledger content (re-serialized)".
- **N4.** `tests/factory/test_empty_input_real_namespace.py:147-151`: the "valid gitfile" case points straight at the parent's `.git`. That is not a real `git worktree add` layout, which has `.git/worktrees/<name>` and a `commondir` file. Test 2 covers a real linked worktree only when it runs from one.
  - **Fix:** use `git worktree add` in the parent repository, or relabel the case.
- **N5.** `docs/designs/empty-input-namespace.md`: two line references are stale.
  - The "`OSError` handler at `factory/batch_holder.py:991`" is now at `:1005`.
  - The "second check (`:980`)" is now at `:994`.
  - **Fix:** update them, or cite the symbol instead of a line number.
- **N6.** `docs/murphy-register.md:80`: the row's fix-direction cell still says "Reject exact-name artifacts". Diff-1's disposition says the PR body carries this as an integrator item, but there is no PR body in the diff to check.
  - **Fix:** add the handoff item to the PR body before merging.

## Author disposition

The verdict is PASS, with no blocking finding. Every fix below is to tests or docs; production code is unchanged since `3e6101c`. The elephant ran `tests/factory/test_empty_input_real_namespace.py` after these fixes: 11 tests OK.

### Major

- **M1 (fixed):** the second-check test now records each `empty_input` outcome and asserts `['admitted', 'request_refused']`. It can no longer pass when dispatch fails for some other reason between the two checks.

### Nits

- **N1 (fixed):** test 1 reads each real file once, writes those bytes, and compares the copy with them. A concurrent rename can no longer break the comparison.
- **N2 (fixed):** the dangling-symlink test also calls `empty_input` directly and asserts that it refuses.
- **N3 (fixed):** the docstring now says "real ledger content (re-serialized)".
- **N4 (fixed):** the direct-gitfile case is replaced by a real `git worktree add` layout (`test_real_linked_worktree_still_reaches_the_common_checkout`).
- **N5 (fixed):** the design cites symbols instead of stale line numbers.
- **N6 (handoff):** the PR body carries the integrator item for the register's fix-direction wording.

These were test and doc changes, made in response to a passing review, so no further goldfish round was run. The full suite runs on the final head.
