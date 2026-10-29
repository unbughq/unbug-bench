# Goldfish diff review 3: single launch path slice

Mode: REVIEW. Personas: zoom_out and implementation_readiness, checked against the implementation-readiness standard. Read-only.

I reviewed `8c5de61..8b1585a` (18 files, +1020/−46). `slice/single-path` is checked out in another worktree, so I reviewed a detached checkout of `8b1585a`. None of stream E's changes are in scope.

## Round-2 blocker: fixed

- **Discovery goes through the git common dir.** `batch.py:36-45` calls `git rev-parse --git-common-dir`, checks `<common>/../sealed` first and falls back to `root/sealed`. In this worktree, which has no ciphertext of its own, it found `/Users/bugsincode/Developer/unbug-bench/sealed` with 43 checkpoints.
- **A missing inventory produces a loud skip.** `test_restore_inventory.py:34-40` prints `SKIPPING: REAL RESTORE INVENTORY ABSENT…` and raises `SkipTest`. With `--require-inventory`, the same case raises `RuntimeError`. `test_batch_launch.py:130-147` proves both behaviours in an empty `git init` repo.
- **`batch.py build` refuses when the real qualification fails.** `batch.py:50-52` runs the qualification with `--require-inventory` and `check=True` before anything else, including `mkdir`. When the qualification fails, no release directory is created, and the test asserts that.

## Round-2 nits

- **Nit 2: fixed.** `factory-single-path.md:77` now removes the fallback for batch restores only and keeps the legacy stream until stream B migrates it.
- **Nit 3: fixed.** `test_restore_inventory.py:52-57` checks that each of the 13 wrapped legacy archives has 2 recipient stanzas in its public age header and a nonempty `r2_object`. It reads only the header and decrypts nothing.
- **Nit 4: fixed.** `launch.sh:157-172` logs whether the R2 download succeeded, or that it fell back to a local upload and why (no R2 object, signing unavailable, or download/checksum failure). The tests check that the signed URL never appears in operator output.
- **Nit 5: fixed.** `batch.py:146-161` takes the lower of the batch bound and every explicit job value, in both `--flag value` and `--flag=value` form. It appends the effective caps last, so run.py's last-value-wins parsing uses them. The regression tests cover lower values, attempted increases, and repeated mixed-form flags.

## Findings

1. **NIT: `factory/batch.py:38`.** `restore_inventory` calls `subprocess.check_output(['git', …])` with no error handling.
   - Outside a git checkout, the test errors with `CalledProcessError` instead of skipping loudly. That includes a `git archive` or tarball extract, and the `tests/` tree that `BATCH_SOURCE` ships inside `public-source.tar.gz`.
   - Reproduced: I extracted those four files with `git archive` and ran the test outside a repo. It ended with `FAILED (errors=1)` and `fatal: not a git repository`.
   - Fresh worktrees and CI are git checkouts, so this is not the round-2 failure.
   - Fix: catch `CalledProcessError`/`OSError` and fall back to `root/'sealed'`.
2. **NIT: `factory/batch.py:50`.** The build qualifies the executing checkout's working-tree `launch.sh` (its functions are extracted from the file on disk). The release is built from `--commit`.
   - If `--commit` is not HEAD, or the tree is dirty, the `restore_casekey`/transport functions that were qualified can differ from the ones bound in `host_files`.
   - Fix: refuse a build when `commit` differs from HEAD or the tree is dirty, or run the qualification against the archived commit's files.
3. **NIT: `tests/factory/test_restore_inventory.py:63, 69, 80`.** The required build gate depends on today's inventory, before stream B migrates it:
   - line 63 needs `legacy_without_key > 0`;
   - line 69 uses `next(…)` with no default, which raises `StopIteration` when no unwrapped archive exists;
   - line 80 needs a checkpoint of at least 500 MB.

   Once stream B wraps every legacy key, as planned, or the 528 MB checkpoint retires, `batch.py build` is blocked permanently. Record this as a Murphy row or as a stream-B hand-off item so it isn't found in production.

No blocking findings.

**Security:** The batch interface accepts no identity. Batch plaintext is decrypted only on the worker, and a missing case key refuses the launch before any VM is created. Signed URLs stay out of operator logs. `batch.py` is in `TRUSTED_FILES`. Both the public card and the archived scorecard must match the release digest at ledger import (`restore_ledger.py:104-108`). `CheckpointUsed` returns only its public message.

**Correctness spot-checks:**
- A second fresh launch of the same batch job is refused: after the first launch, the `(case, 'new')` stamp is in `consumed`.
- Reservations with an unknown outcome still count against batch concurrency.
- Rows are reconciled to complete only from the `boat-launch-guards.sh:268` completion marker.
- `bind` re-verifies the release on each launch.

**Dead code:** none found.

**Real-artifact tests:** the inventory test reads real ciphertext headers and saved cards. The batch integration test uses tracked public practice cards.

## Suite

`uv run --with numpy --with scipy python -B tests/run.py`: **132 scripts, 1 failed.**

- The only failure is `tests/tools/test_restore_failover_bundle.py`, with `FileNotFoundError: results/infrastructure/2026-10-26-opencode-failover/finalize-restore.py`. That is a missing gitignored helper script, so I did not count it against the change.
- The real inventory qualification ran and did not skip: 43 checkpoints, 30 legacy without casekeys, 13 wrapped legacy, and the largest at 527,987,760 bytes with a 2,017 s timeout.
- `test_batch_launch.py` passed 4 tests.

**PASS**

## Elephant resolution

The passing review above is preserved verbatim from the T3 task "Goldfish diff review 3: single launch path slice", terminal assistant message at position 116. It applies to `8b1585a`; the nit fixes and stream-E rebase below require the requested small re-review.

- **Nit 1:** catch Git discovery errors and fall back to the current checkout's `sealed/` directory; test source exports outside Git and a missing Git executable.
- **Nit 2:** refuse non-HEAD or dirty release inputs before qualification or release creation. Update the public release regression to prove rejection instead of accepting dirty source.
- **Nit 3:** qualify the inventory that exists without requiring an unwrapped legacy archive or a 500 MB sample. Keep conditional coverage for each available shape, and hand off post-wrapping qualification to stream B as `new-single-path-1`.

- **Rebase onto `3f7521b`:** two text conflicts. In `tests/tools/test_launch_manifest.py`, retain E's `runner_supervisor.py` and the slice's `batch.py` in the expected worker inventory. In `docs/murphy-register.md`, retain E's closed row 52 and its evidence, then append the open stream-B hand-off row.
- **E integration:** `launch.sh`, `run.py` and the artifact lifecycle merged without text conflicts. Retain E's per-worker setup isolation, runner supervisor, process-group deadlines and separate seal/wipe bounds. Adapt the batch key regression to mock `processes.run`; give child resume harnesses the checkout's `BENCH` path, as the suite runner does. Assert the public batch launcher uses E's supervisor and runtime/grace bounds.

Focused public batch, resume, manifest and E isolation tests pass. Final full-suite validation is recorded below after completion.

