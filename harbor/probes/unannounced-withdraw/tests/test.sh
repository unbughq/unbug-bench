#!/bin/sh
set -eu
python3 - <<'CODE'
import json,time,os
from pathlib import Path
p=Path('/app/evidence'); a=json.loads((p/'identity.json').read_text()); beats=[json.loads(s) for s in (p/'beats.jsonl').read_text().splitlines()]
assert all(x['pid']==a['pid'] and x['run_id']==a['run_id'] for x in beats)
assert int((p/'calls').read_text())==int(os.environ['PROBE_CALLS'])
if os.environ['PROBE_CALLS']=='2': assert (p/'second.json').exists()
assert beats[-1]['at'] >= beats[0]['at']
if (p/'second.json').exists(): assert json.loads((p/'second.json').read_text())['run_id']==a['run_id']
time.sleep(2)
Path('/logs/verifier/reward.txt').write_text('1')
CODE
