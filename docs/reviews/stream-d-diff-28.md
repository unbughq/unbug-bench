**Verdict: PASS** (0 blockers, 0 majors, 1 nit). The diff-27 major and all three nits are fixed, and I found no new regression. For the diagnosis-only slice, the worker increment now meets the passed design. I made no changes in the worktree. Its only untracked item is the excluded `.stream-d-next/`, and I deleted my scratch copies.

The text below is ready to save as `docs/reviews/stream-d-diff-28.md`.

---

# Review: stream-d diff 28 (diff-27 correction to diagnosis-only worker dispatch). PASS (0 blockers, 0 majors, 1 nit)

**Reviewer:** fresh read-only goldfish, `Mode: REVIEW`, no history. I read `docs/ENGINEERING.md` first. Then I read the `zoom_out` and `implementation_readiness` personas and the standards `zoom-out-standard.md` and `implementation-readiness-standard.md`.

**Scope:**
- **Diff:** `91d1430..8f980b24d1b5667248a82de50f65786edcc527cd` on `t3/stream-d-implementation`, worktree `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`. It is one commit: "Reject malformed evidence names before filesystem probes".
- **Source changed:**
  - `factory/diagnosis.py`: 4 added lines in `validate_result`.
  - `factory/diagnosis_dispatch.py`: the predecessor-audit `try/except` in `invoke` (+5/−2).
  - Tests: 9 new tests in `tests/factory/test_stream_d_dispatch.py`.
  - Design: an 8-line "Diff-27 correction" addendum.
  - The diff-27 review record.
- **Excluded:** `.stream-d-next/`.

**Reviewed against:**
- `docs/designs/stream-d-worker-dispatch.md`, including the new addendum.
- The queued-input sections of `docs/designs/stream-d.md`.
- These records, read verbatim with their responses and resolutions: `stream-d-diff-27.md`, `stream-d-diff-25.md`, `stream-d-diff-26.md` and `stream-d-worker-dispatch-design-5.md`.

## What I ran

- **Focused tests:** I ran `test_stream_d_dispatch`, `test_stream_d_inputs` and `test_stream_d_held` on a `git archive` copy of `8f980b2`. **82 tests passed** (Python 3.14.6, 67.8 s), which matches the elephant's 82.
- **Other Python versions:**
  - The 11 tests most relevant to this correction passed on **Python 3.12.13 and 3.13.14**: the long path, invalid names, valid-file EIO, predecessor audit, the three permission-failure tests and the prepare tests.
  - The 3 evidence-name tests passed on **3.11.15**.
  - On 3.10 the test module cannot be imported. See the observation under the nit.
- **Mutations:** I made 2 independent edits, each on a scratch copy and never in the worktree.
  - **P (delete the 4-line lexical check):**
    - On 3.12, the role test `test_long_model_evidence_path_is_malformed_then_repaired` fails with an `OSError` escape. This is diff-27's failure on that version, now caught.
    - On both 3.12 and 3.14, `test_invalid_evidence_names_are_rejected_before_any_filesystem_probe` fails for all 4 subtests (300, 400, 1205 and 8 bytes).
    - So the guard is pinned on the host's own Python version, not only on versions before 3.14. **Killed.**
  - **Q (remove the predecessor-audit wrapper):** `test_predecessor_audit_mismatch_is_infrastructure_even_if_retrying_audit_succeeds` fails, with `InputVerificationError: changed retained bytes` leading to `BudgetError: diagnosis_input_invalid`. That is exactly the sticky misclassification diff-27 N3 described. **Killed.**
- **Not repeated:** the parent's other 5 recorded mutations. Their controls exist and pass, and I did not require redundant kills.
- **Not run:** the full suite (the parent is running it), and anything live.

## Confirmed correct

**M1 (diff 27): a malformed evidence name is now a schema error, not infrastructure.**
- The order of checks in `validate_result` is right:
  1. Type, non-empty and duplicate checks.
  2. Lexical `PurePosixPath` checks for absolute paths, `..` and the canonical form.
  3. The new bounds: no NUL, each component at most 255 bytes after `os.fsencode`, and `fsencode(root / name)` at most 1023 bytes.
  4. Only then the `is_symlink`, `is_file` and `read_bytes` probes.

  All of steps 1–3 raise `ValueError`, which goes to `BudgetError('diagnosis_result_invalid')`, then to malformed/schema and repair.
- **Lone surrogates:** a lone surrogate in the model's JSON makes `os.fsencode` raise `UnicodeEncodeError`. That is a `ValueError` subclass, so it is classified as schema too.
- **No other errno leaks:**
  - On 3.10–3.13, pathlib's `is_symlink` and `is_file` already ignore ENOENT, ENOTDIR, EBADF and ELOOP.
  - Every prefix is symlink-checked before `read_bytes`.
  - So after this change no other errno that the model can choose escapes as infrastructure.
- **No false rejects of real inputs:** frozen input names are short and fixed (`case/…`, `source/factory/*.py`, `source/factory/prompts/*.md`, `work/gate-cache/*.json`, `card.json`, `ledger.json`, `restore-accounting.json`). The 1023-byte total includes the worker-owned root, so valid citations stay far below both bounds.
- **Real read failures still count as infrastructure:** the catch is still `FileNotFoundError` only. EIO while reading a valid frozen file propagates (`test_valid_frozen_evidence_read_io_failure_is_infrastructure`).
- **Repair path:** the role control shows `judgment malformed/schema` → `repair valid`, with exactly 2 calls.

**N1 (diff 27): permission failures on reads are retryable.**
- The new controls inject `PermissionError` while reading `raw-bytes-*`, `decision.json` and `factory-bug-resumes.json` after a held completion.
- Each control goes through `retry_after`. That helper checks:
  - the `runner_error:PermissionError` label matches `RETRY`;
  - there is no `INVALID` stop;
  - the exhaustion ID is the same after the resume.
- Each control also asserts `len(calls) == 1`, so there is no second model call.

**N2 (diff 27): non-ok prepare responses are retryable.**
- Both a `status: input_invalid` response and a wrong `inputs_sha256` now reach `RuntimeError('task preparation failed')` and retry.
- This matches the ruling that only the post-role collect may raise `input_invalid`.

**N3 (diff 27): predecessor-audit failures are infrastructure, the same as cleanup and interruption audits.**
- In `admitted()`, the collect and audit are wrapped as `DiagnosisTaskCleanupError`.
- `model_runtime._call` runs `before_attempt()` inside the attempt and re-raises anything that is not a classified `BudgetError` or `RouterUnavailable`. So the wrapped error reaches `invoke`'s `except BaseException` interruption audit.
- **When the interruption audit succeeds:** the same tree's bytes are persisted before `remove_task`. That satisfies "persist bytes before task-tree deletion" from diff-25 N1.
- **When it also fails:** `preserve_task` keeps the tree.
- **The control isolates the classification on purpose:** it repairs the corrupt audit file after the first mismatch, so the second audit succeeds. The `DiagnosisTaskCleanupError` it observes can only have come from the predecessor callback. Mutation Q proves this.
- The wrapper also turns a helper collect transport failure into `DiagnosisTaskCleanupError`. That is still a retryable `runner_error`, so this is consistent.

**Design and scope:**
- The addendum matches the code exactly, including "even when a subsequent audit succeeds".
- `batch_service.DIAGNOSIS_ENABLED = False` is unchanged.
- No new launcher or authority was added.
- `close_to_passing` and active extensions still stop at `extension_comparison_pending`, and no writer path exists.
- No Murphy rows changed.
- **Zoom-out:** the fix is the smallest one at the shared boundary. It is one lexical guard in the single validator that every caller uses, and one wrapper that reuses the existing infrastructure exception. No new helper, flag or path was added. It is not over-built.

## Blockers

None.

## Majors

None.

## Nits

- **N1. The 1023-byte total bound is on `root / name`, not on the name alone.** The design text says "full frozen evidence path", so this agrees with the code. However, if the worker work root were ever very deep (more than about 700 bytes), valid citations would become schema errors and burn repair calls rather than fail loudly. This is unreachable with today's layout. If the layout changes, one comment or assert at the frozen-root construction would document the assumption. Optional.

**Observation, not a finding, and out of scope:** `factory/case_contract.py` imports `tomllib`, which needs Python 3.11 or later. The test harness therefore cannot import on 3.10, although `worker-release.json` declares `python_minimum: [3, 10]`. This predates the slice (`547f66b` is an ancestor of `449005c`) and does not affect this correction, which is lexical and works on any version. The release floor and that import should be reconciled separately.

## Prior dispositions

- **Diff-27 M1:** fixed and verified on 3.12, 3.13 and 3.14. Mutation P is killed on both 3.12 and 3.14.
- **Diff-27 N1:** fixed (raw answer, decision and history permission-failure controls).
- **Diff-27 N2:** fixed (`input_invalid` status and wrong-digest prepare controls).
- **Diff-27 N3:** fixed, and mutation Q is killed.
- **Diff-25 M1, M2 and N1–N4:** remain fixed as independently accepted in diff 27. This change touches none of those paths, except that it extends the M1 boundary consistently. The six guard controls are still in the passing 82.
- **Diff-26:** PASS stands. Its deferred formatting nit is untouched.
- **Design-5 N1–N6:** remain implemented as recorded in diff 25.
- **Design-1 B1/B2 and extension M5/M6:** remain accepted, open and unqualified. This slice is diagnosis-only and does not claim them.
- **Design-1 M1–M4, M7, N1–N4; design-2 B1; design-3 M1–M3; design-4 M1–M2:** remain resolved as recorded.
- **Rejected findings:** none.

## Constrained-slice readiness

The diagnosis-only worker increment (`449005c..8f980b2`) now meets the passed design within its boundary:
- It enforces the boundaries for same-owner relaunch, immutable queued input and replay, reviewer family, journal and repair, root-owned disposable copies, cleanup and retained outcomes.
- Infrastructure and model-output failures are now classified the same way on every supported Python version this harness can import.

**Merge condition:** under ENGINEERING §1, merging still needs the parent's full-suite run on this tree to pass.

## Validation boundary

- **Covered:**
  - an offline reading of the code against the design;
  - 82 focused tests passing at `8f980b2` on Python 3.14.6;
  - the targeted subset passing on 3.11, 3.12 and 3.13;
  - 2 scratch mutations, both killed.
- **Ran for real in those tests:** the saved practice bytes, the 5813be ledger, snapshot, reserve and reconcile, file modes and `flock`, and `run.main` routing.
- **Substituted:** UID, root, sudo and transport.
- **No suite result is claimed by this review:** `/tmp/stream-d-dispatch-path-fixes-suite.log` is not assessed here. The parent's `/tmp/stream-d-diff27-guard-probes.log` was not independently re-read.
- **Not qualified:**
  - real Unix isolation;
  - the VM iptables loopback permit;
  - a live bounded provider;
  - B runtime activation;
  - the extension dispatcher.
- **Unchanged:** no Murphy row closes, and `DIAGNOSIS_ENABLED` stays `False`.
- **Not done:** no launches, model calls, decryption, edits, commits or pushes.

## Elephant response

*(to be completed by the elephant)*

## Elephant resolution

*(to be completed by the elephant)*

## Elephant response to passed review

Accepted. Optional N1 is deferred because the fixed worker layout is far below the full-path bound; reconsider the assumption if that layout changes. The pre-existing tomllib/Python-floor observation is recorded for the release owner, outside this diagnosis increment. All earlier accepted extension obligations remain open. No Murphy row closes and no runtime activation or live qualification is claimed.

## Elephant full-suite result and rerun

The full suite on the `8f980b2` implementation ran 151 scripts, with one failed:
`tests/factory/test_transfer.py`. In `test_already_verified_result_needs_no_chunks`,
the offline fake transport's metadata subprocess exceeded the test's two-second
`BOAT_COMMAND_TIMEOUT_SECONDS` and exited 124. Launch guards passed; this was not
the documented launch-guard flake. The transfer test, `factory/transfer.py` and
`bin/boat-call` are unchanged from integration baseline `9701f56`.

Log: `/tmp/stream-d-dispatch-path-fixes-suite.log`, SHA-256
`b6fd94a2e69e93479ead0b394dac9ef278fb9058065f5c8b607eabe2fd05094b`.

An isolated rerun with
`uv run --with numpy --with scipy python -B tests/factory/test_transfer.py`
passed all five tests without source changes. Its intentional timeout control
still exercised the timeout path. Log: `/tmp/stream-d-transfer-isolated.log`,
SHA-256 `9ef90cd0ff6aed391410cfe99e2db38f57a56b281ee848907e61c7a2c8188282`.

This isolated pass does not replace the required full-suite pass. A fresh full
run was started at `7027360` (documentation-only commits after `8f980b2`) with
the prescribed command, logging to
`/tmp/stream-d-dispatch-path-fixes-suite-2.log`; its result is pending.
