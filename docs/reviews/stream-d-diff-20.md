Review record: `docs/reviews/stream-d-diff-20.md`

**Verdict: FAIL — one blocking Major finding.**

Fresh read-only goldfish DIFF review, Mode: REVIEW, using the zoom-out and implementation-readiness personas and standards. Read `docs/ENGINEERING.md` and `docs/reviews/stream-d-diff-18.md` verbatim, including its elephant resolution. All five previous findings were accepted; none were rejected.

Reviewed cumulative extension-state changes from `872151c` through `042f1ae6d520821410583607919a2c2dbdeac12e`, “Bind extension admissions to diagnosis progress and durable rounds,” on `t3/stream-d-implementation`.

Scope: `factory/extensions.py`, `tests/factory/test_stream_d_extensions.py`, `tests/tools/test_launch_manifest.py`, and “Extension state implementation boundary,” against the passed extension eligibility/progress design and interfaces §8.

During review, HEAD advanced to `855507b5e9ea1b02a043cbecfe9be8846f06aff1`. That commit adds only two unrelated review records; all reviewed files remain identical. Tests were pinned to `042f1ae`.

**Major — Admission can durably publish a duplicate writer operation that its reader rejects.**

Affected: `factory/extensions.py:263–285`, particularly reservation validation and history publication; reader uniqueness enforcement at lines 101–112.

`read()` requires unique `writer_operation_id` values across extensions. New admission does not enforce that invariant before appending history. A fresh pending reservation with the correct next `builder-<round>` call name can reuse a completed extension’s operation ID. `admit()` accepts it and publishes extension 2, after which `read()` and `active()` raise `extension_history_invalid`.

Reproduced from the committed fixture using ordinary helper calls, without modifying retained history or ledger records:

1. Admit extension 1 and complete it with progress.
2. Record a new completed diagnosis and propose extension 2.
3. Create a fresh lease and call `budget.reserve_invocation()` with `call_name='builder-2'` and extension 1’s `writer_operation_id`.
4. Call `extensions.admit()` with that reservation and operation ID.
5. Admission succeeds. Retained history contains IDs `[1, 2]`, rounds `[1, 2]`, two distinct diagnosis IDs, and only one writer operation ID.
6. `extensions.active()` refuses with `extension_history_invalid`, including after setting `builder_rounds` to 2.

The reader correctly detects the inconsistency, but only after admission has committed it. This leaves the case unable to continue or replay through these helpers.

Reject an operation ID already owned by a completed extension before saving snapshots or publishing new history. Preserve identical active-admission replay. Add a regression asserting refusal leaves history, public projection, and extension count unchanged.

**Previous findings**

All five findings from review 18 are addressed within this slice:

- **B1:** Pending entry stages refuse before proposal or reservation.
- **B2:** Further admission requires current case, ordered stages, frontier, and evidence to match the selected retained outcome; generation alone may differ.
- **B3:** Private history retains a unique authorizing exhaustion ID; another extension requires another diagnosis.
- **Ma1:** Retained rounds must be consecutive, match operation/call-name reservations, and agree with the allowed restored counter.
- **Ma2:** Verified durable admission/completion recovers only its immediately preceding public projection. Unrelated mismatches refuse.

**Verification**

Offline tests ran from clean archives of the pinned commit:

- `tests/factory/test_stream_d_extensions.py`: **10 passed**.
- `tests/tools/test_launch_manifest.py`: **2 passed**.
- Six additional adversarial checks: **five passed; one errored**, exposing the duplicate-operation finding.
- A separate helper-only reproduction confirmed that finding without manually altering retained state.
- Scoped `git diff --check`: **passed**.

Additional checks verified individual current-snapshot mismatch refusals, active replay identity, allowed counter values, rejection of older public projections, reservation/snapshot validation before recovery, pending completion, and no-progress refusal. Existing tests cover five lifetime extensions, stress-first eligibility, version comparisons, repair preservation, and immutable snapshots.

No result is claimed for the separately running expected 147-script suite or the superseded `83ebec3` run.

The implementation appropriately reuses existing reservations, diagnosis validation, runner stage order, and atomic JSON persistence. Tests use verified saved practice bytes and the saved 5813be ledger with authored stage receipts and lease controls; they establish offline state behavior, not live qualification.

Diagnosis implementation, held tests, queued-input design, and `.stream-d-next` were excluded. No runner, snapshot producer, changed-gate evaluator, dispatch, or money enablement is claimed. No Murphy rows close. No model, cloud, launch, or decryption workload ran. No worktree files or commits were changed; this review text was not written to disk.

## Elephant resolution

Finding accepted. Admission now rejects an operation already in completed history
before saving an entry snapshot or appending history; active replay remains the
earlier idempotent path. The regression uses an ordinary second reservation with
the old operation ID and asserts unchanged history/public projection/count,
absence of extension-2 snapshots and a still-readable completed extension.
No finding is rejected. The 042f1ae suite was stopped as superseded; the next
full run will be pinned to the corrected commit. No Murphy row closes.
