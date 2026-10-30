# Stream D: preserve the diagnosis that admitted an active extension

## Problem and scope

The next active-recovery work has a prerequisite independent of writer replay.
`diagnosis._state` validates a diagnosis's original exhaustion against the
current public extension history. After admission, that history has a new active
last row. Two original triggers then cease to validate:

- `extension_incomplete` requires the last row to be completed;
- `late_defect_needs_ruling:G*` requires there to be no active extension.

Those conditions were true when the completed close-to-passing diagnosis was
made, before its new extension was admitted. Applying them to the post-admission
history makes that legitimate state invalid. `finalize_accounting` records a
diagnosis-state cleanup error, and the current diagnosis dispatcher refuses the
next resume before it even reads the private extension history. `inherit_recovery_history` also refuses before dispatch on real resumes. The initial
budget/infrastructure exhaustion controls miss this because their triggers do
not depend on extension history.

This increment preserves that completed diagnosis across active checkpoints and
binds it to the private active row. It does not invoke or resume a writer. The
current dispatcher still stops verified close-to-passing cases at
`extension_comparison_pending`. B1 writer continuation, the history-before-writer-
receipt crash window, B2 comparison isolation, M5 scientific receipts and M6
continuation routing remain open. In particular, this does not claim to recover
the missing writer intent left by the current first-admission write order.

The goal is to remember why the extra round was granted while that round is
still running, without granting another round or losing the original decision.

Target files are `factory/diagnosis.py` (`_state`, `exhaustion`),
`factory/extensions.py` (`read`), and existing
`tests/factory/test_stream_d_extensions.py` and `test_stream_d_dispatch.py`.
The extension tests also cover public projection, batch enqueue and finalization
through their real APIs; no additional harness is needed.

No new field, schema, launcher, authority or runtime switch is added.
`DIAGNOSIS_ENABLED` remains false. The work is one implementation increment,
full suite and fresh diff review. No Murphy row closes: the lifecycle uses real
saved case/ledger bytes, but stage and diagnosis envelopes are authored and the
extension worker is still unwired.

## Public state rule

Keep `_trigger` unchanged. Its live-exhaustion rule remains strict: an active
extension is not a completed `extension_incomplete` event and does not authorize
a late-defect diagnosis.

In `_state(card, history)`, after validating the diagnosis envelope and before
checking its original trigger, select the history used only for that check:

- Guard the prefix condition with `history and ...`, so callers passing None
  for malformed history do not index it.
- If the state is `status='completed', outcome='close_to_passing'`, and the
  supplied validated public history ends in an active row
  (`outcome_sha256 is None`), use `history[:-1]` for the trigger check.
- Otherwise use the supplied history exactly as today.

Do not change the card, its history, or the returned state. Removing the active
last row reconstructs the public view immediately before admission. It does not
drop any earlier completed extension or its progress. In particular, an initial
`extension_incomplete` diagnosis with only one active row and no prior completed
row still fails: the prefix is empty. A late-defect origin still requires the
existing valid gate, ordinary round limit and exhausted count.

This is a projection/lifecycle rule, not money authority. Public rows do not
carry the admitting exhaustion UUID. The private reader below supplies that
binding before any future active writer admission. Pending diagnoses and other
completed outcomes gain no prefix exception; their existing validation behavior
stays unchanged. Malformed histories still fail their existing public schema
validation before `_state` is used.

`record_exhaustion` continues to test a new literal stop against the **full**
current history. Its active-row guard remains. It must not mint another ID while
the extension is active, even if finalization receives `new_exhaustion=True`
from an infrastructure or budget exception. `exhaustion` explicitly returns False for any valid history ending in an active
row, including budget/infrastructure stops and retained infrastructure markers.
This keeps active work out of batch settlement/replacement queues; active
continuation routing remains a separate increment. For budget/infrastructure
origins this deliberately removes the old settlement enqueue; an unknown total
stays held until that routing increment. `pending_projection` stays None
for an active extension. As a consequence (not a separate edit), `propose` now reports `extension_already_active` for
a valid active diagnosis instead of the misleading `extension_diagnosis_required`. Once an outcome is retained and the runner stops with
a new literal `extension_incomplete`, the existing finalizer mints the next
pending exhaustion normally, using the full completed history.

## Private active-row binding

In `extensions.read`, after verifying every private row, reservation, snapshot
and comparison and constructing `projected = public(history)`, add one check
after the public lag check and before assigning the public projection,
when the last private row is active:

1. `_state(c.card, projected)` must return a completed close-to-passing state.
2. Its `exhaustion_id` must equal that active row's `exhaustion_id`.

Otherwise raise the existing `extension_history_invalid` before updating the
public projection or returning a row. This uses the verified projection, not a
possibly lagging `c.card['extension_history']`. The existing one-write public
lag and builder-round rules remain intact. Completed histories do not require
the card to retain their old diagnosis: they may already have a new pending or
completed diagnosis. `admit`'s idempotent path and `complete` both use `read`, so
they also enforce the active binding.

An active row is therefore tied to the completed diagnosis which admitted it,
the actual writer reservation operation and the immutable entry bytes. A caller
cannot change only the card's diagnosis UUID, outcome or status and obtain an
active row. No extra lookup of `decision.json` or new source of diagnosis
authority is introduced: the card is from authenticated restore/current verified
diagnosis application, as in the passed admission design.

For the history-file and ledger-read handlers in `extensions.read`, narrow
`OSError` to `FileNotFoundError`, as already done for diagnosis history readers.
Missing/malformed retained records remain semantic history refusals. Permission,
EIO and other non-missing read failures propagate as infrastructure. This follows the existing diagnosis-reader precedent: directory/wrong-type paths
propagate as infrastructure too, verified with a directory control. A permanent
wrong-type fault therefore retries until infrastructure exhaustion. It does
not change snapshot validation or add a terminal recovery/reset mechanism.

## Tests and artifacts

Extend existing extension/runtime tests rather than add a new harness. Use the
saved 5813be ledger, gzip/hash-verified practice case, real `propose`, writer
reservation, `admit`, immutable snapshot and `complete`. Stage receipts and the
completed diagnosis results remain named authored controls. No model or launch
is needed. Tests must cover these observable transitions:

- **Late-defect origin:** ordinary rounds exhausted, completed close-to-passing
  diagnosis with literal `late_defect_needs_ruling:G4` (and G6 control). Admit an
  extension with the real helpers. Its diagnosis remains valid against the
  pre-admission prefix; the active public projection is None.
- **Second-extension origin:** admit/complete the first extension with strict
  progress, record the next literal `extension_incomplete`, mark that diagnosis
  close-to-passing as an authored result, then admit extension 2. Preserve the
  second diagnosis UUID and both history rows.
- For both origins, run real `finalize_accounting` twice while active under
  `extension_comparison_pending`, `provider_wait`, `money_wait`,
  `runner_error:ValueError` and `infrastructure_exhausted`, including
  `exhaustion_occurred=True`. Assert unchanged diagnosis/ID/history, no
  diagnosis-state cleanup error, None pending projection, no new reservation or
  writer. Reconciliation may settle an already-existing reservation; do not
  assert unchanged accounting bytes when it legitimately does so.
- For both origins, use the existing dispatcher harness to retain a decision and
  replay it with the extension active. Assert `extension_comparison_pending`,
  unchanged diagnosis/history and no new reviewer/writer call. Change the diagnosis
  UUID as a negative control; replay must propagate
  `BudgetError('extension_history_invalid')` without changing extension-history.json,
  extension-snapshots/, diagnosis/<id>/ or the card diagnosis_state/extension_history.
  The binding does not set terminal_stop. Reconciliation may update the existing
  reservation ledger; dispatcher order stays unchanged. The second
  origin must verify frozen `extension_incomplete` evidence after admission.
- Exercise `inherit_recovery_history` directly for a valid active origin, before
  dispatcher replay. Its shared `_state` validation is the entry-path change; a
  second subprocess main harness would duplicate that validation.
- Assert `exhaustion` False and pending projection None for active cards under all
  listed stops, budget exhaustion and a retained infrastructure marker. Exercise
  batch projection/enqueue with known and unknown totals: neither settlement nor
  replacement work is enqueued for the active card.
- Complete the active extension and finalize a literal `extension_incomplete`
  with `exhaustion_occurred=True`.
  Assert exactly one new pending exhaustion ID, then a second finalization keeps
  that new ID. This kills an overbroad implementation that preserves the old
  completed diagnosis forever.
- Public controls: the prefix exception does not validate an
  `extension_incomplete` origin with no earlier completed row, a late-defect
  origin without exhausted rounds, or pending/other-outcome states whose
  original trigger fails on the full history. Malformed public rows remain
  invalid. Do not change the existing held/active projection controls.
- Private controls: change only the active diagnosis UUID, status or outcome;
  `read`, idempotent `admit` and `complete` refuse `extension_history_invalid`
  without changing private history/snapshots. Restore the original card and
  verify the same active row replays. An immediately lagging public history is
  still repaired from the verified private row.
- Read-side PermissionError/EIO on history and ledger propagate as infrastructure
  with history and diagnosis unchanged. Missing/malformed history or ledger
  still refuses semantically. Existing snapshot damage tests remain in force.

The full suite and a fresh goldfish diff review are mandatory. Before writer
wiring, a separate design must still resolve durable writer intent, pending vs
completed writer continuation, stage evidence and routing. This increment
deletes no mechanism; it corrects which historical view validates a retained
state and removes broad read-I/O misclassification from the touched reader.
