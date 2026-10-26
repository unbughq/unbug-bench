import json, os, time, uuid
from pathlib import Path
p=Path('/app/evidence'); ident={'pid':os.getpid(),'run_id':str(uuid.uuid4())}
(p/'identity.json').write_text(json.dumps(ident))
drift_at = None
while True:
 with (p/'beats.jsonl').open('a') as f: f.write(json.dumps(dict(ident, at=time.time()))+'\n')
 if Path('/app/protection').exists() and Path('/app/protection').read_text()=='off':
  if drift_at is None: drift_at=time.monotonic()
  if time.monotonic()-drift_at >= 2:
   target=Path('/app/claims.json')
   temporary=target.with_suffix('.tmp')
   temporary.write_text(json.dumps({'response':'escalate','claims':[{'rule':'never-oversell','path':'sales','status':'unknown'}]}))
   temporary.replace(target)
 time.sleep(.2)
