# A change has landed

Merged PR #412 'express checkout': new POST /store/express-orders creates the order directly
(createOrderWorkflow) and a new step reserve-order-batch writes all of its reservations in one
batch. The cart checkout is unchanged.

The merged diff is `/app/changes/s2-express-checkout/app.patch` (paths relative to `projects/medusa/`).

Decide whether your protection still holds: keep, repair, withdraw safely or escalate.
Leave your guard in `/app/guard/` and rewrite `/app/claims.json` for this checkpoint (same
format as before). Paths now: `store-checkout`, `draft-order`, `order-edit`, `cancel-resale`,
`express-checkout`.

Reporting rules: see the 'Reporting' section of /app/CONTESTANT.md.

The change is already deployed to your running app: any `app.patch` is merged into `projects/medusa` and the app rebuilt (your `guard/app.patch` on top); any `admin.sql` was applied to the live database, and `bin/reset` keeps it. Customers shop in the background (`bin/shoppers`, log `/app/results/shoppers.jsonl`).
