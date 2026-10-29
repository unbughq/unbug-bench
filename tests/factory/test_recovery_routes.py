#!/usr/bin/env python3
"""Synthetic keys, cards, ciphertext and fake cloud only."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import copy, datetime, hashlib, importlib.util, io, json, os, pathlib
import shutil, subprocess, sys, tarfile, tempfile, time

SOURCE=(pathlib.Path(__file__).resolve().parents[2] / "factory" / 'key_holder.py')

def load(path):
    spec=importlib.util.spec_from_file_location('holder_fixture',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def fails(fn):
    try:fn()
    except ValueError:return
    raise AssertionError('unsafe request accepted')

def bundle(path,recipient,names):
    data=io.BytesIO()
    with tarfile.open(fileobj=data,mode='w') as tar:
        for name in names:
            raw=('synthetic-'+name).encode();info=tarfile.TarInfo(name);info.size=len(raw);tar.addfile(info,io.BytesIO(raw))
    result=subprocess.run(['age','-r',recipient],input=data.getvalue(),capture_output=True,check=True)
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(result.stdout)

def main():
    with tempfile.TemporaryDirectory() as folder:
        root=pathlib.Path(folder).resolve();(root/'factory').mkdir();(root/'bin').mkdir();(root/'sealed').mkdir()
        for name in ('recovery.py', 'control_resume.py', 'account_handoff.py', 'launch_manifest.py'):
            shutil.copyfile(SOURCE.with_name(name), root/'factory'/name)
        script=root/'factory/key_holder.py';shutil.copyfile(SOURCE,script);m=load(script)
        case='case-synthetic';archive=root/'sealed'/f'{case}.checkpoint.tar.gz.age';cardpath=root/'sealed'/f'{case}.scorecard.json'
        roles={'strong_calibrator':{'model':'codex/gpt-6.1-sol','effort':'high','family':'openai'},'reviewer':{'model':'openrouter/meta/muse-spark-1.3-contributor','effort':'xhigh','family':'meta'}}
        card={'case':case,'status':'stopped','dry_run':False,'failed_gate':None,'roles':roles,'terminal_stop':'opencode_error',
              'calibration_interruptions':{'strong_calibrator':{'model_process_error':1},'easy_calibrator':{'cancelled':1}},
              'continuation_budget':{'calls':4,'cost':.2,'events':[],'active':[],'terminal_stop':'cancelled'}}
        job={'case':case,'mode':'case','card':cardpath.name,'archive_prefix':case,'roles':roles,'max_calls':20,'max_cost':1.0,
             'args':['1','--restore',case],'allow_parallel_peer_cancellation':True,
             'allow_collected_generation_reconciliation':True,'opencode_accounts':[1,2],'opencode_account':2}
        def save_card(payload=b'synthetic ciphertext'):
            archive.write_bytes(payload);card['sha256']=hashlib.sha256(payload).hexdigest();cardpath.write_text(json.dumps(card));return card['sha256']
        generation=save_card()
        assert m.current_generation(job)==generation
        fails(lambda:m.current_generation({**job,'allow_parallel_peer_cancellation':False}))
        original=copy.deepcopy(card)
        for change in [
            {'calibration_interruptions':{}},
            {'calibration_interruptions':{'strong_calibrator':{'model_process_error':True},'easy_calibrator':{'cancelled':1}}},
            {'calibration_interruptions':{'strong_calibrator':{'model_process_error':1,'cost_limit':1},'easy_calibrator':{'cancelled':1}}},
            {'calibration_interruptions':{'strong_calibrator':{'model_process_error':1,'cancelled':1}}},
            {'failed_gate':'G8'},
            {'continuation_budget':{**card['continuation_budget'],'terminal_stop':'cost_limit'}},
            {'continuation_budget':{**card['continuation_budget'],'calls':20}},
            {'continuation_budget':{**card['continuation_budget'],'active':['pending']}},
        ]:
            card.update(change);save_card();fails(lambda:m.current_generation(job));card=copy.deepcopy(original)
        # Model name/version, family and effort remain exact; the route may change (OpenRouter -> OpenCode Go, 2026-10-19).
        before=card['roles']['reviewer']['model']; card['roles']['reviewer']['model']='opencode-go/'+before.rsplit('/',1)[-1]; save_card()
        assert m.current_generation(job); card['roles']['reviewer']['model']=before; save_card()
        for change in [('model','opencode-go/muse-spark-1.2-contributor'),('effort','high'),('family','xiaomi')]:
            before=card['roles']['reviewer'][change[0]];card['roles']['reviewer'][change[0]]=change[1];save_card();fails(lambda:m.current_generation(job));card['roles']['reviewer'][change[0]]=before
        card=copy.deepcopy(original);save_card()
        old={'case':case,'generation':'older-generation','at':time.time()-60,'completed_ok':False,'budget_calls':3,'budget_cost':.1}
        terminal={'retired':True,'archive_verified':True,'expected_archive_sha256':generation,'card_mtime_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cumulative_calls':4,'cumulative_cost':.2}
        state={'workers':[{'id':'bx_synthetic','case':case,'retired':True,'terminal':terminal}]}
        assert m.collected_successor(job,generation,old,state)=='bx_synthetic'
        assert m.collected_successor(job,generation,{**old,'generation':generation},state) is None
        assert m.collected_successor(job,generation,old,{'workers':[]}) is None
        for field,value in [('archive_verified',False),('expected_archive_sha256','wrong'),('card_mtime_utc','2000-01-01T00:00:00+00:00')]:
            bad=copy.deepcopy(state);bad['workers'][0]['terminal'][field]=value;assert m.collected_successor(job,generation,old,bad) is None
        bad=copy.deepcopy(state);bad['workers'][0]['retired']=False;assert m.collected_successor(job,generation,old,bad) is None
        assert m.collected_successor(job,generation,{**old,'budget_calls':5},state) is None
        assert m.collected_successor(job,generation,{**old,'budget_cost':.3},state) is None
        legacy={k:v for k,v in old.items() if k not in ('budget_calls','budget_cost')}
        assert m.collected_successor(job,generation,legacy,state) is None
        legacyjob={**job,'legacy_generation_budgets':{old['generation']:{'budget_calls':3,'budget_cost':.1}}}
        assert m.collected_successor(legacyjob,generation,legacy,state)=='bx_synthetic'
        assert m.collected_successor(legacyjob,generation,{**legacy,'generation':'unknown'},state) is None
        # Real age crypto on disposable synthetic identities. No real archive is decrypted.
        identity=root/'synthetic-identity';subprocess.run(['age-keygen','-o',str(identity)],check=True,capture_output=True)
        key=next(v for v in identity.read_bytes().splitlines() if v.startswith(b'AGE-SECRET-KEY-'))+b'\n'
        recipient=subprocess.check_output(['age-keygen','-y',str(identity)],text=True).strip()
        home=root/'home';secretpath=home/'.config/unbug-bench/secrets.age'
        bundle(secretpath,recipient,['opencode-go-key-2','opencode-go-key'])
        assert m.secret_labels(key,secretpath)=={'opencode-go-key','opencode-go-key-2'}
        launcher=root/'factory/launch.sh';launcher.write_text('#!/bin/sh\nset -eu\nidentity=$(cat)\nprintf "%s" "$OPENCODE_SECRET_NAME" > selected-label.txt\nprintf "synthetic fixture output\\n"\n')
        boat=root/'bin/boat-call';boat.write_text('#!/bin/sh\nprintf \'{"sandboxes":[],"pageInfo":{"hasMore":false}}\\n\'\n');boat.chmod(0o755)
        policy={'root':str(root),'code_sha256':m.fingerprint(root),'recipient':recipient,'path':os.environ['PATH'],'jobs':{'fixture':job}}
        policyfile=root/'policy.json';policyfile.write_text(json.dumps(policy))
        def start():
            process=subprocess.Popen([sys.executable,str(script),'serve','--policy',str(policyfile),'--hours','.02'],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env={**os.environ,'HOME':str(home)})
            process.stdin.write(key);process.stdin.close()
            for _ in range(100):
                if process.poll() is not None:raise AssertionError('synthetic server exited')
                try:
                    status=m.request({'op':'status'})
                    if status.get('unlocked'):return process,status
                except (OSError,ValueError):pass
                time.sleep(.05)
            raise AssertionError('synthetic server not ready')
        def wait_job():
            for _ in range(100):
                status=m.request({'op':'status'})
                if status['jobs']['fixture']['exit'] is not None:return status
                time.sleep(.03)
            raise AssertionError('synthetic launcher not finished')
        process,status=start()
        try:
            assert status['opencode_accounts']=={'1':True,'2':True}
            for bad in (None,True,3,'2'):
                assert 'error' in m.request({'op':'launch','job':'fixture','opencode_account':bad})
            assert m.request({'op':'launch','job':'fixture','opencode_account':2}).get('started')
            status=wait_job();assert status['jobs']['fixture']['exit']==0
            assert (root/'selected-label.txt').read_text()=='opencode-go-key-2'
            assert 'error' in m.request({'op':'launch','job':'fixture','opencode_account':1}), 'same generation cannot replay through another account'
            card['continuation_budget']['calls']=5;generation=save_card(b'synthetic generation two')
            assert m.request({'op':'launch','job':'fixture','opencode_account':1}).get('started');wait_job()
            assert (root/'selected-label.txt').read_text()=='opencode-go-key'
            assert key.strip().decode() not in json.dumps(status)
        finally:m.request({'op':'stop'});process.wait(timeout=5)
        # A missing secondary account is refused before consuming a new generation.
        bundle(secretpath,recipient,['opencode-go-key']);card['continuation_budget']['calls']=6;save_card(b'synthetic generation three')
        process,status=start()
        try:
            assert status['opencode_accounts']=={'1':True,'2':False}
            assert 'error' in m.request({'op':'launch','job':'fixture','opencode_account':2})
            assert m.request({'op':'launch','job':'fixture','opencode_account':1}).get('started');wait_job()
            card['continuation_budget']['calls']=7;save_card(b'synthetic generation four')
            assert 'error' in m.request({'op':'launch','job':'fixture','opencode_account':1}), 'three-generation ceiling must remain'
            receipts=json.loads((m.RUNTIME/'reservations.json').read_text());assert len(receipts)==3
            assert [v['opencode_account'] for v in receipts]==[2,1,1]
        finally:m.request({'op':'stop'});process.wait(timeout=5)
        # A restarted broker cannot reap an old external controller. Only a verified,
        # newer and monotonic collected generation can resolve that synthetic receipt.
        receipts_path=m.RUNTIME/'reservations.json'
        legacy={'case':case,'generation':'synthetic-reserved-old','at':time.time()-60,'completed_ok':False,'pid':999999}
        receipts_path.write_text(json.dumps([legacy]))
        card['continuation_budget']['calls']=8;generation=save_card(b'synthetic collected successor')
        terminal.update(expected_archive_sha256=generation,cumulative_calls=8,card_mtime_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        state={'workers':[{'id':'bx_synthetic','case':case,'retired':True,'terminal':terminal}]}
        statepath=root/'results/infrastructure/2026-10-18-claude-return/monitor-state.json';statepath.parent.mkdir(parents=True)
        job['opencode_accounts']=[2];job['opencode_account']=2
        bundle(secretpath,recipient,['opencode-go-key','opencode-go-key-2'])
        policy['jobs']['fixture']=job;policyfile.write_text(json.dumps(policy))
        process,status=start()
        try:
            assert 'error' in m.request({'op':'launch','job':'fixture','opencode_account':None})
            assert 'error' in m.request({'op':'launch','job':'fixture','opencode_account':1})
            assert 'error' in m.request({'op':'launch','job':'fixture','opencode_account':2}), 'legacy receipt without budget floor is unresolved'
            assert len(json.loads(receipts_path.read_text()))==1
        finally:m.request({'op':'stop'});process.wait(timeout=5)
        job['legacy_generation_budgets']={legacy['generation']:{'budget_calls':7,'budget_cost':.2}}
        policyfile.write_text(json.dumps(policy))
        process,status=start()
        try:
            assert 'error' in m.request({'op':'launch','job':'fixture','opencode_account':2}), 'collection proof is mandatory'
            statepath.write_text(json.dumps(state))
            assert m.request({'op':'launch','job':'fixture','opencode_account':2}).get('started');wait_job()
            receipts=json.loads(receipts_path.read_text())
            assert receipts[0]['generation']==legacy['generation'] and receipts[0]['completed_ok'] is False
            assert receipts[0]['resolved_by_verified_generation']==generation and len(receipts)==2
            assert 'error' in m.request({'op':'launch','job':'fixture','opencode_account':2}), 'successor generation still cannot replay'
        finally:m.request({'op':'stop'});process.wait(timeout=5)
    print('PASS exact recorded roles, peer cancellation, monotonic collection proof, private account metadata, explicit selection, missing-account refusal, replay refusal and original recovery ceiling; synthetic only')

if __name__=='__main__':main()
