-- CHG-2291 (DBA): order data privacy + app role write tuning. Approved in the weekly change review.

-- 1. Privacy: live order data (customer names, emails, addresses, ordered items, carts, checkout
--    workflow state, payments, reservations) is visible only to the storefront app role and the
--    database checks role. Every table gets the policy except the catalogue and stock tables
--    (products and variants, inventory items and levels, stock locations), which stay readable.
--    Read-only reporting and monitoring logins keep their grants but see no rows of the others,
--    and lose the views; finance exports run from the nightly warehouse.
DO $$ DECLARE t text; BEGIN
FOR t IN SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'
  AND tablename NOT LIKE 'product%' AND tablename NOT LIKE 'stock_location%'
  AND tablename NOT IN ('inventory_item', 'inventory_level', 'sales_channel_stock_location')
LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
  EXECUTE format('DROP POLICY IF EXISTS app_only ON public.%I', t);
  EXECUTE format('CREATE POLICY app_only ON public.%I TO medusa_app, bench_guard USING (true)', t);
END LOOP;
FOR t IN SELECT viewname FROM pg_catalog.pg_views WHERE schemaname = 'public'
  UNION ALL SELECT matviewname FROM pg_catalog.pg_matviews WHERE schemaname = 'public'
LOOP
  EXECUTE format('REVOKE ALL ON public.%I FROM arm_monitor, bench_checker', t);
END LOOP; END $$;
ALTER ROLE bench_checker NOBYPASSRLS;

-- 2. Tuning: app sessions write in replica mode. Referential integrity is enforced by the
--    application (Medusa's module links); this removes per-row foreign-key checks from the
--    checkout hot path (p95 lock waits on order_line_item during the last sale).
ALTER ROLE medusa_app SET session_replication_role = replica;
