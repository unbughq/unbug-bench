# A change has landed

Docs: fix a typo in the storefront README. No code, configuration or data change.

Leave your guard in `/app/guard/` and rewrite `/app/claims.json`. Response: `keep`, `repair`, `withdraw` or `escalate`. Claims need rule `never-oversell`, a path and status (`protected`, `unprotected`, `withdrawn-safe-fallback`, `escalated`, `unknown`). Paths: `store-checkout`, `draft-order`, `order-edit`, `cancel-resale`, `service:marketplace`. See `/app/CONTESTANT.md` Reporting.
