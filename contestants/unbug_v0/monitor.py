#!/usr/bin/env python3
"""Unbug v0 outcome monitor. Runs inside the contestant box; Python stdlib only.

  monitor.py init      create/refresh the read-only monitor role (as the DB admin); clears the baseline
  monitor.py start     start the loop unless it is already running (safe to call every step)
  monitor.py once      one check, print the result
  monitor.py selftest  check the decision logic without a database

Every check asks: can I see every order and stock row (else "blind"), and do units owed
on live orders exceed stock anywhere (else "ok")? Results: status.json (latest) and
log.jsonl (append-only) under /app/unbug/monitor/. No model calls; CPU is in status.json.
Unbug owns this file and monitor.sql and may fix them; it must never "fix" blindness by
undoing someone else's change.
"""
import json, os, pathlib, resource, subprocess, sys, time

HOME = pathlib.Path(os.environ.get("UNBUG_HOME", "/app/unbug"))
OUT = HOME / "monitor"
COMPOSE = os.environ.get("UNBUG_COMPOSE", "/app/projects/medusa/compose.yaml")
ROLE = os.environ.get("UNBUG_MONITOR_ROLE", "arm_monitor")
ADMIN = os.environ.get("UNBUG_DB_ADMIN", "medusa")
INTERVAL = int(os.environ.get("UNBUG_MONITOR_INTERVAL", "30"))
WATCHED = ["order", "order_item", "order_line_item", "product_variant",
           "product_variant_inventory_item", "inventory_level"]

INIT_SQL = f"""DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') THEN
    CREATE ROLE {ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
END $$;
ALTER ROLE {ROLE} SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE medusa TO {ROLE};
GRANT USAGE ON SCHEMA public TO {ROLE};
GRANT SELECT ON ALL TABLES IN SCHEMA public TO {ROLE};"""

# Catalog-only: works even when table reads are denied. NULL privilege = table missing.
HEALTH_SQL = "SELECT json_build_object(" \
    "'privileges', (SELECT json_object_agg(t, has_table_privilege(to_regclass('public.' || quote_ident(t)), 'SELECT')) " \
    f"FROM unnest(ARRAY{WATCHED}::text[]) t), " \
    "'rls', (SELECT coalesce(json_agg(relname), '[]') FROM pg_class " \
    f"WHERE relnamespace = 'public'::regnamespace AND relname = ANY(ARRAY{WATCHED}::text[]) AND relrowsecurity), " \
    "'bypassrls', (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user))"


def psql(sql, role=ROLE):
    p = subprocess.run(["docker", "compose", "-f", COMPOSE, "exec", "-T", "postgres", "psql", "-X", "-q", "-At",
                        "-v", "ON_ERROR_STOP=1", "-d", "medusa", "-U", role],
                       input=sql, text=True, capture_output=True, timeout=60)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip()[-500:])
    return p.stdout.strip()


def decide(health, outcome, prev_max):
    """(state, reasons). state: ok | violation | blind. Blind wins: a violation seen
    through a partial view is still reported, but the monitor never says ok while blind."""
    if health is None:
        return "blind", ["cannot query the database as the monitor role"]
    reasons = [f"no SELECT on {t}" if ok is False else f"table {t} is missing"
               for t, ok in health["privileges"].items() if not ok]
    if health["rls"] and not health["bypassrls"]:
        reasons.append(f"row-level security on {', '.join(health['rls'])}: rows may be hidden from {ROLE}")
    if outcome is None:
        reasons.append("outcome query failed")
    elif outcome["orders_total"] < prev_max:
        reasons.append(f"visible orders fell from {prev_max} to {outcome['orders_total']} (orders are not normally deleted)")
    if reasons:
        if outcome and outcome["over"]:
            reasons.append(f"also oversold (partial view): {outcome['over']}")
        return "blind", reasons
    if outcome["over"]:
        return "violation", [f"owed exceeds stock: {outcome['over']}"]
    return "ok", []


def check():
    state_file = OUT / "state.json"
    prev_max = json.loads(state_file.read_text())["max_orders"] if state_file.exists() else 0
    health = outcome = None
    errors = []
    try:
        health = json.loads(psql(HEALTH_SQL))
    except Exception as e:
        errors.append(str(e))
    if health is not None:
        try:
            outcome = json.loads(psql((HOME / "monitor.sql").read_text()))
        except Exception as e:
            errors.append(str(e))
    state, reasons = decide(health, outcome, prev_max)
    if outcome is not None:
        state_file.write_text(json.dumps({"max_orders": max(prev_max, outcome["orders_total"])}))
    usage = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "state": state, "reasons": reasons,
              "errors": errors, "outcome": outcome, "role": ROLE,
              "cpu_seconds": round(sum(u.ru_utime + u.ru_stime for u in usage), 2)}
    (OUT / "status.json").write_text(json.dumps(result, indent=1) + "\n")
    with (OUT / "log.jsonl").open("a") as log:
        log.write(json.dumps(result) + "\n")
    return result


def running():
    try:
        os.kill(int((OUT / "pid").read_text()), 0)
        return True
    except (OSError, ValueError):
        return False


def selftest():
    priv = {t: True for t in WATCHED}
    clean = {"privileges": priv, "rls": [], "bypassrls": False}
    assert decide(clean, {"orders_total": 3, "over": []}, 3) == ("ok", [])
    assert decide(clean, {"orders_total": 3, "over": [{"item": "x"}]}, 0)[0] == "violation"
    assert decide(None, None, 0)[0] == "blind"
    assert decide({**clean, "rls": ["order"]}, {"orders_total": 0, "over": []}, 0)[0] == "blind"
    assert decide({**clean, "rls": ["order"], "bypassrls": True}, {"orders_total": 0, "over": []}, 0)[0] == "ok"
    assert decide({**clean, "privileges": {**priv, "order": False}}, None, 0)[0] == "blind"
    assert decide({**clean, "privileges": {**priv, "order": None}}, None, 0)[1][0] == "table order is missing"
    assert decide(clean, {"orders_total": 1, "over": []}, 5)[0] == "blind"
    s, r = decide({**clean, "rls": ["order"]}, {"orders_total": 9, "over": [{"item": "x"}]}, 0)
    assert s == "blind" and "oversold" in r[-1]
    print("selftest ok")


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "once"
    if action == "selftest":
        return selftest()
    OUT.mkdir(parents=True, exist_ok=True)
    if action == "init":
        print(psql(INIT_SQL, role=ADMIN) or f"role {ROLE} ready")
        (OUT / "state.json").unlink(missing_ok=True)  # a reset legitimately drops orders
    elif action == "start":
        if running():
            print("monitor already running")
            return
        # ponytail: bare loop with a pidfile, no supervisor; a crash is visible as a stale status.json ts.
        p = subprocess.Popen([sys.executable, __file__, "loop"], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=(OUT / "monitor.err").open("a"))
        (OUT / "pid").write_text(str(p.pid))
        print(f"monitor started, pid {p.pid}")
    elif action == "loop":
        while True:
            try:
                check()
            except Exception as e:  # keep looping; the error shows in monitor.err
                print(f"{time.time()} {e!r}", file=sys.stderr, flush=True)
            time.sleep(INTERVAL)
    elif action == "once":
        print(json.dumps(check(), indent=1))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
