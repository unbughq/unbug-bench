# Verbatim goldfish review

**Verdict: FAIL — 2 Major readiness findings remain. No Blocker found.**

Reviewed frozen HEAD `3b07733473db860f88d14f30efec8313324a9d4c`, the revised maxima section, interfaces §§2/3/4/7, all review-2 findings and the author response, the pinned public audit fixture, real public receipts, and referenced current code. Read the founder’s current `ENGINEERING.md` directly. No files changed, compilation, CLI execution, model calls or production operations occurred.

**Major 1 — Freeze the `cap_used` receipt contract and its relationship to final usage.**

Scope: `docs/designs/router.md:614–620`; `docs/designs/interfaces.md:301–302`.

The design lists information that `cap_used` must contain, but does not define its serialized fields, types or counter relationships. In particular, “completed,” “unknown” and “in-flight” are ambiguous when an HTTP response ends normally but its usage is malformed. “Held USD and tokens” could include active requests, permanently retained unknown allowances, or both.

This matters because these receipts become cross-stream evidence for D’s settlement and B’s final exam. Current `ModelRuntime.call` derives `final_usage_known` from CLI outcome and ledger state; the new gate introduces uncertainty that those existing checks cannot detect.

Before implementation, specify:

- The exact `cap_used` object, numeric representation and counter definitions.
- Whether request categories overlap, and the invariant relating forwarded, validated, unknown and active requests.
- That held amounts include every unreleased allowance exactly once.
- When the final snapshot is taken and the exact rule connecting gate uncertainty to `final_usage_known`.

Include a concrete receipt example with one validated response and one truncated response. Keep gate pricing and allowance replacement distinct from ledger bookings, as already intended. This closes an API/schema decision currently left to the implementer.

**Major 2 — Explicitly require a retry probe through the actual pinned Linux CLI.**

Scope: `docs/designs/router.md:660–680`; review-2 M5.

The Linux exam explicitly includes tools, WebSearch rejection, side requests, compaction, output stops and sudo, but omits retries. Direct gate tests cannot establish that retries made by the pinned CLI re-enter the same gate and allowance. The existing audit already observed multiple HTTP attempts despite the retry environment setting, so `max-retries=0` cannot substitute for this exam.

Add a scripted fake-upstream retry scenario to phase 4. Require the actual pinned Linux CLI to encounter a retry-producing failure, and assert that every subsequent inference attempt passes through the same gate, uncertain attempts retain their full allowance, and exhaustion prevents another forward or account fallback. Require the wrapper result to remain `model_call_cap` after cleanup. This is a test-plan correction; no execution is requested during this design review.

**Assessment of the remaining review-2 findings**

- **B1:** Resolved at design level. The joint allowance permits repeated requests while preserving the pre-forward bound. The documented context and rates support `W=$9.520896` at 32,768 output tokens; blocking premium controls supports removing the fast-mode multiplier. [Context documentation](https://platform.claude.com/docs/en/build-with-claude/context-windows), [Opus pricing](https://platform.claude.com/docs/en/models/opus-5-5/overview), [fast-mode controls](https://platform.claude.com/docs/en/build-with-claude/fast-mode).
- **B2:** Resolved as a design decision: same-Opus helper inference, no forwarded hosted tools, nonfatal local rejection, unchanged G2 requirements, and mandatory Linux continuation probes.
- **B3:** Resolved: current packages remain unqualified; exact-route capacity stays zero, relaunches remain zero, and release migration plus positive capacity controls resumption.
- **M1–M4:** Authentication, accepted operational scope, protocol behavior and the enumerated environment are specified.
- **M5:** Substantially addressed, with the retry-exam omission above.
- **M6:** Addressed by B’s separately authorized practice-case exam; it must not run now.
- **M7:** Addressed: every-role unscored factory-limit propagation and no inline second cap are explicit.
- **M8:** Addressed by draining old leases before deployment.

As an independent arithmetic check, all 153 distinct saved Claude receipt aggregates fit the revised token-only conservative aggregate-plus-W inequalities. Those aggregates do **not** establish per-response ordering, hosted-tool compatibility or successful live admission. No practical availability claim or production qualification follows from them.

## Author response

Both Major findings accepted. Freeze an exact cap_used v1 schema with disjoint categories, held-all-once and immutable post-close snapshot invariants, plus the exact final_usage_known predicate and truncated-response example. Add explicit pinned-Linux retry/exhaustion/no-account-fallback exam. Parent additionally identified the existing budget partial estimator's 2*1.1 multiplier: retain it in BOTH W and validated settled gate cost, so loss of the CLI final result cannot book a partial estimate above the Lease. No estimator or old event is changed. Add interrupted real-usage regression. These fixes receive a new fresh design review; none is an author rejection.

