# WP1 admission probe diff review 1

Fresh read-only goldfish; zoom_out and implementation_readiness; Mode: REVIEW.
Reviewed commit `8bc391b`. Verbatim response:

---

FAIL

- **Major — wake events can be lost.** [engine.py:840](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/engine.py:840) wakes only cases already marked `waiting`. If a settlement or bound raise is processed while a reserve is in flight, [the later WAIT result](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/engine.py:952) starts a full poll delay despite newly available money. The deadline can pass first. [Predecessor release](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/engine.py:992) also does not wake a waiting probe, although the design lists it as a trigger. Record a wake generation or latch for in-flight probes, and wake on predecessor release. Test both orderings with a fresh retry key.

- **Major — an in-flight probe can admit after STOP is processed.** Once [authorization](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/engine.py:908) has been given, a STOP handled during `reserve_step` does not prevent [the positive grant handoff](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/engine.py:943). The existing [STOP test](/private/tmp/unbug-durable-execution-review-20261105/tests/factory/test_durable_admission_queue.py:88) covers only a probe still queued. Serialize STOP with the probe decision, or safely zero-settle an in-flight grant when STOP wins before handoff. Test a delayed reserve with STOP processed before it returns.

- **Major — zero-settlement replay is untested.** The [expiration test](/private/tmp/unbug-durable-execution-review-20261105/tests/factory/test_durable_admission_queue.py:126) does not restart, and the [crash cases](/private/tmp/unbug-durable-execution-review-20261105/tests/factory/test_durable_admission_queue.py:246) cover an unrecorded reserve or an admitted grant. Add WAIT and EXPIRED crashes after the clock decision and zero settlement, restart with a backward clock and raised bound, and verify the settled key is never handed off or reused.

Read-only review; no tests were run.

---

## Resolution

| Finding | Disposition |
|---|---|
| Wake generation and predecessor release | Added a per-probe wake generation and predecessor-release wakes, with real DBOS tests for wakes before and after WAIT; fresh verification pending. |
| STOP during reserve | Added fenced probe-side cancellation and zero settlement before acknowledging STOP, with a delayed-reservation test; fresh verification pending. |
| Zero-settlement replay | Added WAIT and EXPIRED kill/restart tests with the clock moved backwards and a raised-bound fresh-key retry; fresh verification pending. |
