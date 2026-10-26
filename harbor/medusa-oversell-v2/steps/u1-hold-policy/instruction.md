# An operations change has landed

Ops now clears expired manual holds using the existing reservation API. No policy for manual holds is documented in the change.

Leave your guard in `/app/guard/` and rewrite `/app/claims.json`. Response: `keep`, `repair`, `withdraw` or `escalate`. Claims need rule `never-oversell`, a path and status (`protected`, `unprotected`, `withdrawn-safe-fallback`, `escalated`, `unknown`). Paths: `store-checkout`, `draft-order`, `order-edit`, `cancel-resale`, `service:marketplace`. See `/app/CONTESTANT.md` Reporting.
