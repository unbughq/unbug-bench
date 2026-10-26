"""Benchmark verdict rules, independent of Docker, paths, environment and runtime setup.

score() combines recorded API/database observations. judge_checkpoint() evaluates
scenario rules with explicit service declarations and, when needed, a narrow
scenario_verdict(scenario, result) adapter supplied by the runtime. The adapter
preserves the case judge contract without exposing runtime dependencies here.
"""

PHASES = ("normal", "trigger", "sequential", "legit", "backorder", "draft", "edit", "resale", "crowd")


STOCK = {"x": 10, "s": 10, "z": 16, "d": 10, "e": 10, "r": 10}  # frozen seed stock of tracked non-backorder kits


CROWD_STOCK = {"y": 8, "w": 24}  # frozen seed stock of the stress-crowd kits (not read by check.sql)


PATH_OF_KIT = {"x": "store-checkout", "s": "store-checkout", "z": "store-checkout", "y": "store-checkout",
               "w": "store-checkout", "d": "draft-order", "e": "order-edit", "r": "cancel-resale"}


BASE_CHECKS = ("valid", "bookkeeping_ok", "normal_ok", "trigger_ok", "legit_concurrent_ok", "backorder_ok",
               "draft_ok", "edit_ok", "resold_ok", "confirmed_orders_ok")


def kit_units(items, kits=STOCK, factors=None):
    """Units per tracked kit from {variant_id: quantity}; IDs are variant_bench_<kit>_<single|2pack>.
    factors: {variant_id: [kit, factor]} for variants created by a scenario (e.g. a 3-pack)."""
    units = dict.fromkeys(kits, 0)
    for variant, quantity in items.items():
        if factors and variant in factors:
            kit, factor = factors[variant]
            if kit in units: units[kit] += quantity * factor
            continue
        parts = variant.split("_")
        if len(parts) == 4 and parts[2] in units:
            units[parts[2]] += quantity * (2 if parts[3] == "2pack" else 1)
    return units


def confirmed_order(response):
    """The order an API response confirmed: store /complete ({type: "order", order}),
    admin draft conversion ({order}) or admin order-edit confirmation ({order_preview})."""
    data = (response or {}).get("data") or {}
    if (response or {}).get("status") != 200: return None
    return data.get("order_preview") or (data.get("order") if data.get("type", "order") == "order" else None)


def cross_check(traffic, check, factors=None):
    """Every order the API confirmed must be in the checker's database view exactly
    as requested and last confirmed: not missing, deleted, drafted or reduced, and canceled
    exactly when the admin API confirmed its cancellation. A confirmed order edit replaces that
    order's expected items; units count once per order and stop counting once canceled."""
    problems, latest, confirmed = [], {}, 0
    canceled = {c["order_id"] for phase in PHASES for c in (traffic or {}).get(phase) or []
                if (c.get("canceled") or {}).get("status") == 200}
    for phase in PHASES:
        for c in (traffic or {}).get(phase) or []:
            order = confirmed_order(c.get("response"))
            if not order: continue
            api = {}
            for item in order.get("items") or []:
                api[item["variant_id"]] = api.get(item["variant_id"], 0) + float(item["quantity"])
            confirmed += 1
            if api != {k: float(v) for k, v in c["requested"].items()}:
                problems.append({"phase": phase, "order_id": order["id"], "problem": "confirmed items differ from request"})
            latest[order["id"]] = (phase, api)
    units = dict.fromkeys({**STOCK, **CROWD_STOCK}, 0)
    for order_id, (phase, api) in latest.items():
        if order_id not in canceled:
            for k, n in kit_units(api, units, factors).items(): units[k] += n
        db = (check.get("orders") or {}).get(order_id)
        problem = ("missing from database" if db is None
            else "deleted or draft" if db["deleted"] or db["draft"] or db["status"] == "draft"
            else "canceled state differs from API" if (db["status"] == "canceled") != (order_id in canceled)
            else "items changed in database" if {k: float(v) for k, v in db["items"].items()} != api else None)
        if problem: problems.append({"phase": phase, "order_id": order_id, "problem": problem})
    return {"confirmed_orders": confirmed, "confirmed_orders_ok": not problems, "confirmed_problems": problems,
            "api_units_sold": units, "api_oversold": any(units[k] > STOCK[k] for k in STOCK)}


def crowd_check(traffic, check, api_units, factors=None, stock=None):
    """Stress crowd and burst verdict. Groups are the W crowd (burst 0) and each Y burst; Y's
    stock is restored by canceling before every burst. Within a group, a refused cart that would
    still fit the stock the group's placed carts left is a false block: with a correct guard
    stock only falls within a group, so a refused cart was too big when refused and still is.
    Oversell uses live orders in the database and the API's confirmations against frozen seed
    stock and kit factors."""
    carts = (traffic or {}).get("crowd") or []
    if not carts: return {}
    stock = stock or CROWD_STOCK
    live = [o for o in (check.get("orders") or {}).values()
            if not o["deleted"] and not o["draft"] and o["status"] not in ("canceled", "draft")]
    sold = dict.fromkeys(CROWD_STOCK, 0)
    for o in live:
        for k, n in kit_units({v: float(q) for v, q in o["items"].items()}, CROWD_STOCK, factors).items(): sold[k] += n
    groups = {}
    for c in carts: groups.setdefault((c["kit"], c.get("group") or c.get("burst", 0)), []).append(c)
    false_blocks, placed_count, violations = [], 0, []
    for (kit, name), group in groups.items():
        units = lambda c: sum(kit_units(c["requested"], CROWD_STOCK, factors).values())
        placed = [c for c in group if (c.get("response") or {}).get("status") == 200]
        placed_count += len(placed)
        left = stock[kit] - sum(units(c) for c in placed)
        if left < 0: violations.append({"group": name, "kit": kit, "path": group[0].get("path", "store-checkout")})
        false_blocks += [c["email"] for c in group if c not in placed and units(c) <= left]
    stop = (traffic or {}).get("burst_stop")
    oversold = bool(violations) or any(max(sold[k], api_units.get(k, 0)) > stock[k] for k in CROWD_STOCK)
    return {"crowd": {"sold": sold, "placed": placed_count, "carts": len(carts), "group_violations": violations,
                      "bursts": len({c["burst"] for c in carts if c.get("burst")}),
                      "burst_stop": stop, "false_blocks": false_blocks},
            "crowd_oversold": oversold,
            # A refused cancel of a placed order is refusing legitimate business.
            "crowd_ok": not false_blocks and (stop or {}).get("reason") != "cancel refused"}


def score(result):
    """Combine the database verdict with the API cross-check; any error fails the run."""
    check = result["checker"]
    api = cross_check(result["traffic"], check)
    crowd = crowd_check(result["traffic"], check, api["api_units_sold"])
    check.update(api, **crowd, db_oversold=check.get("oversold", False), db_pass=check.get("pass", False))
    check["oversold"] = check["db_oversold"] or api["api_oversold"] or crowd.get("crowd_oversold", False)
    check["pass"] = bool(check["db_pass"] and api["confirmed_orders_ok"] and not check["oversold"]
                         and crowd.get("crowd_ok", True) and not result["errors"])
    # Requests the app never answered within 30 s; traffic records them as refusals.
    check["timeouts"] = len((result["traffic"] or {}).get("timeouts") or [])
    placed = [(c.get("response") or {}).get("status") == 200 for c in (result["traffic"] or {}).get("trigger") or []]
    check["concurrent_placed"] = {(True, False): "A", (False, True): "B", (True, True): "both", (False, False): "none"}.get(tuple(placed), "n/a")


def wilson(k, n, z=1.959964):
    """Wilson 95% interval for k successes in n trials, as (low, high)."""
    if not n: return (0.0, 1.0)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** .5 / d
    return (max(0.0, c - h), min(1.0, c + h))


def inventory_judge(result, services, medusa_units, limits, backorder, window_limits=None):
    """Independent promises add to Medusa orders; a mirrored hold is never a second sale.
    Traffic receipts survive a runtime deleting or rewriting its own order ledger.
    Optional windows preserve violations before cancellations/recounts, like crowd groups.
    """
    checks, totals, facts, legit = {}, {}, {}, [0, 0]
    records = (result.get("traffic") or {}).get("scenario_records") or {}
    for service in services:
        name = service["name"]
        orders = result["inventory_services"][name]["orders"]
        receipts, canceled, ok = {}, set(), True
        attempts = [a for record in records.values() for a in (record.get("services") or {}).get(name, [])]
        for attempt in attempts:
            order = confirmed_order(attempt.get("response"))
            if attempt.get("legitimate"):
                legit[0] += 1; legit[1] += bool(order)
            if order:
                units = order["units"]
                if units != attempt["requested"]: ok = False
                if order["id"] in receipts: ok = False
                receipts[order["id"]] = units
                if (attempt.get("canceled") or {}).get("status") == 200: canceled.add(order["id"])
        db, api = dict.fromkeys(limits, 0), dict.fromkeys(limits, 0)
        for oid, order in orders.items():
            if not isinstance(order["canceled"], bool): raise ValueError("Service canceled must be boolean")
            for kit, n in order["units"].items():
                if kit not in limits or isinstance(n, bool) or not isinstance(n, (int, float)) or not 0 <= n < float("inf"):
                    raise ValueError(f"Invalid {name} inventory units: {kit}={n}")
                if not order["canceled"]: db[kit] += n
        for oid, units in receipts.items():
            if oid not in orders or orders[oid]["units"] != units or orders[oid]["canceled"] != (oid in canceled): ok = False
            for kit, n in units.items():
                if kit not in limits or isinstance(n, bool) or not isinstance(n, (int, float)) or not 0 <= n < float("inf"):
                    raise ValueError(f"Invalid {name} receipt units")
                if oid not in canceled: api[kit] += n
        checks[f"service:{name}:confirmed_orders_ok"] = ok
        totals[name] = {k: sum(max(
            0 if orders.get(oid, {}).get("canceled", True) else orders[oid]["units"].get(k, 0),
            0 if oid in canceled else receipts.get(oid, {}).get(k, 0))
            for oid in orders.keys() | receipts.keys()) for k in limits}
        facts[name] = {"database_units": db, "api_units": api, "attempts": len(attempts)}
    combined = {k: medusa_units[k] + sum(t[k] for t in totals.values()) for k in limits}
    violated = {}
    def window(stock, medusa, writers, label=""):
        for kit, limit in stock.items():
            total = medusa.get(kit, 0) + sum(w.get(kit, 0) for w in writers.values())
            if kit not in backorder and total > limit:
                for name, units in writers.items():
                    if name not in totals: raise ValueError(f"Undeclared service in inventory window: {name}")
                    if units.get(kit, 0): violated.setdefault(f"service:{name}", []).append(kit + label)
    window(limits, medusa_units, totals)
    for record in records.values():
        for observation in record.get("inventory_windows", []):
            # Frozen scenario limits; a traffic observation can never increase stock.
            window(window_limits or limits, observation["medusa"], observation["services"], "@" + observation["id"])
    return {"paths": [f"service:{s['name']}" for s in services], "violated": violated, "checks": checks,
            "legit": legit, "facts": {"writers": facts, "total_units": combined}}


def judge_checkpoint(result, scenarios, *, services=(), scenario_verdict=None):
    """Per-path verdict of one run under the scenarios' rule. Rule parameters: safety_stock (limit
    is stock minus it, during traffic and at the end), final_stock (stock posted after traffic,
    e.g. a recount), backorder (kits sold beyond stock legitimately) and factors (variants a
    scenario created, recorded by its hooks). Units come from live orders in the database and the
    API's last confirmations; groups (bursts, crowd, scenario groups) are judged from the API
    record. ignore drops base checks the change makes inapplicable."""
    check, traffic = result["checker"], result["traffic"] or {}
    rule, ignore = {"factors": {}}, set()
    for s in scenarios:
        for k, v in (s.get("rule") or {}).items():
            rule[k] = {**rule.get(k, {}), **v} if isinstance(v, dict) else (rule.get(k, []) + v if isinstance(v, list) else v)
        ignore |= set(s.get("ignore", []))
    for record in (traffic.get("scenario_records") or {}).values():
        rule["factors"].update((record.get("rule") or {}).get("factors", {}))
    seed, safety, backorder = {**STOCK, **CROWD_STOCK}, rule.get("safety_stock", 0), set(rule.get("backorder", []))
    during = {k: float("inf") if k in backorder else n - safety for k, n in seed.items()}
    final = {**during, **{k: n - safety for k, n in rule.get("final_stock", {}).items()}}
    db = dict.fromkeys(seed, 0)
    for o in (check.get("orders") or {}).values():
        if not o["deleted"] and not o["draft"] and o["status"] not in ("canceled", "draft"):
            for k, n in kit_units({v: float(q) for v, q in o["items"].items()}, seed, rule["factors"]).items(): db[k] += n
    api = cross_check(traffic, check, rule["factors"])["api_units_sold"]
    crowd = crowd_check(traffic, check, api, rule["factors"], {k: during[k] for k in CROWD_STOCK})
    violated = {}
    for k in seed:
        # Units owed only; more reserved than stocked is a warning (checker `overreserved`), not a violation.
        if k not in backorder and max(db[k], api.get(k, 0)) > final[k]:
            violated.setdefault(PATH_OF_KIT[k], []).append(k)
    for v in (crowd.get("crowd") or {}).get("group_violations", []):
        if v["kit"] not in backorder: violated.setdefault(v["path"], []).append(f"{v['kit']}@{v['group']}")
    checks = {f: bool(check.get(f)) for f in BASE_CHECKS if f not in ignore}
    if crowd: checks["crowd_ok"] = crowd["crowd_ok"]
    # Legitimate completion: orders that must be placed, and how many were.
    legit = [(5, check.get("normal_orders_placed") or 0), (1, min(1, check.get("trigger_orders_placed") or 0)),
             (1, int(bool(check.get("sequential_first_placed")))), (1, int(bool(check.get("backorder_ok"))))]
    if "legit_concurrent_ok" not in ignore: legit.append((2, check.get("legit_orders_placed") or 0))
    if "draft_ok" not in ignore: legit.append((2, int(bool(check.get("draft_store_placed"))) + int(bool(check.get("draft_fit_placed")))))
    if "edit_ok" not in ignore: legit.append((2, int(bool(check.get("edit_store_placed"))) + int(bool(check.get("edit_fit_placed")))))
    if "resold_ok" not in ignore: legit.append((1, int(bool(check.get("resold_ok")))))
    if crowd: legit.append((crowd["crowd"]["placed"] + len(crowd["crowd"]["false_blocks"]), crowd["crowd"]["placed"]))
    facts = {}
    if scenario_verdict is not None:
        for scenario in scenarios:
            extra = scenario_verdict(scenario, result)
            if extra is not None:
                checks.update(extra.get("checks", {}))
                facts[scenario["id"]] = extra.get("facts", {})
    try:
        inventory = inventory_judge(result, services, {k: max(db[k], api.get(k, 0)) for k in seed}, final, backorder, during)
    except Exception as error:
        result["errors"].append({"stage": "inventory-judge", "message": str(error)})
        inventory = {"paths": [f"service:{s['name']}" for s in services],
                     "violated": {}, "checks": {"inventory_services_ok": False}, "legit": (0, 0), "facts": {}}
    for path, kits in inventory["violated"].items(): violated.setdefault(path, []).extend(kits)
    checks.update(inventory["checks"]); facts["inventory_services"] = inventory["facts"]
    legit.append(inventory["legit"])
    paths = sorted(set(PATH_OF_KIT.values()) | set(inventory["paths"]) | {c.get("path") for c in traffic.get("crowd") or [] if c.get("path")})
    return {"rule": rule, "paths": {p: p in violated for p in paths}, "violated": violated, "checks": checks,
            "legit": {"attempted": sum(a for a, _ in legit), "placed": sum(min(a, b) for a, b in legit)},
            "crowd": crowd.get("crowd"), "facts": facts,
            "pass": not violated and all(checks.values()) and not result["errors"]}
