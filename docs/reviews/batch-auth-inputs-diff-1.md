I'm returning **FAIL** with one blocker: yes, the `sealed_directories` fallback lets empty admission skip canonical saved evidence. The rest of the diff holds, and the fix is small.

## Blocker

**B1. A failed Git lookup makes the empty-input guard admit instead of refuse** (`factory/batch.py:34-45`, used by `factory/batch_holder.py:177-189`).
- **What happens:** when `git rev-parse --git-common-dir` fails, `sealed_directories` catches the error and returns only `root/sealed`. `empty_input` then checks just that checkout and admits. The design says the opposite at lines 29 and 109: only `ENOENT` counts as absent, and every other `OSError` refuses.
- **Proof (read-only probe on this worktree):**
  - With Git working, it returns `[/Users/bugsincode/Developer/unbug-bench/sealed, <worktree>/sealed]`.
  - With `check_output` patched to raise `FileNotFoundError` or `CalledProcessError(128)`, it returns only `[<worktree>/sealed]`.
  - 83 files exist only in the canonical directory (243 there against 160 in the worktree). Those include the `case-20261017T114415Z-11a9f1` and `case-20261017T114422Z-0f3b37` checkpoints, among others. If a manifest job reused one of those case names, `reserve`, both `dispatch` checks and the qualifier would all see "empty" and admit it. That is exactly the hazard `new-batch-auth-inputs-1` is meant to prevent.
- **When it can happen:** Git missing from the holder's inherited `PATH`; Git's "dubious ownership" exit 128 when the holder runs as another user; a moved main checkout; or a dangling `.git` file in a linked worktree.
- **Scope:** if the VM holder runs from an ordinary checkout, the common directory's parent is `root` itself, so nothing is lost there. The risk is real for linked worktrees, which is where the docstring says the canonical inventory lives.
- **Why tests miss it:** every namespace test patches out `sealed_directories` entirely, so the real lookup inside `empty_input` never runs on a failure.
- **No timeout:** `check_output` has none. In `reserve` and `dispatch` it runs while the batch lock is held, so a hung Git call stalls the batch.

**Fix:**
1. In `batch.py`, let `sealed_directories` raise instead of swallowing errors, and add a timeout:
   ```python
   def sealed_directories(root):
       directories = [root / 'sealed']
       if not os.path.lexists(root / '.git'): return directories  # Installed releases have no Git metadata.
       common = Path(subprocess.check_output([...], text=True, stderr=subprocess.DEVNULL, timeout=10).strip())
       common = (root / common).resolve() if not common.is_absolute() else common.resolve()
       return list(dict.fromkeys([common.parent / 'sealed'] + directories))

   def restore_inventory(root):
       try: directories = sealed_directories(root)
       except (subprocess.SubprocessError, OSError): directories = [root / 'sealed']  # existing tolerant behaviour
       ...
   ```
   Using `lexists` also means a dangling `.git` symlink goes through the lookup and then refuses, instead of being treated as "no Git".
2. In `empty_input`, turn a lookup failure into a refusal:
   ```python
   try: directories = sealed_directories(root)
   except (subprocess.SubprocessError, OSError): raise ValueError('request_refused') from None
   ```
   It has to become a plain `ValueError`:
   - A raw `CalledProcessError` or `OSError` reaching `dispatch` hits the `except (money.MoneyWait, …, CalledProcessError, OSError)` handler at `batch_holder.py:776`. That returns TEMPFAIL, so the operation is retried forever instead of ending terminal `preflight_refused`.
   - A raw `CalledProcessError` would crash the qualifier with a traceback, because it isn't in that tool's `except` tuple.
3. Add a test in `tests/tools/test_qualify_batch_inputs.py` without patching `sealed_directories`: give `h.root` a `.git` entry and patch `batch.subprocess.check_output` to raise `FileNotFoundError`, then `CalledProcessError(128, 'git')`, then `TimeoutExpired`. For each, assert:
   - `empty_input` raises `ValueError('request_refused')`;
   - `qualify()['eligible']` is false;
   - `reserve` creates neither `money.json` nor `reservations.json`;
   - after an earlier successful reserve, `dispatch` ends `failed`/`preflight_refused` with `dispatch_started` false.

   `tests/factory/test_restore_inventory.py` must still pass unchanged.

## Nits
- **N1.** The qualifier reports `observation='journal_present'`, a label the design doesn't list. Either add it to the design's list or use the listed labels.
- **N2.** Every lookup through `empty_input` starts a Git subprocess under the money lock. With the timeout from B1 that's acceptable; just note it.

## What holds
- **Shared admission:** `_admit` keeps the original order (name/digest, deadline, provider wait, replay, incident/concurrency, `_source`, `advance_locked`, `sources[-2]`, `authorize_locked`). `reserve` and the qualifier share it with no drift. Replay returns the authority, and `reserve` still repairs the journal.
- **Guard placement:** `empty_input` runs only for new empty input, after the replay branch. Replay after output still works.
- **Dispatch:** both locked checks run after the early return and before `dispatch_started`. Because a refusal is a plain `ValueError`, the operation ends terminal `preflight_refused`. Both cases are tested.
- **Guard coverage:** exact `collection_files` names plus both generation namespaces and the current pointer, checked with `lstat`. Dangling symlinks and empty parent directories refuse, a nearby name such as `case…0` does not collide, and a `PermissionError` refuses.
- **Qualifier:** read-only, using `O_NOFOLLOW` with a shared `flock`, never `reserve`/`dispatch`/`money.locked`, no exception text in the JSON, and `launch_ready` is always false. `MoneyWait` is a subclass of `ValueError`, so it is caught and refused cleanly.
- **`--qualify`:** mutually exclusive with `--dry-run`, returns before preflight or identities, refuses symlinked metadata, and exits 1 even when local integrity passes. The plan check still exits 2. The committed report shows 64 missing outputs with `qualified`, `vm_unwrap_verified` and `r2_verified` all false.
- **Scope is honest:** the real store is absent and reported as a failure, not an empty pass. `rows_closed: []`, all four Murphy rows stay open, and the new row is well formed in its table. Nothing claims to be migrated qualification.
- **Suite record:** taken at `1bfb11d`. `HEAD` (`256e2f7`) changes only docs, so the record is valid for the code. It still needs a rerun after the B1 fix.

**Verdict: FAIL.** Fix B1 with its regression test, rerun the full suite, then send the diff for a fresh review. Nothing else blocks.

I wrote nothing, started no workers or child agents, made no paid calls and read no keys. The only thing I ran was the in-process `sealed_directories` probe described above.

## Author disposition
B1 accepted. Git lookup is bounded and lookup failures become terminal empty-input refusals; legacy restore_inventory retains tolerant fallback. Regression coverage includes unavailable Git, failed Git, timeout and dangling Git metadata. Nits added to design. Pending full suite and fresh diff review; no blocker rejected.
