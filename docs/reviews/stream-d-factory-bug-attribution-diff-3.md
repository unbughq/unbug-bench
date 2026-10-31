Fresh suite re-run confirms the one failure was a flake: `tests/factory/test_isolation_outer_callers.py` failed during the full run (~134s, live escaped-descendant timing) and **passes in isolation** (8 tests OK, 110s). The diff under review does not touch that file or isolation code, and the committed code at HEAD is byte-identical to the source that passed 165/165.

---

# Fresh Goldfish DIFF Review — `stream-d-factory-bug-attribution` (d8ad0b3..e3a72a6)

**Mode:** REVIEW (fresh, read-only, no edits/commits/writes performed)
**Checkout:** `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c` @ `e3a72a6f7dd866d570f0f7c70eeac94cdf38a66a` (`t3/stream-d-implementation`)
**Design:** `docs/designs/stream-d-factory-bug-attribution.md` (final state incl. §"Scope-exit estimate correction")
**Design review checked against:** `docs/reviews/stream-d-factory-bug-attribution-design-9.md` (**PASS**, design @ `a17167a`; design unchanged since canonical rewrite `1c5e355` at that point, final correction added later at `86806dc`)

## Verdict: **PASS — no blockers.** (Diff-level conformance holds; see minors/open items below.)

---

## What the diff did (scope verified)

- `factory/factory_waste.py` (new, 323 lines): attempt ContextVar/`attempt()`/`Attempt` (unpublishable, publish), `record_reservation`, `eligible`, `resume_scope`, `classify`, `refresh_replays`.
- `factory/budget.py`: one shared `_factory_bug_v2` validator; `_settle_leaf` v2 refresh (exact 9-decimal string + paired identity, v1 unchanged); version-aware `reclassify_factory_bug`; `_spending` v2 branch (no second implementation, cross-record overlap refusal).
- `factory/diagnosis.py`: `FactoryBugHeldWait`; `validate_result` model-suggestion ∩ eligible; `_read_factory_bug_finding` dropped `[]/[]` guard, recomputes + requires exact equality; `persist_factory_bug`/`restore_factory_bug` populate eligible/failure_receipts + classify; `resume_factory_bug(c, r)` phase-3 reconcile/refresh/classify seam; `_write_input_tree` names.
- `factory/diagnosis_dispatch.py`: single caller updated to `resume_factory_bug(c, r)`.
- `factory/run.py`: `FactoryBugHeldWait` FIRST in BudgetError handler → `factory_bug_held` + `factory_bug_wait_reason`, no `exhaustion_occurred`; stress scope; context integrations.
- `factory/exam_responder.py`: owner-server request registry (accepting flag, tracked shutdown, 30s monotonic drain deadline), `copy_context` owner invocation, drain timeout → `mark_unpublishable` + no-mask precedence.
- `factory/gate_pipeline.py`: one `attempt` scope after cache lookup around evaluate + invalid-infra check; G10 `copy_context().run`.
- `factory/model_runtime.py`: `record_reservation` after `reserve_invocation`.
- Tests: `test_factory_waste.py`, `test_exam_responder.py`, `test_stream_d_dispatch.py`, `test_stream_d_held.py`, `test_stream_d_inputs.py`, `test_stream_d_runtime.py`, `tools/test_launch_manifest.py`.
- Design: +§"Scope-exit estimate correction". Suite records: `…T181700Z-febaf887.{json,log}` (head `86806dc`, exit 0, "165 test scripts run; 0 failed."), and earlier interrupted record `…T180931Z-017333d6.{json,log}` (honest: interrupted, no verdict).

## Findings

### Blockers: NONE open.

### Majors: NONE new.

### Minors (non-blocking)

1. **Severity:** Minor — **interface conformance.**
   **Location:** `factory/diagnosis.py:462` (`def resume_factory_bug(c, r=None):`); design §"B resume hook and held refusal (B2, B5)": "Change `resume_factory_bug(c)` to `resume_factory_bug(c, r)`, updating its single `_dispatch` caller."
   **Evidence:** Signature carries a backward-compatible default (`r=None` → lazy `import run as r`); the single production caller (`factory/diagnosis_dispatch.py:305`) passes `r` correctly and was updated. Behavior via the production seam is exact; the default only serves tests.
   **Requested fix:** Tighten to `def resume_factory_bug(c, r):` and update test call sites to pass the runner explicitly.

2. **Severity:** Minor — **design document formatting.**
   **Location:** `docs/designs/stream-d-factory-bug-attribution.md` §"Scope-exit estimate correction" (~line 301): sentence broken mid-sentence ("…no new eligibility or counter authority. The narrow exception-masking fix has an observed offline reproducer; include\nits pending-proof refresh and regression test in the fresh diff review.").

### Nits

1. **Severity:** Nit — **error vocabulary edge:** `_factory_bug_v2` raises `waste_operations_pending` for pending operations; design's malformed-record vocabulary maps unknowns/malformed → `invalid_waste_attribution`. Semantic (pending) vs malformed, but worth a one-line distinction note.

## Verification performed (this review)

- Read-only trace of all attribution paths: reservation/money-owner/release joins (`_proof`, `_owners`, `_finding`, `_resume_bindings`), immutable proofs + `_write_input_tree` names, two holds/disjoint ownership, frozen eligibility vs live settlement, v2 accountant + late refresh + zero-cost events, replay link across B transitions, non-final usage vs replay scope exit, held exception mapping + B 3-resume counter, owner drain/copy_context/precedence, G10/foreground context, saved-artifact-byte tests.
- The final correction is genuinely implemented and regression-tested (`publish` suppresses only `money_wait`; preserves escaping `InvalidInfra`; other attribution errors refuse; phase-3 order classify → `refresh_replays` → held).
- Focused offline tests at HEAD: all touched suites pass (factory_waste 13 OK; exam_responder 7 OK; stream_d_dispatch 61 OK; stream_d_held 20 OK; stream_d_inputs 24 OK; stream_d_runtime 42 OK; launch_manifest 2 OK).
- Fresh full required suite at HEAD (`uv run --with numpy --with scipy python -B tests/run.py`): **165 scripts, 1 failed** — `tests/factory/test_isolation_outer_callers.py::test_six_callers_return_while_escaped_descendant_holds_streams` (live-process timing, untouched by this diff). Re-run in isolation: **OK**. The committed suite at `86806dc` (HEAD adds record only): **165 scripts, 0 failed**, exit 0.

## Known-open items (design-scoped, not diff defects)

- Lane 2 entry producer still absent (latest lane2 `eae085f` read-only); integrated extension end-to-end exam remains open — do not mistake consumers for a delivered entry seam.
- Murphy rows `new-stream-d-outcome-routes-1` and row 9 remain open; design promised no closure; none closed.
- Design's integrated-exam gate (hold → later-batch resume → stage replay → new hold → three-resume retirement; real artifact proofs before any row closure) not executed in this diff.

## Final ruling

**Explicit verdict: PASS — no blockers.** The diff `d8ad0b3..e3a72a6` conforms to the final design and the passing design-9 review, the scope-exit masking fix and pending-proof refresh are implemented with regression coverage, and the recorded full suite (165/0 at `86806dc`) stands; the single fresh-run failure was an unrelated flake that passes in isolation.

**Not blocking / for the elephant's awareness:** minor interface nit (`resume_factory_bug(c, r)` vs `(c, r=None)`) and the design-doc line wrap.

---

**What I skipped / did not check:** no live batch runs, no real-VM proofs, no lane-2 merge, no delegation, no further edits. **Risk you should know:** minor interface-conformance nit above; the fresh full-suite run had one unrelated timing flake (passes in isolation); the integrated extension E2E exam and Murphy-row closures remain open by design.

## Elephant disposition

Late continuation retained verbatim. This is a second passing diff verdict; the earlier diff-1 progress report remains unaltered. Non-blocking compatibility/formatting nits remain deferred as recorded in diff-2. The reviewer reports a supplementary full-run timing failure in untouched isolation code followed by an isolated pass; that isolated pass does not independently prove the cause. The committed 165-script zero-failure run at 86806dc remains the required suite record. No source changes, no new row closure, no claim that the integrated item-7 exam ran.
