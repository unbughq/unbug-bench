Review record: `docs/reviews/stream-d-diff-21.md`

**Verdict: PASS — no blockers, majors, or nits.**

Fresh read-only Codex goldfish DIFF re-review, Mode: REVIEW, using the zoom-out and implementation-readiness personas and standards. Read `docs/ENGINEERING.md` and reviews 18 and 20 verbatim, including their elephant responses. All previous findings were accepted; none were rejected.

Reviewed commit `a769d6741d9159091b1048003c718d7c5e365cdb`, “Refuse duplicate extension writer operations before publication,” on `t3/stream-d-implementation`.

Scope is the two-line admission guard and its regression test, assessed against the passed extension eligibility/progress design, extension state implementation boundary, and interfaces §8.

**Review-20 finding: resolved.**

In `factory/extensions.py:274–275`, new admission rejects an operation ID already present in retained history with `extension_reservation_mismatch`. The check precedes `_save_case()`, history append, and `_write()`, preventing publication of the duplicate operation that `read()` would subsequently reject.

Identical active-admission replay still returns through the earlier identity-checked path. The guard therefore preserves replay while enforcing the reader’s existing uniqueness invariant for new admissions. It introduces no new abstraction, persistence format, or runtime integration.

The regression in `tests/factory/test_stream_d_extensions.py:196` completes extension 1, supplies a fresh diagnosis, and creates an ordinary fresh lease and `builder-2` reservation using the original operation ID. It verifies:

- Admission refuses with the expected error.
- Private history bytes and public projection remain unchanged.
- No extension-2 snapshot directory exists.
- History remains readable with exactly one extension.
- `active()` remains `None`.

Review 20’s resolution of all five review-18 findings is retained; those findings were not reopened by this narrowly scoped re-review.

**Verification**

- `rtk proxy python3 -B tests/factory/test_stream_d_extensions.py` — **11 tests passed**, including existing active-replay coverage.
- Negative control: ran the new regression with the parent commit’s `admit()` substituted only in memory. It **failed as expected** with `AssertionError: BudgetError not raised`, confirming that the test detects the missing guard.
- Scoped `git diff --check` — **passed**.
- Tested source files matched the reviewed commit; HEAD remained unchanged.

The fixtures use verified saved practice bytes and the saved 5813be ledger with authored stage evidence and lease controls. These results establish offline state behavior, not live gate qualification.

No full-suite result is claimed. The corrected full suite remains pending at stable HEAD; the superseded `83ebec3` and `042f1ae` runs provide no passing result.

Diagnosis/held work, queued-input design, and `.stream-d-next` were excluded. Snapshot production, changed-gate evaluation, runner integration, and money enablement remain unwired. No Murphy row closes. No model, cloud, launch, or decryption workload ran. No worktree files or commits were changed; this review text was not written to disk.

## Elephant resolution

PASS accepted. The whole extension-state slice is covered by reviews 18, 20 and
21 and their accepted fixes. The full suite is pinned to a769d67; no result is
claimed until it finishes. No Murphy row closes and runtime wiring remains off.
