import os, subprocess, pathlib, hashlib, json, datetime, time, re
out=pathlib.Path(__file__).resolve().parent
root=pathlib.Path.cwd()
def git(*args):
 return subprocess.check_output(['git',*args],text=True).strip()
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()
def fixtures():
 return {str(p.relative_to(root)):digest(p) for p in sorted((root/'tests/factory/fixtures').rglob('*')) if p.is_file()}
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
sha=git('rev-parse','HEAD'); tree=git('rev-parse','HEAD^{tree}')
assert sha=='8b8635a449f30456832884288536fee8c045f6c5'
assert git('rev-parse','merge/pilot-readiness-20261103')==sha
assert not git('status','--porcelain=v1')
before=fixtures()
(out/'fixture-hashes-before.json').write_text(json.dumps(before,indent=2)+'\n')
env=os.environ.copy(); env.pop('UNBUG_LOCAL_DOCKER_SMOKE',None)
env['PYTHONDONTWRITEBYTECODE']='1'
env['UV_OFFLINE']='1'
env['TEST_SLOTS']=env.get('TEST_SLOTS',str(os.cpu_count() or 1))
cmd=['uv','run','--with','numpy','--with','scipy','python','-B','tests/run.py']
r={'sha':sha,'tree':tree,'branch':git('branch','--show-current'),'cwd':str(root),'command':cmd,'command_text':' '.join(cmd),'environment_choices':{'UNBUG_LOCAL_DOCKER_SMOKE':'explicitly unset','PYTHONDONTWRITEBYTECODE':'1','UV_OFFLINE':'1','TEST_SLOTS':env['TEST_SLOTS'],'TEST_SLOT_DIR':env.get('TEST_SLOT_DIR','/tmp/unbug-test-slots'),'TEST_JOBS':env.get('TEST_JOBS','default CPU count'),'cache':'No test-result cache; fresh runner invocation, python -B. uv dependency cache retained for offline dependency resolution.'},'start_utc':now(),'log_path':str(out/'suite.log')}
(out/'record.json').write_text(json.dumps(r,indent=2)+'\n')
start=time.monotonic()
with (out/'suite.log').open('wb') as log:
 p=subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT)
r.update(end_utc=now(),wall_seconds=time.monotonic()-start,exit_code=p.returncode)
after=fixtures()
(out/'fixture-hashes-after.json').write_text(json.dumps(after,indent=2)+'\n')
r.update(post_sha=git('rev-parse','HEAD'),post_tree=git('rev-parse','HEAD^{tree}'),post_status_porcelain=git('status','--porcelain=v1'),fixture_hashes_unchanged=before==after,fixture_file_count=len(before))
log=(out/'suite.log').read_text(errors='replace')
summary=re.search(r'(\d+) test scripts run; (\d+) failed\.',log)
r['script_count']=int(summary[1]) if summary else None
r['failure_count']=int(summary[2]) if summary else None
r['failed_scripts']=re.findall(r'^FAILED: (.+)$',log,re.M)
r['skip_context']=[line for line in log.splitlines() if re.search(r'skip|SKIP',line)]
r['unittest_skip_count']=sum(map(int,re.findall(r'skipped=(\d+)',log)))
r['hashes_sha256']={p.name:digest(p) for p in [out/'suite.log',out/'fixture-hashes-before.json',out/'fixture-hashes-after.json',out/'validate.py']}
r['result']='PASS' if p.returncode==0 and summary and int(summary[2])==0 and sha==r['post_sha'] and tree==r['post_tree'] and not r['post_status_porcelain'] and before==after else 'FAIL'
(out/'record.json').write_text(json.dumps(r,indent=2)+'\n')
(out/'SHA256SUMS').write_text(''.join(digest(p)+'  '+p.name+'\n' for p in sorted(out.iterdir()) if p.is_file() and p.name!='SHA256SUMS'))
print(json.dumps(r,indent=2),flush=True)
