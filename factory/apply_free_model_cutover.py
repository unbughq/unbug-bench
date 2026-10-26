"""Same-VM, same-controller cutover. Public metadata only; never reads credentials or logs."""
import argparse
import datetime
import fcntl
import json
import os
import pathlib
import shlex
import signal
import subprocess
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = ROOT / 'results/infrastructure/2026-10-19-claude-takeover'
CONFIG = ROOT / 'factory/free-model-cutover.json'


def atomic(path, value):
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as f:
        json.dump(value, f, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
    os.replace(f.name, path)


def update(case, **values):
    with open(BASE / 'free-model-cutover.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        config = json.loads(CONFIG.read_text()); config['cases'][case].update(values); atomic(CONFIG, config)
        for path in (BASE / 'monitor-state.json', ROOT / 'results/infrastructure/2026-10-18-claude-return/monitor-state.json'):
            state = json.loads(path.read_text())
            state.setdefault('free_model_cutover', {}).setdefault('cases', {}).setdefault(case, {}).update(values)
            state['free_model_cutover']['configuration'] = str(CONFIG)
            atomic(path, state)


def remote(worker, code, payload):
    result = subprocess.run([str(ROOT / 'bin/boat-call'), '--stdin', 'ssh', worker, 'python3 -c ' + shlex.quote(code)],
                            input=json.dumps(payload), capture_output=True, text=True, timeout=40)
    if result.returncode:
        raise ValueError('remote_metadata_or_deployment_failed')
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise ValueError('remote_public_result_invalid') from None


PROBE = r'''
import json,pathlib,subprocess,os,sys
r=json.load(sys.stdin);h=pathlib.Path.home();case=r['case'];row=r['row']
assert (h/'work'/case/'case').is_dir()
p=subprocess.run(['pgrep','-f','^python3 /[^ ]*/factory/run.py( |$)'],capture_output=True,text=True);runners=[]
for raw in p.stdout.split():
 pid=int(raw)
 if pid==os.getpid():continue
 a=[v.decode() for v in pathlib.Path(f'/proc/{pid}/cmdline').read_bytes().split(bytes([0])) if v]
 assert len(a)>1 and a[1].endswith('/factory/run.py')
 def val(k):
  v=None
  for i,t in enumerate(a):
   if t==k:v=a[i+1]
   elif t.startswith(k+'='):v=t.split('=',1)[1]
  return v
 assert val('--resume')==case
 assert all(float(val(k))==float(v) for k,v in row['caps'].items())
 runners.append(pid)
assert len(runners)<=1
b=json.loads((h/'sealed'/(case+'.continuation-budget.json')).read_text())
cardpath=h/'sealed'/(case+'.scorecard.json');card=json.loads(cardpath.read_text()) if cardpath.exists() else {}
done=(h/'sealed/DONE').read_text().strip() if (h/'sealed/DONE').is_file() else None
assert done in (None,case)
print(json.dumps({'runner_pids':runners,'done':done==case,'calls':b['calls'],'cost':b['cost'],'active_count':len(b.get('active') or {}),'card_sha256':card.get('sha256'),'card_case':card.get('case'),'card_roles':card.get('roles'),'card_stop':str(card.get('terminal_stop','')).split(':',1)[0]}))
'''

DEPLOY = r'''
import json,pathlib,sys,os,tempfile
p=json.load(sys.stdin);h=pathlib.Path.home();factory=h/'factory'
ns={};exec(p['patch'],ns);source=(factory/'run.py').read_text();new=ns['patch'](source)
for name in ['free_models.py','free_model_patch.py']:compile(p[name],name,'exec')
for name,content in [('free_models.py',p['free_models.py']),('free_model_patch.py',p['free_model_patch.py']),('free-model-cutover.json',json.dumps(p['config'])),('run.py',new)]:
 with tempfile.NamedTemporaryFile('w',dir=factory,delete=False) as f:f.write(content);f.flush();os.fsync(f.fileno())
 os.chmod(f.name,0o644);os.replace(f.name,factory/name)
print(json.dumps({'deployed':True,'case':p['case'],'gate_functions_unchanged':True}))
'''

PAUSE = r'''
import json,os,pathlib,signal,sys
p=json.load(sys.stdin);pid=p['pid']
assert pathlib.Path(f'/proc/{pid}/comm').read_text().strip().startswith('python')
a=[v.decode() for v in pathlib.Path(f'/proc/{pid}/cmdline').read_bytes().split(bytes([0])) if v]
assert len(a)>1 and a[1].endswith('/factory/run.py') and p['case'] in a
for flag,limit in p['caps'].items():
 value=None
 for i,arg in enumerate(a):
  if arg==flag:value=a[i+1]
  elif arg.startswith(flag+'='):value=arg.split('=',1)[1]
 assert float(value)==float(limit)
os.kill(pid,signal.SIGTERM)
print(json.dumps({'pause_sent':True}))
'''


def _cutover_frozen(case, deploy_only=False):
    config = json.loads(CONFIG.read_text()); row = config['cases'][case]; worker = row['worker']
    if not deploy_only and row['status'] != 'planned':
        return {'case': case, 'status': 'existing_transition_not_repeated', 'recorded_status': row['status']}
    if len(row.get('controller_pids', [])) != 1:
        raise ValueError('single_controller_not_verified')
    pid = row['controller_pids'][0]
    command = subprocess.run(['ps', '-p', str(pid), '-o', 'stat=,command='], capture_output=True, text=True).stdout.strip().split(None, 1)
    if len(command) != 2 or command[0].startswith('Z') or not command[1].startswith(('/bin/sh ' + str(ROOT/'factory/launch.sh'), 'sh ' + str(ROOT/'factory/launch.sh'))) or case not in command[1]:
        raise ValueError('matching_controller_not_live')
    states = {p.resolve() for p in pathlib.Path('/private/tmp').glob('boat-launch.*') if (p / (worker+'.started')).is_file()}
    if len(states) != 1:
        raise ValueError('unique_controller_state_not_verified')
    folder = states.pop()
    if any((folder / (worker + '.' + label)).exists() for label in ('retired', 'deleted', 'keep', 'parked')):
        raise ValueError('controller_lifecycle_not_eligible')
    attempts_path = folder / (worker+'.autoresumes')
    attempts = int(attempts_path.read_text()) if attempts_path.exists() else 0
    if not deploy_only and attempts >= 3:
        raise ValueError('existing_retry_allowance_exhausted')
    before = remote(worker, PROBE, {'case': case, 'row': row})
    if before['calls'] >= row['caps']['--max-total-calls'] or before['cost'] >= row['caps']['--max-cost']:
        raise ValueError('issued_budget_exhausted')
    payload = {'case': case, 'config': {**config, 'cases': {case: row}}, 'patch': (ROOT/'factory/free_model_patch.py').read_text(),
               **{name:(ROOT/'factory'/name).read_text() for name in ('free_models.py','free_model_patch.py')}}
    deployed = remote(worker, DEPLOY, payload)
    update(case, deployment=deployed, deployed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    if deploy_only:
        return {'case': case, 'worker': worker, 'status': 'deployed_current_run_finishes_unchanged'}
    if before['runner_pids'] and not before['active_count'] and not before['done']:
        update(case, status='deployed_deferred_during_checks')
        return {'case': case, 'worker': worker, 'status': 'deployed_deferred_during_checks'}
    # Freeze the existing owner, never replace it. Finally always returns lifecycle ownership.
    try:
        before = remote(worker, PROBE, {'case': case, 'row': row})
        update(case, status='pause_reserved', pause_baseline={'calls':before['calls'],'cost':before['cost']}, controller_pid=pid, retry_count_before=attempts)
        if before['runner_pids']:
            remote(worker, PAUSE, {'case': case, 'pid': before['runner_pids'][0], 'caps': row['caps']})
        deadline = time.monotonic() + 180
        while True:
            observed = remote(worker, PROBE, {'case': case, 'row': row})
            if not observed['runner_pids'] and observed['done'] and not observed['active_count']:
                break
            if time.monotonic() > deadline:
                raise ValueError('checkpoint_finish_unconfirmed')
            time.sleep(5)
        result = subprocess.run(['/bin/sh', str(ROOT/'factory/collect.sh'), worker], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        if result.returncode:
            raise ValueError('current_encrypted_collection_failed')
        card_path = ROOT/'sealed'/(case+'.scorecard.json'); stat0 = card_path.stat(); card = json.loads(card_path.read_text())
        assert card.get('case') == case and card.get('sha256') == observed['card_sha256']
        import hashlib
        archives = [ROOT/'sealed'/(case+s) for s in ('.checkpoint.tar.gz.age','.tar.gz.age')]
        selected = archives[1] if not archives[0].is_file() or (archives[1].is_file() and archives[1].stat().st_mtime_ns>archives[0].stat().st_mtime_ns) else archives[0]
        with selected.open('rb') as f:
            digest=hashlib.file_digest(f,'sha256').hexdigest()
        assert digest == card['sha256'] and card_path.stat().st_mtime_ns == stat0.st_mtime_ns
        budget = card['continuation_budget']
        assert budget['calls']>=before['calls'] and budget['cost']>=before['cost'] and not budget.get('active')
        assert budget['calls']<row['caps']['--max-total-calls'] and budget['cost']<row['caps']['--max-cost']
        from free_models import signature
        assert signature(card.get('roles') or {}) == signature(row['before'])
        assert not card.get('failed_gate') and card.get('status')=='stopped' and not card.get('checkpoint_error')
        stop = str(card.get('terminal_stop','')).split(':',1)[0]
        assert stop in ('paused','provider_limit','stalled','timeout','opencode_error','process_error')
        update(case, status='collected_existing_controller_resume_authorized', paused_generation=card['sha256'] if stop=='paused' else None,
               checkpoint_sha256=digest, card_mtime_utc=datetime.datetime.fromtimestamp(stat0.st_mtime,datetime.timezone.utc).isoformat(),
               preserved_calls=budget['calls'],preserved_cost=budget['cost'],checkpoint_verified=True)
        return {'case':case,'worker':worker,'status':'checkpoint_verified_existing_controller_resuming','calls':budget['calls'],'cost':budget['cost'],'new_vm_allocated':False}
    except Exception as error:
        update(case,status='transition_blocked_reconcile_before_retry',failure_category=type(error).__name__)
        raise


def cutover(case, deploy_only=False):
    row = json.loads(CONFIG.read_text())['cases'][case]
    with open(BASE / ('free-cutover-' + row['worker'] + '.lock'), 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if len(row.get('controller_pids', [])) != 1:
            raise ValueError('single_controller_not_verified')
        pid = row['controller_pids'][0]
        command = subprocess.run(['ps','-p',str(pid),'-o','stat=,command='],capture_output=True,text=True).stdout.strip().split(None,1)
        if len(command)!=2 or command[0].startswith('Z') or not command[1].startswith(('/bin/sh '+str(ROOT/'factory/launch.sh'),'sh '+str(ROOT/'factory/launch.sh'))) or case not in command[1]:
            raise ValueError('matching_controller_not_live')
        # Freeze before state/probe/deployment reads; the owner cannot consume a retry mid-preflight.
        os.kill(pid,signal.SIGSTOP)
        try:
            deadline = time.monotonic() + 45
            while True:
                children = subprocess.run(['ps','-axo','ppid=,stat=,comm='],capture_output=True,text=True).stdout.splitlines()
                pending = any(len(parts:=line.split(None,2))==3 and parts[0]==str(pid) and not parts[1].startswith('Z')
                              and pathlib.Path(parts[2]).name not in ('sleep','caffeinate') for line in children)
                if not pending:
                    break
                if time.monotonic() > deadline:
                    raise ValueError('controller_child_operation_still_in_flight')
                time.sleep(.5)
            return _cutover_frozen(case,deploy_only)
        finally:
            os.kill(pid,signal.SIGCONT)


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    parser=argparse.ArgumentParser();parser.add_argument('case');parser.add_argument('--deploy-only',action='store_true');a=parser.parse_args()
    try:
        print(json.dumps(cutover(a.case,a.deploy_only)))
    except Exception as error:
        # No arbitrary remote exception, stderr, log, or credential reaches the caller.
        labels={'controller_child_operation_still_in_flight','remote_metadata_or_deployment_failed','remote_public_result_invalid',
                'matching_controller_not_live','single_controller_not_verified','unique_controller_state_not_verified',
                'controller_lifecycle_not_eligible','existing_retry_allowance_exhausted','issued_budget_exhausted',
                'checkpoint_finish_unconfirmed','current_encrypted_collection_failed'}
        print(json.dumps({'case':a.case,'status':'blocked','category':type(error).__name__,'reason':str(error) if str(error) in labels else 'public_validation_failed'}));raise SystemExit(1)
