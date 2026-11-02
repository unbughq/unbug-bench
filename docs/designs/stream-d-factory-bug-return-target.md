# Return to the interrupted comparison after a factory fix

## Objective, scope and baseline

After the factory is fixed, return to the case's interrupted extension comparison,
rather than ordinary construction. Keep the prior diagnosis and use its existing
replay route. This avoids another paid diagnosis and an unrelated writer round.

Lane 1 slice 3, Murphy new-stream-d-current-comparison-1. Baseline accepted
4dcbda8 includes factory-simplify 02f3bc9. Merge factory-simplify after land10 lands
and before handback. Diagnosis remains disabled. No other lane's work, enabling
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
extension_resume_target_invalid rather than being silently replaced. Record even
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
is unchanged. Retirement and existing money waits retain their priority.

After atomic scorecard success, when X was restored, set the ephemeral
c.extension_resume_previous = deepcopy(admitted_card). This is only the previous
card argument for writer feedback, not routing or authority. B already removes
failed_gate and infrastructure_gate from admitted_card. In main's existing
integer branch, use getattr(c, 'extension_resume_previous', prev_card) for BOTH
admit_extension and extension_package.run. The original held prev_card Y must
not feed an infrastructure failure to writer_feedback. Keep c.checkpoint_card
unchanged because it belongs to authenticated installation. On later launches
the checkpoint is already the restored X card, so no attribute is needed.

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
writer_receipt route. Missing/corrupt X inputs, attempts or decision refuse via
the existing replay/input-invalid policy, never ordinary construction or a new
diagnosis call. A debit already durably admitted is not refunded.

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

## Tests and row closure

New tests/factory/test_stream_d_resume_target.py, with one small main-harness
extension in test_stream_d_dispatch.py if needed. Use real saved practice case
and 5813be ledger bytes. Pin reused producers:
- DispatchTests' InputTests setup, real queued_inputs/journal/decision/apply with
  its labelled CLI answer control and actual reservation/settlement.
- test_stream_d_comparison.ComparisonTests' real admit/complete/snapshot flow,
  evaluator child transport control, and DiagnosisBoundaryTests.check_handoff's
  real retry exhaustion/finalize/freeze sequence.
- test_stream_d_held.ResumeTests.transition for actual later-batch release/
  money-chain transitions (not its already-held setUp or a nonexistent class).

The row-closing final exam is
test_completed_extension_comparison_factory_bug_relaunch_returns_to_original_target:
produce a completed extension, validated X, real comparison retry exhaustion,
Y pending/frozen factory_bug, and later-batch admission. Copy the actual hashed
runtime files into the private test tree, bind run_validity.__file__ to that
private bin/run_validity.py before the first comparison, and clear its cache.
After the hold, append an authored fix comment to a copied factory .py file,
clear runtime_revision.cache_clear(), assert the hash changed, and keep the
original journal bytes/entries. Restore the module binding/cache in cleanup.
The actual comparison now succeeds using the named evaluator transport control;
entry/progress admission buys exactly one writer. No ordinary build/validation,
extra diagnosis CLI, reset journal or writer before progress. X's original input,
decision, attempt bytes and reservation identities survive the release change.
Check exactly one B debit, one new extension, unchanged prior entry/outcome
bytes, conservative cumulative spend and ordinary/waste conservation.

Midterm/negative exams:
- Unchanged runtime/science: original journal immediately re-exhausts with no
  evaluator/writer call, one B admission only; another later hold uses a new
  admission, eventual three-resume retirement unchanged.
- Crash after B append before card clear, after cleared-card publication, and
  after actual writer admission: reconstruct from disk, preserve one debit and
  no duplicate writer. Reused-admission validation also rejects changed records.
- Committed-package target replays extension_incomplete without work, as above.
- No-extension/no-record ordinary hold remains ordinary. Missing/corrupt/
  symlinked live/frozen record, missing X replay artifacts, and changed owners
  refuse with held/input-invalid/owner policy and no paid work.
- Disabled activation still stops extension_comparison_pending; no build path.
- Main subprocess harness (DispatchTests.main_stop) checks restored previous
  context reaches both admission and package, has no failed_gate/infrastructure
  feedback, and forbids ordinary build/validate. Its setup controls stay labelled.
- Freeze/input inventory and ledger authority tests remain intact.

Close new-stream-d-current-comparison-1 ONLY with the final real-artifact test
and fresh diff review confirming the chain; otherwise leave it open and report
the missing exam. No row 9, full item 7 or live qualification closure.

## Cost, risk, schedule and delivery

Offline inference $0; no workers/network or new runtime spending authority.
Risk: X's original retained artifacts must survive carry-over; explicit
cross-release replay and corruption exams test that existing assumption.
Unhashed fixes cannot refresh retries; immutable package replay may re-exhaust.
Legacy post-extension holds without the record refuse rather than guess.
These limits are explicit, not new reconstruction work for lane 2.

One medium increment, 3–5 hours excluding lock wait/outages. Two design and two
diff rounds maximum; no blockers may be self-verified. After implementation run
single files, then the required full suite to a unique committed log/result:
lockf -t 7000 /tmp/unbug-suite.lock uv run --with numpy --with scipy python -B tests/run.py
Wait for completion, merge newest factory-simplify before review/handback, and get
fresh diff review. A round-2 blocker is handed back in three lines.
