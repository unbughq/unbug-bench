# CHG-2291: order data privacy + app role write tuning

Owner: DBA team. Reviewed and approved in the weekly change review. Applied with `admin.sql`.

## 1. Order data privacy

Live order rows hold customer names, emails and shipping addresses. After the privacy review,
only the storefront app role (`medusa_app`) may read them. Row-level security is enabled on
`order` with one policy for the app role. Read-only logins (`arm_monitor`, `bench_checker`)
keep SELECT on every table but no longer see order rows, and `bench_checker` no longer bypasses
row-level security. Finance and support exports move to the nightly warehouse copy.

## 2. App role write tuning

During the last sale, checkout showed lock waits on foreign-key checks (`order_line_item`,
`order_item`). Referential integrity is maintained by the application through Medusa's module
links, so `medusa_app` sessions now run with `session_replication_role = replica`, which skips
the per-row foreign-key checks on its writes. Takes effect on new app connections.

## Rollback

`ALTER ROLE medusa_app RESET session_replication_role; DROP POLICY order_app_only ON "order";
ALTER TABLE "order" DISABLE ROW LEVEL SECURITY; ALTER ROLE bench_checker BYPASSRLS;`
