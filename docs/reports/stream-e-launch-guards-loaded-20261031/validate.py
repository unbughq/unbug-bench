import subprocess, time, os, json, threading
from pathlib import Path
p=Path(__file__).parent
root=Path('/Users/bugsincode/.t3/worktrees/unbug-bench/t3-b66ae96c')
env={**os.environ,'BENCH':str(root),'PYTHONUNBUFFERED':'1'}
results=[]
lock=threading.Lock()
stop=threading.Event()
def run(label, args):
    start=time.time()
    with (p/(label+'.log')).open('w') as f:
        proc=subprocess.Popen(['nice','-n','10',*args],cwd=root,env=env,stdout=f,stderr=subprocess.STDOUT)
        row={'label':label,'command':args,'pid':proc.pid,'start':start,'load_start':os.getloadavg()}
        code=proc.wait()
    row.update(exit_code=code,end=time.time(),load_end=os.getloadavg())
    with lock:
        results.append(row)
        (p/'results.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(row),flush=True)
    return code
burners=[subprocess.Popen(['python3','-c','while True: pass']) for _ in range(3)]
(p/'environment.json').write_text(json.dumps({'cpu_count':os.cpu_count(),'load':os.getloadavg(),'burners':[x.pid for x in burners],'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()},indent=2))
def suites():
    n=0
    while not stop.is_set():
        n+=1
        run('full-suite-'+str(n),['uv','run','--with','numpy','--with','scipy','python','-B','tests/run.py'])
t=threading.Thread(target=suites)
try:
    t.start()
    for n in range(1,6):
        for label,path in [('launch','tests/bench/test-launch-guards.py'),('isolation','tests/factory/test_isolation_timeouts.py')]:
            if run(f'{label}-{n}',['uv','run','--with','numpy','--with','scipy','python','-B',path]):
                raise SystemExit('Focused check failed; inspect logs')
finally:
    stop.set()
    t.join()
    for x in burners: x.terminate()
    for x in burners: x.wait()
