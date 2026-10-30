# Batch service increment 2: money authority and worker installation

Branch: t3/batch-service-control-vm. Implementation at19289c8, rebased onto
factory-simplify f2d2a16 (merged D accounting/settlement foundation). Increment1
ends at9b1fcef; increment2 follows it. Parent alone merges.

Design PASS: docs/reviews/batch-service-design-6.md. Code PASS:
docs/reviews/batch-service-diff-4.md; the trusted host import blocker from
diff-3 is fixed and covered by a fresh-process regression. Contract PASS:
docs/reviews/batch-service-diff-5.md, copied to interfaces-design-12.md, and the
latest replacement/diagnosis refinement PASS in diff-6 / interfaces-design-13
and diff-7 / interfaces-design-14 (readiness clarifications).
The failed contract review and response are preserved in diff-4 and
interfaces-design-11. No review objections were rejected.

Full suite PASS: 138 test scripts, zero failures on the rebased implementation.
Command: `uv run --with numpy --with scipy python -B tests/run.py`.
Log: /tmp/unbug-batch-increment2-final-tests.log. The earlier run's sole failure
was the independent expected worker inventory missing the three intended B
files; that expectation is fixed and its focused test passes.
Final log SHA256:
5096b1725028449403e174fdd0894eeb894f02e0f13e31de104d5fb49941debc.
No code/test/tool files changed after reviewed implementation19289c8; subsequent
commits contain only design refinements, reviews and these evidence reports.

## Delivered

- Serialized cumulative fresh-job money reservations, deadline/headroom checks,
  authoritative-first durable state and replay repair of D's projections.
- Holder-frozen config bytes/hash, checked against case/source/release before
  worker creation and delivered atomically to RAM after credentials.
- Independently verified RAM `authenticated_job_config`, checkpointed `job_money`
  and binding attributes, matching real D `job_authority.for_case`. Fresh,
  revision-transition, stale/tampered replay and history-crash tests use that
  actual consumer, not a stub.
- Manifest delivery through the verified worker release, batch-only founder+VM
  casekey wrapping, and removal of batch argv's competing monetary cap.
- Reviewed conservative unknown-total resume and receipt-backed decrease contract
  in interfaces§8 and the design, including both required live qualifications.
  Settlement resumes precede dependent admissions; exhausted owners settle
  before any further model call. Blocked requests do not block later eligible requests.
- D scheduling hook: one queue/launcher, D-owned eligibility and pending-diagnosis
  projection, ordinary same-owner diagnosis resume and deterministic authorized
  replacement chains. The parent's latest refinement passed fresh review.

## Enablement gates and evidence limits

No batch is enabled. This increment funds fresh jobs only; every new source
generation still refuses. Conservative source rebinding, collection/retirement
proofs, reconciliation and actual scheduling are increment2b obligations.
D's concrete action projection adapter and derived-job resolver must be
reviewed before enabling that integration. Diagnosis adds no launch mode or
frozen-config fields. The holder's scoped restore and
async protocol and Codex renewal still require their addenda before coding.
The real practice lifecycle, G10 tester+reviewer capacity, owner waits and
conservative-charge evidence remain required before enablement/row closure.

No Murphy rows closed. No real exam case executed or decrypted. No founder
migration executed. No VM file/service changes; the credential capability probe
was read-only, returned only booleans, and made no refresh/model request.
Live-test spend: $0 model / $0 incremental infra; reviewer usage unmeasured.

Next: generation/journal/outbox and the reviewed collection/source transition;
then scoped holder/restore, renewal/status and real VM/Boat qualification.
