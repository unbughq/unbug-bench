# Return to the interrupted comparison after a factory fix

## Objective, scope and baseline

After the factory is fixed, return to the case's interrupted extension comparison,
rather than ordinary construction. Keep the prior diagnosis and use its existing
replay route. This avoids another paid diagnosis and an unrelated writer round.

Parent-approved after round 2. Lane 1 slice 3, Murphy new-stream-d-current-comparison-1. Baseline accepted
4dcbda8; land10/factory-simplify b75c9b4 was merged at ae93bba before
implementation. Merge newest factory-simplify again before handback. Diagnosis remains disabled. No other lane's work, enabling
active-extension diagnoses, legacy entry reconstruction, new resume authority,
money allowance, launch path or retry reset is in scope. The control service's
existing later-batch admission remains the only factory-bug resume counter.

## Problem and existing route

A completed extension can require a comparison before another extension. Its
close_to_passing decision X selects that route. Comparison infrastructure
exhaustion creates a new pending diagnosis Y; a factory_bug decision holds it.
resume_factory_bug validates the later batch/release, appends or reuses one
admission, reconciles usage and waste, then clears diagnosis_state. _dispatch
returns False and main falls into ordinary construction.

Keep X, not another router. queued_inputs' existing-manifest branch validates
the original frozen inputs; replay validates the decision against that manifest's
original generation, and journal joins the original reservations still retained
in the case ledger. It does NOT compare X's generation against the new owner.
The existing apply already routes empty/no matching history to 0, an admitted
matching successor through writer_receipt to its positive ID, and a completed
matching successor through completed_route to its positive ID. Its existing
activation and comparison_route gates remain authoritative.

## One private state record, no second router (B1)

Keep helpers in diagnosis.py; add no module. File work/extension-resume.json has
exact envelope keys record, sha256. record has exactly schema_version=1,
case=c.case_id, diagnosis_state=X. sha256 is carry_over.digest(record). X has
the existing five diagnosis-state keys and is completed/close_to_passing.
Validate it using _state with the current card's other fields and
extensions.public(extensions.read(c)); use a copied card, never mutate on read.
All reads use _input_bytes, exact-key/type checks and existing no-follow rules.

retain_extension_resume(c, state) runs in apply's enabled close_to_passing branch,
after its existing history/receipt/completed_route checks, before scorecard
publication and integer return. atomic_json plus a directory fsync publishes
the record before any entry or writer. Same record preserves its bytes; a new
validated X replaces the old record. A malformed existing record refuses
extension_resume_target_invalid rather than being silently replaced. During
selection/replay this check follows the existing completed_route side effects;
its refusal is a plain evidence stop, not a factory-bug held wait. The held-wait
mapping below applies only inside factory-bug admission. Record even
empty-history selection: the existing apply then recovers any successor already
admitted under X without buying another writer.

Add extension-resume.json to _write_input_tree's selected work names. The later
Y manifest binds its frozen copy at inputs/work/extension-resume.json. No record
mutation while held; findings and frozen trees remain immutable. Keep X's entire
diagnosis directory and its reservations through the existing full checkpoint,
rather than duplicating them in this file or copying them into Y's selected tree.

_extension_resume_state(c, evidence_root) returns X or None. On both NEW and
REUSED resume admission branches, after the existing finding/history validation
and three-resume retirement check, but BEFORE a new append, validate:
- Live and frozen record bytes are equal, both valid, case identity correct,
  and X valid under the existing current public extension history.
- No frozen record, no live record and no extension history means ordinary
  pre-extension recovery: None, retaining the existing behavior.
- Any missing legacy post-extension record, unexpected live-only record,
  mismatched/corrupt/symlinked record or invalid state raises
  FactoryBugHeldWait('extension_resume_target_invalid'), before any new debit.
  No reconstruction, journal scanning or fallback to ordinary work.

The B finding/history/money-owner chain remains the authority. This helper adds
no admission ID, target kind, history anchors, owner checks or linked-record
reconciliation. Original X decision authenticity is checked by existing replay,
not by a new duplicate validator.

## Restore once; replay through the existing dispatcher

After the existing locked provider-wait/reconcile/classify/refresh_replays phase
succeeds, restore X in the SAME admitted_card write that clears Y's held fields
and retains factory_bug_resume_count. None keeps the existing ordinary clearing.
The private record is unchanged. Existing post-admission I/O held-wait behavior
is unchanged. Retirement keeps its priority; the existing money guards remain.

Keep main and its previous-card argument unchanged. The real subsequent_entry
comparison path already clears failed_gate, failed_detail and infrastructure_gate
before attempting comparison. A previous-card override could discard legitimate
scientific feedback when an existing pair is reused, so no override is added.

In _dispatch, when resume_factory_bug returns True:
- no restored completed close_to_passing state: return False as today;
- restored X: assign local previous=deepcopy(c.card), state=previous's X, and
  FALL THROUGH the existing prepare_dispatch, lock, reconcile, queued_inputs,
  journal, replay and apply code. Keep comparison_route unchanged.
There is no early router, special apply call, new dispatcher return type or
activation bypass. Model work remains outside the dispatch lock as today.

Crashes after B appends but before clearing reuse the existing admission.
Crashes after clearing replay X from the scorecard; B sees close_to_passing and
does nothing. Crashes after a subsequent writer admission use apply's existing
writer_receipt route. Missing/corrupt bound X inputs or an invalid journal refuse
via the existing replay/input-invalid policy, never ordinary construction or a
new diagnosis call. A missing decision with a valid completed journal keeps the
existing model-free decision publication recovery. A debit already durably
admitted is not refunded.

## Retry and immutable-package limits (B2, M3, M4)

Never reset pair-attempts.json or any scientific journal. Comparison retry keys
include run_validity.runtime_revision() and scientific identity/versions. Only
a changed hashed runtime or stage versions grants fresh infrastructure attempts.
An unchanged revision, or a fix only outside those hashes, immediately
re-exhausts; a later diagnosis can hold again, with at most three lifetime
factory-bug resumes under the existing service.

record_exhaustion refuses active extensions: do not manufacture an active-package
factory-bug hold to claim coverage. Existing apply's successor handling is reused,
not extended. A factory bug diagnosed after a committed package restores its X
and replays that immutable package; extension_incomplete can recur without work
or outcome mutation. A resume can be consumed this way, bounded by three. This
change preserves the correct target; it cannot revise an immutable result.

## Parent-approved after round 2: focused tests, no row closure

Parent approved the design logic after final design round 2, with no round 3.
B1's combined fixture/row-closing exam is explicitly removed from this increment.
M1 is accepted: no previous-card override or main change. M2 is accepted:
owner/release transitions in the focused tests happen IN PLACE; they are not an
archive/restore or imported-ledger proof. The item-8 checklist must require:
"close new-stream-d-current-comparison-1 with a real decision → extension →
subsequent_entry comparison exhaustion → factory-bug hold/resume chain on
retained artifacts".

New tests/factory/test_stream_d_resume_target.py uses these fixtures honestly:
- DispatchTests.setUp (saved practice and 5813be bytes), its labelled CLI answer
  control and real queued_inputs/journal/decision/apply. Test retaining X, freezing
  it under a new factory-bug diagnosis, an in-place authenticated owner transition
  using ResumeTests.transition, and dispatch replay of the original X with no
  second diagnosis. This chain has NO extension/comparison execution claim.
- Existing DispatchTests.admit_active_control uses authored snapshot controls,
  real pending_call admission and writer_receipt. These exercise return to an
  already admitted successor without a second writer, not subsequent_entry.
  A completed-route unit seam may be controlled explicitly; do not imply an
  authored snapshot proves package scientific execution.
- ResumeTests.setUp/transition provide a real finding/admission and saved ledger
  with authored lifecycle state. Where needed, retain an explicitly authored X
  before freeze to test the helper/atomic restore only. This is not a journal or
  subsequent_entry proof.

Focused assertions: enabled selection writes before scorecard return; disabled
selection does not retain or bypass activation; identical replay preserves bytes;
new validated diagnosis replaces X; malformed/symlinked/changed/missing records
refuse without a new debit; bad reads map extension_resume_target_invalid rather
than factory_bug_resume_io_wait; reused admission validates again. Crash after
append and before card clear reuses its admission; crash after clear replays X;
active successor recovers the same writer receipt. Original X manifest, journal,
decision and reservation bytes/identities remain intact during the in-place owner
transition. Missing replay artifacts refuse input-invalid, no new diagnosis call.
Existing no-record pre-extension tests keep ordinary recovery. Existing tests
cover the unchanged lifetime retirement/money rules. No full main harness or
pair-attempts/runtime-revision qualification is claimed by these focused tests.

Record read/parse errors are caught inside the target helper and mapped to
FactoryBugHeldWait('extension_resume_target_invalid'). A missing/invalid retained
record permanently holds the case until its original evidence is restored;
later batches do not repair it, do not consume a new admission and cannot safely
guess a replacement target. It requires evidence repair/operator action.

Murphy new-stream-d-current-comparison-1 stays OPEN. Close no rows, claim no full
item-7 or live qualification. The real retained-artifact chain is deferred to
item 8 explicitly, not hidden behind a conditional closure promise.

## Cost, risk, schedule and delivery

Offline inference $0; no workers/network or new runtime spending authority.
Risk: X's original retained artifacts must survive carry-over. Focused in-place
owner/release transitions test local retention only; checkpoint archive/restore
and the full comparison chain remain unproven item-8 obligations.
Unhashed fixes cannot refresh retries; immutable package replay may re-exhaust.
Legacy post-extension holds without the record refuse rather than guess.
These limits are explicit, not new reconstruction work for lane 2.

One medium increment, 3–5 hours excluding lock wait/outages. Two design and two
diff rounds maximum; no blockers may be self-verified. After implementation run
single files, then the required full suite to a unique committed log/result:
lockf -t 7000 /tmp/unbug-suite.lock uv run --with numpy --with scipy python -B tests/run.py
Wait for completion, merge newest factory-simplify before review/handback, and get
fresh diff review. A round-2 blocker is handed back in three lines.


## Parent delivery amendment after the locked suite

The locked run at source 9cd1a66 completed 179 scripts with one failure in the
untouched key_holder heartbeat isolation timing test. The exact method passed
its targeted recheck. The parent identified the known flake and explicitly
cancelled the queued repeat before it started: the parent's merge suite is now
the gate. Preserve both the failing run and cancelled command records. Continue
the fresh diff review (max two rounds) and hand back when it passes. This does
not change implementation scope, diagnosis activation or the open Murphy row.
