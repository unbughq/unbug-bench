from pathlib import Path
import json,sys,time,socket,shlex
root=Path('/home/user/durable-first-case-20261106')
sys.path.insert(0,str(root/'source-0578f9c8/factory'))
from durable.workers import BoatPool,BoatCli,ReleaseStore
from durable.ledger import SqlLedger
c=json.loads((root/'config.json').read_text())
request=json.loads((root/'campaign-request.json').read_text())
state=Path(c['state_dir'])
out={'at':time.time(),'batch':request['batch_id']}
try:
 with socket.socket(socket.AF_UNIX) as client:
  client.settimeout(20);client.connect(str(state/'operator.sock'))
  client.sendall(json.dumps(dict(op='status',batch=request['batch_id'])).encode()+b'\n')
  with client.makefile('rb') as stream:reply=json.loads(stream.readline(1048576))
 out['scorecard']=reply['result'] if reply.get('ok') else None
except Exception:out['operator']='unavailable'
l=SqlLedger(Path(c['database_url_file']).read_text().strip())
try:out['ledger']=l.balance(request['batch_id'])
except Exception:out['ledger']=None
finally:l.close()
pool=BoatPool(state/'pool',ReleaseStore(state/'releases'),c['pool_id'],boat=BoatCli())
rows=[r for r in pool._inventory() if pool._ours(r) is not None]
out['owned_workers']=[r['id'] for r in rows]
out['pool_records']={case:{'worker':v.get('worker'),'uncertain':v.get('worker') is None} for case,v in pool._records().items()}
probe='''from pathlib import Path
import json,math,re,sys
h=Path.home();work=h/'work'/CASE
def load(p):
 try:return json.loads(p.read_text()) if p.stat().st_size<16777216 else {}
 except Exception:return {}
def number(v):return v if type(v) in (int,float) and math.isfinite(v) and v>=0 else None
ledger=load(work/'continuation-budget.json');card=load(work/'scorecard.json')
preflight=[]
for row in card.get('provider_preflight',[]):
 if row.get('status') in ('running','completed','failed') and row.get('role') in ('reviewer','reviewer2','stress_tester','strong_tester','easy_tester'):
  preflight.append({'role':row['role'],'status':row['status']})
receipts=[]
completed_preflight=set()
preflight_roles={'attacker-provider-preflight':'stress_tester','reviewer-provider-preflight':'reviewer','strong-calibrator-provider-preflight':'strong_tester','easy-calibrator-provider-preflight':'easy_tester'}
for path in (work/'usage-receipts').glob('*.json'):
 value=load(path);cap=value.get('cap_used') or {}
 row={k:number(cap.get(k)) for k in ('validated_requests','unknown_requests')}
 row['final_usage_known']=value.get('final_usage_known') is True
 row['closed']=cap.get('closed') is True
 if value.get('outcome')=='done' and row['final_usage_known'] and value.get('invocation') in preflight_roles:completed_preflight.add(preflight_roles[value['invocation']])
 for k in ('settled_usd','held_usd'):
  v=cap.get(k)
  row[k]=float(v) if isinstance(v,str) and re.fullmatch(r'[0-9]+[.][0-9]+',v) and float(v)<=50 else None
 receipts.append(row)
output=sum(e.get('tokens',{}).get('output',0) for e in ledger.get('events',[]) if type(e.get('tokens',{}).get('output',0)) is int and e.get('tokens',{}).get('output',0)>=0)
release=load(h/'factory-release/RELEASE.json')
errors=[]
phase_counts={}
for event in ledger.get('events',[]):
 name=event.get('invocation','')
 phase='preflight' if 'provider-preflight' in name else 'selection' if any(k in name for k in ('select','admission','idea','dedup','freshness')) else 'other'
 phase_counts[phase]=phase_counts.get(phase,0)+1
try:
 sys.path.insert(0,str(h/'factory-release/factory'))
 from durable.diagnostics import _error_fields
 words=set('timeout zod parsing parse native_finish_reason duplicate completion finish_reason stream streaming json usage requests service invalid unsupported tools tool_choice required max_price parameters provider request model organization scope not_found permission credits api unavailable schema limit output tokens date object undefined properties length unknown cancelled aborted connection reset apierror typeerror validationerror'.split())
 for transcript in (work/'transcripts').glob('*.jsonl'):
  for line in transcript.open('rb'):
   try:event=json.loads(line)
   except (ValueError,UnicodeError):continue
   fields=_error_fields(event) if isinstance(event,dict) else None
   if fields:
    text,statuses=fields;errors.append({'http_statuses':statuses,'known_error_terms':sorted(set(re.findall(r'[a-z_]+',text.lower())) & words)})
except ImportError:pass
print(json.dumps({'release':{k:v for k,v in release.items() if k in ('plumbing_version','bench_version')},'accounted_calls':number(ledger.get('calls')),'output_tokens':output,'preflight':preflight,'admission':card.get('admission',{}).get('status') if card.get('admission',{}).get('status') in ('passed','rejected') else None,'receipts':receipts,'error_diagnostics':errors,'completed_preflight_roles':sorted(completed_preflight),'phase_counts':phase_counts}))
'''.replace('CASE',repr(request['case_id']))
for row in rows:
 code,data=pool.boat.ssh(row['id'],'python3 -I -B -c '+shlex.quote(probe),timeout=25)
 if code==0:
  try:out['worker_observation']=json.loads(data)
  except ValueError:out['worker_observation']='unavailable'
 else:out['worker_observation']='not_ready'
print(json.dumps(out,sort_keys=True))
