# Provider waits design review 1

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

FAIL

- **Blocker — credential metadata is lost.** The WP5a `run_step` at `63d01f1` converts `ProviderWait` to the string `provider_wait`; `worker_step.py` classifies only that string. Missing or expired credentials therefore remain `router:provider_wait`, and the proposed status is never shown. Preserve and translate the fixed `credential_expiring` wait reason at the worker boundary, with a real router-to-worker test. An old generic `router:provider_wait` result with no retained metadata is indistinguishable from a genuine wait; keep it generic.

- **Blocker — repair does not necessarily resume work.** `model_router.py:287-294` keeps an observed credential failure blocked until an explicit healthy observation; the existing router test confirms this. Replacing a credential alone does not ensure the next attempt can acquire the route. Specify credential redistribution and clearing the router’s recorded block as part of repair, and test the actual path.

- **Blocker — replay behavior is unspecified.** The changed policy and new status/sleep operations alter the sequence of DBOS operations when an existing case replays an old provider result. The durable design requires workflow changes behind `DBOS.patch()`. Specify replay-compatible branching and test recovery from an old credential-result sleep and an old threshold decision, as well as a crash during the new wait.

- **Blocker — the public status will be rejected.** `report.py:18-19,59-61` accepts only its listed statuses; `waiting_for_credentials` is absent. Add it to the report and test the public scorecard’s status and fixed reason, including publishing `running` on wake.

- **Blocker — worker release is ambiguous.** The proposed 900-second credential wait is shorter than the default 1,800-second release threshold in `contract.py:356`; following the existing sleep rule retains the worker through indefinitely repeated waits. Specify when credentials release the worker and test the default behavior. Also state the intended behavior for repeated short genuine-provider waits.

The frozen `max_spent_limits_per_step` field can remain serialized and validated while being ignored for genuine provider limits, as the design says. Paid limits must continue settling as batch waste and remain subject to the cumulative batch bound. No tests were run; this was a read-only review.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–5 | Revision 2 specifies WP5a metadata translation, the later credential-delivery/router repair gate, the disposable-draft replay boundary, report status and release on every wait. Fresh review and implementation remain pending. |
