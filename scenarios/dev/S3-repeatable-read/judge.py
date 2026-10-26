def judge(run, bench):
    setting = bench.sql("SELECT COALESCE((SELECT array_to_string(setconfig, ',') FROM pg_db_role_setting s JOIN pg_database d ON d.oid = s.setdatabase WHERE d.datname = 'medusa' AND s.setrole = 0), '')")
    return {"checks": {"repeatable_read": "default_transaction_isolation=repeatable read" in setting}, "facts": {"database_settings": setting}}
