# O5b: retire a request-only extension without scoring it

## Problem and scope

When the stress reviewer's last allowed round only asks for an outside freshness
check but gives no link to check, retire the case instead of leaving it parked,
and never count that request as a defect in the admitted package.

The three-case pilot needs a bounded disposition for O5b in
`stream-d-item8-offline-preparation.md` (d814231): package stress has an
authenticated, exhausted report containing only freshness-review requests, but
no freshness metadata. It parks at `extension_execution_pending`, with
no outcome, diagnosis or automatic relaunch, requiring a human pit stop. Replays
repeat the hold. A request is not a defect. Inferring a URL or
inventing a scored extension outcome to trigger diagnosis would be wrong.

Choose the permitted bounded terminal disposition: retire this case unscored,
with `retired_stress_request_only`, without further model work. This replaces
the exhausted hold and removes that pit stop; it does not claim to recover the
missing review or improve case yield. A request already independently cleared
must instead consume its authenticated proof and proceed normally.
Baseline is land12 `7f1c09e`, branch `t3/isolation-o5b`. No live activation,
multi-scenario clamps, diagnosis scheduler, schema, money, allowance or launch
changes. Supports Murphy 9 and preserves 13; closes no register rows. Tests use
saved case and ledger artifacts with explicitly authored CLI answers, not live
acceptance evidence.

## Decision and implementation

In `extension_package.stress`, retain the existing record replay first and all
actor/phase/pending/round/report/completion-hash/scientific-binding checks.
After parsing, before the existing clearance and unfinished-work hold, recognize
only this conjunction:

- (`complete is True` or `result.get('status') == 'scored'`), nonempty blocking list, and the existing
  `r.freshness_only_clearance(result)['blocking']` is empty. Reuse that exact
  matcher; do not introduce a prose classifier. In particular, `review incomplete`
  and a request mixed with a genuine defect do not qualify.
- No nonempty `freshness_review`, no `freshness_review_malformed`, no
  `unfinished_validation`, and no unfinished diagnostic claim for this round.
- Validated receipt has `exhausted is True` and
  `stop_reason == 'rounds_exhausted'`.
- Neither `report.with_suffix('.clearance.json')` nor the sibling
  `report.stem + '-writer.json'` exists. Treat symlinks, including dangling
  symlinks, as present too; never let a malformed retained artifact authorize
  retirement.

Absent metadata and an explicitly empty list qualify; malformed or nonempty
metadata do not. Preserve the current clearance-proof path for those. Missing
exhaustion proof retains the current refusal. Explicit invalid infrastructure
detail must still raise `InvalidInfra` before any card change:
`if comparison._pending(False, result): raise InvalidInfra('invalid package gate result')`.
It must not become retirement evidence.

Expand the existing no-findings clearance trigger to include a present
`.clearance.json` (including a symlink). `loop_freshness` can independently
exclude flagged `freshness.jsonl` rows even when report metadata is absent or
empty. It then publishes the clearance and writer report and advances to
`extension_comparison` without exhaustion. Reuse `late_recovery.cleared_stress`
to authenticate those bytes; its equality check permits only the existing
request-line projection. Valid proof proceeds through the unchanged pass/gates
path. Invalid proof retains `extension_execution_pending`; writer report alone
also keeps the hold. Never retire or score a pass from the existence check alone.

On this conjunction, clear stale `failed_gate`, `failed_detail`,
`infrastructure_gate`, `gates`, and `gate_results` from the card, and set
`stress_review = {status: 'unresolved', reason: 'request_only_without_metadata',
round: <round>}`. Set status stopped and terminal_stop to the new label, then
raise `BudgetError` with that label. Do not save a stress record, call
`extensions.complete`, clear the admitted row, or modify its entry/outcome.
Retirement is an operational disposition, never a stress failure or writer
feedback. Retain report, completion receipt, category evidence, diagnostics,
ledger and open extension-history bytes. Their normal checkpoint is the durable
record; no new journal or sidecar is needed.

Normal run finalization already checkpoints stopped cards and excludes
`retired*` from diagnosis exhaustion. No diagnosis or replacement is fabricated.
Known settled usage remains chargeable normally; unknown usage must retain its
ordinary accounting hold, never be declared known by retirement. B keeps the
job's held reservation exactly as for any terminal stop, with no release, no new
authorization and no settlement resume. Case-level reservations are settled by
`reconcile_reservations` in `finalize_accounting`.
The existing recovery allowlists reject this label. Add a public status mapping
in `batch_status.py` so it displays as retired, before failed-gate handling,
with reason 'stress reviewer request lacks freshness metadata'.
Add that STOPS entry and extend the existing `retired_factory_bug_limit` branch
to test membership in the two retired labels.

Replay must reproduce retirement from the retained receipt/report, even if the
scorecard lags. The existing exhausted writer loop returns without model work,
then package stress authenticates and retires again. Exercise two package
replays with model calls and gates forbidden. An explicit launch through the
ordinary diagnosis/extension resume route must reach the same package guard;
do not trust a stop-label-only bypass of evidence authentication. No new
extension is admitted while this row remains open.
The dispatch replay test enables `batch_service.DIAGNOSIS_ENABLED=True`, as the
pilot requires. With diagnosis disabled, existing dispatch overwrites this label
with `extension_comparison_pending` without reaching the package. That disabled
configuration is not qualified here.

The changed decision is the admitted package O5b boundary only. Ordinary writer
repair and version-comparison evaluator policy remain unchanged. Comparison
re-runs can still score a request-only report without metadata as a stress failure,
which can end in `retired_no_progress`. The ordinary writer loop forwards request
lines as writer problems. These are explicit residual risks outside this package
increment and must be included in handback; no broad never-scored claim is made.
Cross-batch export's partial retired-label filter also remains unchanged and is
outside this three-case pilot.

## Deletions and risks

Delete the indefinite hold for this one exact authenticated shape, replacing it
with one terminal branch. Reuse the request matcher, retained receipt and normal
checkpoint path. No new recovery service or paid reviewer call. Main tradeoff:
a potentially salvageable case retires because there is no actionable review
metadata. The pilot accepts bounded disposition rather than broad recovery.
Main safety risks are stale scientific evidence, interrupted output, and stale
gate failures making retirement look scored; guard them with existing receipt
checks and explicit negative/status tests.

## Exams and delivery

Extend `tests/factory/test_stream_d_blocking_stress.py` using its saved practice
case, real 5813be ledger/admission and real category publication pipeline.
Authored external answers and checkpoint acknowledgements stay labelled. Keep
the prior request-only negative evidence: no scored result, no outcome, no new
diagnosis. Update missing/empty metadata expectations only after this review.

1. Produce a completed request-only report through the real writer/category
   path (with real `loop_freshness`, not its fixture no-op). Missing/empty
   metadata both retire, leave history open, clear stale gate failure and emit
   no stress record or gate call. Assert reservations settled and usage retained.
   Require no hit/ambiguous rows in the saved case's `freshness.jsonl`; make
   `confirm_hits` raise AssertionError so no retrieval/reviewer can run.
   Emit the request from `case_freshness` with that category incomplete through
   REAL_CATEGORIES; assert aggregate complete=False, status='scored', retirement.
2. Twice replay package execution, including a lagging card; report, receipt,
   history, ledger and model-call count remain unchanged. Run real accounting
   finalization; no pending diagnosis or scored outcome appears.
3. Retain nonempty/malformed metadata, no-exhaustion, missing/mismatched
   completion hash, pending review, scientific drift, partial report, incomplete
   sentinel, unfinished validation/diagnostic and invalid-infrastructure
   negatives. Genuine mixed defect remains a stress failure; clean pass remains
   a pass. No broad limit is relaxed.
   A re-hashed complete=False, status='pending' request-only report still holds.
4. Assert recovery restart/holder rejection and public retired status for the
   resulting card. B `plan` must return exhaustion=False, pending_projection=None
   and an empty queue for both known and unknown totals. Assert aggregate(state),
   held_usd and known_floor_usd unchanged by retirement. For unknown usage,
   card_total remains None and no settlement request is queued.
5. Negative control: locally remove the retirement branch in a temporary source
   copy and show the positive integration test fails with the original hold.
6. Request-only/no-metadata plus flagged freshness row: use real loop_freshness
   and confirm_hits with saved HTTP bytes and an authored external reviewer
   exclusion answer, so production code creates and authenticates the proof.
   Valid clearance passes stress and
   reaches gates. Tampering its proof keeps extension_execution_pending and no
   outcome. Test orphan writer artifact and dangling clearance symlink as holds.

One offline increment, roughly half a day excluding shared-lock/review waits;
zero live inference cost. One fresh Claude design review, max two rounds, then
implementation and focused checks. Full suite under
`lockf -t 7000 /tmp/unbug-suite.lock uv run --with numpy --with scipy python -B tests/run.py`
with a 7200000 ms execution budget. Preserve timing failures and unchanged
single-file reruns, never weaken limits. One fresh diff review, max two rounds.
After design round 2 hand unresolved blockers to the parent in three lines;
hand back immediately after diff pass, with pass or approval in commit subject.

## Parent-approved after round 2

The parent approved accepting complete=True OR status='scored' under the existing
authenticated, validated, exhausted receipt and report-hash binding. The real
category engine stops at the first blocker, including an incomplete case_freshness
category; remaining coverage cannot change this unscored terminal disposition.
Sentinel and mixed-defect exclusions stay. Exam 1 covers that exact category
shape; exam 3 adds a pending-report negative. Unfinished diagnostic claims and
unfinished_validation remain explicitly accepted residual holds even for this
shape. No third design review; diff review checks these decisions.
