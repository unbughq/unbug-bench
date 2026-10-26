#!/usr/bin/env python3
"""Print a small credential-free record from a completed Harbor trial directory."""
import json
from pathlib import Path
import sys

trial = Path(sys.argv[1])
result = json.loads((trial / "result.json").read_text())
trajectory_path = trial / "agent/trajectory.json"
trajectory = json.loads(trajectory_path.read_text()) if trajectory_path.exists() else {}
steps = trajectory.get("steps", [])
record = {
    "harbor_version": "0.24.0",
    "trial": trial.name,
    "auth": "ChatGPT subscription auth.json; API-key environment removed",
    "agent_info": result.get("agent_info"),
    "agent_result": result.get("agent_result"),
    "verifier_result": result.get("verifier_result"),
    "exception_info": result.get("exception_info"),
    "trajectory_agent": trajectory.get("agent"),
    "trajectory_final_metrics": trajectory.get("final_metrics"),
    "tool_calls": [{"name": call.get("function_name"), "arguments": call.get("arguments")} for step in steps for call in step.get("tool_calls", [])],
}
print(json.dumps(record, indent=2))
