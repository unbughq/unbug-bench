-- Bench-internal probe (not a contestant guard). Counts units owed by live orders per
-- inventory item and refuses an order that takes them over stock. Correct one order at a
-- time on every sales path, but it takes no lock: two orders whose inserts overlap each see
-- only the other's committed rows, so both pass. Adding FOR UPDATE on inventory_level would
-- serialize them. Used to measure whether traffic catches race-window (timing-only) guards.
CREATE FUNCTION bench_order_units_check() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  changed_order text;
  over text;
BEGIN
  IF TG_TABLE_NAME = 'order' THEN changed_order := NEW.id; ELSE changed_order := NEW.order_id; END IF;
  SELECT link.inventory_item_id INTO over
  FROM "order" o
  JOIN order_item oi ON oi.order_id = o.id AND oi.version = o.version AND oi.deleted_at IS NULL
  JOIN order_line_item li ON li.id = oi.item_id AND li.deleted_at IS NULL
  JOIN product_variant v ON v.id = li.variant_id AND v.manage_inventory AND NOT v.allow_backorder
  JOIN product_variant_inventory_item link ON link.variant_id = li.variant_id AND link.deleted_at IS NULL
  WHERE o.deleted_at IS NULL AND o.status NOT IN ('canceled', 'draft') AND NOT o.is_draft_order
    AND link.inventory_item_id IN (
      SELECT l2.inventory_item_id FROM order_item i2
      JOIN order_line_item li2 ON li2.id = i2.item_id
      JOIN product_variant_inventory_item l2 ON l2.variant_id = li2.variant_id AND l2.deleted_at IS NULL
      WHERE i2.order_id = changed_order)
  GROUP BY link.inventory_item_id
  HAVING SUM((oi.quantity - oi.fulfilled_quantity) * link.required_quantity) >
    (SELECT COALESCE(SUM(stocked_quantity), 0) FROM inventory_level
     WHERE inventory_item_id = link.inventory_item_id AND deleted_at IS NULL)
  LIMIT 1;
  IF over IS NOT NULL THEN
    RAISE EXCEPTION 'Insufficient stock for order on %', over USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER bench_order_units_check AFTER INSERT OR UPDATE ON order_item
FOR EACH ROW EXECUTE FUNCTION bench_order_units_check();
CREATE TRIGGER bench_order_units_check AFTER UPDATE ON "order"
FOR EACH ROW EXECUTE FUNCTION bench_order_units_check();
