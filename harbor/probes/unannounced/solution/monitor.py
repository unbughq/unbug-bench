import json, os, time, uuid
from pathlib import Path
p=Path('/app/evidence'); ident={'pid':os.getpid(),'run_id':str(uuid.uuid4())}
(p/'identity.json').write_text(json.dumps(ident))
while True:
 with (p/'beats.jsonl').open('a') as f: f.write(json.dumps(dict(ident, at=time.time()))+'\n')
 time.sleep(.2)
