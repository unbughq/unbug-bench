**PASS — no blocking findings or nits.** Mode: REVIEW.

Reviewed only `docs/designs/router.md` § “Invocation-local gate access through pilot_wall” and `new-router-gate-wall-1`, in the specified worktree on `t3/router-maxima-rounding`, HEAD `f833eb3`, including the uncommitted clarification. Read the required engineering rules, all three personas and standards, and rounds 1–3 with responses. Round 2 supplied no verdict.

Round 3’s M1 is resolved:

- Lines 1252–1256 establish cleanup ownership before insertion, confirm insertion only after exit zero, prohibit CLI launch on unconfirmed insertion, and require exact deletion after every attempt.
- Lines 1258–1264 require socket retention regardless of deletion success when insertion is unconfirmed.
- Lines 1272–1279 specify state/server shutdown, `_RETAINED`, usage snapshots, and `cancellation_failed` precedence.
- Lines 1296–1300 require the insertion-applied-then-`TimeoutExpired` regression, including no launch, attempted deletion, preserved usage, and `EADDRINUSE` even after successful deletion.

Earlier accepted responses remain adequate: cancellation-independent commands, exact UID/loopback/interface/protocol/port scope, checked chain-creation backstop, concrete live-probe fixture and identities, and per-worker billing/deletion evidence within the stated conditional $0.082 envelope. Code searches confirmed the existing firewall patterns and lifecycle integration points.

The Murphy row appropriately remains open pending test and live evidence. No finding was rejected.

This is a **design verdict only**. Implementation, full-suite validation, live proof, and fresh diff review remain pending. No edits, tests, launches, secret access, or merge performed.

## Author response

Accepted. No findings were rejected. Implementation and validation remain separate gates; no merge is authorized.
