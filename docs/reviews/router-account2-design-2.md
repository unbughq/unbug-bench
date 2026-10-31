**B1 rejection upheld. The transport default change does not block this router-only increment.** Admission and credential transport are separate: `await_lease()` refuses a missing selected credential, and runtime loads the leased account’s key. Documented B-owned activation prerequisites suffice; changing launch defaults or deploying is outside scope.

**One blocker remains in the design’s B2 response: its existing automatic round-trip claim is inaccurate.**

- `account_handoff.choose()` accepts only `terminal_stop == 'provider_wait'`.
- `launch.sh:568` and `:597` invoke handoff planning/application only for `provider_limit:*`. The automatic same-worker path therefore skips the new wait.
- `launch_accounts()` gives `initial_accounts.claude=2` precedence over `choose()`. With the required activation policy, a relaunch requesting fallback account 1 still transports account 2.

Calling `choose/apply` directly in a test would not establish that either controller path performs the round trip. This is potentially repeated waiting, not merely bounded handoff latency.

**Smallest resolution:** correct the design’s transport claim and explicitly assign working controller integration and its round-trip verification to B’s pre-activation prerequisites. That documentation correction suffices for this admission-only increment; transport implementation need not enter this branch.

Other responses:

- **M1 accepted:** `credential_expiring` waiting is compatible with the requested provisioning semantics. HTTP `ValueError` becomes `router_unavailable`; refusal is not inherently more correct. Test that waiting never admits account 1 without qualifying evidence.
- **M2–M5 substantially addressed:** label identity remains an explicit founder-owned activation prerequisite; predicate, ordering, capacity, fixture attribution, cost and verification are sufficiently specified for this small increment.
- Preserve the promised admission, FIFO, expiry and lease-continuity tests. Full-suite and fresh diff review remain required.

**Verdict: B1 is not a blocker; fix the B2 documentation overclaim before design PASS. No activation work is required here.** Read-only review; no tests run.

## Elephant response

Accepted B2 correction. Removed the automatic transport round-trip claim and
assigned controller wiring plus real round-trip verification to B before activation.
B1 rejection upheld independently; M1 accepted; other clarifications retained.
No remaining design blocker after this documentation correction.
