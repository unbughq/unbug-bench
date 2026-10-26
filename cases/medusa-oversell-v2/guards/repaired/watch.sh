#!/bin/sh
set -eu
exec python3 - <<'CODE'
import json,os,subprocess,time,uuid
from pathlib import Path
root=Path(os.environ.get('BENCH_ROOT','/app')); identity={'pid':os.getpid(),'run_id':str(uuid.uuid4())}
compose=['docker','compose','-f',str(root/'projects/medusa/compose.yaml'),'exec','-T','postgres','psql','-XqAt','-v','ON_ERROR_STOP=1','-U','medusa','-d','medusa']
query="""SELECT format('ALTER TABLE %s ENABLE ALWAYS TRIGGER %I;',tgrelid::regclass,tgname)
FROM pg_catalog.pg_trigger WHERE NOT tgisinternal AND (tgname='bench_check_reservation' OR tgname LIKE 'practice_commit_%') AND tgenabled != 'A'
\gexec
"""
evidence=root/'unbug'; evidence.mkdir(exist_ok=True)
while True:
 subprocess.run(compose,input=query,text=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 temporary=evidence/'reference-watcher.tmp'
 temporary.write_text(json.dumps(dict(identity,at=time.time())))
 temporary.replace(evidence/'reference-watcher.json')
 time.sleep(.25)
CODE
