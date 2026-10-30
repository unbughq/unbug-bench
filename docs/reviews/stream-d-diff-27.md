**Verdict: FAIL** (0 blockers, 1 major, 3 nits). Both diff-25 majors are fixed and their tests are real. But narrowing one older helper's exception catch made a new problem: a model answer that should be a schema error is now treated as an infrastructure failure. I wrote nothing to the worktree; the only untracked item there is the excluded `.stream-d-next/`. I deleted my scratch copies.

---

# Review: stream-d diff 27 (diff-25 correction to diagnosis-only worker dispatch). FAIL (0 blockers, 1 major, 3 nits)

**Reviewer:** fresh read-only goldfish, `Mode: REVIEW`, no history. I read `docs/ENGINEERING.md` first, then the `zoom_out` and `implementation_readiness` personas and `zoom-out-standard.md` and `implementation-readiness-standard.md`.

**Scope:**
- **Diff:** `f010528..1bb3a93261cb401916762f659db96b07e70e47b3` on `t3/stream-d-implementation`, worktree `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`.
- **Source changed:** `factory/diagnosis.py`, `factory/diagnosis_dispatch.py`, `tests/factory/test_stream_d_dispatch.py`, plus a 12-line design addendum.
- **Cumulative range:** I checked `449005c..1bb3a93` where needed.
- **Excluded:** `.stream-d-next/`.

**Reviewed against:**
- `docs/designs/stream-d-worker-dispatch.md`, including the new "Diff-25 correction" paragraph and the audit-preservation paragraph.
- The queued-input sections of `docs/designs/stream-d.md`.
- `stream-d-diff-25.md` verbatim, including the elephant response and resolution, and `stream-d-diff-26.md` verbatim.

## What I ran

- **Focused tests:** a `git archive` copy of `1bb3a93` ran `test_stream_d_dispatch`, `test_stream_d_inputs` and `test_stream_d_held`. **73 tests passed** (Python 3.14.6, 47.9 s). This matches the expected 72 + 1.
- **Mutation probes:** 15 single-change edits, each on its own scratch copy and never in the worktree. Results are below.
- **Probe test:** one scratch-only probe test, run under Python 3.12 and 3.14 (results under M1).
- **Not run:** the full suite (the parent runs it). Nothing live, no model calls, no decryption.

## Confirmed correct

**M1 correction: where failures are classified**
- `dispatch()` now converts only `InputVerificationError` (and the existing `diagnosis_result_invalid` / `diagnosis_finding_invalid` BudgetErrors) to `diagnosis_input_invalid`.
- `verify()` wraps only reads and validation: `card_total`, the ledger read, `reviewer`, `journal`, `raw_answer`, `validate`, and the decision and finding reads.
- These now propagate to the existing `runner_error:<type>` handler:
  - `verify_selected_drivers`;
  - helper transport (`prepare` and `reset` raise `RuntimeError`/`ValueError`);
  - `retain` writes;
  - `atomic_json` on journal, decision and scorecard.
- **Mutation A** (restore the old broad catch) is killed by 9 tests: qualification, prepare, reset, raw-bytes ENOSPC, decision ENOSPC, history, input manifest, model-free publication, and the real `run.main` retry.
- **Real `run.main` subprocess:** publishes `runner_error:ValueError` for a failed qualification, then resumes to `diagnosis_pending` with the same exhaustion ID and no reservations.
- **Older helpers:**
  - `queued_inputs`, `_factory_bug_history`, `_read_factory_bug_finding` and `contract` catch `FileNotFoundError` instead of `OSError`.
  - The history initializer's `atomic_json` now runs after its validation `try`.
  - **Mutation E** (put `OSError` back in the `queued_inputs` catch) is killed by the ENOSPC manifest control.
- **Post-role integrity:** the explicit `status == 'input_invalid' or inputs_sha256 != expected → invalid(c)` check is no longer masked. **Mutation I** (delete it) is killed by 2 tests, including the new wrong-digest test.
- **Semantic stops are kept:**
  - A changed retained `raw-bytes-*`, `decision.json` or finding fails through `InputVerificationError` → `diagnosis_input_invalid`.
  - The model-free valid-row path still converts validation failure to invalid.
  - Prepare returning non-ok is now retryable. That matches the diff-25 ruling that only the post-role collect may raise input-invalid.

**M2: the six guards**
I independently re-ran the parent's single-guard deletions. All six are killed by the intended test:

| Mutation | Guard deleted | Killed by |
| --- | --- | --- |
| K | reviewer family | 3 subtests, one each for writer, stress tester and strong calibrator |
| L | decision ≠ retained raw | `test_changed_decision_cannot_disagree_with_its_valid_raw_answer` |
| M | unknown task name → `continue` | `test_unknown_task_names_refuse_cleanup` |
| N | repair-route pin | `test_schema_only_repair_gets_no_inputs_and_keeps_route`, with the stub rotated and more than one route asserted |
| O | `diagnosis_loopback` replaced by a null context in `_invoke` | the runtime driver test, which now requires 2 net inserted permits before transport |
| I | post-role digest check | see above |

**Nits N1–N4 from diff 25**
- **N1 (keep the task tree when an audit fails):**
  - `cleanup_tasks` no longer removes the tree in `finally`. **Mutation C** is killed.
  - In `invoke`, `preserve_task` skips both removals when the interruption audit fails. **Mutation B** is killed.
  - The pilot identity is still disposed in the outer `finally`.
  - Both tests then show that a later cleanup succeeds and writes the audit bytes. This matches the design addendum.
- **N2 (private qualification):** qualification is stored on the private context. **Mutation J** (move it back onto the public card) is killed.
- **N3 (OpenCode sudo environment):** the `--preserve-env` set must equal the filtered environment keys.
- **N4 (schema contract):** the test checks the declared schema's exact top-level and nested fields, outcome conditions, and null/type rules against `validate_result`.

**Scope**
- `batch_service.DIAGNOSIS_ENABLED = False` is unchanged.
- No new launcher or authority.
- `close_to_passing` still stops at `extension_comparison_pending`, and no writer path exists.
- No Murphy rows changed.
- The design addendum matches the code.

## Blockers

None.

## Majors

### M1. A model answer can now be classified as infrastructure: an over-long evidence path makes the diagnosis retry and pay again instead of going to schema repair

- **Where:** `factory/diagnosis.py` `validate_result`, the catch at line ~199. This correction narrowed it from `OSError` to `FileNotFoundError`.
- **Cause:** `validate_result` probes the filesystem with paths the model chose (`evidence[].path`):
  - `root.joinpath(...).is_symlink()`;
  - `target.is_file()`.

  On Python 3.10–3.13, pathlib's `is_symlink` and `is_file` re-raise `ENAMETOOLONG`; only Python 3.14 swallows it. The worker supports Python 3.10 and later (`worker-release.json` `python_minimum: [3, 10]`). So a path segment longer than 255 bytes now raises `OSError`, where before it was `diagnosis_result_invalid`.
- **Evidence:**
  - I called `validate_result` with `path='x'*300` under 3.11, 3.12 and 3.13: each raised `OSError [Errno 63] File name too long`. Under 3.14 it raised `BudgetError diagnosis_result_invalid`.
  - My scratch probe test (gate patched true) had the authored answer name a 300-character evidence path:
    - **Python 3.12:** `dispatch` raised `OSError`. The journal row stayed `('judgment', 'pending')`, with 1 paid call and its raw bytes retained but not referenced. On resume, that pending row would prepare and invoke the model again.
    - **Python 3.14:** the same answer correctly went `malformed/schema` → repair → `retired_diagnosis_malformed` after 4 calls.
  - **Mutation F** (restore `OSError` in this catch) survives all 73 tests. The test host runs Python 3.14, which hides the difference.
- **Why it breaks the design:** "malformed outputs, not transport retries", and the diff-25 M1 boundary in reverse. Output the model controls becomes retryable infrastructure, so the attempt never reaches schema repair or route exhaustion. ENGINEERING §3 says infrastructure is retried and never becomes a case result. Here a model result is being treated as infrastructure. The impact is enabled-path only, the same reachability that made diff-25 M1 major.
- **Required:**
  - Reject model-supplied evidence names lexically before any filesystem call, for example any component over 255 bytes or an over-long total path. Alternatively, probe with `os.path.islink` / `os.path.isfile`, which swallow `OSError` on every supported version.
  - Keep real read errors on frozen files (`read_bytes` EIO) as infrastructure.
  - Add one control that an over-long evidence path becomes `malformed`/`schema` and goes to repair. A lexical check also makes deleting the guard fail on any Python version, not only versions before 3.14.

## Nits

- **N1. Read-side non-missing I/O classification is untested.** The design addendum says permission failures do not create sticky input or history stops. Every new control injects write failures only (ENOSPC on `atomic_json`/`retain`).
  - **Mutation G** (`verify()` also catches `OSError`) survives.
  - **Mutation D** (`_factory_bug_history` catches `OSError` again) survives.
  - A `PermissionError` while reading `raw-bytes-*`, `decision.json` or `factory-bug-resumes.json` would therefore become sticky without any test failing.
  - One `PermissionError`-on-read control would pin both.
- **N2. Prepare's non-ok status is unpinned.** **Mutation H** (`raise RuntimeError('task preparation failed')` changed back to `invalid(c)`) survives. The prepare retry control raises from `helper` instead of returning `status: input_invalid` or a wrong `inputs_sha256`. Returning a non-ok prepare response in the existing control would cover it.
- **N3. Audit retain mismatch is classified two ways (found by reading; I did not probe it).**
  - In `cleanup_tasks`, an `audit()` → `retain()` mismatch on an existing `audit-bytes-<sha>` becomes `DiagnosisTaskCleanupError` (infrastructure).
  - In `admitted()` (inside `before_attempt`), the same `InputVerificationError` propagates to `dispatch` → sticky `diagnosis_input_invalid`, unless `r.opencode` re-wraps callback exceptions.
  - The design says predecessor and interruption audits "never change diagnosis state or terminal_stop". Wrapping the `admitted()` audit like the cleanup path would make the two consistent.

## Mutation summary

All mutations were made on scratch copies and checked against the 73 focused tests.

| Result | Mutations |
| --- | --- |
| Killed | A, B, C, E, I, J, K, L, M, N, O |
| Survived | **F** (M1), G and D (N1), H (N2) |

## Prior dispositions

- **Diff-25 M1:** fixed for every case diff 25 listed. The new regression is M1 above.
- **Diff-25 M2:** fixed. All six guards are independently confirmed killed.
- **Diff-25 N1–N4:** fixed as described in "Confirmed correct".
- **Diff-26:** PASS stands. Its deferred formatting nit is untouched.
- **Design-1 B1/B2 and extension M5/M6:** remain open and unqualified, as accepted. This slice is diagnosis-only and does not touch them.
- **Design-1 M1–M4, M7, N1–N4; design-2 B1; design-3 M1–M3; design-4 M1–M2; design-5 N1–N6:** remain resolved as recorded in diff 25. Design-4 M2's integrity half is now unmasked (mutation I killed).

## Validation boundary

- **Covered:** an offline reading of the code against the design, 73 focused tests passing at `1bb3a93` on Python 3.14.6, 15 scratch mutations, and one scratch probe under Python 3.11–3.14.
- **Ran for real in those tests:** the saved practice bytes and the 5813be ledger, snapshot, reserve and reconcile, file modes and `flock`, and `run.main` routing.
- **Substituted:** root, UID, sudo and transport.
- **No suite result is claimed by this review:** the parent's full-suite run (`/tmp/stream-d-dispatch-fixes-suite.log`) is not assessed here.
- **Not qualified:** real Unix isolation, the VM iptables loopback permit, a live bounded provider, and B activation.
- **Unchanged:** no Murphy row closes, and `DIAGNOSIS_ENABLED` stays `False`.

## Elephant response

M1 and N1–N3 accepted. Add a lexical evidence-path bound before filesystem access while preserving infrastructure handling for real file reads. Pin permission failures and non-ok prepare responses with retry controls. Wrap predecessor audit failure as infrastructure consistently with cleanup and interruption audits. No Murphy closure or activation change.

## Elephant resolution

M1: evidence citations now reject NUL, components over 255 encoded bytes and full
frozen paths over 1023 encoded bytes before filesystem probes. The latter is a
conservative Unix limit, independent of pathlib's version-specific behavior.
A role control proves overlong output becomes malformed/schema and gets one
repair. A separate control forbids any filesystem probe for invalid names, and
an EIO control proves valid-file read failures still propagate as infrastructure.

N1: PermissionError controls cover raw answers, decisions and held-history
reads, followed by replay with the same exhaustion ID and no second model call.
N2: non-ok prepare and wrong-copy-digest responses both retry without a sticky
stop. N3: the predecessor audit is wrapped as infrastructure. Its control fixes
the audit bytes after the first mismatch so the interruption audit succeeds;
this isolates the first callback's classification instead of masking it with
the second failure.

Focused validation: **82 dispatch/input/held tests passed**. Seven isolated
in-memory mutations target the component/total path bounds, real-read/verify/
history I/O catches, prepare response and predecessor-audit classification.
All seven were killed by their matching controls. Results are retained at
`/tmp/stream-d-diff27-guard-probes.log`; the fresh
diff reviewer and full suite are still required. No Murphy row closes.
