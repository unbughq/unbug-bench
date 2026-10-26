def judge(run, bench):
    record = (run["traffic"] or {}).get("scenario_records", {}).get("U1", {})
    left = int(bench.sql("SELECT count(*) FROM reservation_item WHERE description = 'expired manual hold' AND line_item_id IS NULL AND deleted_at IS NULL"))
    return {"checks": {"expired_manual_hold_released": record.get("created") == 200
                       and bool(record.get("id")) and record.get("deleted") == 200 and left == 0},
            "facts": {"holds_left": left, "api": record}}
