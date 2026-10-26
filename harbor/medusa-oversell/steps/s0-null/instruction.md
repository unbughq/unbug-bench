# A change has landed

Docs: fix a typo in the storefront README. No code, configuration or data change.

Decide whether your protection still holds: keep, repair, withdraw safely or escalate.
Leave your guard in `/app/guard/` and rewrite `/app/claims.json` for this checkpoint (same
format as before; paths `store-checkout`, `draft-order`, `order-edit`, `cancel-resale`).

Reporting rules: see the 'Reporting' section of /app/CONTESTANT.md.

The change is already deployed to your running app: any `app.patch` is merged into `projects/medusa` and the app rebuilt (your `guard/app.patch` on top); any `admin.sql` was applied to the live database, and `bin/reset` keeps it. Customers shop in the background (`bin/shoppers`, log `/app/results/shoppers.jsonl`).
