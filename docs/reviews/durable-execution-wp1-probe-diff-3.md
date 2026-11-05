# WP1 admission probe diff review 3

Fresh read-only goldfish; zoom_out and implementation_readiness; Mode: REVIEW.
Reviewed probe fixes at `92b2ca2`. Verbatim response:

---

FAIL

- **Major — the event-storm test can pass with the original polling bug.** The test sends events every 20 ms but checks only that the sender thread is alive ([test_durable_admission_queue.py:178](/private/tmp/unbug-durable-execution-review-20261105/tests/factory/test_durable_admission_queue.py:178)). A scheduling or send delay longer than `batch_poll_s` lets the actor take the timeout path ([engine.py:813](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/engine.py:813)), so timeout-only polling could still produce the second reservation. Assert that no receive timeout occurs across the retry deadline.

The implementation checks due retries after events, and the bound-update child leaves the actor responsive to STOP and probe results. The WAIT and EXPIRED replay tests raise the fake bound during downtime and check that the settled key is not handed off or reused.

Read-only review; no tests were run.

---

## Resolution

| Finding | Disposition |
|---|---|
| Event-storm proof | Record actual batch receives and assert that at least two unrelated events, but no receive timeout, occur between the WAIT response and the new reservation. Verification pending. |
