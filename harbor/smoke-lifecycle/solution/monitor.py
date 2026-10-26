import json, os, time, uuid
from pathlib import Path
root = Path('/app/lifecycle')
identity = {"pid": os.getpid(), "run_id": str(uuid.uuid4())}
(root / 'monitor.json').write_text(json.dumps(identity))
while True:
    with (root / 'heartbeat.jsonl').open('a') as f:
        f.write(json.dumps(dict(identity, ts=time.time())) + '\n')
    time.sleep(0.25)
