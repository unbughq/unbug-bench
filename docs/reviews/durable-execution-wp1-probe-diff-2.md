# WP1 admission probe diff review 2

Fresh read-only goldfish; zoom_out and implementation_readiness; Mode: REVIEW.
Reviewed probe fixes at `73893d0`. Verbatim response:

---

FAIL

- **Major — WAIT polling can starve.** [engine.py:800](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/engine.py:800) skips `after_poll()` whenever a case event arrives, while [engine.py:865](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/engine.py:865) checks retry deadlines only there. Unrelated events arriving faster than `batch_poll_s` can delay a WAIT retry until after the admission deadline. Check due retries after events as well, and test a stream of unrelated events across the poll deadline.

- **Major — a stalled bound raise blocks the batch actor.** [engine.py:772](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/engine.py:772) calls the retrying ledger step synchronously inside the event loop. A stalled raise prevents STOP, probe results, and cancellation acknowledgements from being processed, contrary to the [non-blocking actor requirement](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:32). Run the raise outside the actor and report its completion back; test STOP and probe progress while it is stalled.

- **Major — the requested raised-bound replay case remains untested.** In [test_durable_admission_queue.py:372](/private/tmp/unbug-durable-execution-review-20261105/tests/factory/test_durable_admission_queue.py:372), WAIT recovery completes before the bound is raised; the EXPIRED recovery never raises it. Raise the bound during downtime, then restart with the reversed clock and verify the settled key is never handed off or reused.

Read-only review; no tests were run.

---

## Resolution

| Finding | Disposition |
|---|---|
| Poll starvation | Check due retries after every event and timeout; a real-DBOS event-storm test proves a fresh-key retry. Fresh verification pending. |
| Bound-raise actor blocking | Moved the ledger update to a child workflow and added tests for STOP and probe progress while it is stalled. Fresh verification pending. |
| Raised-bound replay | WAIT and EXPIRED tests now raise the fake ledger bound while the engine is down before restarting with a reversed clock. Fresh verification pending. |
