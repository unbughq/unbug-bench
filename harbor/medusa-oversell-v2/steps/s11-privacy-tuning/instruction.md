# A change has landed

The marketplace `/monitor` login also loses live order and stock-cache visibility.

CHG-2291: live order rows are restricted to the storefront role by row-level security; reporting and monitoring logins retain their other grants. App sessions now run with `session_replication_role = replica` to reduce foreign-key lock waits.

The change record and SQL are in `/app/changes/s11-privacy-tuning/`.

Leave your guard in `/app/guard/` and rewrite `/app/claims.json`. Response: `keep`, `repair`, `withdraw` or `escalate`. Claims need rule `never-oversell`, a path and status (`protected`, `unprotected`, `withdrawn-safe-fallback`, `escalated`, `unknown`). Paths: `store-checkout`, `draft-order`, `order-edit`, `cancel-resale`, `service:marketplace`. See `/app/CONTESTANT.md` Reporting.
