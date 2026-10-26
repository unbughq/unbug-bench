#!/bin/bash
set -euo pipefail
python3 - <<'PYTHON'
import json, time
from pathlib import Path
root = Path('/app/lifecycle')
start = time.time()
assert root.exists()
assert not Path('/app/ask-human').exists(), 'separate verifier must have a fresh image'
step = 'observe' if (root / 'observe.json').exists() else 'establish'
a = json.loads((root / 'establish.json').read_text())
beats = [json.loads(line) for line in (root / 'heartbeat.jsonl').read_text().splitlines()]
assert beats and all(b['run_id'] == a['run_id'] and b['pid'] == a['pid'] for b in beats)
if step == 'observe':
    b = json.loads((root / 'observe.json').read_text())
    assert a['run_id'] == b['run_id'] and a['pid'] == b['pid']
    assert b['ts'] - a['ts'] >= 5, 'did not span separate verifier wait'
    assert max(y['ts'] - x['ts'] for x, y in zip(beats, beats[1:])) < 2, 'heartbeat gap'
time.sleep(5)
logs = Path('/logs/verifier')
logs.mkdir(parents=True, exist_ok=True)
(logs / 'lifecycle-verifier.json').write_text(json.dumps(dict(step=step, start=start, end=time.time(), heartbeat_count=len(beats), run_id=a['run_id'], monitor_pid=a['pid'], fresh_verifier=True)))
(logs / 'reward.txt').write_text('1')
PYTHON
