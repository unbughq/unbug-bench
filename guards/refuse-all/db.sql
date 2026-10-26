CREATE FUNCTION bench_refuse_reservation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Reservations refused by calibration guard' USING ERRCODE = '23514';
END $$;
CREATE TRIGGER bench_refuse_reservation AFTER INSERT OR UPDATE ON reservation_item
FOR EACH ROW EXECUTE FUNCTION bench_refuse_reservation();
