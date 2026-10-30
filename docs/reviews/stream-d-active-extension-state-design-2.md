I'm returning **FAIL: 0 blockers, 1 major, 4 nits.** The revised design resolves all four findings from round 1. One new gap stops it passing: the dispatcher negative-control test can't pass as written, and the obvious way to make it pass would reorder the dispatcher. That needs one sentence to fix.

```markdown
# Review: stream-d active-extension-state design 2. FAIL (0 blockers, 1 major, 4 nits)

Mode: REVIEW, fresh read-only goldfish. Personas: zoom_out, design_critic,
implementation_readiness. Standards: Heilmeier, implementation readiness.
Scope: working-tree `docs/designs/stream-d-active-extension-state.md` (modified, uncommitted)
against round-1 findings in `docs/reviews/stream-d-active-extension-state-design-1.md`.
Worktree HEAD c450ce0. No production code changed.

## Files read
- docs/ENGINEERING.md; tools/egm/agents/{zoom_out,design_critic,implementation_readiness}.md;
  tools/egm/document_standards/{heilmeier-standard,implementation-readiness-standard}.md.
- factory/diagnosis.py: `extension_history`, `_trigger`, `_state`, `exhaustion`,
  `pending_projection`, `record_exhaustion`, `_input_stop_evidence`, `_verify_input_records`,
  `queued_inputs`.
- factory/extensions.py (whole file).
- factory/diagnosis_dispatch.py: `STOPS`, `apply`, `replay`, `carry_context`, `_dispatch`, `dispatch`.
- factory/run.py: `inherit_recovery_history`, `finalize_accounting`, resume order (3025–3066).
- factory/batch_service.py: `_facts`, `_project`, `_replacement`, `_enqueue`;
  factory/batch_accounting.py `card_total`, `_inputs`; factory/budget.py `reconcile_reservations`.
- tests/factory/test_stream_d_dispatch.py (harness, 100–238), test_stream_d_runtime.py:228–247,
  test_stream_d_projection.py:100–128.

## Round-1 findings: resolved
- **Major 1 (the active `exhaustion()` value): resolved.** "`exhaustion` explicitly returns False
  for any valid history ending in an active row" is a single, decided rule. It agrees with
  `pending_projection` (which already returns None first) and with `record_exhaustion`'s early
  return. `exhaustion` has no callers outside diagnosis.py and batch_service `_project`. The test
  plan covers `_project`/`_enqueue` with known and unknown totals. The existing projection
  control (test_stream_d_projection:117–121) already expects False for active rows.
- **Major 2 (dispatcher replay untested): resolved.** Both origins replay a retained decision with
  the extension active, assert `extension_comparison_pending`, and include a negative control on
  the diagnosis UUID. The order I traced: carry → `_state` (now valid via the prefix) →
  reconcile → `extensions.read` (with the new binding) → `queued_inputs` (frozen card is
  pre-admission, so the binding never fires) → `replay` → `apply` →
  `stop('extension_comparison_pending')`.
- **N1: resolved.** The diagnosis-reader precedent is named: wrong-type paths propagate, with a
  directory control.
- **N2: resolved.** The check sits after the lag check and before `c.card['extension_history'] = projected`.

## What holds
- **The prefix rule is narrow and correct.** The public schema allows an active row only in the
  last position, so `history[:-1]` is exactly the view before admission. Pending, factory_bug and
  not_converging states keep checking against the full history. An `extension_incomplete` origin
  with no earlier completed row fails (empty prefix).
- **It also fixes the real resume entry.** run.py:2817 `inherit_recovery_history` runs before
  dispatch and calls `_state`, so it accepts active cards too (see N3).
- **The private binding uses `projected`, not the possibly stale card copy.** When the public
  history lags, `builder_rounds` may be `round-1`. That count was already at or above the limit
  for late-defect origins, so they still validate. `admit` replay, `complete`, `active`,
  `propose`, `retain_comparison` and the dispatcher all route through `read`.
- **No new ID while an extension is active.** `record_exhaustion` returns early through
  `not exhaustion(card)`, even with `new_exhaustion=True`. Once the extension completes, a
  literal `extension_incomplete` with `exhaustion_occurred=True` mints exactly one new ID
  (diagnosis.py:118–120).
- **Narrowing the I/O handling is safe for frozen inputs.** A frozen tree that has been changed
  fails the manifest/inventory check in `queued_inputs` before `_input_stop_evidence` reaches
  `extensions.read`.
- **No new field, schema, authority or switch.** `DIAGNOSIS_ENABLED` stays false and no Murphy row
  closes. The scope is the right size.

## Major 1: the dispatcher negative control conflicts with reconciliation order
Affected: "Tests and artifacts", the dispatcher bullet ("replay must refuse without private writes").

`admit` requires the writer reservation to be `state == 'pending'` (extensions.py:308). In
`_dispatch`, `reconcile_reservations(c.work, c.ledger)` runs at line 292, before
`extensions.read(c)` at line 298. With no receipt, reconciliation charges the remaining
reservation explicitly (budget.py:387–401), so the ledger is rewritten before the binding check
refuses.

Read literally, "without private writes" therefore fails whenever "private" includes the ledger.
The implementer then has to choose: relax the assertion, or move the binding check ahead of
reconciliation. Moving the check reorders a money step in the dispatcher, which this increment
says it does not touch. That is the kind of open choice the zero-decision rule forbids.

**Fix (one sentence):** define "private writes" for this control as `extension-history.json`,
`extension-snapshots/`, `diagnosis/<id>/` and the card's `diagnosis_state`/`extension_history`.
State that reconciling the already-existing writer reservation may change the ledger, as the
finalize bullet already says, and that dispatcher order is unchanged. Also name the expected
refusal: `BudgetError('extension_history_invalid')` propagated from `dispatch`, with
`terminal_stop` not set by the binding.

## Nits
- **N1. The settlement consequence is unstated.** Under today's code, a budget- or
  infrastructure-origin close-to-passing card with an active row and stop `budget_exhausted`,
  `infrastructure_exhausted` or a retained infra marker already has `exhaustion() == True`. With
  an unknown total, it gets a `settlement` resume (batch_service:278). The new rule removes that,
  so the card's unknown total stays held in batch accounting until M6 routing. That is the
  conservative direction and is intended ("keeps active work out of batch settlement"). Add one
  line saying it is a deliberate change for these origins, so a later reviewer doesn't read it as
  a regression.
- **N2. `_state` receives `history=None`.** Callers pass `extension_history(card)` unguarded
  (diagnosis.py:552, 580; dispatch:286). The prefix condition must short-circuit on None
  (`history and history[-1]['outcome_sha256'] is None`). The word "validated" implies this; say it.
- **N3. The problem statement leaves out the first refusal.** On a real resume,
  `inherit_recovery_history` (run.py:2817) raises `diagnosis_state_invalid` before dispatch for the
  same reason. The dispatcher harness calls `dispatch.dispatch` directly (test_stream_d_dispatch
  `resume()`), so that entry is untested. Name it, and run one origin through the existing
  `main_resume` path, or state why the shared `_state` change makes that test redundant.
- **N4. Readiness and Heilmeier polish.**
  - List the target files: factory/diagnosis.py (`_state`, `exhaustion`), factory/extensions.py
    (`read`), and the tests by file: test_stream_d_extensions, test_stream_d_runtime,
    test_stream_d_dispatch, test_stream_d_projection, and the batch_service test file.
  - The "complete then finalize" bullet needs `exhaustion_occurred=True`
    (`record_exhaustion(new_exhaustion=True)`). Say so.
  - "`propose` now reports `extension_already_active`" is a consequence of the change, not an
    edit. Mark it as such.
  - The objective still leans on the labels B1/B2/M5/M6; one plain sentence would satisfy
    Heilmeier's no-jargon rule. Cost and timeline are implicit ("one increment").
  - Classifying a directory at a retained path as infrastructure means a permanent fault is
    retried until infrastructure exhaustion. This matches the precedent and is accepted, but say
    so explicitly.

## Scope confirmation
These stay open and are not blocked: B1 writer continuation, the crash window where history is
written before the writer receipt (durable writer intent), B2 isolation, M5 stage evidence and M6
routing. No writer is wired. No Murphy row closes. `DIAGNOSIS_ENABLED` stays false. The money
checks (reservation before admission, reconciliation) are unchanged.

## Validation boundary
Static reading only. I edited nothing and ran no tests, suite, launch, models or decryption.
`.stream-d-next/` was excluded. Behaviour claims come from reading the worktree at c450ce0 plus
the uncommitted design revision.

## Verdict
FAIL: 0 blockers, 1 major (M1: define "private writes" and the expected refusal in the
dispatcher negative control without reordering reconciliation). All round-1 findings are
resolved. After the M1 one-line fix, this is ready to implement; the nits are optional.
```

## Elephant response

M1 accepted and fixed: private state excludes the existing reservation ledger, the exact refusal is named, and dispatcher order stays unchanged. All nits are accepted and clarified in the design. The shared entry validation is exercised directly with inherit_recovery_history. No findings rejected.
