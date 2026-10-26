#!/usr/bin/env python3
"""Execute the real verifier reward adapter: invalid checkpoints cannot earn a pass."""
import json, pathlib, sys, tempfile
from unittest.mock import patch
script = ((pathlib.Path(__file__).resolve().parents[3] / 'harbor/medusa-oversell-v2/tests') / "test.sh").read_text()
source = script.split("python3 - \"$out\" \"$attempt\" <<'EOF'\n", 1)[1].split("\nEOF", 1)[0]
with tempfile.TemporaryDirectory() as temporary:
    out = pathlib.Path(temporary)
    for errors, invalid, reward in [(0, 0, 1), (1, 0, 0), (0, 1, 0)]:
        checkpoint = {"claims_score": {"response_correct": True, "unsafe_checkpoint": False},
            "expected_violations": [], "paths": {}, "legit_completion": 1.0,
            "runs": 1, "pass_runs": int(not errors and not invalid), "error_runs": errors, "invalid_runs": invalid}
        (out / "checkpoint.json").write_text(json.dumps(checkpoint))
        with patch.object(sys, "argv", ["-", str(out), "2"]): exec(compile(source, "test.sh reward adapter", "exec"), {})
        actual = json.loads((out / "reward.json").read_text())
        assert actual["reward"] == reward, actual
        assert actual["judge_error"] == errors and actual["invalid_runs"] == invalid, actual
print("reward adapter: valid response passes; error/invalid checkpoints fail closed")
