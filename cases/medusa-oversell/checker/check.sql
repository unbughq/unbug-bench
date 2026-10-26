-- Only pg_catalog is searched: guard-created public functions/operators cannot
-- shadow anything the checker calls. Every table name is schema-qualified.
SET search_path = pg_catalog;
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH kit(k, item, product, single, pack, stock, backorder) AS (VALUES
  -- x: concurrent trigger; s: sequential trigger; z: legitimate concurrent pair;
  -- bo: backorder exception; d: admin draft-order conversion; e: admin order edit;
  -- r: cancel then resale, and resale after an admin reservation deletion.
  -- Fixed seed IDs; 2-pack factor frozen at 2.
  ('x', {{inventory_x}}, {{product_x}}, {{variant_single}}, {{variant_pack}}, 10, false),
  ('s', 'iitem_bench_s', 'prod_bench_s', 'variant_bench_s_single', 'variant_bench_s_2pack', 10, false),
  ('z', 'iitem_bench_z', 'prod_bench_z', 'variant_bench_z_single', 'variant_bench_z_2pack', 16, false),
  ('bo', 'iitem_bench_bo', 'prod_bench_bo', 'variant_bench_bo_single', NULL, 4, true),
  ('d', 'iitem_bench_d', 'prod_bench_d', 'variant_bench_d_single', 'variant_bench_d_2pack', 10, false),
  ('e', 'iitem_bench_e', 'prod_bench_e', 'variant_bench_e_single', 'variant_bench_e_2pack', 10, false),
  ('r', 'iitem_bench_r', 'prod_bench_r', 'variant_bench_r_single', 'variant_bench_r_2pack', 10, false)
), line AS (
  -- Current-version order lines (a confirmed order edit raises the order's version).
  -- quantity is what the order still owes: ordered minus fulfilled. Reservations are
  -- never used to count sales, so deleting one cannot hide a promise from the checker.
  -- Clamped at 0: a line fulfilled beyond its quantity owes nothing and cannot offset another.
  SELECT o.id AS order_id, o.email, o.status, o.is_draft_order, o.deleted_at IS NOT NULL AS order_deleted,
         li.variant_id, li.variant_sku, GREATEST(oi.quantity - oi.fulfilled_quantity, 0) AS quantity
  FROM public."order" o
  JOIN public.order_item oi ON oi.order_id = o.id AND oi.version = o.version AND oi.deleted_at IS NULL
  JOIN public.order_line_item li ON li.id = oi.item_id AND li.deleted_at IS NULL
), units AS (
  SELECT kit.k, line.*, line.quantity * CASE WHEN line.variant_id = kit.pack THEN 2 ELSE 1 END AS n
  FROM line JOIN kit ON line.variant_id IN (kit.single, kit.pack)
), facts AS (
  SELECT kit.k, kit.stock, kit.backorder,
    EXISTS (SELECT FROM public.inventory_item WHERE id = kit.item AND deleted_at IS NULL)
    AND EXISTS (SELECT FROM public.product WHERE id = kit.product AND deleted_at IS NULL)
    AND (SELECT COUNT(*) = CASE WHEN kit.pack IS NULL THEN 1 ELSE 2 END FROM public.product_variant
         WHERE id IN (kit.single, kit.pack) AND product_id = kit.product AND deleted_at IS NULL
           AND manage_inventory AND allow_backorder = kit.backorder)
    AND (SELECT COUNT(*) = CASE WHEN kit.pack IS NULL THEN 1 ELSE 2 END AND BOOL_AND(
           inventory_item_id = kit.item AND
           required_quantity = CASE WHEN variant_id = kit.pack THEN 2 ELSE 1 END)
         FROM public.product_variant_inventory_item
         WHERE variant_id IN (kit.single, kit.pack) AND deleted_at IS NULL) AS identity_ok,
    (SELECT COALESCE(SUM(stocked_quantity), 0) FROM public.inventory_level
      WHERE inventory_item_id = kit.item AND deleted_at IS NULL) AS stocked,
    (SELECT COALESCE(SUM(reserved_quantity), 0) FROM public.inventory_level
      WHERE inventory_item_id = kit.item AND deleted_at IS NULL) AS reserved,
    (SELECT COALESCE(SUM(quantity), 0) FROM public.reservation_item
      WHERE inventory_item_id = kit.item AND deleted_at IS NULL) AS rows_sum,
    -- Units promised on live orders: not deleted, canceled or draft. Canceling frees stock;
    -- an API-confirmed order found canceled without an API cancel fails the cross-check.
    (SELECT COALESCE(SUM(n), 0) FROM units WHERE units.k = kit.k AND NOT order_deleted
       AND NOT is_draft_order AND status NOT IN ('canceled', 'draft')) AS sold
  FROM kit
), item_facts AS (
  -- Every inventory item, not only the kits above: units owed on live orders through the
  -- catalog's own variant links (factor = required_quantity) against live stock. Kits keep
  -- their frozen factors in `facts`; this catches oversells on any other product.
  SELECT i.id AS item, i.id IN (SELECT item FROM kit) AS is_kit,
    EXISTS (SELECT FROM public.product_variant_inventory_item link
            JOIN public.product_variant v ON v.id = link.variant_id
            WHERE link.inventory_item_id = i.id AND link.deleted_at IS NULL AND v.allow_backorder) AS backorder,
    (SELECT COALESCE(SUM(stocked_quantity), 0) FROM public.inventory_level
      WHERE inventory_item_id = i.id AND deleted_at IS NULL) AS stocked,
    (SELECT COALESCE(SUM(reserved_quantity), 0) FROM public.inventory_level
      WHERE inventory_item_id = i.id AND deleted_at IS NULL) AS reserved,
    (SELECT COALESCE(SUM(line.quantity * link.required_quantity), 0) FROM line
     JOIN public.product_variant_inventory_item link ON link.variant_id = line.variant_id AND link.deleted_at IS NULL
     WHERE link.inventory_item_id = i.id AND NOT line.order_deleted AND NOT line.is_draft_order
       AND line.status NOT IN ('canceled', 'draft')) AS sold
  FROM public.inventory_item i
), per_order AS (
  SELECT order_id, email, k, SUM(n) AS units FROM units
  WHERE NOT order_deleted AND status NOT IN ('canceled', 'draft') AND NOT is_draft_order
  GROUP BY order_id, email, k
), expect(email, k, units) AS (VALUES
  ('cart-a@bench.test', 'x', 5), ('cart-b@bench.test', 'x', 7),
  ('seq-a@bench.test', 's', 5),
  ('legit-c@bench.test', 'z', 8), ('legit-d@bench.test', 'z', 8),
  ('backorder@bench.test', 'bo', 6),
  -- Admin paths: the store order and the conversion that fits must be placed.
  ('draft-store@bench.test', 'd', 5), ('draft-fit@bench.test', 'd', 5),
  -- The first R order was canceled, so the resale of its 10 units must be placed.
  ('resale-after-cancel@bench.test', 'r', 10)
), placed AS (
  SELECT e.email, EXISTS (SELECT FROM per_order p WHERE p.email = e.email AND p.k = e.k AND p.units = e.units) AS ok
  FROM expect e
), normal AS (
  SELECT COUNT(DISTINCT email) AS normal_orders_placed FROM line
  WHERE NOT order_deleted AND status <> 'canceled' AND quantity = 1
    AND variant_sku IN ('N1-SINGLE', 'N2-SINGLE', 'N3-SINGLE', 'N4-SINGLE', 'N5-SINGLE')
    AND email = 'normal-' || substring(variant_sku from 2 for 1) || '@bench.test'
), integrity AS (
  -- RLS cannot hide rows from this role, and every table read above is a plain
  -- table (not a view or other relation kind that could answer per user).
  SELECT (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user)
     AND (SELECT COUNT(*) = 9 FROM pg_class
          WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' AND relname IN (
            'order', 'order_item', 'order_line_item', 'inventory_item', 'inventory_level',
            'reservation_item', 'product', 'product_variant', 'product_variant_inventory_item')) AS checker_ok
), orders AS (
  -- Every order row with unfulfilled current-version quantities, for the bench's
  -- cross-check against API confirmations (traffic fulfils nothing).
  SELECT COALESCE(json_object_agg(o.id, json_build_object(
    'email', o.email, 'status', o.status, 'draft', o.is_draft_order, 'deleted', o.deleted_at IS NOT NULL,
    'items', (SELECT COALESCE(json_object_agg(variant_id, q), '{}'::json)
              FROM (SELECT variant_id, SUM(quantity) AS q FROM line WHERE line.order_id = o.id
                    AND variant_id IS NOT NULL GROUP BY variant_id) v))), '{}'::json) AS orders
  FROM public."order" o
), x AS (SELECT * FROM facts WHERE k = 'x'), s AS (SELECT * FROM facts WHERE k = 's'),
d AS (SELECT * FROM facts WHERE k = 'd'), e AS (SELECT * FROM facts WHERE k = 'e'),
r AS (SELECT * FROM facts WHERE k = 'r'),
admin AS (
  SELECT (SELECT ok FROM placed WHERE email = 'draft-store@bench.test') AS draft_store_placed,
         (SELECT ok FROM placed WHERE email = 'draft-fit@bench.test') AS draft_fit_placed,
         EXISTS (SELECT FROM per_order WHERE email = 'edit-store@bench.test' AND k = 'e') AS edit_store_placed,
         -- 5 store units + the 5-unit edit that fits; the refused 7-unit edit would make 12.
         EXISTS (SELECT FROM per_order WHERE email = 'edit-store@bench.test' AND k = 'e' AND units = 10) AS edit_fit_placed
),
verdict AS (
  SELECT
    (SELECT BOOL_AND(identity_ok AND stocked = stock) FROM facts) AND (SELECT checker_ok FROM integrity) AS valid,
    -- The promise: units owed on live orders never exceed stock (kits, then every other item).
    (SELECT BOOL_OR(sold > stocked) FROM facts WHERE NOT backorder)
      OR COALESCE((SELECT BOOL_OR(sold > stocked) FROM item_facts WHERE NOT is_kit AND NOT backorder), false) AS oversold,
    (SELECT COALESCE(json_agg(item ORDER BY item), '[]'::json) FROM item_facts
      WHERE NOT is_kit AND NOT backorder AND sold > stocked) AS oversold_other_items,
    -- Warning only (founder decision 2026-10-14): more reserved than stocked while no live
    -- order owes too much does not break the promise.
    (SELECT COALESCE(BOOL_OR(stocked - reserved < 0), false) FROM item_facts WHERE NOT backorder) AS overreserved,
    (SELECT BOOL_AND(reserved = rows_sum) FROM facts) AS bookkeeping_ok,
    (SELECT normal_orders_placed FROM normal) AS normal_orders_placed,
    (SELECT COUNT(*) FROM placed WHERE ok AND email LIKE 'cart-_@bench.test') AS trigger_orders_placed,
    (SELECT ok FROM placed WHERE email = 'seq-a@bench.test') AS sequential_first_placed,
    (SELECT COUNT(*) FROM placed WHERE ok AND email LIKE 'legit-_@bench.test') AS legit_orders_placed,
    (SELECT ok FROM placed WHERE email = 'backorder@bench.test') AS backorder_ok,
    (SELECT ok FROM placed WHERE email = 'resale-after-cancel@bench.test') AS resold_ok
)
SELECT json_build_object(
  'units_sold_x', x.sold, 'stocked_x', x.stocked, 'reserved_x', x.reserved,
  'available_x', x.stocked - x.reserved, 'reservation_rows_sum_x', x.rows_sum,
  'units_sold_s', s.sold, 'available_s', s.stocked - s.reserved,
  'kits', (SELECT json_object_agg(k, json_build_object('stocked', stocked, 'reserved', reserved,
            'reservation_rows', rows_sum, 'sold', sold, 'identity_ok', identity_ok)) FROM facts),
  'normal_orders_placed', normal_orders_placed, 'trigger_orders_placed', trigger_orders_placed,
  'sequential_first_placed', sequential_first_placed, 'legit_orders_placed', legit_orders_placed,
  'concurrent_oversold', x.sold > x.stocked,
  'sequential_oversold', s.sold > s.stocked,
  'oversold', oversold, 'oversold_other_items', oversold_other_items, 'overreserved', overreserved,
  'bookkeeping_ok', bookkeeping_ok, 'normal_ok', normal_orders_placed = 5,
  -- Exactly one concurrent trigger cart fits; the first sequential cart fits.
  'trigger_ok', trigger_orders_placed >= 1 AND sequential_first_placed,
  'legit_concurrent_ok', legit_orders_placed = 2, 'backorder_ok', backorder_ok,
  'draft_oversold', d.sold > d.stocked,
  'edit_oversold', e.sold > e.stocked,
  'draft_store_placed', draft_store_placed, 'draft_fit_placed', draft_fit_placed,
  'edit_store_placed', edit_store_placed, 'edit_fit_placed', edit_fit_placed,
  'draft_ok', draft_store_placed AND draft_fit_placed, 'edit_ok', edit_store_placed AND edit_fit_placed,
  'resold_oversold', r.sold > r.stocked, 'resold_ok', resold_ok,
  'checker_ok', (SELECT checker_ok FROM integrity), 'valid', valid,
  'pass', valid AND NOT oversold AND bookkeeping_ok AND normal_orders_placed = 5
    AND trigger_orders_placed >= 1 AND sequential_first_placed AND legit_orders_placed = 2 AND backorder_ok
    AND draft_store_placed AND draft_fit_placed AND edit_store_placed AND edit_fit_placed AND resold_ok,
  'orders', (SELECT orders FROM orders)
) FROM verdict, x, s, d, e, r, admin;
COMMIT;
