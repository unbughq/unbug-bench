SET search_path = pg_catalog;
DO $$DECLARE t record; BEGIN
FOR t IN SELECT c.oid::regclass AS relation, g.tgname FROM pg_trigger g
JOIN pg_class c ON c.oid = g.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE NOT g.tgisinternal AND n.nspname = 'public'
LOOP EXECUTE format('ALTER TABLE %s DISABLE TRIGGER %I', t.relation, t.tgname); END LOOP;
END $$;
