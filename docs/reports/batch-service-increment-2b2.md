# Stream B increment2b.2 and held-status validation

Rebased cleanly onto factory-simplify49b178b. Accounting commit22894b2
(pre-rebase6a69978), status commitf334be1 (pre-rebase23e29b1). Source diffs
of B implementations are unchanged by rebase. Current recorded HEAD5067d5d.

Accounting: final design15 PASS after accepted design14 findings; diff13 PASS.
Status: batch-status-held-design-2 and batch-status-held-diff-1 PASS. Fresh
post-rebase integration review14 PASS at5067d5d, including independent
verification of the146-script full-suite footer. All reviews are retained verbatim. No blocker was rejected.

Full command: uv run --with numpy --with scipy python -B tests/run.py
Post-rebase result:146 test scripts run;0 failed. Log SHA256: 75543e9f50e4a9e3f50cb548af4f4d4708aecda3ba31e0ea522d0a3cc12f007e.
The prior143-script pre-router baseline passed. Two overlapping intermediate
runs were superseded/stopped on requested rebase; neither is qualification.
One intermediate attack-recovery timing failure passed all18 focused tests on
the rebased tree and passes the authoritative full run above. No code change was
made for that transient. Focused accounting12, real-D projection9, contract12,
status14 and inventory2 checks passed before the full run.

Delivered: pure collection_facts consumer of D's case_spending/usage_coverage,
public receipt arithmetic and immediately previous estimated map, null coverage,
known overrun preservation, P-R-epsilon, no duplicate release; strict projection
provenance before facts replay, null-safe total normalization, and actual D
known/null infrastructure pending/completed no-child regressions. Status renders
factory_bug_held unscored with factory bug: see finding <id>; saved-card tests
cover stopped/lifecycle precedence, malformed-ID redaction and read-only snapshot.
Tests use saved ledgers and clearly authored operational/receipt transitions;
none is a live qualification artifact. DIAGNOSIS_ENABLED remains False.

Remaining production prerequisites: reviewed durable ACK/publication, source
transition/installer history, holder scoped restore/operation binding and
capacity dispatch integration; deployment onto the real control VM; D's held
producer/contract update; bounded practice route fitting the3-dollar model cap.
49b178b bounds only Claude at50 dollars per lease, so live money admission cannot
fit the authorized practice cap. Parent notified; A must provide the reviewed
cheap route/lower test lease cap. No override or larger spend is authorized.

The VM read-only preflight and hashes are in batch-service-vm.md and its JSON.
No workers exist in the observed complete inventory, but controller retirement
has not been proved for rollout. No VM mutations, workers or real exam cases.
Live spend:0 model/0 incremental infra; reviewer usage unmeasured and separate.
Murphy rows closed:none. new-batch-service-3 records malformed-state activation
handling; new-batch-service-4 records cross-batch carry-over, explicitly deferred
until after2b.2 and the E2E test. No carry-over implementation.

Migration founder command dry-run passed; exact command and expected output are
in batch-service-migration-readiness-20261030.md. No real key used. No merge/push.
