# Provider waits policy diff review 2

Fresh read-only goldfish; zoom_out and implementation_readiness; Mode: REVIEW.
Reviewed WP1 at `728857d`. Verbatim response:

---

**BLOCKED:** Two test-evidence gaps remain at commit `728857d`. No runtime policy defect was confirmed.

1. **Major — legacy credential visibility:** In [test_durable_engine.py](/private/tmp/unbug-durable-execution-review-20261105/tests/factory/test_durable_engine.py:315), the first observation requires only that attempt 1 has ever run. Its log remains present, so both observations can fire during attempt 2’s credential wait even if attempt 1 never published the status. Assert that the first observation occurs before attempt 2 starts and the second before attempt 3 starts; check the fixed reason on each card.

2. **Major — credential sleep wake time:** [The restart test](/private/tmp/unbug-durable-execution-review-20261105/tests/factory/test_durable_engine.py:299) confirms the journal row is unchanged and the retry does not start early, but it has no upper bound. Restarting the full delay would also pass. Ensure replay begins while the original sleep is pending and assert that retry occurs near its original wake time, with appropriate timing tolerance. The separate generic provider-sleep test does not exercise this credential path.

The **short-wait finding passes**: the 97-wait test checks distinct workers and releases, and the fake pool only issues a new worker generation after release.

DBOS 3.4 source confirms that the future `completed_at_epoch_ms` identifies the recorded explicit sleep. The separately documented WP5a and WP8 integration gates remain open. No tests or network calls were run.

RTK automatically wrote truncated search-output cache logs outside the repository during one search; repository files were unchanged.

---

## Resolution

| Finding | Disposition |
|---|---|
| Credential visibility | The real-DBOS fake-worker test checks each observation's fixed reason and that it precedes the next attempt; it passes. Fresh verification pending. |
| Recorded wake time | The restart test waits during downtime, resumes before the original wake and checks early and late bounds; it passes. Fresh verification pending. |
