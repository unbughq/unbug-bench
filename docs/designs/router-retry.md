# Router retry (2026-11-20)

Kept out of the top-level ARCHITECTURE.md on purpose: top-level *.md files are part of the G8/G9 gate identity (factory/gate_state.py STAGE_DEPENDENCIES), so editing them would make any later plumbing release rerun G8/G9 on held cases. Fold into ARCHITECTURE.md when no held case depends on it.

Paid credit check, replacing the sentence "live wallet credit is checked separately on every paid request":

credit is checked separately on every paid request (a refused request still records the balance it saw)
against the balance the reconcile loop reads every 60 s (`Store.refresh_credit`; read live only when that is
over `CREDIT_FRESH_SECONDS`, 120 s, old), counting every hold granted since that read, so no provider round trip
sits on the request path; a cached balance too short for the request is read again live before it refuses. The gate asks a `paid_reserve` with no definite answer (a lost reply, the router's
4 s self-refusal) again with the same request id for up to 30 s; only a `credit` refusal ends the call at once.
A lease renewal whose reply is lost is retried every 10 s until 30 s before the lease would expire; a router
refusal still ends the call. A request with no eligible lane at all waits as `router:no_route`, a
provider-limit sleep to the router's retry time (only a worker sending `capacity_protocol` 2 is told
`no_route`; an older one still gets `outage`).
