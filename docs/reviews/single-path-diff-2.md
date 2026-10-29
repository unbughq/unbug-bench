# Goldfish diff review 2: single launch path slice

Reviewer: fresh Claude Opus 5.5, working in a clean-room worktree, read-only. Personas: zoom_out and implementation_readiness, with the implementation-readiness standard. Mode: REVIEW. The writer was Codex.

**Verdict: FAIL.** Both round-1 blockers are fixed. One new blocker remains.

## Round-1 blockers
- **Blocker 1 (upload timeout): fixed.**
  - `launch.sh:149-163` sizes the timeout from the archive: at least 1,200 s, or 2 s plus 1 s per 256 KiB. It covers the R2 download, the upload and the legacy stream (`launch.sh:658-669`).
  - The largest real checkpoint, 527,987,760 bytes, gets 2,017 s.
  - The timeout cannot leak into later `boat` calls.
- **Blocker 2 (casekey for every restore): fixed.**
  - `restore_casekey` (`launch.sh:144-148`) refuses a missing casekey only when `--batch-release` is set, and before any VM is created.
  - Real inventory: 43 checkpoints are restorable, 30 of them legacy checkpoints without casekeys.

## Round-1 nits
- **Fixed:** nits 3, 4, 5, 6, 7 and 8.
- **Nit 9:** partly fixed. See nit 2 below.

## Findings
1. **BLOCKING: `tests/factory/test_restore_inventory.py:21`.** The test raises `RuntimeError` when `sealed/` holds no `*.checkpoint.tar.gz.age`.
   - That ciphertext is never committed, so the suite fails in every fresh worktree, every goldfish review checkout and every CI run.
   - ENGINEERING step 4 requires the suite to be green.
   - Fix: either find the inventory through the main checkout (`git rev-parse --git-common-dir`), or call `skipTest` with a loud message, as `test_late_rehearsal.py:48` does, and keep a separate required qualification command.
2. **NIT: `docs/factory-single-path.md:77`.** Step 2 still says "Remove the plaintext restore fallback". That contradicts lines 57-59, which keep the legacy stream until stream B migrates it.
3. **NIT: `test_restore_inventory.py:34`.** The 13 real checkpoints that have a casekey but no batch digest get no assertion. They now always take the casekey path, with no host fallback.
   - All 13 currently have 2 recipients and an `r2_object`, so they are fine today.
   - Assert it, for example by counting the recipients in the header.
4. **NIT: `launch.sh:157-163`.** When `restore_ciphertext` falls back from R2 to a local upload, nothing is logged, and the "restored from R2" message is gone. Operators can't tell which path ran, or why, before a possible 2,017 s upload.
5. **NIT: `batch.py:116-119, 133-134`.** `--max-total-calls` and `--max-cost` are not in the forbidden set, and the bound from the job wins. That silently drops a lower value set in the job's own args, against run.py's rule that "lower explicit caps stay lower". Either forbid them in the job args or keep the lower value.

Security: batch plaintext stays on the worker, and the founder identity is never sent. `batch.py` is in TRUSTED_FILES, so the fingerprint covers it. No new secret goes to argv, env or committed files. Real saved cards are used as test inputs.

Suite: 132 scripts, 2 failed.
- `test_restore_failover_bundle.py` fails only because it needs a gitignored helper. Not counted against this change.
- `test_restore_inventory.py` fails because of this change (finding 1). It passes when pointed at the main checkout's real `sealed/`.

## Elephant resolution

1. **Fixed.** Inventory discovery follows `git rev-parse --git-common-dir` to the main checkout's canonical `sealed/`, with the current checkout as fallback. With no ciphertext in either location, ordinary tests print a loud skip message and use `SkipTest`. `batch.py build` first runs the same qualification with `--require-inventory`; absence is then an error and no release directory is created. The public build integration also skips when qualification data is absent. A separate empty-repository regression proves that the ordinary suite skips but an actual build command refuses. No fake inventory can authorize a batch build.
2. **Fixed.** Order-of-work step 2 now explicitly removes the fallback for batch restores only and preserves legacy streaming until stream B migration.
3. **Fixed.** Each wrapped, non-batch archive must return its actual casekey path, contain two recipient stanzas in its bounded public age header, and have a nonempty string `r2_object`. The canonical dataset includes 13 such archives; no identities or payloads are decrypted.
4. **Fixed.** Logs identify R2 download and verified completion, local ciphertext upload, or the legacy stream. Local fallback names its reason: no R2 object, signing unavailable, or download/checksum failure. Operator messages never include the signed URL. Transport tests check all three fallback reasons and R2 success.
5. **Fixed.** Effective call/cost limits are the lower of every explicit job argument and the corresponding batch-policy bound. Both `--flag value` and `--flag=value` are supported; admission and runner arguments use the same effective limits. Regressions cover lower values, attempted increases, and repeated mixed-form flags.

Work is isolated in `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-6bf980ef` on `slice/single-path`, finally rebased onto `factory-simplify` at `8c5de61`. The intervening upstream changes were documentation-only; the documentation conflict was resolved by preserving stream D's cumulative bounds and uncapped replacement chains alongside this slice's single digest and batch-only plaintext restrictions. Runtime and test bytes are unchanged from the passing full-suite run. The existing failover-bundle test needs its gitignored public `finalize-restore.py`; that one prerequisite was copied read-only into this worktree's ignored results directory and verified byte-for-byte against the main checkout. No ciphertext was copied into the worktree. These are fixes for re-review, not a passing Goldfish verdict.

Validation in the fresh worktree: `uv run --with numpy --with scipy python -B tests/run.py` — **132 scripts, 0 failures**. Local ignored log: `results/infrastructure/2026-10-29-single-path-round2/full-suite.log`. The real inventory qualification ran (43 checkpoints, 30 unwrapped legacy, 13 wrapped legacy); it did not skip. The separate empty-repository regression exercised the loud skip and strict build refusal. No real case, holder or worker was launched, and no case material was decrypted.
