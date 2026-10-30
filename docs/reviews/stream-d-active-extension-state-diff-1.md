# Goldfish diff review: Stream D, preserving the diagnosis while an extension is active

**Mode:** REVIEW (read-only, Claude family)
**Range:** `c450ce0..07f902f854f0344f4acb694a5bec9b3d361e7122`
**Design:** `docs/designs/stream-d-active-extension-state.md` (design review 3 PASS)
**Personas/standards applied:** zoom_out, implementation_readiness; `zoom-out-standard.md`, `implementation-readiness-standard.md`
**Files read:** the files above, `factory/diagnosis.py`, `factory/extensions.py`, the `_dispatch` entry in `factory/diagnosis_dispatch.py`, the `inherit_recovery_history` entry in `factory/run.py`, `recovery.infrastructure_exhausted`, and the new test code. `.stream-d-next/` was not read. No tests were run. I relied on the parent's suite result: 154 scripts, 0 failed.

## Verdict: **PASS**

There are no Blocker or Major findings. Three Nits follow.

## Scope check

- **Code changed:** only `diagnosis._state`, `diagnosis.exhaustion` and `extensions.read`. These are exactly the target functions the design names.
- **Tests changed:** only the existing `test_stream_d_extensions.py` and `test_stream_d_dispatch.py`. No new test harness was added.
- **Docs changed:** the design file (wording that design reviews 1–3 settled), the three design review records, and a one-paragraph status note in `stream-d-worker-dispatch.md`.
- **Nothing extra added:** no new field, schema, launcher, authority or runtime switch. `batch_service.DIAGNOSIS_ENABLED = False` is unchanged; tests only patch it locally.
- **No writer wiring or activation:** no writer is invoked or resumed. The dispatcher still stops at `extension_comparison_pending`.
- **No Murphy row closure:** `docs/murphy-register.md` is not in the diff. The design's justification for leaving rows open holds: stage and diagnosis envelopes are authored, and the extension worker is unwired.

## Correctness

1. **`_state` checks the diagnosis against the history before admission.** It removes the last row only when all of these hold: the state is completed, the outcome is `close_to_passing`, the history is non-empty and the last row is active (`outcome_sha256 is None`). The `history and` guard means a `None` history (malformed) never gets indexed. The envelope is validated before the original trigger is checked. `_trigger` itself is unchanged, so the live-exhaustion rules stay strict. Pending states and other outcomes still validate against the full history.
   - An `extension_incomplete` origin with only one active row fails, because the shortened history is empty.
   - A late-defect origin still needs `rounds` and `count >= rounds`.
2. **`exhaustion` now returns False for any valid history ending in an active row.** This is checked before `_state`, so it covers budget and infrastructure stops and a retained `infrastructure_gate.exhausted` marker. Batch projection then yields no settlement or replacement work. The design explicitly accepts losing the old settlement enqueue for budget and infrastructure origins.
   - `record_exhaustion` cannot mint a new ID while an extension is active: `exhaustion` returns False there, and its own active-row guard is still in place.
   - After completion, `record_exhaustion` sees a completed last row. It accepts a new literal `extension_incomplete` via `new_exhaustion`, tests it against the full history and mints a new pending ID. The test asserts this, and also asserts that a second finalization keeps the same ID.
3. **`extensions.read` ties the active row to the diagnosis that admitted it.** The check runs after the one-write public lag check and before `c.card['extension_history'] = projected`. It uses the verified `projected`, not the card's possibly lagging history. A missing state, a non-completed state, a different outcome or a mismatched `exhaustion_id` all raise `extension_history_invalid` before the card is changed.
   - `admit` (idempotent path), `complete`, `active` and `propose` all go through `read`, so they all enforce the binding.
   - Reusing an old diagnosis is blocked by the existing per-row `exhaustion_id` uniqueness check.
   - Completed histories are not bound to the old diagnosis, as the design requires.
4. **Read errors are classified as the design asks.** Both handlers now catch `FileNotFoundError` instead of all `OSError`. A missing ledger, or JSON that is malformed or the wrong shape, is still refused as invalid history (`ValueError`, or `AttributeError` for `null`). Permission errors, EIO and directory/wrong-type paths propagate as infrastructure failures. This matches the design's note that a permanent wrong-type fault retries until infrastructure exhaustion.
5. **Entry paths:** `diagnosis_dispatch._dispatch` (line 286) and `run.inherit_recovery_history` (run.py:2817) now accept a valid active origin through the shared `_state`. No caller-specific edits were needed. This is the root-cause fix the design describes.
6. **`propose` error code:** it now reports `extension_already_active` for an active card with a valid diagnosis instead of `extension_diagnosis_required`. The design documents this as a consequence, and a test asserts it.

## Tests against the design's checklist

| Design obligation | Covered by |
|---|---|
| Late-defect origin, G4 and G6 | `test_late_g4_active_checkpoints`, `test_late_g6_active_checkpoints` |
| Second-extension origin keeps the second diagnosis UUID and both rows | `test_second_extension_active_checkpoints` (asserts `len == 2`) |
| Finalization twice under each listed stop plus `budget_exhausted`, with `exhaustion_occurred=True` and an infrastructure marker | Asserted: diagnosis, history, private bytes and reservation keys unchanged; no `diagnosis_state` cleanup error; `exhaustion` False; pending projection None |
| Batch `_project` / `_enqueue` with known and unknown totals | Asserted: empty queue and derivations |
| Lag repair from the verified private row | Covered |
| Complete, then a new pending ID that stays stable | Covered |
| Dispatcher replay for both origins | Covered, including `inherit_recovery_history`, `extension_comparison_pending`, no pilot/qualify/helper/reviewer calls, unchanged private trees and history bytes |
| Dispatcher UUID-only negative control | Covered: raises `extension_history_invalid`, no `terminal_stop`, card and files unchanged |
| Private controls (UUID / status / outcome changes for `read`, idempotent `admit`, `complete`) | Covered: work tree unchanged, and the original card replays |
| Public prefix controls | Covered: no earlier completed row, rounds 7 < 8, pending and other outcomes, `None` history, malformed row |
| Read I/O controls | Covered: PermissionError and EIO on both files; malformed (`{`, `null`); missing; directory; card and tree unchanged |

The test assertions are strong enough to fail on wrong implementations:
- A version that keeps the old completed diagnosis forever is caught by the new-pending-ID assertion.
- A version without the binding is caught by the UUID controls.
- A version that still catches broad `OSError` is caught by the `assertRaises(type(error))` checks.

## Findings

**Nit 1: unreachable checks left behind.** Category: simplification. Files: `factory/diagnosis.py` (`pending_projection` and `record_exhaustion`).
- `exhaustion()` now returns False for an active last row.
- So the `history and history[-1]['outcome_sha256'] is None` checks in `pending_projection` (`if ...: return None`) and at the end of `record_exhaustion` can no longer change the result.
- They are harmless belt-and-braces. They could be deleted in a later simplification pass. Not needed in this increment, because the design says "Its active-row guard remains."

**Nit 2: cross-file coupling between test classes.** Category: test structure. File: `tests/factory/test_stream_d_dispatch.py` (`admit_active_control`).
- It calls the unbound `extension_tests.ExtensionTests.snapshot` and `.reserve` methods with the dispatch test's own `self`.
- This silently depends on the two harnesses sharing attribute names (`c`, `work`, `ledger`, `models`, `baseline`, …). A rename in either file would break the other with an `AttributeError`, not a clear failure.
- It works and reuses real helpers, which the design prefers. A future refactor could move these two helpers to module-level functions.

**Nit 3: import order.** Category: style. File: `tests/factory/test_stream_d_extensions.py`.
- The new imports (`batch_service`, `diagnosis`, `run`) break the alphabetical order of the existing import block.
- The test docstring still says it "proves lifecycle/progress guards". It now also covers batch projection and finalization, but that is still accurate under the design's framing.

## Not re-raised (deferred by the design, out of scope)

These remain open, as the design and the dispatch-doc status note both say:
- B1 durable writer intent, and the crash window between writing history and the writer receipt
- B2 comparison isolation
- M5 scientific receipts
- M6 continuation routing
- Unknown-total settlement for active budget/infrastructure origins, which stays held until the routing increment

**Result: PASS.** Nits only. Scope matches the brief, and no Murphy row was closed.

## Elephant response

Pass accepted. No blocking findings or rejections. The three optional nits are deferred: retained active guards match the approved scope; shared test helpers follow the existing harness pattern; import ordering needs no behavior change.

## Validation and handoff

Command: `uv run --with numpy --with scipy python -B tests/run.py`.
Result: `154 test scripts run; 0 failed.` Exit status 0.
Implementation tested: 9ee05db28edb7e31e09c888610fd002bff08c8cd.
Reviewed head: 07f902f854f0344f4acb694a5bec9b3d361e7122 (subsequent changes only record reviews and status).
The local full log is `/tmp/stream-d-active-extension-suite.log`.

No Murphy rows close. D rows 8, 9, 10, 11, 12, 13, 15, 21 and 39 remain open. A batch still cannot rely on diagnosis and extensions: active writer continuation and durable writer intent, comparison isolation, scientific stage receipts, continuation routing (including unknown-total active settlement), and real-artifact/live qualification remain unfinished. `DIAGNOSIS_ENABLED` stays false.

This increment stops here. Nothing was pushed, merged into factory-simplify, or changed on main.
