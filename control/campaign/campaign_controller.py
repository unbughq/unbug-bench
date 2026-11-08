import fcntl,json,math,os,sys,time
from pathlib import Path
root=Path(os.environ.get('UNBUG_CAMPAIGN_ROOT',Path(__file__).parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'factory'))
from durable import cli
from durable.guard import CHECKPOINT_GRACE_S,CheckFailed,campaign_limits,compute_bound,compute_fits,reserve_start
from durable.runtime import Runtime
from durable.workers import PoolError,_atomic_json

def grace():
 return float(os.environ.get('UNBUG_CHECKPOINT_GRACE_S',CHECKPOINT_GRACE_S))

def checked_request():
 """The campaign request, refused at startup unless its worker limits are readable and fit."""
 request=json.loads((root/'campaign-request.json').read_text())
 try:
  campaign_limits(request)
  if not compute_fits(request,grace()):raise CheckFailed('compute_bound')
 except (CheckFailed,KeyError,TypeError) as error:
  raise SystemExit(f'campaign-request.json: worker limits missing or over the approval ({error})') from None
 return request

class BoundedRuntime(Runtime):
 def __init__(self,config):
  checked_request()
  super().__init__(config)
  self.pool.ttl=7200
  self.pool.vm_type='default'
  create=self.pool._create
  def assess(worker):
   request=json.loads((root/'campaign-request.json').read_text())
   try:
    # A request edited into an unreadable state refuses the step but keeps the worker.
    campaign_limits(request);compute_bound(request,grace())
   except Exception:
    raise PoolError('infra:compute_approval_unverified') from None
   try:
    if time.time()>=request['deadline_epoch']:raise ValueError()
    code,data=self.pool.boat.run(['usage',worker,'--json'],timeout=30)
    if code:raise ValueError()
    usage=json.loads(data);values=[usage.get(k) for k in ('dollars','billingMultiplier','secondsPerDollar')]
    if not all(type(v) in (float,int) and math.isfinite(v) and v>=0 for v in values) or values[2]<=0:raise ValueError()
    rate=values[1]/values[2]
    if rate>request['max_worker_rate_usd_per_second']:raise ValueError()
    # Every running slot busy for the whole wall must fit the typed approval; starts add nothing.
    if not compute_fits(request,grace()):raise ValueError()
    worker_bound=compute_bound(request,grace())
    if values[0]>worker_bound or time.time()>=request['deadline_epoch']:raise ValueError()
    _atomic_json(root/'campaign-compute-bound.json',{'worker':worker,'observed_rate_usd_per_second':rate,'joint_worker_bound_usd':worker_bound,'max_running_sandboxes':request['max_running_sandboxes'],'max_starts_per_hour':request['max_starts_per_hour'],'deadline_epoch':request['deadline_epoch']})
   except Exception:
    self.pool._delete_raw(worker)
    raise PoolError('infra:compute_approval_unverified') from None
  def running():
   """Sandboxes holding a slot: every live one Boat lists as ours, plus create requests whose
   sandbox may still appear (pool records not yet settled)."""
   pool=self.pool
   try:
    rows=pool._inventory()
    live={r['id'] for r in rows if pool._live(r) and pool._ours(r) is not None}
    listed={r['id'] for r in rows}
    held=0
    for case,record in pool._records().items():
     if not record or record['intent'] is None or pool._settled(case):continue
     # A recent create Boat does not list yet, with or without a known id, still holds a slot.
     if record['worker'] is None or record['worker'] not in listed:held+=1
    return len(live)+held
   except PoolError:raise
   except Exception:raise PoolError('infra:inventory_unavailable') from None
  def bounded_create(case,bench):
   # Held until the create request is on record, so the next start counts this one.
   with open(self.state/'campaign-create.lock','a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    request=json.loads((root/'campaign-request.json').read_text())
    if request['deadline_epoch']-time.time()<1:raise PoolError('infra:campaign_deadline')
    # Timed after the inventory lookup inside reserve_start, right before the create request.
    now=reserve_start(self.state/'campaign-starts.json',request,running)
    remaining=request['deadline_epoch']-now
    if remaining<1:raise PoolError('infra:campaign_deadline')
    self.pool.ttl=min(7200,int(remaining+grace()))
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
