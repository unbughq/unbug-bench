# Protect the shared-stock shop

Read `/app/CONTESTANT.md`. Medusa 2.19.0 and the marketplace channel are running and sell the same stock. Marketplace code and read-only monitor details are in `/app/projects/marketplace/README.md`.

Supply `/app/guard/` (`db.sql`, `app.patch` and/or `services.patch`) and `/app/claims.json`. Use response `keep` once established.

Leave your guard in `/app/guard/` and rewrite `/app/claims.json`. Response: `keep`, `repair`, `withdraw` or `escalate`. Claims need rule `never-oversell`, a path and status (`protected`, `unprotected`, `withdrawn-safe-fallback`, `escalated`, `unknown`). Paths: `store-checkout`, `draft-order`, `order-edit`, `cancel-resale`, `service:marketplace`. See `/app/CONTESTANT.md` Reporting.
