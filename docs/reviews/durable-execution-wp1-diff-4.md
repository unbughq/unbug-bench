# WP1 fixes diff review 4

Fresh read-only goldfish; zoom_out and implementation_readiness; Mode: REVIEW.
Reviewed WP1 at `b5babec`. Verbatim response:

---

**FAIL at `b5babec` — three blockers remain in completed-output verification.**

1. **A killed decrypt is treated as invalid ciphertext.** [executor.py:157](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/executor.py:157) treats `open_failed` as conclusive. The real [AgeSealer](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/artifacts.py:147) uses that same code for every nonzero decrypt exit, including termination by SIGKILL. A transient killed decrypt therefore discards a valid DONE result and can rerun ADMIT or SEAL. Distinguish conclusively invalid ciphertext from an ambiguous process failure, and test a killed decrypt followed by successful verification.

2. **A received DONE result is not durable while verification waits.** [attempt_step](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/engine.py:165) journals its result only after [verification returns](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/executor.py:110). If verification is temporarily unavailable, the control process restarts, and the original worker is then lost, recovery cannot recover the already-received result even though its ciphertexts reached the store. It returns `infra:worker_lost` and may rerun completed work. The [contract](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/contract.py:576) says workers are a cache, not state. Durably preserve the received result as provisional before verification, and test restart plus worker loss while verification is blocked.

3. **The local store can report a transient filesystem error as absence.** [LocalObjects.exists](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/artifacts.py:324) uses `Path.is_file()`. On the workspace’s Python 3.14, it suppresses `OSError`, including transient `stat` EIO, and returns `False`. [Verification](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/executor.py:160) treats that as confirmed missing and discards the DONE result. Distinguish confirmed absence from operational errors and test the real local backend with a transient stat failure.

The **positive-spend money-growth fix passes this review**: fully granted batch-only money stops double the next request, and the DBOS regression covers repeated positive-spend stops.

Separate production risks remain: the admission queue and terminal reconciliation are unfinished; the enabled path retains the dispatch-version and global-slot ordering risks; and WP5a provider waits, WP8 credentials and fresh-database rollout, WP11 snapshot settings, and WP10 lineage remain integration gates. A prolonged verification outage also holds the attempt’s queue slot and grant.

No tests, writes, network access, or infrastructure actions were performed.

---

## Resolution

| Finding | Disposition |
|---|---|
| Ambiguous age failure | Open; `open_failed` must not be treated as conclusive invalidity. |
| Provisional DONE durability | Open; the proposed design separates receipt from verification. |
| Local stat failure | Open; the local backend must distinguish missing from I/O failures. |
| Positive-spend growth | Verified by this review. |
