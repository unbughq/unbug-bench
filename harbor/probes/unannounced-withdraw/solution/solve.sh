#!/bin/sh
set -eu
python3 - <<'CODE'
import json, subprocess, sys, time
from pathlib import Path
p=Path('/app/evidence'); p.mkdir(exist_ok=True)
c=p/'calls'; n=int(c.read_text()) if c.exists() else 0
assert n < 2, 'Agent was invoked during silent window'
c.write_text(str(n+1))
if n == 0:
 subprocess.Popen([sys.executable,'/solution/monitor.py'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
 Path('/app/protection').write_text('on')
 Path('/app/claims.json').write_text(json.dumps({'response':'keep','claims':[{'rule':'never-oversell','path':'sales','status':'protected'}]}))
else:
 ident=json.loads((p/'identity.json').read_text()); import os; os.kill(ident['pid'],0)
 (p/'second.json').write_text(json.dumps(dict(ident, at=time.time())))
time.sleep(1)
CODE
