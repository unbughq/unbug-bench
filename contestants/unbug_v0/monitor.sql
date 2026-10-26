-- Unbug v0 outcome query, run as the monitor role. Returns one JSON object:
--   orders_total: every order row the monitor can see (blindness canary)
--   over: inventory items where units owed on live orders exceed stocked units
-- Starting point read from Medusa 2.19 migrations, NOT verified against a live DB.
-- Unbug must check it in the establish step (place one order, watch "owed" move) and fix it.
-- Live = placed, not canceled, not a draft; owed = quantity not yet fulfilled, current order version.
-- Backorder and unmanaged variants are excluded (the promise does not cover them).
WITH live AS (
  SELECT li.variant_id, oi.quantity - oi.fulfilled_quantity AS units
  FROM "order" o
  JOIN order_item oi ON oi.order_id = o.id AND oi.version = o.version AND oi.deleted_at IS NULL
  JOIN order_line_item li ON li.id = oi.item_id
  WHERE o.deleted_at IS NULL AND NOT o.is_draft_order AND o.status NOT IN ('canceled', 'draft')
), owed AS (
  SELECT link.inventory_item_id, sum(live.units * link.required_quantity) AS owed
  FROM live
  JOIN product_variant pv ON pv.id = live.variant_id AND pv.manage_inventory AND NOT pv.allow_backorder
  JOIN product_variant_inventory_item link ON link.variant_id = pv.id AND link.deleted_at IS NULL
  GROUP BY 1
), stock AS (
  SELECT inventory_item_id, sum(stocked_quantity) AS stocked
  FROM inventory_level WHERE deleted_at IS NULL GROUP BY 1
)
SELECT json_build_object(
  'orders_total', (SELECT count(*) FROM "order"),
  'over', (SELECT coalesce(json_agg(json_build_object('inventory_item_id', owed.inventory_item_id,
                                                      'owed', owed.owed, 'stocked', coalesce(stock.stocked, 0))), '[]')
           FROM owed LEFT JOIN stock USING (inventory_item_id)
           WHERE owed.owed > coalesce(stock.stocked, 0)));
