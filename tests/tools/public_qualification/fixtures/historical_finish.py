# Historical public finisher from the 2026-10-21 combined factory qualification.
# Preserved only to reproduce its single-query processing race; never a runtime entry point.
import pathlib,json,subprocess,os,time
from collector import save
E=pathlib.Path(__file__).resolve().parent;ROOT=E.parents[2]
status=json.loads((E/'monitor-status.json').read_text());assert status['collection_verified'] and status['worker_deleted']
raw=json.loads((E/'deletion.json').read_text());operation=json.loads(raw['stdout'])['operation'];assert operation['targetId']==status['worker_id']
p=subprocess.run([str(ROOT/'bin/boat-call'),'deletion','status',operation['id'],'--json'],capture_output=True,text=True,timeout=130)
save(E/'deletion-completion-query.json',{'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr});assert p.returncode==0
completion=json.loads(p.stdout)['operation'];assert completion['targetId']==status['worker_id'];save(E/'deletion-completion.json',completion)
assert completion['status']=='completed' and completion['stage']=='completed' and completion['completedAt'],completion
card=json.loads((E/(status['case']+'.scorecard.json')).read_text());code=1 if card.get('failed_gate') or card.get('terminal_stop') or card['gates'].get('G12')!='pass' else 0
p=subprocess.run([str(ROOT/'bin/boat-spend'),'--finish',str(E/'spend.json'),str(code),str(E/'worker-ids.txt')],capture_output=True,text=True,timeout=130)
save(E/'spend-finish.json',{'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr});assert p.returncode==0
print(json.dumps({'deletion_completed_at':completion['completedAt'],'spend':json.loads((E/'spend.json').read_text())}))
