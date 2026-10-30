# Verbatim goldfish review

**Verdict: PASS — no Blocker or Major findings remain.**

Reviewed frozen HEAD `fc589e68bab1a4186c666aadc38d94efc5316df4`, the revised router follow-up, interfaces §§2/3/4/7, both prior reviews and responses, audit/reference artifacts, and relevant code. Read the founder’s current `ENGINEERING.md` directly.

- **Review 3 Major 1 is resolved.** `cap_used` v1 defines field types, disjoint request categories, held allowances counted exactly once, immutable close behavior, and the precise `final_usage_known` predicate. The validated-plus-truncated example is consistent.
- **Review 3 Major 2 is resolved.** Phase 4 explicitly requires actual pinned Linux CLI retries through the same gate, retained uncertain allowances, exhaustion preventing another forward/account fallback, and `model_call_cap` surviving cleanup.
- **The financial design is coherent.** Both W and validated settled usage retain the existing `2*1.1` estimator multiplier. Independently checked: W at 32,768 output tokens is **$19.041792**; aggregate token ceilings are **113,636,363 input** and **1,136,363 output**. The documented provider context and thinking limits support the per-request bound. [Context limits](https://platform.claude.com/docs/en/build-with-claude/context-windows), [pricing](https://platform.claude.com/docs/en/models/opus-5-5/overview).
- **Numerical and interruption verification is actionable.** The design requires additional admission headroom and an exact, non-epsilon regression proving already-booked usage remains within the Lease maximum when every HTTP response completed but the CLI final result was lost.
- **Availability claims are appropriately limited.** Independent repricing reproduced **143 aggregate-plus-W fits, 2 aggregate failures, and 8 inconclusive prefixes**. These aggregates prove neither complete request compatibility nor live completion. The design discloses that all current rotation packages remain unqualified.

The prior review’s remaining requirements are addressed: authentication, accepted operational scope, protocol/environment controls, unscored cap-stop propagation, zero-capacity waiting, and drained rollout. No unrelated redesign is needed.

This is a **design/readiness pass**. Implementation, Linux gate integration, the full suite, and fresh diff review remain required; production qualification remains with B’s separately authorized practice run.

No files changed, compilation, CLI probes, model calls, or production operations occurred.

## Author response

PASS accepted. Implement frozen design at fc589e68bab1a4186c666aadc38d94efc5316df4. No blocking finding rejected; all prior blockers and majors were fixed/reviewed. No production-readiness or Murphy closure claim follows from this design pass.

