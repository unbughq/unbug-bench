def judge(run, bench):
    record = (run["traffic"] or {}).get("scenario_records", {}).get("S9", {})
    left = int(bench.sql("SELECT count(*) FROM reservation_item WHERE inventory_item_id = 'iitem_bench_w' AND line_item_id IS NULL AND deleted_at IS NULL"))
    job = record.get("job") or {}
    return {"checks": {"holds_created": record.get("holds") == [200, 200],
                       "job_completed": job.get("status") == 200 and (job.get("data") or {}).get("deleted") == 2 and left == 0},
            "facts": {"holds_left": left, "job": job}}
