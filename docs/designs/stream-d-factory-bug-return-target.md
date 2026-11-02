# Return to the interrupted extension after a factory fix

## Objective, scope and baseline

After a factory fix, continue the same extra writing round or comparison that
stopped. Do not fall back to ordinary construction, ask for another diagnosis,
or buy a second writer round. Infrastructure work remains unscored.

Lane 1 slice 3, Murphy new-stream-d-current-comparison-1. Baseline is accepted
4dcbda8 on t3/stream-d-implementation, with factory-simplify 02f3bc9 merged.
Parent is validating land10; merge factory-simplify when land10 lands and again
before handback. Do not write parent worktrees, push, touch main or merge INTO
factory-simplify. Diagnosis remains disabled. Do not reopen accepted slices.

This fixes routing across B's existing later-batch factory-bug admission. It does
not create an admission, counter, allowance, launch path, attribution authority,
scientific result, or entry reconstruction mechanism. Lane 2 still owns the
remaining producers/all-outcomes integration. In particular, enabling automatic
new diagnoses during an active extension (currently refused by record_exhaustion)
is not part of this change; valid already-held package checkpoints can be routed.
The row's primary end-to-end exam is a completed extension's failed comparison.

## Current behavior and loss

A close_to_passing decision returns a positive package ID, or 0 for entry/
comparison followed by admission. The prior decision authorizes that route.
After comparison infrastructure exhaustion, a new diagnosis can say factory_bug.
B validates the new owner/release chain, durably appends or reuses its one resume,
reconciles usage, classifies waste, then atomically clears the held scorecard.
It deletes diagnosis_state; diagnosis_dispatch._dispatch returns False, and main
then enters ordinary build/validation. The prior close_to_passing route is lost.

A RAM-only return cannot fix a crash after B writes the cleared scorecard. Merely
retaining the factory_bug diagnosis would replay the hold. Reusing the older
close_to_passing journal through queued_inputs would bind its old checkpoint
generation against the new owner. Preserve a private route and B admission link
instead, and route through the existing main integer seam on every restart.

## One private durable record

Add factory/extension_resume.py. File: work/extension-resume.json, envelope
{target, admission, sha256}, sha256=digest({target,admission}), atomic_json plus
existing directory sync. All reads use diagnosis._input_bytes, strict exact-key
JSON validation, no links/special files. No public-card field or B history schema.

target exact keys: schema_version=1, case, diagnosis_state, kind, extension_id,
history. diagnosis_state is the exact validated completed close_to_passing state;
history is extensions.public(extensions.read(c)) at route selection. kind is
'admission' with extension_id=0 (first entry or subsequent comparison), or
'package' with the positive last row's ID. For package, its exhaustion_id equals
the retained state's ID. Admission requires no active row. Validate _state using
the recorded history and ensure case equals c.case_id. This is code-owned state,
not a new model-provided target. admission is None or exact keys finding_id and
resume_id referencing one existing B factory-bug-resumes row; it grants nothing.

retain(c,state,number) is called only in apply's enabled close_to_passing integer
return branch, before scorecard publication/return and before any entry/model
work. Record even the empty-history 0 target: a crash after its first writer
admission must still resolve to that admitted row, not repeat entry/admission.
This routes to existing entry(), without taking over its reconstruction policy.
An existing target for the same state is validated and preserved byte-for-byte,
including its admission link; normal replay must not erase B's link. A different
validated diagnosis replaces it with admission=None. Corrupt existing records
refuse extension_resume_target_invalid rather than being silently overwritten.

History reconciliation uses immutable public anchors, never a whole private
history digest (comparisons legitimately append). It permits:
- the exact recorded prefix, with the last recorded active package outcome
  optionally advancing from None to its committed SHA;
- for an admission target only, exactly one successor row whose exhaustion_id is
  the retained state's ID, with unchanged prefix; resolve to that positive ID,
  whether its writer is pending or its outcome has already committed.
No other row replacement, skip, extra successor or changed writer/entry/outcome
identity is permitted. Thus a kill after admit and before any callback still
uses the existing admitted writer. No new on_admitted hook or duplicate counter.

Add extension-resume.json to diagnosis._write_input_tree's selected work names.
Its immutable frozen copy is bound by input.json.files before the factory-bug
finding. Never alter the frozen copy. No private bench or whole comparison-runs
copy is added. The new module is picked up by worker globs; update the launch
manifest expected-file test, not the launch path.

## B seam and crash-safe admission link

Use three helpers in the new module: retain above; prepare(c,finding,root) ->
target or None; mark(c,target,admission) -> restored_state or None. Existing
B factory-bug history and _resume_bindings remain the ONLY admission authority.

After B verifies the finding and validates its resume history, preserve existing
history-invalid and three-resume retirement priority. Before appending any new
resume, prepare validates the frozen and live target cores are identical and
reconciles live extension history. Frozen admission links may be older; they do
not authorize this resume. No frozen target AND no frozen/live extension history
AND no live target means ordinary pre-extension recovery: return None unchanged.
A missing legacy post-extension target or any invalid/missing live target for a
frozen target raises FactoryBugHeldWait('extension_resume_target_invalid'); keep
held state and do not consume an admission. No speculative journal scanning or
fallback to ordinary work. Legacy target reconstruction is explicitly deferred.

B appends/reuses its existing admission as today. Its lock, active-call/ledger
checks, provider wait, reconciliation, classify and refresh_replays are unchanged.
After these succeed and BEFORE admitted_card is published, mark atomically saves
the live envelope with its original target and the exact validated B finding/
resume IDs. It is idempotent; frozen old bytes remain unchanged. Restore the
retained close_to_passing diagnosis_state in the SAME admitted_card write that
clears factory_bug/held flags and retains B's resume count. No intermediate
running card without a durable routing link. OSError after admission remains
FactoryBugHeldWait('factory_bug_resume_io_wait') under B's existing handler.

A kill after B's append but before mark re-enters the held path and reuses the
same admission. A kill after mark but before card clear also reuses it. A kill
after card clear is handled by the durable link, without another B debit.

## Dispatch after admission and on later launches

resolved(c,r) -> int or None lives in extension_resume. It ignores a well-shaped
unadmitted target, and an old target belonging to a different valid diagnosis
state; those continue normal diagnosis dispatch. A malformed record is an
extension_resume_target_invalid evidence stop, never permission for ordinary
work. A current factory_bug state always goes through B before any routing.

For a linked target matching the card's restored diagnosis_state, read the
existing B history via _factory_bug_history and require the link matches its last
admission. Reuse factory_waste._finding(c,admission) to authenticate finding,
input inventory and old/current owner-release chain WITHOUT classifying spend.
Require its frozen target core equals the live target. Then reconcile history as
above. An active package requires extensions.writer_receipt; a completed package
requires extension_package.completed_route. An admission target with no successor
requires immutable retained last outcome/entry verification and the current live
case matching that outcome (empty-history entry uses existing entry validation).
All scientific versions, attempt journals and progress remain existing entry/
package policy. Do not reset an exhausted comparison journal or re-score a pass.

In _dispatch, after carry_context and job_authority.for_case, check resolved for
an already-cleared linked target before ordinary diagnosis input replay. A held
factory_bug bypasses this early check. After resume_factory_bug returns True,
return resolved's integer if present, otherwise False for ordinary recovery.
Use c.card's restored state, not the old checkpoint_card state. When activation
is not True and a linked target exists, stop extension_comparison_pending with
no model work or ordinary fallback; its link persists for later activation.
Main's existing integer branch (0 -> admit_extension, positive -> package.run)
already applies mode guards and bypasses ordinary build/repair. No new main path.

Once a new diagnosis supersedes this state, the old link is not routed. Its next
close_to_passing decision replaces the target normally. A new factory_bug hold
with a frozen target can link the next B admission after the same validations.
No in-place modification of finding/decision/ledger authority is introduced.

## Exams, cost and bounded delivery

New tests/factory/test_stream_d_resume_target.py. Reuse real saved practice and
5813be ledger, real extension receipts/records, and HeldResumeTests' actual
frozen input/release/money-transition setup. CLI answers, diagnosis choice,
external gate failure and remote publication ACK are explicitly authored controls.

Midterm: retain comparison and package targets through actual dispatch; freeze a
factory-bug finding with the target; transition through B's real later-batch
chain; restore state and resolve 0 or the same positive ID. Ordinary no-extension
hold remains ordinary. First-admission crash promotes the 0 target to its already
admitted successor with no second writer or extension. Missing/symlinked/changed
live/frozen target, history anchor, state, admission link and owner chain refuse
before paid work, with held waits before B's append. Three-resume retirement,
active/pending money waits and waste accounting remain existing behavior.

Final: test_completed_extension_comparison_factory_bug_relaunch_returns_to_original_target
runs the completed-extension -> close_to_passing comparison -> infra exhaustion
-> frozen factory_bug -> changed batch/release -> same comparison route chain.
Forbid ordinary build/validate, diagnosis CLI and writer before actual successful
entry/progress admission. Crash at append, after link, after cleared-card write,
and after actual writer admission; restart from retained bytes, checking exactly
one B debit, one writer round, stable cumulative ordinary/waste totals and no
reset of comparison evidence/journals. Test repeated hold/retirement and disabled
activation. An already-held active-package fixture tests routing only; it does
not claim to enable active-extension diagnosis production. Fresh diff review
must verify real artifact use before closing new-stream-d-current-comparison-1
with this named test. No row 9 or full-item-7 closure, no live qualification.

Offline inference $0; runtime uses existing B bounds, no new allowance or remote
workflow. Risk: stale targets could buy duplicate work; immutable history/frozen
finding/B-link checks and kill tests are the exam. Legacy missing targets refuse
held rather than guessing. B's existing historical-release/deadline restrictions
are unchanged. Estimate medium, 3–5 hours excluding lock wait/outages; one increment.
Merge factory-simplify after land10 lands. Run one required full suite with unique
committed log/result and wait: lockf -t 7000 /tmp/unbug-suite.lock uv run --with numpy --with scipy python -B tests/run.py.
Single files may run unlocked. Max two design and two diff rounds; a remaining
blocker after round 2 is handed back in three lines. Never self-verify a blocker.
