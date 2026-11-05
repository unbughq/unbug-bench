# Admission decision queue design review 11

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL — revision 11.**

**Blocker — recovery acknowledgement is not recoverable across reaper generations.** [Generations](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:116), [response](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:174), [stable send key](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:350). A case can consume a recovery response and acknowledge reaper generation 1, which fails before receiving the acknowledgement. Generation 2 repeats the same response key, but DBOS 3.4 retains consumed notifications and suppresses that send. The design does not specify a generation-independent acknowledgement destination or durable acknowledgement record that generation 2 can consult. Waiting for an acknowledgement addressed to generation 1 can leave the reaper and batch stuck. This affects both `no_dispatch` and ordinary recovered results.

**Minimal fix:** Record the case’s operation-and-attempt acknowledgement at a stable batch- or case-owned location that every reaper generation can read. Require a new generation to finish once that fact is recorded. Test generation 1 failing after the case consumes and acknowledges the response but before the reaper receives the acknowledgement. Generation 2 must retire, later case work and batch termination must progress, and the response must be applied once. Test both response types.

The applied-operation guard and case correlation address the stale ADMIT and duplicate-response safety scenarios. The no-dispatch transition specifies zero settlement, lease and token resolution, a fresh attempt key, and preservation of the admission count, subject to the acknowledgement gap. For clarity, explicitly exempt proven `no_dispatch` from the otherwise unconditional authenticated-result requirement for closing an ADMIT fence at [lines 166–172](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:166); no such result exists on that path.

The fault tests remain to be implemented. WP2 and WP8 remain separate prerequisites.

---

## Resolution

| Finding | Disposition |
|---|---|
| Acknowledgement and no-dispatch clarity | Revision 12 records acknowledgement at a case-owned operation/attempt key and explicitly exempts proven no-dispatch. Fresh review and implementation remain pending. |
