import fcntl,json,math,os,sys,time
from pathlib import Path
root=Path(os.environ.get('UNBUG_CAMPAIGN_ROOT',Path(__file__).parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'factory'))
from durable import cli
from durable.guard import CHECKPOINT_GRACE_S
from durable.runtime import Runtime
from durable.workers import PoolError,_atomic_json

class BoundedRuntime(Runtime):
 def __init__(self,config):
  super().__init__(config)
  self.pool.ttl=7200
  self.pool.vm_type='default'
  create=self.pool._create
  def assess(worker):
   request=json.loads((root/'campaign-request.json').read_text())
   try:
    if time.time()>=request['deadline_epoch']:raise ValueError()
    code,data=self.pool.boat.run(['usage',worker,'--json'],timeout=30)
    if code:raise ValueError()
    usage=json.loads(data);values=[usage.get(k) for k in ('dollars','billingMultiplier','secondsPerDollar')]
    if not all(type(v) in (float,int) and math.isfinite(v) and v>=0 for v in values) or values[2]<=0:raise ValueError()
    rate=values[1]/values[2]
    if rate>request['max_worker_rate_usd_per_second']:raise ValueError()
    batches=len(request.get('batch_ids') or [request['batch_id']])  # one worker per watched batch for the whole wall
    worker_bound=request['max_worker_rate_usd_per_second']*(batches*request['wall_seconds']+request['max_workers_lifetime']*7200)
    if worker_bound+request['prior_compute_retained_usd']+request['control_allowance_usd']+request['cleanup_margin_usd']>request['approved_infrastructure_usd']:raise ValueError()
    if values[0]>worker_bound or time.time()>=request['deadline_epoch']:raise ValueError()
    _atomic_json(root/'campaign-compute-bound.json',{'worker':worker,'observed_rate_usd_per_second':rate,'joint_worker_bound_usd':worker_bound,'max_creation_attempts':request['max_workers_lifetime'],'deadline_epoch':request['deadline_epoch']})
   except Exception:
    self.pool._delete_raw(worker)
    raise PoolError('infra:compute_approval_unverified') from None
  def bounded_create(case,bench):
   request=json.loads((root/'campaign-request.json').read_text())
   remaining=request['deadline_epoch']-time.time()
   if remaining<1:raise PoolError('infra:campaign_deadline')
   remaining+=float(os.environ.get('UNBUG_CHECKPOINT_GRACE_S',CHECKPOINT_GRACE_S))
   with open(self.state/'campaign-create.lock','a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    marker=self.state/'campaign-create-count.json'
    count=json.loads(marker.read_text()) if marker.exists() else 0
    if type(count) is not int or not 0<=count<request['max_workers_lifetime']:raise PoolError('infra:creation_limit')
    _atomic_json(marker,count+1)
   self.pool.ttl=min(7200,int(remaining))
   worker=create(case,bench)
   assess(worker)
   return worker
  deliver=self.pool._deliver_credentials
  def bounded_delivery(worker):
   assess(worker)
   return deliver(worker)
  self.pool._create=bounded_create
  self.pool._deliver_credentials=bounded_delivery

if __name__ == '__main__':
 cli.Runtime=BoundedRuntime
 raise SystemExit(cli.main())
