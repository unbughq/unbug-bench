#!/bin/sh
set -eu
mkdir -p /logs/verifier
python3 - <<'PY'
import json
from pathlib import Path
p = Path("/app/smoke-answer.txt")
passed = p.is_file() and p.read_bytes() == b"harbor-codex-ok\n"
Path("/logs/verifier/reward.json").write_text(json.dumps({"reward": int(passed)}))
assert passed, "Codex file action missing or incorrect"
print("instruction -> Codex shell write/read -> verifier: PASS")
PY
