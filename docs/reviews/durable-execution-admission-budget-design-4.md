# Admission budget design review 4

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL — revision 4 is not ready for a safe initial implementation.** The pre-settlement handshake addresses the original settlement-before-notification race in the normal path, and the non-paid replacement workflow addresses the immediate-launch interpretation. The remaining blockers affect replay, liveness, and the ability to implement the stated behavior without guessing.

1. **Blocker — immediate retries can leave a barrier open forever.**  
   `docs/designs/durable-execution-admission-budget.md:94–105`; `factory/durable/engine.py:384–409`.

   The case must resolve an attempt’s barrier before sleeping, waiting, or returning. The current policy also has immediate `RETRY` paths that do none of those: for example, an ADMIT pool failure can settle at zero and immediately enqueue another attempt. Under the written rule, the first key remains open even if the retry succeeds, permanently blocking new admissions.

   Require a keyed resolution for **every** ADMIT and SEAL attempt, including before an immediate retry is enqueued. Test a failed first attempt followed by a successful retry and assert that both keys close and pending admissions resume.

2. **Blocker — a recorded unknown-usage result does not prove the worker stopped.**  
   `admission-budget.md:123–146`; `factory/durable/contract.py:657–670`; `factory/durable/engine.py:144–151, 212–213`.

   The reconciliation procedure permits a recorded result with an unknown-usage code to settle lost, but requires worker-death or tombstone proof explicitly only when the attempt result is absent. `guarded_run` can synthesize `engine:executor_raised` after dispatch; recording that result does not prove the detached worker stopped. The current retry path also ignores a false cancellation confirmation. A later attempt could therefore run beside it.

   Apply the same exact-lease poll/cancel and proof requirement to unknown-usage results whether or not a result was recorded. Keep the terminal barrier until that proof and the recovered decision exist, and do not start a retry after an unconfirmed cancel. The test at line 173 states the stronger requirement, but the transition itself needs to specify how to meet it.

3. **Blocker — replacement dispatch can race the stopped case’s worker release.**  
   `admission-budget.md:69–79, 107–114`; `engine.py:115–125, 205–223, 302–315`.

   The batch may grant and send the replacement’s permit as soon as it receives `line_stopped`; the stopped case releases its worker afterward. With one available worker, or a delayed release, the replacement can reach `lease_step` while capacity is still occupied. Current pool failures consume the ADMIT infrastructure-retry allowance and can end in `STOP_ADMISSION` before release succeeds.

   Preserve immediate creation and grant priority, but define how the replacement waits for capacity without exhausting its retry allowance—for example, gate its execution on confirmed predecessor release, or specify a durable capacity wait that does not count as an infrastructure failure. Also specify continued cleanup after a release step exhausts its finite retries or its case workflow fails. Test delayed and transiently failing release with a one-worker pool, including recovery.

4. **Blocker — pending-work wakeups, termination, and reporting are not implementable from the plan as written.**  
   `admission-budget.md:28–42, 52–60, 148–179`; `factory/durable/report.py:18–20, 42–48, 104–120`.

   Excluding probe settlements prevents the original self-wake loop, but revision 4 no longer states which external settlements, bound raises, or bounded polls retry a WAIT probe, how queued requests are selected on a wake, or when the batch may finish with pending workflows. Those choices determine whether a replacement ever runs after another case frees a hold. In addition, the required public `pending_admission` status is rejected by the current report whitelist, and the plan does not name the reporting changes or specify the final status for `NOT_ADMITTED`.

   Specify the event loop, retry triggers and bounded polling, pending-work cancellation and batch-exit conditions, status transitions, and the affected reporting files and tests. Verify that a real settlement and a bound raise each unblock eligible work, while a probe’s own settlement does not spin. The implementation phases must also say how phase 1 provides a valid permit before phase 2 moves the first reservation to the batch, or keep the incomplete path disabled until its dependencies are present.

5. **Blocker — the ordering of queued barrier messages versus subsequent probes is ambiguous.**  
   `admission-budget.md:83–105`.

   The text says only a probe already in progress when `barrier_open` arrives is ordered first, while also disallowing FIFO assumptions. If the barrier is queued alongside other events, a batch that processes an unrelated event first may start another probe before consuming the barrier. The handshake still prevents that attempt’s settlement before acknowledgement, but it does not by itself establish the stated arrival-time ordering.

   Define the linearization point the implementation can enforce. If it is batch processing of `barrier_open`, say that explicitly and specify fair processing so queued barriers cannot be starved by probe triggers. If arrival time itself must stop later probes, use a shared atomic gate. Test an already queued barrier alongside multiple settlement and bound events with reordered and tied delivery.

The target and seal behavior also needs explicit tests. In particular, an ADMITTED decision made before the target is reached must retain its grant and permit even if the case has not yet executed; that case may finish later, and every authenticated seal from already-admitted cases must be kept and counted exactly once. Test this alongside a successful seal followed by cleanup failure and a second seal after the target. Revision 4 describes recovery of a known seal, but does not pin these grandfathered cases in the verification plan.

**Prior findings:** Review 1’s accepted deadline interpretation and review 2’s start-retry blocker are addressed in the design. Zero case money, positive sub-minimum `NOTHING`, and suppression of probe self-wakes are specified. Review 3’s pre-settlement handshake and immediate pending replacement address the principal normal-path races, but its reconciliation, worker-liveness, ordering, and implementation-readiness findings remain open in the cases above. The revised tests are broader, but do not yet establish all of those transitions or stable phases.

A smaller option worth evaluating is to install a keyed terminal barrier **before enqueueing** each ADMIT or SEAL attempt, then close it with one case-reported resolution after the attempt has settled. The first ADMIT barrier could be installed with the permit. This removes the attempt’s separate pre-settlement handshake and the need to join independent `settled` and resolution halves; failure reconciliation is still required. Its tradeoff is that pending admissions wait for the entire queued or running terminal attempt, rather than only its settlement window, so it needs an explicit throughput and liveness decision. Another option is a separately reviewed additive ledger operation that atomically opens an opaque barrier with settlement and checks barriers during reservation; that would require coordinated changes to the frozen contract and ledger implementation.

Read-only review; no files changed and no tests run.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–5 and target tests | Revision 5 specifies per-attempt pre-enqueue barriers, exact-lease reconciliation, capacity gating, wakeups and target tests. Fresh review and implementation remain pending. |
