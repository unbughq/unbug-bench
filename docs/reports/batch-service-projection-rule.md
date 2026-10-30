# Present-projection derivation correction

Code: 175cba3 and 165a0fd. Review record: 8c6e836.
Fresh reviews: batch-service-diff-11.md (FAIL, accepted test-coverage finding),
batch-service-diff-12.md (PASS, no findings). The missing eligible unknown-total
priority assertion was restored; no blocking finding was rejected.

Full suite on the corrected sources:
uv run --with numpy --with scipy python -B tests/run.py
140 test scripts run; 0 failed. Focused service module: 12 tests pass.
Log: /tmp/unbug-b-projection-rule-tests.log.
SHA256: 1cc23ac33babf85e5f63123e0bda12ee33f2270e6bacf24d07933c0977410a1b.
No code or tests changed during this run; subsequent commits only changed docs.

First replacement derivation requires a present eligible D projection. None
never derives even with both predicates true. Unknown-total None still queues
same-owner settlement; eligible unknown totals prioritize settlement ahead of
replacement. Existing children survive later None projections. Stored facts
replay without re-calling D. No B stop predicate was added.

DIAGNOSIS_ENABLED remains False. D's actual pending/completed infrastructure
projection integration is an explicit 2b.2 requirement after its reviewed code
merges; the current tests prove the consumer contract using authored API answers.

Rows closed: none. Spend: $0 model / $0 incremental infrastructure. No VM
changes, worker, real exam, merge or push. Reviewer-agent usage unmeasured.
Next: finish 2b.2 design review against reviewed D interface6055678, then name
the reviewed merged D3a implementation and retained fixture sources before
implementation. Holder/source transitions and live practice remain gated.
