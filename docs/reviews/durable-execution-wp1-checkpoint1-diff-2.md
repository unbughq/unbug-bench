# WP1 disabled admission bookkeeping diff review 2

Fresh read-only goldfish; zoom_out and implementation_readiness; Mode: REVIEW.
Reviewed checkpoint fixes at `5acefe2`. Verbatim response:

---

**FAIL — one blocker remains in checkpoint 1.**

- **Blocker: the real-DBOS test does not establish the required message ordering or duplicate delivery.** [test_durable_admission_bookkeeping.py](/private/tmp/unbug-durable-execution-review-20261105/tests/factory/test_durable_admission_bookkeeping.py:190) sends `done` and `line_stopped` at equal timestamps but does not observe which the batch handles first. It can pass with the request first, leaving `done` before request unproved. The repeated sends reuse their idempotency keys, so DBOS suppresses them before `_BatchV2.handle`. Add controlled real-DBOS cases that record and assert the handling order, deliver repeated facts with distinct message IDs, and separately verify same-key suppression.

- **Major: a post-cleanup failure is reported as a cleanup failure.** [report.py](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/report.py:130) sets `cleanup_error=True` for every failed workflow with a verified seal. Yet [engine.py](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/engine.py:342) can release the worker successfully and then fail while publishing the card or sending `done`. Record cleanup completion independently, or represent its outcome as uncertain, and test a failure after successful release.

The verified-seal event is recorded after archive authentication; the loader tests cover valid and stale evidence through the scorecard, the DBOS cleanup-failure test checks batch seal counting, and text rendering exposes the cleanup flag. The restart test uses the same application version and database.

I did not run tests, edit files, or assess later queue, reconciliation, limit, or rollout work.

---

## Resolution

| Finding | Disposition |
|---|---|
| DBOS ordering and duplicate delivery | Added observed done-before-request and release-before-request cases, equal timestamps, distinct duplicate IDs and same-key suppression across restart; verified by checkpoint diff review 3. |
| Cleanup evidence | Added an independent cleanup-complete event and a real DBOS post-release fault test; verified by checkpoint diff review 3. |
