**REQUEST CHANGES — one Major blocks implementation readiness.**

**Major — Emergency deletion cannot pass the proposed command fence while EX is busy.** [Design line 103](/Users/bugsincode/Developer/unbug-bench/docs/designs/boat-final-usage-before-delete.md:103) requires managed `delete` calls to acquire SH and reject the retiring marker; the exception at line 118 requires an inherited EX FD. But [line 195](/Users/bugsincode/Developer/unbug-bench/docs/designs/boat-final-usage-before-delete.md:195) requires emergency deletion to proceed while another process holds EX. The reused [_delete transport](/Users/bugsincode/Developer/unbug-bench/factory/boat_lifecycle.py:253) invokes `boat-call`, so this emergency caller would either wait behind EX or fail the fence. Neither reaches the provider within the stated deadline.

Specify the exact **delete-only emergency authorization** at `bin/boat-call`, including its ownership/deadline validation and binding to the atomic-intent winner. It must work without EX while preserving refusal of other mutations and duplicate DELETEs. Extend the contention exam to exercise this wrapper boundary and assert that the provider DELETE is invoked.

The pinned stop contract, durable proof/schema compatibility, historical `$0.036` hold and existing-launcher reuse otherwise address the prior findings.

Read-only review completed. No edits, tests, Docker, network, credentials or delegation.

## Parent disposition

Major accepted and fixed in the design. The existing atomic delete-intent claim moves to boat-call for fenced requests, so the wrapper itself determines the unique winner. Only exact canonical DELETE after independently validated ownership/envelope/generation and recomputed policy deadline may bypass a busy EX; other mutations remain fenced. The deadline winner alone records metering-bypassed. The real wrapper contention exam must observe one actual authored-provider invocation and refuse duplicates/foreign/future/extra-flag mutations. Existing no-ID uncertainty is preserved. A fresh focused verification checks this corrected interface before implementation; no finding rejected.
