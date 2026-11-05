# Admission budget design review 6

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL — revision 6 is not yet sufficiently specified for the guarded increment.** The design resolves several earlier findings, but it contains a worker-capacity deadlock and a release-version regression. It also relies on a WP2 creation guarantee that its current implementation does not establish.

1. **Blocker — barrier fairness can deadlock worker capacity.**  
   `docs/designs/durable-execution-admission-budget.md:70–78, 116–129, 144–149, 163–170`

   With one available worker, let admitted case B own it and approach SEAL. The batch admits A, installs A’s first ADMIT barrier, and A waits for worker creation because B owns the only capacity. A third pending case C is eligible, so the fairness rule defers B’s new SEAL barrier until A’s acknowledged barrier closes. B cannot run SEAL and release its worker; A cannot acquire a worker and close its barrier.

   Specify a protocol that breaks this cycle. For example, a case blocked on a barrier acknowledgement could release its idle worker before waiting, provided cleanup and acknowledgement races are handled durably. Alternatively, defer installation of a first-ADMIT barrier until capacity is ready, while explicitly bounding preparation and preserving the admission ordering guarantees. Add a deterministic three-case, one-worker test covering the cycle, replay, and eventual progress.

2. **Blocker — release changes can bypass the required gate rerun.**  
   `admission-budget.md:131–138`; `factory/durable/engine.py:219–226, 509–517`

   Revision 6 says a dispatch child that cannot use its prepared lease returns STALE, after which the parent reinstalls or reacquires and retries the same attempt. For SEAL, the current engine instead returns `RERUN_GATES` when plumbing or bench differs from the versions that passed GATES. Retrying SEAL under a newly installed release can seal a case without rerunning the affected gates. A comparison only against the prepared lease also misses the case where preparation already chose the newer release.

   At SEAL dequeue, compare current releases with the versions that passed GATES. If either relevant version changed, do not dispatch SEAL: safely release its unstarted grant, resolve its barrier as nonterminal, and return to the gate-rerun path. Test release changes both before preparation and while queued, including replay. Preserve the existing rule for reading the latest ADMIT registry inside the serialized ADMIT queue when restructuring its child workflows.

3. **Blocker — automatic retry assumes stronger WP2 create idempotence than the implementation proves.**  
   `admission-budget.md:116–129`; `de/wp2:factory/durable/workers.py:373–403, 435–481, 485–510`

   WP2 records a creation intent and may return `infra:worker_create_unknown` after a timeout and an inventory miss. On the next `acquire`, another miss clears that intent and `_create` generates a new nonce. If the original provider request can complete after the miss, its late VM is no longer the recorded worker. It can consume the only provider capacity while the replacement keeps retrying; `recover()` scans on engine start and does not itself prove that an outstanding create cannot complete afterward. The code does **not** establish duplicate model execution here, because the late worker was never returned as a lease.

   Before relying on automatic retry, either establish a provider guarantee that a negative inventory observation after timeout proves the create cannot later succeed, or change WP2 to retain and reconcile uncertain creation intents until terminal, including late-worker cleanup. The same proof should cover a nonzero create response if that response can also be ambiguous. Test a create completing after a subsequent inventory miss, capacity exhaustion, and restart.

4. **Blocker — the preparation/permit protocol and fairness eligibility are ambiguous.**  
   `admission-budget.md:28–32, 58–61, 97–105, 144–149, 163–170`

   The pending child is said to prepare a worker and *then* wait for `ADMIT_GRANTED`, but the only specified message delivering its successful attempt number is the permit. The first barrier is said to be installed with that permit before delivery. The document therefore does not say what durably tells the child it may prepare, or whether preparation can begin before the barrier exists. That matters because preparation provisions paid VMs outside the global model queue.

   Define the exact recorded sequence and payloads. A single permit installed after the first barrier could authorize both preparation and eventual dispatch; a separate preparation message is also possible if its ordering is explicit. Define “eligible pending” for the fairness rule, including a WAIT candidate before its next real wake or bounded poll, and specify deterministic selection within each priority class. Test crashes and duplicate messages at each signal boundary, and assert the intended bound on first-ADMIT worker preparations.

**Prior findings and remaining risk.** The proposal now specifies keyed pre-enqueue barriers, resolutions before immediate retry, predecessor-keyed release facts, non-paid replacement workflows, suppression of probe self-wakes, and grandfathering of admitted grants and authenticated seals. The recorded reserve and clock steps, fresh keys after WAIT or EXPIRED, and exact-lease reconciliation address the corresponding replay and ownership concerns in the written design. These claims still need the specified fault-injection tests and diff review; they do not remove the blockers above.

The parent amendment correctly distinguishes a launched waiting replacement from an admitted case. Its target wording should also make clear that an admitted case whose execution has not begun is grandfathered, since the following target paragraph still refers to cases “already running.”

The pre-enqueue barrier remains a reasonable small approach without changing the frozen ledger, but only if its capacity cycle is resolved. The current disabled-switch phase does not make that design decision unnecessary: its permit and worker-preparation interfaces are among the unresolved choices. A strictly inert scaffold could be written, but it would not establish a meaningful guarded admission increment.

Read-only review; no files changed and no tests run.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–4 and target wording | Open; revise the design and request a fresh review before implementation. |
