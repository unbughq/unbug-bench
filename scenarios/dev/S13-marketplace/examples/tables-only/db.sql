CREATE FUNCTION bench_check_reservation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  stock numeric;
  live numeric;
  owed numeric;
BEGIN
  IF NEW.deleted_at IS NOT NULL OR NEW.allow_backorder THEN RETURN NEW; END IF;
  SELECT stocked_quantity INTO STRICT stock FROM inventory_level
    WHERE inventory_item_id = NEW.inventory_item_id AND location_id = NEW.location_id
      AND deleted_at IS NULL FOR UPDATE;
  SELECT COALESCE(SUM(quantity), 0) INTO live FROM reservation_item
    WHERE inventory_item_id = NEW.inventory_item_id AND location_id = NEW.location_id
      AND deleted_at IS NULL AND NOT allow_backorder;
  -- Deleting or shrinking a reservation does not free stock while its order still owes the
  -- units. For every order line ever reserved here whose order is live (not deleted,
  -- canceled or draft), add the unfulfilled units its live reservations no longer hold.
  -- Lines never reserved are skipped: Medusa creates the order before reserving it.
  -- ponytail: Medusa only soft-deletes reservations outside compensation; a raw hard
  -- DELETE leaves no row to find. Record deletions in a guard table if that path matters.
  SELECT COALESCE(SUM(GREATEST(
      (oi.quantity - oi.fulfilled_quantity) * link.required_quantity
      - (SELECT COALESCE(SUM(h.quantity), 0) FROM reservation_item h
         WHERE h.line_item_id = li.id AND h.inventory_item_id = NEW.inventory_item_id
           AND h.deleted_at IS NULL AND NOT h.allow_backorder), 0)), 0) INTO owed
  FROM (SELECT DISTINCT line_item_id FROM reservation_item
        WHERE inventory_item_id = NEW.inventory_item_id AND location_id = NEW.location_id
          AND NOT allow_backorder) ever
  JOIN order_line_item li ON li.id = ever.line_item_id AND li.deleted_at IS NULL
  JOIN order_item oi ON oi.item_id = li.id AND oi.deleted_at IS NULL
  JOIN "order" o ON o.id = oi.order_id AND oi.version = o.version AND o.deleted_at IS NULL
    AND o.status NOT IN ('canceled', 'draft') AND NOT o.is_draft_order
  JOIN product_variant_inventory_item link ON link.variant_id = li.variant_id
    AND link.inventory_item_id = NEW.inventory_item_id AND link.deleted_at IS NULL;
  IF live + owed > stock THEN
    RAISE EXCEPTION 'Insufficient stock for reservation' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER bench_check_reservation AFTER INSERT OR UPDATE ON reservation_item
FOR EACH ROW EXECUTE FUNCTION bench_check_reservation();
