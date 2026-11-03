# Three-case real pilot — design only
Founder decision (2026-11-02): replace full item 8 with a small REAL PILOT:
three fresh real cases, diagnosis ON, existing accounts, after practice passes
and lane 2 finishes item 7. This document grants no launch or spending authority.
Goal: observe real outcomes and at least one diagnosis; not all cases must seal.

## Scope and remaining work

Exactly three fresh cases, one batch, concurrency one; no dry-run or legacy input.
Propose replacement_policy.enabled=false for this bounded three-case pilot;
retirement ends that case, not a fourth case. Founder must approve this scope.
At most six worker lifecycles: three initial plus one diagnosis/checkpoint resume
each; extensions must fit those lifecycles and existing time/money authority.
S = config/small seam; M = one bounded code increment; L = integrated lifecycle work.

| Gap | Size | Exact required change / evidence before activation |
|---|---|---|
| Pilot admission | M | HOLDER_ENABLED=False; practice.py admits only one plumbing batch. Add a release/manifest-authenticated pilot opt-in to existing batch_holder.active/key_holder/batch.bind call sites; keep old/practice IDs off and general default off. No second launch API. |
| Diagnosis scheduling | L | DIAGNOSIS_ENABLED=False; batch_service.plan has no production caller and ordered_queue is metadata only. Wire authenticated collected generations to plan and drain its resume requests through existing holder.reserve/dispatch; persist replay identity, enforce ACK/retirement/money checks. Scope diagnosis activation to the pinned pilot; toggling the constant alone is insufficient. |
| Item-7 completion | L (lane 2) | Consume merged writer/stress/gate/comparison and factory-bug/retirement routing; qualify an actual queue-to-resume-to-diagnosis-to-outcome cycle. Do not invent missing adapters; factory-bug results hold for a separate reviewed fix. |
| Multiple lifecycles | L | bin/boat-spend refuses any other reserved/finished/reconciled_expired row. Implement reviewed attributed settlement in its existing ledger before pilot admission, including practice liabilities; retain charges/unknown holds cumulatively, never reset or use another home to evade the refusal. |
| Cleanup/deployment | M | Generalize practice_cleanup's hard-coded batch/activation binding for this pinned pilot on the same holder path. Require ready PID/policy/operation/launch binding before each dispatch, worker-start+30m collection < +45m deletion < +60m TTL; persist the six-creation bound and absolute deadline. |
| Manifest, routes, pins | S config + M headroom | Three ordinary jobs, fresh case IDs and authenticated S=0, $20 authority each/$60 batch; no practice.py reuse. Reuse batch.build/verify and qualify-batch-inputs, with a pilot pin wrapper instead of practice's exact manifest. Explicit five-role AND diagnosis routes must have current enforced maxima; reserve diagnosis headroom before initial work using those maxima, not an invented call price. |
Review/test each gap with locked suite and fresh review before switch-on.
Supersede the item-8 matrix and manual/global activation; keep evidence/journals. No rows closed.
Relevant open obligations: Murphy 9 (diagnosis), new-batch-service-4 (carry),
new-isolation-settlement-1 and new-stream-d-current-comparison-1; assess their
actual applicability against merged item 7, not this proposal's optimism.

## Money proposal — founder approval required

Propose $20 per case INCLUDING diagnosis, extensions, retries and unknown holds:
3 × $20 = $60 model/list-equivalent total; fresh baselines are zero.
Source: factory/batches/b-practice-20261031.json requested_total_usd=20;
docs/designs/stream-d.md records a $15.0531879 writer call, so $5/case is no success guarantee.
Propose $5 infrastructure TOTAL across all six possible lifecycles, not $5 each:
each lifecycle may draw only the remaining shared $5; total proposal is $65.
This reuses practice-run.md's founder-accepted prepaid balance/no-top-up/TTL bound,
subject to founder acceptance for multiple workers; it is not a provider quote.
Actual paid OpenRouter stays inside the EXISTING shared min($11.63, observed credit)
ledger ceiling, less prior charges/holds (router-shared-paid-spend.md); never refill/reset.
Subscriptions still count at list-equivalent cost toward $20/$60. Practice spend
is separately reported; neither old holds nor used wallet credit becomes fresh money.

## Steps, stop rules and pass

1. Founder approves $65 ceilings, three-case/no-replacement scope, six lifecycle cap,
   existing-account labels/distinctness waiver if retained, and a <=6h absolute window;
   refresh/rewrap credentials locally to founder+control recipients; key stays on Mac.
2. After practice PASS and item-7 PASS, pin the merged pilot release and UTC deadline;
   verify CLI version, credential lifetime, router/credit/R2, empty inputs and cleanup.
3. Admit three jobs sequentially via key-holder; collect/ACK, diagnose and route
   outcomes only through that same holder path. Retain case/usage/lease/operation IDs.
4. Abort admissions on cap/refusal, unknown settlement/ownership, duplicate creation,
   invalid diagnosis, unsafe cancellation, failed publication or deadline; cleanup stays
   armed until every created VM has completed deletion receipts plus full absence inventory.
5. Pass: all three have attributable terminal outcomes, >=1 genuine diagnosis and
   authenticated routed outcome, no duplicate spend/work, full money reconciliation,
   verified deletion and all caps met. All-sealed/no-diagnosis or cap stops are incomplete;
   missing proof is never a pass. Founder receives outcomes/costs and decides any next run.
