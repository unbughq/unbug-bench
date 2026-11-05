# Provider waits design review 5

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL — two integration blockers remain.** The two findings from design review 4 are resolved in revision 5: it selects terminal waits separately from earlier serial waits, and it specifies reset validation and the 900-second fallback.

- **Incomplete usage can turn a genuine limit into a case failure.** The engine context is non-factory (`de/wp5a:factory/run.py:3319–3323`). An interrupted Claude or Codex call with incomplete usage can leave `unpriced_invocations` in its retained ledger (`budget.py:1349–1353`). The worker conservatively charges the attempt ceiling (`worker_step.py:576–584`), but `resume_ledger` does not resolve the marker (`budget.py:771–786`). A subsequent budget check sees unknown spend and raises `budget_exhausted` (`budget.py:612–615,719–721`), which WP4 classifies as `EXHAUSTED`. The design’s instruction to preserve interrupted-usage evidence does not specify how to reconcile or conservatively settle it while allowing the case to continue. Specify that path and test an interrupted provider limit with incomplete usage through recovery and a successful retry.

- **A quota wait can be reported as a credential problem.** Revision 5 treats the terminal `credential_expiring` reason as sufficient evidence of a credential fault. However, `de/wp5a:factory/model_router.py:295–299,334–336,371–375` also synthesizes that reason when a bounded Claude model has no eligible alternatives, including when a per-call quota failure excluded the available lane. `model_runtime.py:432–443,489–494` excludes such a lane without adding shared health. The design would consequently publish `waiting_for_credentials` despite healthy credentials. Make that reason reflect verified credential evidence, and test an excluded-lane quota failure through the real router-to-worker path.

The WP1 policy and fake-seam slice can proceed. **Real integration remains gated** on the WP5a router-to-worker tests and the WP8 verified credential-delivery and scoped health-update tests, including stale and concurrent observations. No files were changed, and no tests, jobs, network calls, or infrastructure operations were run.

---

## Resolution

| Finding | Disposition |
|---|---|
| Unknown interrupted usage | Open WP5a integration blocker; the runner must preserve evidence, conservatively account for unknown prior usage and allow a new attempt without inventing a case-money stop. |
| Ambiguous credential reason | Open WP5a integration blocker; the router must distinguish verified credential trouble from excluded-lane quota waits. |
