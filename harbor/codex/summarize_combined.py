#!/usr/bin/env python3
"""Verify a completed trial and emit sanitized lifecycle evidence (stdlib only)."""
import json
import sys
from datetime import datetime
from pathlib import Path

trial = Path(sys.argv[1])
result = json.loads((trial / "result.json").read_text())
steps = result["step_results"]
assert [s["step_name"] for s in steps] == ["establish", "observe"]
for step in steps:
    assert step["exception_info"] is None, step["exception_info"]
    assert step["verifier_result"]["rewards"]["reward"] == 1
artifacts = trial / "steps/observe/artifacts"
root = artifacts / "lifecycle"
a, b = [json.loads((root / (s + ".json")).read_text()) for s in ("establish", "observe")]
assert a["run_id"] == b["run_id"] and a["pid"] == b["pid"]
beats = [json.loads(line) for line in (root / "heartbeat.jsonl").read_text().splitlines()]
assert all(x["run_id"] == a["run_id"] and x["pid"] == a["pid"] for x in beats)
max_gap = max(y["ts"] - x["ts"] for x, y in zip(beats, beats[1:]))
assert max_gap < 2
window = steps[0]["verifier"]
start, end = [datetime.fromisoformat(window[k]).timestamp() for k in ("started_at", "finished_at")]
assert beats[0]["ts"] < start and beats[-1]["ts"] > end
inside = [x for x in beats if start <= x["ts"] <= end]
assert len(inside) >= 10
questions = [json.loads(line) for line in (artifacts / "responder/questions.jsonl").read_text().splitlines()]
assert [q["step"] for q in questions] == ["establish", "observe"]
assert sum(q["minutes_charged"] for q in questions) == 10
verifiers = [json.loads((trial / "steps" / s / "verifier/lifecycle-verifier.json").read_text()) for s in ("establish", "observe")]
assert all(v["fresh_verifier"] and v["end"] - v["start"] >= 5 for v in verifiers)
web = [json.loads(line) for line in (artifacts / "web/web.jsonl").read_text().splitlines()]
assert sum(row["domain"] == "example.com" and row["method"] == "GET" for row in web) >= 2
assert all(row["visibility"] == "tunnel" for row in web if row["domain"].endswith(".oaiusercontent.com") or row["domain"] in ("chatgpt.com", "ab.chatgpt.com", "auth.openai.com", "api.openai.com"))
models = sorted({row["domain"] for row in web if row["visibility"] == "tunnel"})
sessions = [json.loads((trial / "steps" / step / "agent/trajectory.json").read_text()) for step in ("establish", "observe")]
assert all(t["agent"]["version"] == "0.162.1" and t["agent"]["model_name"] == "gpt-6.1-sol" for t in sessions)
print(json.dumps({
    "actual_session_agents": [t["agent"] for t in sessions],
    "session_tool_names": [[call.get("function_name") for step in t["steps"] for call in step.get("tool_calls", [])] for t in sessions],
    "agent_info": result["agent_info"],
    "step_usage": [step["agent_result"] for step in steps],
    "public_web_events": [row for row in web if row["domain"] == "example.com"],
    "web_event_count": len(web),
    "web_domains": sorted({row["domain"] for row in web}),
    "tunnel_domains": models,
    "agent": "codex", "model_sessions": 2, "steps": 2, "rewards": [1, 1],
    "questions": len(questions), "human_minutes_charged": 10,
    "same_monitor_pid": a["pid"], "same_monitor_run_id": a["run_id"],
    "heartbeat_count": len(beats), "heartbeat_max_gap_sec": round(max_gap, 3),
    "heartbeat_count_during_first_separate_verifier": len(inside),
    "first_separate_verifier_window": window,
    "verifiers": verifiers,
    "step_agent_windows": [s["agent_execution"] for s in steps],
    "verdict": "PASS",
}, indent=2))
