# WP1 specification diff review 1

Fresh read-only goldfish, implementation_readiness persona, Mode: REVIEW.
Reviewed `durable-execution...de/wp1` at `7d09daee6d373eddb4e7201d32aeea0d9b2efad2`.
Verbatim response:

---

**FAIL — nine blocking findings.**

1. **Blocker — INPUTS scope prevents every admitted case from progressing.** `factory/durable/executor.py:225–234` reseals INPUTS into the case scope. Merged WP3’s `artifacts.py:197–207,248–265` rejects case-scoped INPUTS, which the frozen contract classifies as batch-scoped. After ADMIT, `engine.py:393` exhausts its retries and the case ends in error. The permissive fake store masks this incompatibility.

2. **Blocker — output references are not authenticated.** `executor.py:136–154` checks only existence for returned refs and checkpoints. The WP1/WP2 handoff requires WP3’s `open_from` and `scope_for` before recording them. Corrupt, wrong-key, or digest-mismatched ciphertext can therefore be recorded as a successful snapshot, registry, or archive. Test invalid ciphertext and mismatched digests, not just missing objects.

3. **Blocker — pool failures terminate the workflow and strand money.** `engine.py:198–209` reserves a grant before `lease_step`; WP2 `PoolError` becomes `SeamError`, so exhausted step retries abort the case without settlement. `executor.py:88–94` also replaces the pool’s specified reason with `infra:dispatch_failed`. Route the fixed pool reason as an INFRA_ERROR and settle the unstarted reservation.

4. **Blocker — a late completed result is discarded.** If polling remains unreachable through the first cancellation window but recovers before retry, `executor.py:177–182` reduces the previous attempt’s DONE result to a boolean; `engine.py:204–208` ignores it and starts another attempt. Completed work and an ADMIT registry update can be repeated or lost, contrary to the no-rerun requirement in `durable-execution.md:91–104`.

5. **Blocker — the cancellation deadline can precede the worker’s deadline.** `engine.py:207` records time before blob transfer; WP2 pushes blobs afterward, while WP5a starts its deadline only when its supervisor starts. After a sufficiently long transfer, `executor.py:100–118,177–182` can abandon an unconfirmed cancel while the worker is still live. Another ADMIT can then run on a different worker, violating `durable-execution.md:269–271`.

6. **Blocker — batch-deadline stops eventually diagnose.** `policy.py:114–116` gives up on the 97th late `infra:deadline`, routing an ordinary step to DIAGNOSE. This contradicts the handoff requirement that batch-deadline stops never do so. `tests/factory/test_durable_policy.py:183–193` currently asserts that incorrect boundary.

7. **Blocker — admission continues after the batch bound is exhausted.** `engine.py:533–535,555–566` records waiting cases but does not consider the bound in `admission_open`. A second case stopping can launch a replacement while the batch has no available money, contrary to `durable-execution.md:215–220`.

8. **Blocker — ADMIT bypasses `max_concurrency`.** `engine.py:311–313,655–659` uses a separate ADMIT queue outside the steps queue. With `max_concurrency=1`, ADMIT and WRITER can run concurrently. The WP1 note acknowledges the extra slot, but the reviewed design requires a slot for model steps (`durable-execution.md:183–184`).

9. **Blocker — completed cases retain Boat workers.** `engine.py:279–282,508–518` finishes cases without releasing their leases. WP2 recovery adopts recorded workers, so sealed and retired cases leave VMs running across batches, accumulating cost and capacity use.

**Minor —** `engine.py:200–202` settles a sub-minimum unstarted reservation without sending the `settled` wake event. Other waiters eventually retry on their polling timeout rather than waking on every settlement as specified.

**Checks performed:** Reviewed the pinned diff, design, WP1 note, contract, handoff, tests, WP2 channel and pool, and merged WP3 artifacts. Pause routing, the 96 free-limit allowance, positive BATCH money-wait routing, blob names, and `infra:cancelled` settlement were inspected. `reset_at` belongs at WP5a’s classifier call; its current call omits it and needs WP5a follow-up. No tests were run, per the read-only instruction.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–9 | Open; fix and fresh verification required. |
| Minor | Open; evaluate with the fixes. |
