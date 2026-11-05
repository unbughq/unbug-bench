# WP1 admission probe diff review 4

Fresh read-only goldfish; zoom_out and implementation_readiness; Mode: REVIEW.
Reviewed the event-storm test at `20f9ed9`. Verbatim response:

---

FAIL

**Major — the test does not prove that two unrelated events arrived before the retry reservation.** In [test_durable_admission_queue.py:202](/private/tmp/unbug-durable-execution-review-20261105/tests/factory/test_durable_admission_queue.py:202), the test waits for the second reservation, then reads a list that the actor continues to append to. Both counted unrelated events could arrive after the reservation. This does not satisfy the explicit interval required by [review 3](/private/tmp/unbug-durable-execution-review-20261105/docs/reviews/durable-execution-wp1-probe-diff-3.md:22). Record the reservation in the same ordered trace and count events only up to that point.

The new `None` assertion does prevent the original timeout-only implementation from passing in this scenario: the instrumented receive records a timeout before the actor can enter `after_poll` and schedule the retry.

Read-only review; no tests were run.

---

## Resolution

| Finding | Disposition |
|---|---|
| Unbounded observation interval | Record the beginning of the second reservation on the same trace and check unrelated events and timeouts only before that marker. Verification pending. |
