"""One-shot authorized gate-wall worker proof, with per-worker cost and deletion."""
from pathlib import Path
import datetime,gzip,hashlib,json,os,re,signal,subprocess,time
ROOT=Path('/Users/bugsincode/.t3/worktrees/unbug-bench/t3-b7dfac7a')
STATE=Path('/tmp/router-gate-wall-boat-proof');STATE.mkdir(exist_ok=True)
BOAT=str(ROOT/'bin/boat-call');NAME='router-gate-wall-proof'
record={'status':'preflight','name':NAME,'source_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
now=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00','Z')
def save():
    p=STATE/'record.json';p.write_text(json.dumps(record,indent=2)+'\n')
def call(args,timeout=45,check=True):
    r=subprocess.run([BOAT,*args],cwd=ROOT,capture_output=True,text=True,timeout=timeout+5,
        env={**os.environ,'BOAT_COMMAND_TIMEOUT_SECONDS':str(timeout)})
    if check and r.returncode:raise RuntimeError('Boat '+args[0]+' failed with exit '+str(r.returncode))
    return r
def objects(text):
    rows=[]
    for line in text.splitlines():
        try:rows.append(json.loads(line))
        except ValueError:pass
    return rows
def listing_ids(value):
    if isinstance(value,list):return [i for v in value for i in listing_ids(v)]
    if isinstance(value,dict):
        own=[value] if isinstance(value.get('id'),str) else []
        return own+[i for v in value.values() if isinstance(v,(dict,list)) for i in listing_ids(v)]
    return []
limits=json.loads(call(['limits','--json']).stdout)
price=limits['overagePrices']['vmHourDollars'];fee=limits['nextStartDollars'];ttl=1200
assert limits['canStart'] and not limits.get('checkoutRequired') and price<=.036 and fee<=.07
assert price*ttl/3600+fee<.10
record['preflight']={'at':now(),'vm_hour_usd':price,'next_start_usd':fee,'ttl_seconds':ttl,
    'reserved_maximum_usd':.082,'current_expected_ceiling_usd':round(price*ttl/3600+fee,9),
    'pricing_source':'https://boat.dev/','pricing_checked':'2026-10-30'}
prior=listing_ids(objects(call(['list','--json']).stdout))
assert not any(v.get('name')==NAME for v in prior),'preexisting proof worker; reconcile, do not create'
assert not (STATE/'creation-attempted').exists(),'one creation attempt only'
archive=STATE/'public-source.tar.gz'
with archive.open('wb') as f:
    subprocess.run(['git','archive','--format=tar.gz','HEAD','factory','bin','projects/marketplace',
        'scenarios/dev/S13-marketplace/scenario.json','tests/factory/live/gate_wall_probe.py'],cwd=ROOT,stdout=f,check=True)
record['archive_sha256']=hashlib.sha256(archive.read_bytes()).hexdigest();save()
worker=None;started=time.monotonic();deadline=started+900

def remaining():
    value=min(90,deadline-time.monotonic())
    if value<=0:raise TimeoutError('proof deadline')
    return value

def interrupted(signum,frame):raise InterruptedError('proof interrupted')
for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,interrupted)
try:
    (STATE/'creation-attempted').write_text(now());record['creation_attempted_at']=now();save()
    try:
        created=call(['new','--type','default','--no-env','--no-monitoring','--no-snapshots','--ttl','1200','--name',NAME,'--json'],timeout=180,check=False)
    except subprocess.TimeoutExpired as error:
        output=error.stdout or ''
        if isinstance(output,bytes):output=output.decode(errors='replace')
        created=subprocess.CompletedProcess([],124,output,'')
    events=objects(created.stdout)
    record['creation_billing_fields']=[{k:v for k,v in e.items() if any(word in k.lower() for word in ('cost','fee','charge')) and type(v) in (int,float)} for e in events if isinstance(e,dict)]
    matches=[v['id'] for v in events if isinstance(v,dict) and v.get('event')=='created' and re.fullmatch('[A-Za-z0-9_-]+',str(v.get('id','')))]
    if matches:worker=matches[0]
    if worker is None:
        listed=listing_ids(objects(call(['list','--json']).stdout))
        matches=[v['id'] for v in listed if v.get('name')==NAME]
        assert len(set(matches))==1,'ambiguous creation; no retry'
        worker=matches[0]
    record.update(worker_id=worker,created_observed_at=now(),creation_exit_code=created.returncode);save()
    if created.returncode:raise RuntimeError('creation command did not confirm ready')
    call(['scp',str(archive),worker+':/tmp/router-wall-public.tar.gz'],timeout=remaining())
    remote='mkdir -p /tmp/router-wall-public && tar -xzf /tmp/router-wall-public.tar.gz -C /tmp/router-wall-public && cd /tmp/router-wall-public && BENCH=/tmp/router-wall-public python3 -B tests/factory/live/gate_wall_probe.py'
    proof=call(['ssh',worker,remote],timeout=remaining(),check=False)
    (STATE/'probe.stdout').write_text(proof.stdout)
    (STATE/'probe.stderr').write_text(proof.stderr)
    record['probe_exit_code']=proof.returncode
    record['probe']=json.loads(proof.stdout)
    assert proof.returncode==0 and record['probe']['status']=='passed','live proof failed'
    record['status']='passed'
except BaseException as error:
    record['status']='failed';record['failure_type']=type(error).__name__;record['failure']=str(error);save()
    raise
finally:
    # A known worker is always deleted, even after proof/setup failure. No model key was copied.
    if worker is None:
        try:
            matches=[v['id'] for v in listing_ids(objects(call(['list','--json']).stdout)) if v.get('name')==NAME]
            if len(set(matches))==1:
                worker=matches[0];record['worker_id']=worker;save()
        except BaseException as error:record['reconciliation_error']=type(error).__name__
    if worker:
        try:record['usage_before_delete']=json.loads(call(['usage',worker,'--json']).stdout)
        except Exception as error:record['usage_before_delete_error']=type(error).__name__
        try:
            request=json.loads(call(['delete',worker,'--yes','--json']).stdout)['operation']
            op=request['id']
            def identity(value):
                assert value['id']==op and value['targetId']==worker and value['kind']=='sandbox'
                return {k:value.get(k) for k in ('id','targetId','kind','status','stage','completedAt')}
            record['deletion_request']=identity(request);save()
            until=time.monotonic()+60
            while time.monotonic()<until:
                value=identity(json.loads(call(['deletion','status',op,'--json'],timeout=min(20,until-time.monotonic())).stdout)['operation'])
                record['deletion_completion']=value;save()
                if value['status']=='completed':
                    assert value['stage']=='completed' and value['completedAt']
                    assert datetime.datetime.fromisoformat(value['completedAt'].replace('Z','+00:00')).tzinfo is not None
                    break
                assert value['status'] in ('pending','processing');time.sleep(2)
            else:raise TimeoutError('deletion confirmation')
            record['absent_from_inventory']=not any(v['id']==worker for v in listing_ids(objects(call(['list','--json']).stdout)))
            assert record['absent_from_inventory']
            try:record['final_usage']=json.loads(call(['usage',worker,'--json']).stdout)
            except Exception as error:record['final_usage_error']=type(error).__name__
        except BaseException as error:
            record['status']='failed';record['deletion_error']=type(error).__name__+': '+str(error)
    record['finished_at']=now();record['wall_seconds']=round(time.monotonic()-started,3);save()
    print(json.dumps({k:record.get(k) for k in ('status','worker_id','probe_exit_code','absent_from_inventory','wall_seconds','failure','deletion_error')},indent=2),flush=True)
