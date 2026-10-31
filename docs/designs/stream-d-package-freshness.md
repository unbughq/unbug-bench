# Stream D package increment 1: retained freshness recovery

## Problem and scope

Diagnosis replay republishes scorecard.json before admitted writer/stress execution.
Its carry_context whitelist omits loop_freshness. A restored completed G2 reviewer
answer can lose its scorecard pointer when freshness-verdict.json was not published.
Existing confirm_hits recovery verifies completion, case/search binding, retrieval
digest, verdict semantics and freshness; losing the pointer repeats paid review.
This fixes the explicit deferral in stream-d-admitted-execution.md. Gate traversal,
outcome capture/comparison remain a separate large increment. Diagnosis outcome
routes remain later. Activation stays false. No section 4 rule changes.

## Change and deletions

Add loop_freshness to diagnosis_dispatch.CARRY using the existing deep-copy path.
Do not interpret the carried outcome as authority: only existing confirm_hits
validation can reuse verdict_path. No run.py edit or new recovery mechanism.
The change deletes no code and adds no allowance, paid operation,
writer round or pass-cache rule. Lane 1 legacy allowance removal stays untouched.

## Tests and failure boundaries

Extend dispatch tests using their saved practice case and collected ledger:
authenticated admitted replay publishes loop_freshness through two replays, with
nested values deep-copied. Add loop freshness regression with local HTTP retrieval
and explicitly authored model output: finish reviewer, save scorecard pointer,
remove only binding receipt to model documented restore window, carry_context and
republish scorecard as dispatch does, then run real loop_freshness again. Assert
no second reviewer, unchanged original stress report and rebuilt binding receipt.
Repeat with missing completion marker or changed case: fallback cannot clear
without a new review. Prove public match remains G2 failure after recovery.
These are offline mechanics tests, not live interruption/model-verdict evidence.
Existing binding/expiry tests remain authoritative for confirmation rules.
Run full suite: uv run --with numpy --with scipy python -B tests/run.py. Unique log,
wait for completion, commit log/result. Fresh design review before code, fresh diff
review after tests; save verbatim. Supports Murphy row 9; closes none because full
lifecycle and item 8 live qualification remain unproved.

## Cost and risk

No inference spend. Carried path is a hint, never a pass. Main risk: trusting stale
or partial answers; negative tests exercise real confirmation validator. Remaining
package and diagnosis work stays unchecked.

## Review clarifications

After a diagnosis-approved extension resumes, the factory can forget a finished
freshness review and pay for it again. This is one small implementation/review
cycle. Tests extend test_main_recovers_admitted_writer_before_ordinary_launch_twice
in tests/factory/test_stream_d_dispatch.py and use the existing harness in
 tests/factory/test_freshness_restore_fixes.py. The restore test deletes only
freshness-verdict.json, retaining review-completed.json, verdict.json younger than
24 hours, case snapshot and retrieval/. This represents a restored missing receipt;
it does not claim a live crash was observed. Only one missing-marker negative case
is added; existing changed-case/expiry coverage remains. A carried value can remain
stale if no freshness work runs, but no consumer treats it as current-round proof.
The existing 24-hour mtime limit still forces a new review after that interval.
Row 9 is supported indirectly by avoiding repeated paid work after exhaustion.
