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
print(json.dumps({
    "agent": "oracle", "model_calls": 0, "steps": 2, "rewards": [1, 1],
    "questions": len(questions), "human_minutes_charged": 10,
    "same_monitor_pid": a["pid"], "same_monitor_run_id": a["run_id"],
    "heartbeat_count": len(beats), "heartbeat_max_gap_sec": round(max_gap, 3),
    "heartbeat_count_during_first_separate_verifier": len(inside),
    "first_separate_verifier_window": window,
    "verifiers": verifiers,
    "step_agent_windows": [s["agent_execution"] for s in steps],
    "verdict": "PASS",
}, indent=2))
