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

-- Plausible wrong reading: every reservation is a customer commitment, so never delete one.
CREATE FUNCTION refuse_expired_hold_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.description = 'expired manual hold' AND
     (TG_OP = 'DELETE' OR (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL)) THEN
    RAISE EXCEPTION 'Hold deletion refused' USING ERRCODE = '23514';
  END IF;
  RETURN COALESCE(NEW, OLD);
END $$;
CREATE TRIGGER refuse_expired_hold_delete BEFORE UPDATE OR DELETE ON reservation_item
FOR EACH ROW EXECUTE FUNCTION refuse_expired_hold_delete();

-- A refused workflow can leave an order behind if its later compensation fails.
-- Reject overcommitted order transactions themselves, before any such order can persist.
CREATE FUNCTION practice_check_commitment() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE items text[]; bad text;
BEGIN
  IF TG_TABLE_NAME = 'reservation_item' THEN
    items := ARRAY[NEW.inventory_item_id];
  ELSIF TG_TABLE_NAME = 'order_line_item' THEN
    SELECT array_agg(DISTINCT inventory_item_id) INTO items FROM product_variant_inventory_item
      WHERE variant_id = NEW.variant_id AND deleted_at IS NULL;
  ELSIF TG_TABLE_NAME = 'order_item' THEN
    SELECT array_agg(DISTINCT link.inventory_item_id) INTO items
      FROM order_line_item li JOIN product_variant_inventory_item link ON link.variant_id = li.variant_id
      WHERE li.id = NEW.item_id AND link.deleted_at IS NULL;
  ELSE
    SELECT array_agg(DISTINCT link.inventory_item_id) INTO items
      FROM order_item oi JOIN order_line_item li ON li.id = oi.item_id
      JOIN product_variant_inventory_item link ON link.variant_id = li.variant_id
      WHERE oi.order_id = NEW.id AND link.deleted_at IS NULL;
  END IF;
  IF items IS NULL THEN RETURN NULL; END IF;
  -- Lock affected stock only: unrelated SKU transactions need not wait for one another.
  PERFORM id FROM inventory_level WHERE inventory_item_id = ANY(items) AND deleted_at IS NULL
    ORDER BY inventory_item_id, location_id FOR UPDATE;
  WITH owed AS (
    SELECT link.inventory_item_id,
      SUM(GREATEST(oi.quantity - COALESCE(oi.fulfilled_quantity, 0), 0) * link.required_quantity) AS units
    FROM "order" o JOIN order_item oi ON oi.order_id = o.id AND oi.version = o.version AND oi.deleted_at IS NULL
    JOIN order_line_item li ON li.id = oi.item_id AND li.deleted_at IS NULL
    JOIN product_variant v ON v.id = li.variant_id AND v.deleted_at IS NULL AND v.manage_inventory AND NOT v.allow_backorder
    JOIN product_variant_inventory_item link ON link.variant_id = v.id AND link.deleted_at IS NULL
    WHERE o.deleted_at IS NULL AND o.status NOT IN ('canceled', 'draft') AND NOT o.is_draft_order
      AND link.inventory_item_id = ANY(items)
    GROUP BY link.inventory_item_id
  ), held AS (
    SELECT inventory_item_id, SUM(quantity) AS units FROM reservation_item
    WHERE deleted_at IS NULL AND line_item_id IS NULL AND NOT allow_backorder AND inventory_item_id = ANY(items)
    GROUP BY inventory_item_id
  ), stocked AS (
    SELECT inventory_item_id, SUM(stocked_quantity) AS units FROM inventory_level
    WHERE deleted_at IS NULL AND inventory_item_id = ANY(items) GROUP BY inventory_item_id
  )
  SELECT i.inventory_item_id INTO bad FROM
    (SELECT inventory_item_id FROM owed UNION SELECT inventory_item_id FROM held) i
    LEFT JOIN owed o USING (inventory_item_id) LEFT JOIN held h USING (inventory_item_id)
    LEFT JOIN stocked s USING (inventory_item_id)
    WHERE COALESCE(o.units, 0) + COALESCE(h.units, 0) > COALESCE(s.units, 0) LIMIT 1;
  IF bad IS NOT NULL THEN
    RAISE EXCEPTION 'Insufficient stock for live commitment: %', bad USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER practice_commit_order AFTER INSERT OR UPDATE ON "order"
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION practice_check_commitment();
CREATE CONSTRAINT TRIGGER practice_commit_item AFTER INSERT OR UPDATE ON order_item
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION practice_check_commitment();
CREATE CONSTRAINT TRIGGER practice_commit_line AFTER INSERT OR UPDATE ON order_line_item
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION practice_check_commitment();
CREATE CONSTRAINT TRIGGER practice_commit_hold AFTER INSERT OR UPDATE ON reservation_item
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION practice_check_commitment();
