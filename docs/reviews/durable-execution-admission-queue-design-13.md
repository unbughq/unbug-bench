# Admission decision queue design review 13

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**PASS — revision 13 addresses both review 12 blockers.**

- The [terminal-case resolution](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:202) requires proof that the case cannot continue and safe resolution of its worker, grant and fence. It is keyed by operation and attempt, observable by every reaper generation, and preserves an accepted successful SEAL.
- The [reserve-intent transition](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:136) permits `no_reserve` only after proving the holder and synchronous operation quiescent. An existing intent instead requires quiescence and exact idempotent reserve recovery. A fresh probe uses a new key and authorization.

Neither repair relies on CANCELLED alone proving quiescence or an absent event alone proving a call cannot run. Both specify the requested fault scenarios. No corrections are required for these two blockers.

Read-only review; no tests were run. This verdict does not resolve the separate policy conflict, code checkpoint, WP2 or WP8.

---

## Resolution

| Finding | Disposition |
|---|---|
| Review 12 findings | Design verification passed; implementation and fault tests remain pending. |
| Policy, checkpoint, WP2 and WP8 | Separate work remains open. |
