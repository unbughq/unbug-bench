**PASS: 0 blockers, 0 majors, 2 nits.** Round 2's one major is fixed, and its nits are all handled. The design is ready to implement as written.

```markdown
# Review: stream-d active-extension-state design 3. PASS (0 blockers, 0 majors, 2 nits)

Mode: REVIEW. Fresh, read-only goldfish review using the zoom_out, design_critic and
implementation_readiness personas. Standards: heilmeier-standard.md and
implementation-readiness-standard.md.
Scope: docs/designs/stream-d-active-extension-state.md at HEAD 9ee05db, checked
against docs/reviews/stream-d-active-extension-state-design-{1,2}.md.

## Files read
- docs/ENGINEERING.md, the three persona files and both standards.
- The design (all of it) and the round-2 review with the elephant's response.
- factory/diagnosis.py `_state`, `exhaustion` (lines 59–90).
- factory/extensions.py `read` (lines 96–156).
- factory/diagnosis_dispatch.py `carry_context`, `_dispatch`, `dispatch` (lines 270–335).
- factory/model_runtime.py `prepare_dispatch`; factory/run.py `resume_provider_wait` (opening lines).

HEAD 9ee05db already has an implementation commit (diagnosis.py, extensions.py and tests).
I read the code only to check what the design claims. I did not review that code: the
separate diff review covers it.

## Round-2 findings
- **M1 (meaning of "without private writes" in the dispatcher negative control): resolved.**
  - The design now lists the protected state: extension-history.json, extension-snapshots/,
    diagnosis/<id>/ and the card's diagnosis_state/extension_history.
  - It allows reconciliation to update the existing reservation ledger.
  - It names the refusal: `BudgetError('extension_history_invalid')`, propagated.
  - It states that the binding does not set terminal_stop and that dispatcher order is unchanged.
  - I traced the path and it agrees. A changed diagnosis UUID is still a valid uuid4, so
    `_state` at dispatch line 286 passes through the prefix. `reconcile_reservations` (292)
    runs, then `extensions.read` (298) raises. `dispatch` re-raises it, because it is not
    one of the codes that call `invalid`/`stop`.
  - The test cannot pass by reordering the dispatcher, and the implementer has no choice left.
- **N1 (settlement consequence): resolved.** Lines 79–82 now say the change is deliberate:
  budget/infra origins lose the settlement enqueue, and an unknown total stays held until
  routing is built.
- **N2 (`history=None`): resolved.** Lines 53–54 say the check must short-circuit on None.
  This matches the guard at diagnosis.py:67–68.
- **N3 (`inherit_recovery_history` entry point): resolved.**
  - Line 17 names this refusal in the problem statement.
  - The test plan exercises the function directly.
  - It also explains why a subprocess main harness would only repeat the shared `_state`
    validation. That reasoning is sound.
- **N4 (polish): resolved.**
  - Target files are listed (lines 32–36).
  - `exhaustion_occurred=True` is given for both the finalize-twice test and the
    complete-then-finalize test.
  - The `propose` change is marked as a consequence, not a separate edit.
  - Lines 29–30 now state the objective without jargon. Cost and timeline: one increment,
    the full suite, then a diff review.
  - The design accepts that a permanent wrong-type path is retried until infrastructure
    exhaustion.

## What holds
- **Simplicity.**
  - The change is three small edits: a prefix choice inside `_state`, one False rule in
    `exhaustion`, and one binding check in `read`.
  - It narrows the `OSError` handlers in the same reader.
  - It adds no field, schema, authority or harness, and no new way to look up a diagnosis.
  - It reuses the existing projection (`public(history)`) and `_state`. Nothing is reinvented.
- **Root cause.** The design fixes which historical view is used to validate a retained
  decision. It does not relax `_trigger`, which stays strict for live exhaustion.
- **Safety.**
  - Without the private binding, the public prefix rule could not prove that this diagnosis
    is the one that admitted the extension. The binding supplies that proof.
  - `record_exhaustion` cannot mint a new ID while an extension is active.
  - After the extension completes, a literal `extension_incomplete` mints exactly one new ID.
  - The test plan includes a check that kills an implementation which keeps the old
    diagnosis forever.
- **Scope.**
  - No writer is wired, and `DIAGNOSIS_ENABLED` stays false.
  - No Murphy row closes, and the design explains why: authored envelopes, and the extension
    worker is not yet wired.
  - Open work is named: B1, the crash window between history write and writer receipt, B2,
    M5 and M6.
- **Readiness.** Every behaviour change has a named positive test and a named negative test.
  The negative tests cover:
  - an empty prefix;
  - late-defect without exhausted rounds;
  - pending and other outcomes;
  - malformed rows;
  - private UUID, status and outcome changes, with replay after the original card is restored;
  - a lagging public history being repaired;
  - permission/EIO errors versus a missing file.
  - The rule "do not assert unchanged accounting bytes" is in the finalize bullet as well as
    the dispatcher bullet, so the two are consistent.

## Nits (optional)
- **N1. Unchanged relative to what?** In the dispatcher negative control, "unchanged … card
  diagnosis_state" should mean unchanged from the *mutated* card the test injected, not from
  the original card. One extra word would remove the ambiguity.
- **N2. Why the UUID is the field to change.** In the dispatcher, the negative control has to
  change the UUID, as the design says. Changing status or outcome would make `_state` fail at
  dispatch:286, which calls `invalid(c)` (a terminal stop) before `read` is reached. The design
  already picks the UUID. A short note on why would stop a later editor from "broadening" the
  dispatcher control to status/outcome. Those cases belong only in the direct `read`/`admit`/
  `complete` controls, which is where the design already puts them.

## Validation boundary
Static reading only. I edited nothing and ran no tests, suite, launches or models.
`.stream-d-next/` was excluded.

## Verdict
PASS: 0 blockers, 0 majors, 2 optional nits. Every round-1 and round-2 finding is resolved.
The full suite and a fresh diff review are still required before merge.
```

## Elephant response

Pass accepted. Both optional nits clarified in the design; tests already assert the injected UUID remains unchanged and keep status/outcome checks at the direct reader boundary. No findings rejected.
