# Diff review 1: empty-input-namespace

- **Goldfish:** a fresh local `claude -p` process with read-only tools (Read, Grep, Glob, git show/diff/log).
- **Personas:** zoom_out and implementation_readiness, `Mode: REVIEW`.
- **Standard:** implementation-readiness-standard.md.
- **Subject:** `git diff fbca505..e74c8d0`, reviewed against `docs/designs/empty-input-namespace.md`.

## Review (verbatim)

**Verdict: PASS.** Nothing blocks the merge. There is one Major (non-blocking) finding and five Nits.

I could not run the tests, because the sandbox needed approval for `python3 -m unittest`. Everything below comes from reading the code. The claims about what fails on the base code are reasoned from `git diff fbca505..HEAD`, not seen in a test run.

**Does the code match the design?** Yes, on every point the review asked about.
- **Error handling in `empty_input` (`factory/batch_holder.py:235-243`):**
  - Both the `scandir()` call and the iteration over its entries sit inside the `try`.
  - The `ValueError('request_refused')` raised inside the `with` block is not an `OSError`, so neither handler swallows it.
  - Any `OSError` other than `FileNotFoundError` becomes `ValueError`. In `dispatch` that lands in `except Exception` (`:1006`) and ends `failed`/`preflight_refused`, not `TEMPFAIL` (`:1001`).
- **Replay and the dispatch boundary:** unchanged. Replay returns at `:322` before `empty_input` at `:370`. Both locked checks (`:946`, `:990`) run before `dispatch_started` is set.
- **Whether the rule can block a legitimate path:** I found no case where it does.
  - Batch collection writes to `UNBUG_LAUNCH_STATE/collected` (`factory/collect.sh:9-11`), not `root/sealed`.
  - Holder publication writes to `<batch>/generations`.
  - The qualifier only reads.
  - `tests/tools/test_qualify_batch_inputs.py:79-101` still holds: its `<case>0.statement.age` neighbour does not match `<case>.`.
  - Transfer locks are never deleted (`factory/transfer.py:63`), so after any non-batch collection attempt the namespace stays occupied for good. That is the intended behaviour.
- **Git environment (`factory/batch.py:41-45`):** correct.
  - The ceiling `root.resolve().parent` still lets Git inspect `root/.git` itself.
  - A gitfile is resolved regardless of the ceiling.
  - Dropping `GIT_DIR`, `GIT_WORK_TREE` and `GIT_COMMON_DIR` covers every variable that affects `--git-common-dir`.
- **Murphy row left open:** correct. Every retained case name contains an uppercase `T`/`Z`, so no batch manifest can produce it (`factory/batch_money.py:52,67-68`). Test 4 uses an authored name and is labelled as contract-level evidence.
- **Would the tests fail on the base code?**
  - Test 1 would, on `.throwaway-key.txt` and the `.transfer.lock` files.
  - Test 3's dangling-symlink and empty-directory cases would, through `restore_inventory`, which would return the parent's archive. The inherited-`GIT_DIR` case would too.
  - Test 4's reserve and replay variants would.

### Major (non-blocking)

**M1. Test 2 can still fail at random on the shared common `sealed/`.** `tests/factory/test_empty_input_real_namespace.py:80-92`
- `real_case_files` matches `.<case>.<suffix>.<sha>.part` partials as well as other files.
- A non-batch collection running in another session grows a partial and then renames it (`factory/transfer.py:68`).
- If that happens between the "before" snapshot and the comparison at `:92`, `digest()` raises `FileNotFoundError` or the mtime/hash no longer match. The review's M4 fix narrowed the check but did not close this.
- **Fix:** build the before/after snapshot from `git ls-files -z sealed`, tracked files only, or at least exclude `*.part`. Treat an entry that disappears as a skip, not a failure.

### Nits

- **N1.** `tests/factory/test_empty_input_real_namespace.py:183-190`: the `NotADirectoryError` variant also passes on the base code, where `lstat` under a file raises an `OSError` that becomes `ValueError`. So it is not a red test. Nothing exercises an `OSError` raised during iteration either. **Fix:** say in the docstring that this is a regression guard, not a red step.
- **N2.** `tests/factory/test_empty_input_real_namespace.py:39-40,116`: the `git` helper inherits the runner's environment. A `GIT_DIR` or `GIT_CEILING_DIRECTORIES` set by a hook or CI breaks the "unbounded Git walks up" assertion. **Fix:** pass a copy of `os.environ` with every `GIT_*` variable removed.
- **N3.** `factory/batch_holder.py:242`: a sealed path that is a dangling symlink, or a directory removed during the scan, is treated as absent and admitted. This matches the old behaviour. **Fix (optional):** `lstat` the sealed path first and refuse if it exists but `scandir` then raises `FileNotFoundError`. Otherwise, state this in the docstring.
- **N4.** `docs/murphy-register.md:80`: the fix-direction cell still says "Reject exact-name artifacts", and the follow-up exists only in the design text. **Fix:** record it as a handoff item for the practice4 integrator, so the register gets updated when that branch merges.
- **N5.** `tests/factory/test_empty_input_real_namespace.py:84-86`: test 2 runs one Git subprocess for each real case, more than 100 calls. **Fix (optional):** patch `batch.sealed_directories` to return the directories it already resolved at `:75`. That call is real Git, unpatched, so the test still proves discovery once.

## Author disposition

The verdict is PASS, with no blocking finding. The reviewer could not run the tests in its sandbox. The elephant ran them: on `e74c8d0`, `test_empty_input_real_namespace.py` gave 10 tests OK. Against the base `factory/batch.py` and `factory/batch_holder.py` (`fbca505`), the same tests gave 25 failures:
- 21 real-file subtests (the throwaway key and 20 transfer locks);
- 3 Git discovery tests;
- 3 holder-wiring tests.

The `NotADirectoryError` variant passed on base, as expected.

### Major

- **M1 (fixed):**
  - Test 2's no-write check now covers only this checkout's tracked files (`git ls-files -z sealed`).
  - Enumeration excludes `*.part` partials, which other sessions' collections rename.

### Nits

- **N1 (fixed):** the `NotADirectoryError` test's docstring now says it is a regression guard, not a red step.
- **N2 (fixed):** the test's `git` helper now strips every inherited `GIT_*` variable.
- **N3 (fixed in code):**
  - `empty_input` now `lstat`s a sealed path whose scan raised `FileNotFoundError`. If the path exists as a dangling symlink, it refuses.
  - New test: `test_dangling_symlinked_sealed_directory_is_not_absence`.
  - The design is updated to match.
  - On base, `lstat` under a dangling directory symlink raised `FileNotFoundError`, so that namespace was admitted.
- **N4 (handoff):** `docs/murphy-register.md` is not edited here, because the separately owned practice4 branch changes that file. The PR body lists aligning the row's fix-direction wording as an integrator item.
- **N5 (fixed):** test 2 runs real `sealed_directories(ROOT)` once, then reuses that answer for the per-case checks.

Code changed after this review, so a fresh diff review 2 follows.
