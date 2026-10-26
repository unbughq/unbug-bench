def judge(run, bench):
    records = run["traffic"]["scenario_records"]["S13"]["services"]["marketplace"]
    status = [a["response"]["status"] for a in records]
    return {"checks": {"marketplace_trade_ok": status == [200, 409, 200, 409],
                       "marketplace_monitor_ok": run["traffic"]["scenario_records"]["S13"].get("monitor_ok", False)}, "facts": {"status": status}}
