I've finished reading the code. I'm writing up the review now. I couldn't run the tests: running them here needs approval, and the persona is read-only. Everything below comes from reading the code. The elephant's report of which tests fail on base matches my reading of the tests.

# Goldfish diff review: `claude/murphy-immutable-checkpoints` @ 3b0ccd3 vs `factory-simplify` fbca505

Both personas ran in Mode: REVIEW. Implementation readiness was checked against `implementation-readiness-standard.md`. The persona grades Blocker/Major/Nit map to BLOCKING/NON-BLOCKING/NIT.

## What I checked and found correct

- **Revocation order.** `revoke_replaced` is called at `factory/run_artifacts.py:118`. That is before:
  - the `scorecard.json` write (`:120`);
  - `staged.replace(out)` (`:141`);
  - `r2_upload.upload` (`:145`).

  It does not depend on `case_key`, which is computed later at `:126`. Inside `checkpoint_progress` it does nothing, because the new receipt has `local_durable: False` (`durable_checkpoint.py:27-29`). The `:40` guard returns early for it.
- **Read-back** (`r2_upload.py:53-69`).
  - It streams 1 MiB blocks into SHA-256 and never buffers the whole archive.
  - It returns `None` as soon as `seen > size` (`:62`). `finally` kills curl when it is still running (`:68`), and `Popen.__exit__` then reaps it.
  - Time is bounded by curl's `--max-time 1800`, which unblocks a stalled `read()`, by the monotonic check, and by `wait(timeout=…)`. `TimeoutExpired` is caught (`:65`).
  - It does not use `--retry`. It requires exit code 0 and exactly `size` bytes. `upload` compares against `hashlib.file_digest` of the local file (`:83-85`), which the factory already uses at `restore_bundle.py:64`.
- **No URL leak.**
  - The GET's stderr goes to `DEVNULL`. The PUT's output is captured and thrown away.
  - Both `TimeoutExpired` exceptions carry the URL in `cmd`, and both are caught and never re-raised (`:65`, `:81`).
  - Anything that does escape `seal` is recorded only as a type name (`durable_checkpoint.py:48`, `run.py:3507`).
- **Resume guard quoting** (`resume-in-place.sh:34`).
  - The host's double-quoting turns `\"` into `"`. The line has no `$`, backtick or `\\`, so the host shell expands nothing in it.
  - The `~` characters are expanded on the remote side: by `test` for the first one, and by Python's `expanduser` for the other.
  - `! test -f F || python… || { echo …; exit 1; }` behaves as intended:
    - no links file: passes;
    - links file with both GET links: passes;
    - missing GET links or invalid JSON: refused.

    `set -eu` does not fire on the non-final parts of the `||` list.
  - The guard runs before `rm -rf ~/factory` (`:35`). On refusal the ssh call fails, so `set -e` stops the script before the `parked` label is removed (`:50`).
- **Launcher** (`launch.sh:781-783`). `r2-presign` accepts `GET` (`bin/r2-presign:25`). The argument order `id put_ckpt get_ckpt put_final get_final` matches the design.
- **Backward compatibility.**
  - `test_r2_upload.py:53-55` still gets `None`.
  - `test_durable_checkpoint.py` stubs `seal` and does not assert `version`.
  - `test_account_handoff.py:245,256` extracts the `COPYFILE_DISABLE` line and the `rm -rf ~/factory && tar ` line. Neither line changed, and the guard is on its own line.
  - `test_startup_smoke.py:188` does a final seal (`checkpoint=False`), so it never reaches `target()`, and it patches `upload`.
  - `test_practice_startup.py:76` stubs `upload`.
  - Code that reads the receipt (`run.py:233`, `extension_evaluator.py:437`, `factory_dashboard.py:34`, `factory_board.py:189`) only reads keys that already exist, so the new `superseded` key and `version: 2` break nothing.
- **T1 proves the proposed `new-checkpoint-readback-1` text.**
  - It uses the real e15450 receipt (`460a8f21…`, `vm/bx_gdt298d7` key) and the real `seal`, `tar` and `age`.
  - After the seal, the receipt is revoked in `c.card` and in `work/durable-checkpoint.json` (`test_checkpoint_readback.py:308-311`).
  - The `scorecard.json` and `durable-checkpoint.json` sealed inside the new archive both carry the revoked receipt (`:313-314`). That proves the revocation came before the archive was written, and so before the PUT of those same bytes (`:316`).
  - The revocation goes through the key condition, because the saved `/home/user/sealed` path does not match. It reads only the links file, not the HTTP double, so the proof does not depend on how faithful the double is. T1c covers the local-path condition.
- **The tests would fail without the fix.** Static reading agrees with the elephant:
  - T1 and T1c fail because `revoke_replaced` is absent.
  - T2 fails because base writes `version: 1`.
  - T3 fails in 5 of 6 modes, because base returns the key after any PUT that exits 0. `put500` passes on base by design.
  - T6 fails because base has no guard line, so the unpacking at `:384` raises.
  - T1b passes on base by design.

## 1. Zoom Out (Skeptical Architect)

**NIT: the GET's time bound is enforced three times.** `r2_upload.py:57,62,64` use curl `--max-time`, a monotonic check between blocks, and a `wait` timeout. Only `--max-time` can unblock a stalled `read()`, so the other two guard only the margin. They are cheap, so keep them or drop them.

**NIT: the archive is fully read again for its hash.** `seal` has already hashed `out` (`run_artifacts.py:142`), and `checkpoint_progress` hashes it once more (`durable_checkpoint.py:40`). `upload` reads it a third time (`r2_upload.py:84`). At the 528 MB worst case this is small next to the transfers. Keeping `upload(archive, checkpoint)` self-contained is a defensible choice.

**Positive:**
- The diff matches the design's scope and adds nothing speculative.
- `revoke_replaced` carries its deletion condition (`run_artifacts.py:38`).
- Not reusing `r2_publish` is justified in the design.
- No new configuration or abstraction beyond `_links` and `target`.

## 2. Implementation Readiness

**NON-BLOCKING: the timeout path and the early kill on oversize are never run.**
- T3's `extra` mode adds 4 bytes to a small body, which all arrive in one block. Remove the `seen > size` early return and kill (`r2_upload.py:62`), and the test still passes: the final `seen == size` check (`:69`) also fails closed.
- No mode stalls the GET, so the timeout path is untested. `_readback` already takes a `timeout` parameter, so this is cheap to fix. Call `_readback` directly with `timeout=2`, using two handler modes:
  - one that sends headers and then stalls, asserting `None` within a few seconds;
  - one that streams more than `size` bytes, asserting `None` and that curl exited.
- This is non-blocking: the design's T3 list does not require these cases, and the code paths look correct.

**NIT: the "failed upload" check in `test_r2_upload.py:54-55` no longer reaches curl.** Its links have no `checkpoint_get`, so `_links` returns `None` before any PUT. The assertion still passes, but it now tests "missing GET link" rather than "failed PUT". T3 `put500` covers the failed PUT. Optionally add `checkpoint_get` there so the old test keeps its meaning.

**NIT: T6 decodes the shell escapes itself instead of letting a shell do it** (`test_checkpoint_readback.py:386`). It turns `\$` into `$` and `\"` into `"`, following the existing convention at `test_account_handoff.py:258-259`. It is correct for the current line. But a future unescaped `$` in the guard would be expanded on the host and not in the test. Having `sh` evaluate the quoted string (`sh -c 'printf %s "…"'`) would test exactly what the host sends.

**NIT: a refused resume leaves `~/factory.tgz` on the VM.** The archive is copied before the guard runs (`resume-in-place.sh:28`). That is harmless: the next resume overwrites it, and code and plaintext are untouched. But the design's "the VM … stay[s] unchanged" (design `:171`) is not strictly true.

**NIT: one T1 input is written by the test.** T1 writes `work/durable-checkpoint.json` from the saved receipt (`test_checkpoint_readback.py:305`), because the collected card does not carry that file. Its content is what `checkpoint_progress` writes (`durable_checkpoint.py:53`), so the "(and `work/durable-checkpoint.json`)" part of the row is still proven. The module docstring could name it as authored.

## Overall verdict: **PASS**

There are no blocking findings. The read-back, the revocation order, the guard quoting and backward compatibility all hold, and T1 proves the proposed `new-checkpoint-readback-1` row. Row 34 correctly stays open. Before merge, the main item to consider is the non-blocking gap: no test runs the timeout or the early kill on oversize.

---

## Elephant dispositions (recorded after the verbatim review above)

The reviewer was a fresh `claude -p` process with read-only `Read,Grep,Glob`
tools. It read the saved diff at 3b0ccd3 and the working-tree files.

**Verdict: PASS.** No blocking findings.

**NON-BLOCKING: timeout and early oversize kill untested. Fixed.**
- New T3b, `test_t3b_readback_stall_and_oversize_cut_off`, calls the real
  `_readback` with two handler modes:
  - `stall`: headers, then a 30 s sleep, with a 2 s bound;
  - `flood`: 4 MiB against `size=1024`, with a 25 s bound.
- Both must return `None` within 10 s. In `flood` the bound is 25 s, so a
  return within 10 s proves the early cut-off.
- Mutation check: with `seen > size` removed from `_readback` in a scratch
  copy, T3b `flood` fails (`25.01 not less than 10`).

**Nits**
- **The `test_r2_upload.py` "failed upload" case no longer reaches curl:
  fixed.** That case is kept, and labelled "PUT-only links". A second case
  with both GET links now exercises a failing PUT.
- **T1's `work/durable-checkpoint.json` is authored: fixed.** The test
  module docstring now names it as written from the saved receipt.
- **A refused resume leaves `~/factory.tgz`: fixed in the design wording.**
  The code is unchanged, because the leftover is harmless and the next resume
  overwrites it.
- **Triple time bound: kept.** It is cheap, and the margin checks are
  harmless.
- **Archive hashed a third time: kept.** `upload` stays self-contained, which
  the reviewer called defensible.
- **T6 decodes the escapes by hand: kept.** This follows the existing
  `test_account_handoff.py` convention. The guard line contains no `$`. A
  future guard edit that adds one would need this revisited.
