import json,math,os,socket,subprocess,sys,time
from pathlib import Path
root=Path(__file__).parent
sys.path.insert(0,str(root/'source-0578f9c8/factory'))
from durable.workers import BoatPool,ReleaseStore,BoatCli,_atomic_json
request=json.loads((root/'campaign-request.json').read_text())
config=json.loads((root/'config.json').read_text())
state=Path(config['state_dir'])
pool=BoatPool(state/'pool',ReleaseStore(state/'releases'),config['pool_id'],boat=BoatCli(env={**os.environ,'HOME':'/home/user','XDG_CONFIG_HOME':'/home/user/.config','BOAT_CMD':'/usr/local/bin/boat'}))
service='unbug-durable-case-campaign.service'
heartbeat={'at':time.time(),'stopping':False,'deadline_epoch':request['deadline_epoch']}
def rpc(op):
 with socket.socket(socket.AF_UNIX) as client:
  client.settimeout(15);client.connect(str(state/'operator.sock'))
  client.sendall(json.dumps({'op':op,'batch':request['batch_id']}).encode()+b'\n')
  with client.makefile('rb') as stream:reply=json.loads(stream.readline(1024*1024))
  if not reply.get('ok'):raise ValueError()
  return reply['result']
stop='--cleanup' in sys.argv or time.time()>=request['deadline_epoch']
try:
 rows=[r for r in pool._inventory() if pool._ours(r) is not None]
 heartbeat['owned_workers']=len(rows)
 if len(rows)>1:stop=True
 marker=state/'campaign-create-count.json'
 count=json.loads(marker.read_text()) if marker.exists() else 0
 if type(count) is not int or not 0<=count<=request['max_workers_lifetime']:stop=True
 heartbeat['worker_allowances_retained']=count
 worker_bound=request['max_worker_rate_usd_per_second']*(request['wall_seconds']+request['max_workers_lifetime']*7200)
 heartbeat['reserved_compute_usd']=request['prior_compute_retained_usd']+request['control_allowance_usd']+worker_bound
 if heartbeat['reserved_compute_usd']>request['approved_infrastructure_usd']-request['cleanup_margin_usd']:stop=True
 for row in rows:
  code,data=pool.boat.run(['usage',row['id'],'--json'],timeout=30)
  if code:raise ValueError()
  values=[json.loads(data).get(k) for k in ('dollars','billingMultiplier','secondsPerDollar')]
  if not all(type(v) in (float,int) and math.isfinite(v) and v>=0 for v in values) or values[2]<=0:raise ValueError()
  if values[1]/values[2]>request['max_worker_rate_usd_per_second'] or values[0]>worker_bound:stop=True
 if not stop:
  report=rpc('status');_atomic_json(root/'campaign-scorecard.json',report)
  if report['cases'] and all(c['status'] in ('sealed','retired','held','stopped_admission','engine_error') for c in report['cases']):
   heartbeat['publication']=rpc('publish');stop=True
 stop=stop or time.time()>=request['deadline_epoch']
 if not stop:
  for row in rows:
   ttl=min(7200,int(request['deadline_epoch']-time.time()))
   if ttl<1:stop=True;break
   code,_=pool.boat.run(['extend',row['id'],'--ttl',str(ttl)],timeout=30)
   if code:raise ValueError()
except Exception:
 stop=True;heartbeat['error']='campaign_guard_failed'
if stop:
 subprocess.run(['systemctl','stop',service],capture_output=True,timeout=150)
 active=subprocess.run(['systemctl','show',service,'-p','ActiveState','--value'],capture_output=True,text=True,check=True).stdout.strip()
 if active not in ('inactive','failed'):raise RuntimeError('campaign_controller_not_stopped')
 rows=[r for r in pool._inventory() if pool._ours(r) is not None]
 for row in rows:pool._delete_raw(row['id'])
 heartbeat['owned_workers']=sum(pool._ours(r) is not None for r in pool._inventory())
 heartbeat['stopping']=True
_atomic_json(root/'campaign-guard-heartbeat.json',heartbeat)
os.chown(root/'campaign-guard-heartbeat.json',0,1000)
os.chmod(root/'campaign-guard-heartbeat.json',0o640)
