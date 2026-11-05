# Provider waits policy diff review 1

Fresh read-only goldfish; zoom_out and implementation_readiness; Mode: REVIEW.
Reviewed `ea8f705..230d8e4`. Verbatim response:

---

**BLOCKED:** The implementation follows the new policy on inspection, but the required verification has gaps.

1. **Repeated short waits:** [test_durable_engine.py:237](/private/tmp/unbug-wp1-provider-code-20261105/tests/factory/test_durable_engine.py:237) runs 97 short provider waits but does not assert that each worker is released. The former threshold-based release could return without failing this test. Assert a release for every wait under the default threshold, including a fresh lease on retry.

2. **Both credential result shapes:** [test_durable_engine.py:256](/private/tmp/unbug-wp1-provider-code-20261105/tests/factory/test_durable_engine.py:256) exercises only the new `INFRA_ERROR` shape. Revision 5 requires fake-seam coverage of the older `PROVIDER_LIMIT` shape too. Exercise both through the engine, including visible status, release, retry, and preservation of the infra retry allowance.

3. **Kill during the durable wait:** [test_durable_engine.py:266](/private/tmp/unbug-wp1-provider-code-20261105/tests/factory/test_durable_engine.py:266) kills after observing a card and pool release, but the release log can appear before `DBOS.sleep` is recorded. Synchronize on the sleep being recorded and still pending before killing, then verify replay preserves its wake time and resumes.

No runtime policy or settlement defect was confirmed. Paid provider limits settle as batch waste, and the frozen contract is unchanged.

**Separate integration gates:** WP5a must prove the real router-to-worker metadata and supervisor-deadline paths. WP8 must prove scoped credential-health repair and delivery to newly provisioned workers, enforce the fresh-generation database gate, and publish with the fixed-reason allowlist. These gates are outside this diff.

No tests were run; this was a read-only review.

---

## Resolution

| Finding | Disposition |
|---|---|
| Repeated short waits | The real-DBOS 97-wait test checks a distinct lease and recorded release for every short wait; diff review 2 confirms this finding.  |
| Credential result shapes | A real-DBOS fake-worker test covers both result shapes, visible waits and releases, and a subsequent ordinary infra retry; it passes. |
| Kill during durable wait | The kill/restart test waits for the recorded future sleep, verifies its journal row and wake boundary after restart, and passes. |
