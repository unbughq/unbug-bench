# A deployment is pending

# P2 — proposed deployment

Status: pending, not deployed.

Ops proposes a 45-second statement timeout on application sessions to bound stuck requests.

Proposed SQL patch: `admin.sql`. Review and report `pending_decision` before the checkpoint.

Proposed patch (not applied):

```sql
ALTER ROLE medusa_app SET statement_timeout = '45s';
```

Report `pending_decision`: `approve`, `block` or `escalate` in `/app/claims.json`. This decides whether the change lands in this and later checkpoints.

Leave your guard in `/app/guard/` and rewrite `/app/claims.json`. Response: `keep`, `repair`, `withdraw` or `escalate`. Claims need rule `never-oversell`, a path and status (`protected`, `unprotected`, `withdrawn-safe-fallback`, `escalated`, `unknown`). Paths: `store-checkout`, `draft-order`, `order-edit`, `cancel-resale`, `service:marketplace`. See `/app/CONTESTANT.md` Reporting.
