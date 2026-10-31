**PASS: 0 blockers, 1 major, 7 nits.** The revision fixes B1, B2 and all six majors from round 1. The one new major (what happens when the empty-input guard refuses, or hits an I/O error, inside dispatch) needs one sentence in the design and no new review round. I wrote, ran and launched nothing, and read no secrets. The real migrated store is still absent; that is the accepted external blocker, and all four rows stay open.

## Round-1 items

| Item | Resolved? | How |
|---|---|---|
| **B1** checkpoint check | Yes | `_admit` is now taken out of `reserve` and runs the real order: `_source`, provider wait, `advance_locked`, the `sources[-2]` check, then `authorize_locked`. `reserve` and the qualifier share it, so they can't drift apart. The tests include successor acceptance and stale-sources refusal. |
| **B2** guard paths | Yes | The design lists the exact namespaces and uses `collection_files(case)` as the name set. It specifies `lstat`, says empty parents and dangling symlinks refuse, and covers job1/job10. Directory lookup is taken out of `restore_inventory` rather than copied. |
| **M1** guard placement | Yes | The guard runs after the replay branch, and replay after output is explicitly allowed. In `dispatch` it runs at both locked checks before `dispatch_started`. `_post` and `source_directory` are unchanged. |
| **M2** Murphy row | Yes | `new-batch-auth-inputs-1` is added as open. |
| **M3** read-only reads | Yes | The qualifier opens the existing lock with `O_NOFOLLOW` and a shared `flock`, as `lookup`/`source_directory` already do. Missing state gets labels: `batch_absent`, `journal_absent`, `state_unlocked`, `input_refused`. |
| **M4** test plan | Yes | Test artifacts are named; they are tracked in git and already used by `test_batch_service`. Tests are listed for the qualifier and for `--qualify`. |
| **M5** live evidence | Yes | `docs/reports/batch-auth-inputs-live-20261031.json` exists, matches the fields the design lists, and has `rows_closed: []`. |
| **M6** Heilmeier | Yes | Plain-language goal, Impact, Risks, Cost and Timeline sections are present, plus mid-term and final exams. |
| Zoom-out note | Adopted | Migrated-store checking is now `--qualify` on the existing migration tool. |
| Nits N1–N5 | All addressed | |

## Major

**M1. The guard's failure outcome is not specified (lines 29, 34–37).**
- This is a Zero-Decision gap, and the code makes the two choices behave differently:
  - In `dispatch`, a `ValueError` goes to `except Exception`. The operation is marked `failed`/`preflight_refused`, which is terminal.
  - An `OSError` goes to `except (... OSError)`, which returns `TEMPFAIL`. The operation stays pending and is retried forever.
- Line 29 says "Permission and I/O errors also refuse". A raw `PermissionError` from `lstat` would instead retry indefinitely. Neither path launches anything, so this is not a blocker.
- **Fix:** add one sentence:
  - `empty_input` treats `ENOENT` as absent.
  - Every other `OSError`, and every existing object, raises `ValueError('request_refused')`.
  - In `reserve`, that means no operation is created.
  - In `dispatch`, it means a terminal `preflight_refused`.
- The "collision after reserve, before dispatch" test then asserts the operation ends `failed`/`preflight_refused` with `dispatch_started` still false.

## Nits

- **N1. `_admit` has no return contract.** Say what it returns for a replay (the existing op, which `reserve` then repairs with `_save`) versus a new admission (the authority passed to `configuration`). Also confirm that `empty_input` runs inside `_admit`; the `root` parameter implies it does.
- **N2. `--root` is redundant.** `policy_load` already requires `policy['root'] == key_holder.ROOT`. Drop `--root`, or require it to equal that value.
- **N3. Replay results are not fully defined.** Say which report field carries the `replay` label and which exit code a pending/launched replay returns. The design currently says only "exit 0 = eligible".
- **N4. `--qualify` details.**
  - The existing `main` handler returns 2 for an invalid plan; state whether `--qualify` keeps 2 there and returns 1 otherwise.
  - Say whether the symlink refusal goes into the shared `complete`/`existing` functions, which would also tighten the real migration run, or into a qualify-only wrapper.
- **N5. Scope of the no-writes test.** Name the trees it compares: the batch home, `root/sealed` and `output_root`. Run the qualifier with `-B` so `__pycache__` doesn't count as a write.
- **N6. Test files aren't named.** They should be `tests/factory/test_batch_holder.py`, `tests/tools/test_migrate_legacy_checkpoints.py` and a new `tests/tools/test_qualify_batch_inputs.py`. `tests/factory/test_restore_inventory.py` should still pass after the lookup is moved out.
- **N7. The Murphy row is malformed.** A blank line before `new-batch-auth-inputs-1` cuts it off from the table, so it won't render as part of it. Its stream is `B2`, which is not one of the defined workstreams (A–F); line 104 also uses the undefined labels "B" and "B3".

## What holds

- One launch path, with no legacy import and no fabricated bindings.
- The guard covers exact names, so job1 does not match job10.
- Replay and collection keep working after `dispatch_started`.
- The qualifier never calls `reserve`, `dispatch` or `money.locked`, and never changes `HOLDER_ENABLED`.
- A missing migrated store or output fails rather than being skipped. VM unwrap and R2 are always reported as unverified, and `--qualify` exits 1 even when local integrity passes.
- Contract tests are explicitly kept apart from row closure.
- `new-single-path-1`, `new-batch-service-1`, `new-batch-service-2` and `new-batch-auth-inputs-1` all stay open.

**Verdict: PASS.** Implementation can start once M1's sentence is added to the design. Fix the nits inline.

## Author disposition
M1 and all nits accepted and incorporated before implementation. No blocker remains.
