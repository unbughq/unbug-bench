**FAIL — 1 Major finding.** Mode: REVIEW. Reviewed only the final gate-access section and `new-router-gate-wall-1` in the specified worktree, branch `t3/router-maxima-rounding`, HEAD `cb434e3`, including uncommitted design changes.

**M1 — An uncertain insertion outcome lacks a fail-closed cleanup contract.**  
Affected scope: `docs/designs/router.md:1244–1248`, `1255–1263`.

“Setup failure closes the gate” does not distinguish a rejected insertion from an insertion whose outcome is unknown. An `iptables -I` operation can install the rule before its invoking process times out or is interrupted. An unsuccessful `subprocess.run` therefore does not always prove that no exception exists.

The design specifies socket retention for failed **revocation**, but does not explicitly require that attempted, unconfirmed **insertion** enters that same cleanup path. An implementer could close the socket on setup failure, leaving a reusable port behind a live ACCEPT rule—the condition this design must prevent.

Specify that cleanup ownership starts **before attempting insertion**. For an uncertain insertion outcome, refuse CLI launch and conservatively retain the bound socket unless cleanup establishes that the exception cannot remain or subsequently appear. Apply the existing `cap_used` snapshot and `cancellation_failed` precedence when cleanup remains unresolved. Add a regression case simulating insertion taking effect before reporting a timeout; assert no launch and no port release while its outcome is unresolved.

The round-1 findings otherwise have adequate design responses:

- B1: direct, cancellation-independent firewall subprocess calls.
- M1: explicit close split, retained server references, revoke-before-release, error precedence, and `EADDRINUSE` coverage.
- M2: concrete public fixture, probe context and identities, Boat commands, attributed billing evidence, and verified deletion.
- Nits: corrected process-death and bearer-isolation claims; Murphy row remains open pending evidence.

The exact UID/address/interface/protocol/port scope is narrow. The checked chain-creation backstop matches existing `make_pilots` behavior. The stated cost calculation is consistent, conditional on the required live preflight.

No edits, tests, worker launches, or secret access performed. Round 2 supplied no verdict. This is a design verdict only; implementation, full-suite validation, live proof, and fresh diff review remain pending.


## Author response for round 4

M1 fixed: cleanup ownership starts before insertion; every attempted insertion
enters finally. Any unconfirmed insert conservatively retains the socket even
after a successful delete, because a late mutation cannot be excluded. No
launch, snapshot/error precedence, and EADDRINUSE regression are explicit.
No finding rejected. All earlier accepted responses remain unchanged.
