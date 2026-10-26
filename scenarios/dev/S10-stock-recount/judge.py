def judge(run, bench):
    stocked = bench.sql("SELECT COALESCE(SUM(stocked_quantity), 0) FROM inventory_level WHERE inventory_item_id = 'iitem_bench_w' AND deleted_at IS NULL")
    recount = (run["traffic"] or {}).get("scenario_records", {}).get("S10", {}).get("recount", {})
    return {"checks": {"correction_applied": recount.get("status") == 200 and float(stocked) == 20},
            "facts": {"stocked_w": float(stocked), "recount": recount}}
