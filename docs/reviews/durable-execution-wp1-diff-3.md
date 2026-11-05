# WP1 existing fixes diff review 3

Fresh read-only goldfish; zoom_out and implementation_readiness; Mode: REVIEW.
Reviewed WP1 at `728857d`. Verbatim response:

---

**FAIL at `728857d` — two blockers remain in the requested scope.**

1. **A transient authentication failure discards completed work.** [executor.py](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/executor.py:161) converts any store, key-service, or sealer exception during output verification into `infra:output_missing` or `infra:output_invalid`. The engine then settles and retries the step. A temporary failure after `poll()` returned a valid DONE result can therefore rerun a completed ADMIT or SEAL, losing its registry update or repeating a seal. Preserve the completed result and retry verification of its immutable outputs; still reject conclusively invalid ciphertext. Add a regression where verification fails transiently, recovers, and records the original result without another worker start.

2. **Batch-only retries can exhaust the bound without increasing their effective ceiling.** [engine.py](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/engine.py:492) increases the next request only when the money stop reports zero usage. If each attempt spends something before reaching a call that cannot fit the $50 request, every retry requests $50 again until the batch bound runs out. Grow the request, or use another progress-aware rule that guarantees an individually oversized call can eventually fit. Add a repeated positive-spend money-stop regression; the existing growth test covers only zero spend.

The original scope and authentication changes otherwise use the batch-scoped INPUTS ref and authenticate output and checkpoint refs. The pool-failure path preserves the fixed reason and settles an unstarted grant; replay keeps the exact lease, and late results survive prolonged cancellation attempts. The late deadline retry cap and absolute five-extension ceiling are enforced. The failed-workflow scorecard overlay and verified-seal cleanup markers are present.

**Pending gates:** The admission queue and terminal reconciliation remain unfinished. In the current enabled path, release versions are read before potentially slow worker acquisition and are not rechecked at actual dispatch; the planned queue design calls for that final check. A queued ADMIT also holds a global slot while waiting for the serial ADMIT queue, which can starve other work. WP5a provider-wait integration, WP8 credential delivery and fresh-database rollout, WP11 snapshot settings, and WP10 cross-batch factory-bug lineage remain separate integration work.

No tests were run, as requested.

---

## Resolution

| Finding | Disposition |
|---|---|
| Transient output authentication | The executor retries transient store, key-service and sealer failures on the same result; focused executor and real-DBOS fake-worker tests pass. Fresh verification pending. |
| Positive-spend batch-only money stops | Fully granted batch-only money stops grow the next request regardless of prior spend; zero- and positive-spend DBOS regressions pass. Fresh verification pending. |
| Dispatch release and global-slot ordering | Open; the V2 path is under implementation and a prepared-attempt child checks release at dispatch. |
