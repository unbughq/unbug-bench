# Factory-bug return target

Parent-approved after round 2. Design logic approved with the combined
row-closing fixture explicitly deferred; no third design review.

Implementation source: 9cd1a66c6b034497e37961c5fb7997a49323fe14, based on merged
land10/factory-simplify b75c9b4 (merge ae93bba).
Only production changes are diagnosis.py and diagnosis_dispatch.py:
retain the completed close_to_passing state, freeze its record in the next
diagnosis, validate live/frozen equality before new or reused admission, restore
the state with the cleared scorecard, then fall through the existing replay
router. No main change, previous-card override, new router, counter, allowance,
retry reset or activation change.

Focused tests passed: test_stream_d_resume_target.py (13),
test_stream_d_held.py (20), test_stream_d_dispatch.py (63).
The new tests use real decision/journal/freeze/finding/admission functions on
saved practice/5813be bytes, with labelled CLI, snapshot and owner-chain controls.
Owner transitions occur in place; this is not archive/restore evidence.
The completed-route seam is controlled explicitly, and no subsequent_entry or
pair-attempts qualification is claimed.

Required locked full suite:
docs/reports/stream-d-return-target-suite-20261102T153452Z-a3cd3353.json/.log
Completed: 179 scripts, 1 failed (exit 1). Only
OuterCallerTests.test_six_callers_wait_for_slow_cleanup_after_inherited_deadline
failed, for key_holder index 0: injected descendant heartbeat never appeared.
All stream-D tests passed, including the new 13; control_resume passed 24.

The exact failing method passed in a targeted process recheck, 1 test / exit 0:
docs/reports/stream-d-return-target-isolation-20261102T165025Z-7497c83b.json/.log.
This was not a quiet-host qualification (recorded load roughly 14–15). Isolation
code/tests are unchanged in this diff. Do not waive the failed full suite from
this recheck. A second locked full suite on unchanged code is queued; its final
result and fresh diff review are still required before delivery.

Murphy new-stream-d-current-comparison-1 remains OPEN, no rows closed.
Item 8 now explicitly requires:
close new-stream-d-current-comparison-1 with a real decision → extension → subsequent_entry comparison exhaustion → factory-bug hold/resume chain on retained artifacts

Retained-record corruption/missing evidence permanently holds until its original
evidence is repaired; another batch cannot guess it. Unchanged hashed runtime/
scientific versions preserve exhausted retry journals. Diagnosis stays disabled.
