**PASS.** No blockers. B1 from `docs/reviews/batch-auth-inputs-diff-1.md` is fixed by `16f8159`. One non-blocking finding and one note for you below.

## B1 checks

- **Bounded, strict discovery:** `factory/batch.py:35-44`. `sealed_directories` treats only a missing `.git` as "no Git metadata" (installed release). Otherwise it runs `git rev-parse --git-common-dir` with `timeout=10` and lets every error propagate.
- **Legacy fallback kept separate:** `restore_inventory` alone catches `SubprocessError`/`OSError` and falls back to `root/sealed`, so it keeps its old tolerant behaviour. `TimeoutExpired` is now covered because it is a subclass of `SubprocessError`. `tests/factory/test_restore_inventory.py` passes unchanged.
- **Empty admission refuses:** `empty_input` (`factory/batch_holder.py:177-191`) turns any lookup failure into a plain `ValueError('request_refused')`. This one guard sits under all three callers: `_admit` (used by both `reserve` and the qualifier) and the two locked checks in `dispatch`. The qualifier never sees a raw `CalledProcessError` or `TimeoutExpired`.
- **Dispatch ends terminally:** a plain `ValueError` skips the TEMPFAIL handler at `:778` and reaches `except Exception`. That sets `failed`/`preflight_refused` while `dispatch_started` is still false.
- **Regression test:** `test_git_lookup_failures_refuse_every_admission_surface` runs the real `sealed_directories` with `check_output` patched to raise `FileNotFoundError`, `CalledProcessError(128)` and `TimeoutExpired`, against a dangling `.git` symlink. For each error it asserts:
  - `empty_input` refuses;
  - the qualifier reports not eligible;
  - `reserve` writes neither `money.json` nor `reservations.json`;
  - `timeout == 10`;
  - the legacy fallback still works.

  It also checks the terminal dispatch outcome for each error, using a fresh fixture each time.
- **Design and nits:** the design's "Diff-review clarification" covers the change, and nit N1 (`journal_present`) is now documented there.

## The rest of the diff against the design

- **`_admit`:** keeps the original order. Replay returns its authority and `reserve` still repairs the journal. The empty check runs only for new empty input, after the replay branch.
- **Name matching:** exact `collection_files` names, both generation namespaces and the current pointer, all checked with `lstat`. A nearby name like `job10` versus `job1` does not collide. Dangling symlinks, an empty parent directory and `PermissionError` all refuse.
- **Qualifier:** read-only, using `O_NOFOLLOW` with a shared lock, `launch_ready` always false, and no exception text in the output.
- **`--qualify`:**
  - It cannot be combined with `--dry-run`.
  - It returns before preflight or identity handling.
  - It refuses symlinked metadata.
  - It always exits 1.
- **Reports are honest:** the migration report shows 64 missing outputs with `qualified`, `vm_unwrap_verified` and `r2_verified` all false. The live report has `rows_closed: []`. All four Murphy rows stay open, and the new `new-batch-auth-inputs-1` row is well formed.
- **Suite record:** `docs/reports/batch-auth-inputs-suite-20261031T151828Z-b7422f94.json` records head `16f8159`, exit 0, 161 scripts, 0 failed. `HEAD` (`f1cc7db`) adds only that record, so it is valid for the code under review.
- **Targeted reruns (read-only):** `test_qualify_batch_inputs`, `test_restore_inventory`, `test_batch_holder` and `test_migrate_legacy_checkpoints` all pass.

## Non-blocking findings

**M1 (Major, non-blocking). Git can walk up to an enclosing repository** (`factory/batch.py:40`).
- **What happens:** the design says dangling or unreadable Git metadata must refuse. The test only proves that with `check_output` patched. Real Git behaves differently when `.git` is a dangling symlink or a corrupt directory and some parent directory is a repository: Git skips the broken `.git` and uses the parent's repository instead.
- **Probe:** a repo at `$d` with `$d/sub/.git -> absent` makes `git -C $d/sub rev-parse --git-common-dir` return `../.git` with exit 0. The lookup then succeeds against the wrong repository, so the canonical sealed directory may be missed.
- **The exact case B1 named still refuses:** a dangling gitfile in a linked worktree (`gitdir: <missing>`) makes Git exit 128.
- **Impact is low:** `root/sealed` is always checked anyway, and on the VM `/home/user` is not expected to be a repository.
- **Fix:** one line. Pass `env={**os.environ, 'GIT_CEILING_DIRECTORIES': str(root.parent)}` to `check_output`, and add one test using real Git with a dangling symlink inside a temporary parent repository.

**N1 (Nit). Git now runs under the batch lock** each time `empty_input` is called. With the 10-second bound this is acceptable.

## Note: uncommitted change in the worktree

`docs/reports/batch-auth-inputs-live-20261031.json` has an uncommitted change that is not part of this review. It adds a `final_store_recheck` block with VM and Mac stores absent, observed at 15:42:36Z. It was written about 40 seconds before I checked, and nothing in `tests/`, `tools/` or `factory/` writes that file, so it came from another session, not this review. It has not been reviewed: commit it or revert it before merging.

I modified no files, started no agents or workers, made no paid calls and read no keys. Besides the four test scripts, I only ran Git probes in temporary directories.

## Author disposition
PASS accepted; no blocking finding remains. M1 is explicitly non-blocking and deferred: the documented installed VM root is not nested in an enclosing Git repository. The limitation remains recorded here and no Murphy row is closed. N1's bounded lookup is accepted. The final_store_recheck is this implementation agent's read-only SSH recheck, not a reviewer edit; it is committed with this review. No production code changed after the reviewed 16f8159 source and its passing full-suite record.
