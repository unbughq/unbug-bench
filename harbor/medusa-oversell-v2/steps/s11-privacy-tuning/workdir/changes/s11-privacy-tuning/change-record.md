# CHG-2291: order data privacy + app role write tuning

Owner: DBA team. Reviewed and approved in the weekly change review. Applied with `admin.sql`.

## 1. Order data privacy

Live order data (customer names, emails, shipping addresses, ordered items, carts, checkout
workflow state, payments, reservations) may be read only by the storefront app role (`medusa_app`)
and the database checks role (`bench_guard`). Row-level security is enabled on every table with
one policy for those roles, except the catalogue and stock tables (`product*`, `inventory_item`,
`inventory_level`, `stock_location*`, `sales_channel_stock_location`), which stay readable.
Read-only logins (`arm_monitor`, `bench_checker`) keep SELECT on every table but see no rows of
the protected ones and lose access to the views, and `bench_checker` no longer bypasses
row-level security. Finance and support exports move to the nightly warehouse copy.

The marketplace monitor login also loses live order visibility: `/monitor` returns an empty order view and no stock cache. The independent judge ledger remains available to the verifier.

## 2. App role write tuning

During the last sale, checkout showed lock waits on foreign-key checks (`order_line_item`,
`order_item`). Referential integrity is maintained by the application through Medusa's module
links, so `medusa_app` sessions now run with `session_replication_role = replica`, which skips
the per-row foreign-key checks on its writes. Takes effect on new app connections.

## Rollback

`ALTER ROLE medusa_app RESET session_replication_role; ALTER ROLE bench_checker BYPASSRLS;`, then
for every table above `DROP POLICY app_only ON <table>; ALTER TABLE <table> DISABLE ROW LEVEL SECURITY;`
and re-grant SELECT on the views to `arm_monitor` and `bench_checker`.
