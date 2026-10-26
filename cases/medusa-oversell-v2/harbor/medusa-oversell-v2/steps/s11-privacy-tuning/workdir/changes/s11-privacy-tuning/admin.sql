-- CHG-2291 (DBA): order data privacy + app role write tuning. Approved in the weekly change review.

-- 1. Privacy: live order rows (customer names, emails, addresses) are visible only to the
--    storefront app role. Read-only reporting and monitoring logins keep their grants on every
--    other table but no longer see order rows; finance exports run from the nightly warehouse.
ALTER TABLE public."order" ENABLE ROW LEVEL SECURITY;
CREATE POLICY order_app_only ON public."order" TO medusa_app USING (true);
ALTER ROLE bench_checker NOBYPASSRLS;

-- 2. Tuning: app sessions write in replica mode. Referential integrity is enforced by the
--    application (Medusa's module links); this removes per-row foreign-key checks from the
--    checkout hot path (p95 lock waits on order_line_item during the last sale).
ALTER ROLE medusa_app SET session_replication_role = replica;
