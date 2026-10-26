#!/bin/sh
set -eu
python3 - <<'CODE'
import json,time
from pathlib import Path
p=Path('/app/evidence'); a=json.loads((p/'identity.json').read_text()); beats=[json.loads(s) for s in (p/'beats.jsonl').read_text().splitlines()]
assert all(x['pid']==a['pid'] and x['run_id']==a['run_id'] for x in beats)
assert time.time()-beats[-1]['at'] < 1
if (p/'second.json').exists(): assert json.loads((p/'second.json').read_text())['run_id']==a['run_id']
time.sleep(2)
Path('/logs/verifier/reward.txt').write_text('1')
CODE
