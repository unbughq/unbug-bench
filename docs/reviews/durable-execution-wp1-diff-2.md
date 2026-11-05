# WP1 standards and integration diff review 2

Fresh read-only goldfish, zoom_out and implementation_readiness personas,
Mode: REVIEW. Reviewed `durable-execution...de/wp1` at
`7d09daee6d373eddb4e7201d32aeea0d9b2efad2`. Verbatim response:

---

**FAIL.** The WP1 diff has the following blocking findings:

1. **INPUTS cannot be rescoped with WP3.** `factory/durable/executor.py:225–234` stores an INPUTS ref under the case ID, but merged WP3’s `factory/durable/artifacts.py:197–206` rejects case-scoped INPUTS. Every successful ADMIT therefore fails before WRITER. Settle the scope contract across WP1, WP3 and the worker, and test with the merged store.

2. **Worker outputs are not authenticated.** `executor.py:136–154` checks only existence for result refs and checkpoints. Invalid ciphertext can be recorded and later restored or published. Authenticate every ref using WP3’s `open_from` and `scope_for` before recording it, as required by the handoff.

3. **Pool failures kill the workflow and strand grants.** `engine.py:198–209` reserves before `lease_step`, which converts WP2 `PoolError` into a repeatedly raised seam error. Once retries expire, the case becomes `engine_error` and its reservation remains held. Preserve the pool’s fixed reason as an INFRA_ERROR and settle or release the grant.

4. **Replay can lose spending.** After a crash following worker start, a key or blob-fetch failure during replay reaches `executor.py:93–94`, which assumes nothing started. The engine settles zero despite the prior worker potentially spending its grant. Query the prior attempt or conservatively settle unknown usage as lost.

5. **Queued steps miss releases.** `engine.py:299–313` captures plumbing before enqueue; `engine.py:420–444` similarly captures GATES and SEAL versions. A release arriving while the queue is blocked is ignored by an attempt starting afterward, contrary to `durable-execution.md:300–311`. Resolve releases at dispatch and preserve the GATES/SEAL version check.

6. **Cancellation can time out before the worker deadline.** `engine.py:207–208` timestamps before blob fetching and pushing; WP5a starts its deadline only after dispatch. `executor.py:177–182` can thus stop retrying cancellation while the previous attempt remains live. Confirm cancellation or absence, or anchor the timeout to the worker’s actual deadline.

7. **Late batch-deadline stops eventually diagnose.** `policy.py:114–116` gives up on the 97th late `infra:deadline`, violating the handoff’s requirement that a batch-deadline stop never push a running case to DIAGNOSE. Separate these stops from worker timeouts or continue retrying them without diagnosis.

8. **Batch-only money stops impose a step cap.** `policy.py:125–133` retries only when usage reaches the grant, but `budget.py:162–165` raises `money_wait` before an unaffordable call. A diagnosis that spends $49 of a $50 grant and needs a $3 call retires despite available batch funds. Retry with a fresh grant and handle an individually oversized call safely.

9. **Admission ignores an exhausted bound.** `engine.py:533–535` checks the target and deadline but not remaining batch money. A stopped case can start a replacement while another reservation exhausts the bound, contrary to `durable-execution.md:215–220`. Include ledger availability in admission decisions.

10. **The five-extension ceiling is not enforced.** `policy.py:215–218` trusts `spec.max_extensions`, while `contract.py:371–373` accepts values above five. The newly wired engine can therefore allow a sixth progressive extension, contrary to ENGINEERING section 3. Enforce the absolute ceiling.

11. **Failed cases remain “running” in the scorecard.** `engine.py:611–614` records `engine_error` only in batch-local state; `report.py:104–112` reads the stale case event. Reconcile workflow failures into the published card.

The operator-pause and BATCH-limited zero-spend money-stop paths are present. The free-limit test gives up on the **97th** result; the handoff’s “at 96” wording should be reconciled with that behavior. WP1 consumes `retry_at`, but `de/wp5a:factory/durable/worker_step.py:509` does not pass a known `reset_at` to the classifier; that requires follow-up in WP5a.

No finding relies solely on a smell heuristic. This was a read-only review; no tests were run.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–11 | Open; fix and fresh verification required. |
| Free-limit wording and WP5a reset time | Open; reconcile before the relevant merge. |
