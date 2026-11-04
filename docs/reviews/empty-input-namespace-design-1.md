# Design review 1: empty-input-namespace

- **Goldfish:** a fresh local `claude -p` process with read-only tools (Read, Grep, Glob, git show/diff/log).
- **Personas:** zoom_out, design_critic and implementation_readiness, `Mode: REVIEW`.
- **Standards:** heilmeier-standard.md and implementation-readiness-standard.md.
- **Subject:** `docs/designs/empty-input-namespace.md` as first drafted on base `fbca505`.

## Review (verbatim)

**Verdict: PASS.** Nothing blocks. Four Major (non-blocking) findings should be fixed in the design before implementation.

The whole-namespace rule is correct. It cannot block a legitimate replay, because replay returns before `empty_input` (`factory/batch_holder.py:311-315` vs `:360`). It cannot block a legitimate new batch launch either: batch collection writes to `UNBUG_LAUNCH_STATE/collected` (`factory/collect.sh:9-11`), and `run.py` writes to the worker's `HOME/sealed` (`factory/run.py:28`), never to the host's `root/sealed`. The ceiling change is correct for a main checkout and for a linked worktree. Git finds `.git` in `root` itself before the ceiling matters, and resolving a gitfile is not affected by the ceiling.

Keeping the Murphy row open is correct. Tests 1–3 use real artifacts, but only case names that no manifest can produce: every manifest case is `case-<id>-<job>` (`factory/batch_money.py:52,67-68`). Test 4's file name is authored. No test proves the row.

I could not run the real-Git probe because the sandbox needed approval. Findings M2 rests on documented Git behaviour, not an observed run.

### Major (non-blocking)

**M1. Transfer partials and locks with a leading dot are outside the namespace.** `docs/designs/empty-input-namespace.md:47-49`
- `factory/transfer.py:63,68` writes `.<case>.<suffix>.transfer.lock` and `.<case>.<suffix>.<sha>.part` into the collection directory.
- The real common-checkout `sealed/` holds such files, for example `.case-20261019T061116Z-3826d5.checkpoint.tar.gz.age.transfer.lock`, with no matching archive.
- A non-batch collection that is in flight, or interrupted, leaves only these files. The proposed rule (`<case>` or `<case>.`) admits that namespace.
- **Fix:** also refuse names that start with `.<case>.`, and say this in the design. Test 1 should copy the real `.…transfer.lock` files too. Its filter currently skips every name that starts with a dot.

**M2. The design claims more for the Git fix than the fix delivers.** `docs/designs/empty-input-namespace.md:65,128-129`
- `env={**os.environ, …}` passes through any `GIT_DIR`, `GIT_WORK_TREE` or `GIT_COMMON_DIR` already set. Git then skips discovery and silently reports that repository.
- Git ignores a relative ceiling entry.
- Git resolves symlinks in the ceiling path and compares it with the real working directory. So if `root` is a symlink, `str(root.parent)` does not bound the search.
- Production `key_holder.ROOT` is already resolved (`factory/key_holder.py:28`), so the realistic risk is low. Even so, "discovery cannot silently drop the canonical store" (line 128) is not true as specified.
- **Fix:** use `GIT_CEILING_DIRECTORIES=str(root.resolve().parent)` and remove the three `GIT_*` variables above from the environment. Add a test 3 case with `GIT_DIR` set to the parent repository.

**M3. What "refuses" means for a scan error is not pinned down.** `docs/designs/empty-input-namespace.md:56-57`
- If `os.scandir` raises an `OSError` that is not caught, dispatch returns `TEMPFAIL` (`factory/batch_holder.py:990`) and retries forever. The design-review rule requires a terminal `ValueError('request_refused')`.
- **Fix:** state that both the `os.scandir()` call and the iteration over its entries are wrapped, and that any `OSError` other than `FileNotFoundError` on the directory raises `ValueError('request_refused') from None`. Add a test with a `PermissionError` or `NotADirectoryError` sealed path that asserts dispatch ends `failed`/`preflight_refused`.

**M4. Test 2's no-change check reads a shared directory other sessions write to.** `docs/designs/empty-input-namespace.md:95-96`
- In a worktree, the common checkout's `sealed/` (224 entries, including lock files) can be written by other sessions while the test runs. The names/mtimes/hash check will then fail at random.
- **Fix:** check unchanged contents only for the directories this test can touch, and snapshot only the entries that match a case name. Or document that the test must run without concurrent collection.

### Nit

- **N1.** `:85-86`: "the same isolated root with `<case>0.<suffix>` and `<case>` minus its last character" reads as if the real file is renamed, which would make it an authored artifact. Specify that the real file keeps its name and the adjacent names are passed as the `case` argument to `empty_input`.
- **N2.** `:99-103`: test 3 covers only a dangling symlink, but lines 37-38 also name a corrupt `.git` directory. Add an empty `.git` directory inside the parent repository as a second case.
- **N3.** `:105-116`: test 4 puts the ledger in place only before the first locked dispatch check. Add the variant that places it after preflight, before `dispatch_started`, so the second check (`factory/batch_holder.py:980`) is exercised with a name that is not a collection file.
- **N4.** `:120-122`: "One exception: … which stays compatible" contradicts "must pass unchanged". Reword it as a note: the test is in `tests/tools/test_qualify_batch_inputs.py:79`, and its `case0` check at lines 95-96 still holds.
- **N5.** `:54-55`: the case-name rule is derived, not stated in the code. `check_manifest` applies `[a-z0-9-]+` to the batch id and job names, and the case is `'case-'+id+'-'+name`, or a `carry_from` case built the same way. Say that.
- **N6.** `:61-63`: the Murphy row's fix direction still says "Reject exact-name artifacts" (`docs/murphy-register.md:80`). Update that cell to match the namespace rule, in the same commit.
- **N7.** Heilmeier: there is no timeline. Add one line, for example "one implementation/review cycle".

## Author disposition

The verdict is PASS, with no blocking finding. Each Major and nit was handled in the design before implementation, as follows.

### Majors

- **M1 (fixed):** the namespace now also covers `.<case>.`, the prefix used by transfer locks and partials. Test 1 includes the 18 real tracked `.transfer.lock` files.
- **M2 (fixed):**
  - The ceiling is now `root.resolve().parent`.
  - `GIT_DIR`, `GIT_WORK_TREE` and `GIT_COMMON_DIR` are dropped from the inherited environment.
  - Test 3 adds an inherited-`GIT_DIR` case and a positive gitfile case.
  - The claim on what tests 1–3 prove is narrowed to match.
- **M3 (fixed):** the design now states the error path:
  - the `os.scandir` call and its iteration are both wrapped;
  - any non-ENOENT `OSError` becomes `ValueError('request_refused')`;
  - so dispatch ends terminally, not as `TEMPFAIL`.

  Test 4 adds a `NotADirectoryError` variant to prove it.
- **M4 (fixed):** test 2 compares mtimes and hashes only for the real case entries it enumerated, not for the shared directory as a whole.

### Nits

- **Fixed:** N1 (the real file keeps its name; neighbours are passed as `case`), N2 (an empty `.git` directory variant), N3 (a second-check variant), N4 (reworded), N5 (the derivation is stated) and N7 (a timeline was added).
- **Not applied: N6 (edit the register's fix-direction cell).**
  - The row stays open.
  - `docs/murphy-register.md` is changed by the separately owned practice4 branch, and this package was told not to touch files that owned branches change.
  - "Exact-name" still describes the rule, because every match is exact on the `<case>` component.
  - This was a nit, so no second goldfish was needed. The design records it for the integrator.
