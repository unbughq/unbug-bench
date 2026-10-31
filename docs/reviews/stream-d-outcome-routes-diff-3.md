# Diff Review — Stream D outcome routes (consumer slice)

**Reviewer:** fresh read-only goldfish (DIFF)
**Branch:** `t3/stream-d-implementation` @ `ac3115e`
**Diff:** `1338c61..ac3115e`
**Design:** `docs/designs/stream-d-outcome-routes.md`
**Preceding design review:** `docs/reviews/stream-d-outcome-routes-design-2.md` (passing, R1 + N1–N6)
**Personas:** `zoom_out`, `implementation_readiness` + `implementation-readiness-standard.md`
**Mode:** REVIEW (no edits, no commits, no delegation)

Scope note up front: this verdict covers the **routing/admission consumer slice** only. The attribution producer design on this branch is unimplemented and has no completed review; the lane-2 `entry` producer is absent. Neither is approved by this review, and neither is required for this verdict.

---

## Verification performed

- Traced `apply` → `_dispatch` → `invoke` → `admit_extension` → `pending_call` → `extensions.propose/read/active/writer_receipt/retain_writer/admit`, plus `diagnosis._state`/`_trigger`, `extension_package.run`/`completed_route`, `run.main`'s `extension_id == 0` conversion, and the checkpoint seal handler.
- Confirmed against the design: routing table and its three result-propagation sites; 0→positive conversion before `package.run`; `entry is None → extension_comparison_pending` **before** reservation; `LIMIT` check **before** `entry`; writer-receipt field table; prompt formula; continuation merge (`{**resume_unit, **receipt}` / `deepcopy(resume_unit)`); `on_admitted=invalidate`; orphan intent; bounded counts; no new ledger.
- Ran the four files locally: `test_stream_d_outcomes.py` (10), `test_stream_d_dispatch.py` (59), `test_stream_d_admission.py` (37), `test_launch_manifest.py` (2). All pass.
- Confirmed `fcd21dc..ac3115e` is docs-only, so the committed suite at `fcd21dc` (163 scripts, exit 0, `docs/reports/stream-d-outcome-routes-suite-20261031T161219Z-f939c066`) does cover the HEAD code.
- Confirmed the manifest change is correct rather than papering over a bug: `factory/extension_package.py` is a genuine worker dependency (`WORKER_GLOBS = ('factory/*.py', …)`); the historical `build.json` inventory simply predates it, and the failure originated in lane 2 commit `40822e7`.
- Confirmed no Murphy row status changed and no implementation files exist for the attribution design.

---

## Findings

### Major (non-blocking) — `_dispatch` valid-journal return is untested for `close_to_passing`

**Severity:** Major (non-blocking under `docs/ENGINEERING.md`: pass = no *blocking* finding)
**Affected scope:** `factory/diagnosis_dispatch.py:333`, `tests/factory/test_stream_d_dispatch.py`

The `return` on the valid-journal-without-decision path is load-bearing: without it, a resume falls through to `invoke` and buys a **second paid diagnosis call** for a case that already has a valid journal. Every existing test that reaches this branch (`test_valid_journal_without_decision_finishes_before_gate`, `test_missing_valid_raw_is_input_invalid_before_gate`, `test_model_free_publication_failure_is_retryable_before_the_gate`, `test_schema_contract_roll_waits…`) runs with the default `self.answer = 'factory_bug'`, where `apply` raises before the branch's happy path is exercised. So the guard is currently protected only by tests that fail for a different reason.

**Requested fix:** one test with `answer='close_to_passing'`, with a `dispatch.decision` side effect that raises `Crash`, asserting the resume returns `0`, makes no additional model call, and has published `decision.json`.

### Nit — dead `resume` parameter in `apply`

**Severity:** Nit
**Affected scope:** `factory/diagnosis_dispatch.py:224` (definition), `:280` (caller passes `resume=True`)

After the routing change the parameter is never read. Delete the parameter and the argument — deletion before addition.

### Nit — admission AST guard is too permissive

**Severity:** Nit
**Affected scope:** `tests/factory/test_stream_d_admission.py` (~line 660)

The guard now accepts any `extension_proposal=` call anywhere in `diagnosis_dispatch.py`, so a future stray call outside `admit_extension` would satisfy it. Assert the enclosing function name is `admit_extension` (or that there is exactly one occurrence).

### Nit — missing-entry refusal doesn't prove "before reservation"

**Severity:** Nit
**Affected scope:** `tests/factory/test_stream_d_outcomes.py:80-87`

The test asserts no history growth, no calls, and `entry is None`, but not that `self.ledger.read_bytes()` is unchanged or that no `invocation_reservations` row appeared. One assertion would directly evidence the design's ordering requirement rather than inferring it.

### Nit — continuation prompt content not asserted against the frozen `input_problems`

**Severity:** Nit
**Affected scope:** `tests/factory/test_stream_d_outcomes.py` (restart/continuation test)

Fresh admission asserts the prompt body matches the frozen `input_problems`; the continuation test does not. The merge semantics are the part most likely to regress silently.

### Nit — unapproved attribution design revision sits on the branch

**Severity:** Nit
**Affected scope:** `docs/reviews/stream-d-factory-bug-attribution-design-2.md`

It is a raw mid-run transcript with no header, and attempts 3/4 were unavailable. The branch therefore carries an attribution design revision with no completed independent review. Merge notes must not cite this as approved.

---

## Conformance summary (no findings)

- Routing table and all three propagation sites match the design.
- `extension_id == 0` → positive conversion occurs before `package.run`, as specified.
- `entry is None` yields `extension_comparison_pending` before any reservation; `LIMIT` is checked before `entry`.
- Writer receipt field table and prompt formula match exactly.
- Continuation merge is `{**resume_unit, **receipt}` with `deepcopy(resume_unit)` for the non-continuation path.
- `on_admitted=invalidate` and orphan-intent handling match.
- Bounded counts respected; no new ledger introduced.
- `extensions.public(history)` is correctly used for `_state` (private rows lack `outcome_sha256`).
- `pending_call` re-verifies the proposal twice and rejects admission-owned keys in the fresh receipt.
- Manifest expectation change is a correct fix of a stale inventory.

---

## Verdict

**Passing — no blocking findings.**

This is a pass for the consumer routing/admission slice only. Nothing here closes Murphy row `new-stream-d-outcome-routes-1` (still open), and full item 7 is **not** delivered: lane-2 `entry`, B carry-over, the attribution producer plus its independent review, and the integrated exam all remain outstanding. The Major above should be fixed before this slice is relied on in production, but it does not block the diff.

---

Skipped: no full-suite re-run (relied on the committed log at `fcd21dc`, verified docs-only ahead); did not review the attribution design's content in depth since it is unimplemented and out of scope. Risk: the untested `_dispatch` return is a silent duplicate-paid-call regression path if it is ever refactored.

## Elephant disposition

The non-blocking Major is accepted: add a close_to_passing valid-journal interruption regression test. Optional nits are deferred; attribution remains explicitly unapproved pending its separate design review. No blocking findings were rejected.

Validation: uv run --with numpy --with scipy python -B tests/factory/test_stream_d_dispatch.py -k valid_close_journal passed (1 test). Only an additive regression test and this review record changed after the reviewed code; the committed 163-script full-suite pass still covers the production code.
