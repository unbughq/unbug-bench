# WP2 initial diff review 1

Fresh read-only goldfish; zoom_out and implementation_readiness; Mode: REVIEW.
Verbatim response:

---

**WP2 initial diff review: BLOCK**

Reviewed `git diff durable-execution...de/wp2` with integration ref `durable-execution` at `526e620f5fa3d29a62565ede28a9245b0e3fbc76`, merge base `db13be8f2ec5e51d453a7aea76fc16e37666bb7f`, and package head `de/wp2` at `18b2d2c472e88dbcc1034398e439a7bdf03a665c`.

1. **Blocker — An unresolved create can produce duplicate and forgotten workers.** `factory/durable/workers.py:385-403`, `:485-510`, `:452-455`. After a create times out without an ID, a complete inventory with no matching label causes the next acquire to discard the intent and create under a new nonce. Completeness of one inventory snapshot does not prove the original request cannot appear later. Recovery also drops the unresolved record; if the old worker appears after the one startup recovery, it is never found. The test at `tests/factory/test_durable_workers.py:437-449` explicitly permits a second creation and only cleans the late worker by manually invoking recovery. Preserve and reconcile the original intent until the provider gives authoritative terminal evidence, or use provider-enforced idempotency; otherwise quarantine the uncertainty. Test delayed creation across retries and restart, including appearance after startup recovery.

2. **Blocker — Deletion is not journaled before the external effect.** `factory/durable/workers.py:587-594`, `:617-628`. A crash or lost response after Boat accepts a delete but before the operation ID is written leaves `deleting` unset. A subsequent acquire can return the still-visible worker while its deletion is pending. Persist a deletion intent before issuing the request and reconcile its operation or authoritative absence before leasing or creating a replacement. Test lost responses and crashes at that boundary, including restart while the worker remains visible.

3. **Blocker — Malformed inventory can be treated as proof a live worker is dead.** `factory/durable/workers.py:338-369`, `:385-390`, `:426-433`. `_inventory` validates pagination and that rows are dictionaries, but `_find` silently ignores a recorded worker whose row has missing or malformed labels or state. `alive` then returns false and acquire may create another worker, even though the recorded worker can still be running. Treat insufficient metadata or an unrecognized state as unknown, rather than absence; only use validated evidence to declare the worker dead. Test missing labels, missing or unknown state, and malformed rows while the recorded worker remains reachable.

4. **Blocker — Recovery leaves known orphans behind.** `factory/durable/workers.py:452-456`, `:461-480`. A recorded worker in `archived` or another non-live state is removed from the journal, and the orphan loop skips it. A transient failure deleting a live orphan is also suppressed, with no durable retry scheduled. This contradicts the WP2 requirement to delete other pool-labelled workers; archived Boat workers can retain their disks. Keep cleanup ownership until deletion is confirmed, include stopped or archived pool workers, and surface or retry failures. Extend `test_dead_worker_is_replaced` to assert cleanup, and test a transient orphan deletion failure followed by recovery.

5. **Blocker — Unauthenticated ciphertext can permanently poison an immutable artifact reference.** `factory/durable/channel.py:121-132`. The SHA-256 check compares ciphertext with a checksum supplied by the same worker; it does not authenticate the ciphertext or its `Ref`. WP3’s `SealedStore` accepts an age header and stores first-wins. WP1’s later `open_from` correctly detects a bad output, but a retry producing valid ciphertext for the same plaintext and `Ref` cannot replace the poisoned object, and `_fetch` returns early on `exists`. Authenticate under the scope selected by `scope_for` before the first durable put, and define recovery for an already-invalid object. Test corrupt age-shaped ciphertext followed by valid ciphertext for the same reference using the real store and sealer.

6. **Blocker — A confirmed DONE with a permanently missing output stalls forever.** `factory/durable/channel.py:90-98`; `de/wp1:factory/durable/executor.py:110-137`, `:185-202`. Channel polling turns DONE into RUNNING whenever an output cannot be fetched. After the deadline, WP1 repeatedly cancels and polls while the worker is alive; cancellation cannot replace the worker’s first-wins DONE result, so polling never resolves. Provide a bounded reconciliation path that distinguishes a confirmed finished attempt with unavailable output and yields a safe infrastructure outcome without accepting an invalid reference. Test a live worker whose DONE output remains missing or corrupt through the deadline; the existing channel test supplies the missing output later.

**Cross-package integration blockers**

- `de/wp1:factory/durable/engine.py:1122-1137` never calls WP2’s `BoatPool.recover()`. The WP2 note requires recovery on engine startup, but the frozen `WorkerPool` protocol does not expose it. Define and invoke the lifecycle seam before recovered work can race it, and test startup with a recorded worker and an orphan.
- `de/wp5a:factory/durable/worker_step.py:629-631` defaults `BENCH` to the release directory. WP2 ships only factory files there (`factory/durable/workers.py:180-184`); the full baked bench is `~/unbug-bench`, which WP2 fingerprints at `:573-575`. Real steps therefore target an incomplete bench. Point the worker at the baked bench while importing factory code from the release, and test the actual WP2 bundle with the actual WP5a command.

**Handoff contract checks**

1. The `bx_` to `bx-` mapping round-trips the captured Boat IDs. The accepted input domain is wider than the inverse: for example, `a_b` becomes `a-b` and does not map back. Restrict accepted IDs or make the mapping reversible; this is separate from the unverified real CLI.
2. `build_bundle` includes top-level `factory/durable/*.py`, including `worker_step.py` once WP5a is integrated. It does not include the planned `factory/durable/steps/` subdirectory; wave 2 must address that.
3. WP2 and WP1 use the same `<digest>.<kind>.age` blob name. Checkpoint fetching assumes the attempt’s `out/`; it remains unexercised until WP5f.
4. The WP1 engine’s `lease_for` path preserves a validated `PoolError.reason` as an infrastructure result.
5. `cancel()` returns `None`, and WP1 retries it based on subsequent polling. The unavailable-output case in finding 6 prevents that reconciliation from finishing.

WP1 authenticates result and lost-attempt checkpoint references through `open_from`, using `scope_for`, before returning them to the engine. WP2 sends scope keys in the start frame on stdin and does not put them in Boat arguments. The real Boat label behavior, CLI pin, Medusa build, and real `worker_release.py` qualification remain unverified as stated in the handoff.

No tests, network calls, database access, checkouts, or file modifications were performed.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–6 | Open; fixes and verification follow after WP1 in the specified merge order. |
| Cross-package blockers | Open; coordinate lifecycle and bench fixes on their owning packages before integration. |
| Handoff checks | ID domain and later bundle/checkpoint dependencies remain open as noted. |
