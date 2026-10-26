"""Deterministic production seam + real local PostgreSQL privileges. No models.
Run: python3 tests/bench/test_refusal.py
All business fixtures here are synthetic, not a real Medusa qualification.
"""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import copy
import json
import pathlib
import shutil
import socket
import subprocess
import tempfile
import types
import sys
from unittest.mock import patch
import bench
import refusal
sys.path.insert(0, str(bench.ROOT / 'factory'))
import fairness
import run as factory_run


def rpc(path, data):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(5)
        client.connect(str(path))
        client.sendall(json.dumps(data).encode() + b'\n')
        response = json.loads(client.makefile('rb').readline())
        if response.get('error'):
            raise RuntimeError(response['error'])
        return response


def production_seam(root):
    guard = root / 'guard'; guard.mkdir(); (guard / 'db.sql').write_text('-- synthetic fixture\n')
    base = root / 'base'; base.mkdir()
    q = root / 'qualification'; q.mkdir()
    (q / 'refusal-policy.json').write_text('{"policy":"synthetic"}')
    (q / 'refusal_oracle.py').write_text("""TAGS=('excess',)
FITTING=('fit',)
CHECKS=('business',)
CAPTURE_SQL='SELECT 1 AS synthetic_capture'
def fitting_path_usable(*args): return True
def complete(run, behavior, final):
    return {'status':'qualified' if final['facts']['controls'] else 'invalid','reason':'synthetic_controls'}
def qualify(operation, stage, wire, before, after):
    facts=before['facts']
    if 'remaining' not in facts:
        return {'status':'unqualified','reason':'prestate_missing'}
    return {'status':'qualified' if wire['body']['items'][0]['quantity']>facts['remaining'] else 'unqualified',
            'reason':'synthetic_excess_prestate'}
""")
    (base / 'judge.py').write_text("def judge(run, bench): return {'checks':{'business':True}}\n")
    (q / 'judge.py').write_text("""def judge(run, bench):
    op=run['traffic']['scenario_records']['BASE']['returns'][1]
    result=bench.qualify_refusal(run,op,op['failed_at'])
    return {'checks':{'refused':result['status']=='qualified'},
            'facts':{'qualification':{'status':'qualified' if result['status']=='qualified' else 'blocked'},'result':result}}
""")
    scenarios=[{'id':'BASE','dir':base},{'id':'SYNTHETIC','dir':q}]
    trial={'history':[], 'bad_nonce':False,'missing_history':False,'remaining':1,'controls':True,
           'missing_facts':False,'transport':False,'fit':True,'path':'/admin/returns/r/request-items',
           'instance':0,'retry':False,'drift':False,'source_drift':False,'transient_schema':False,'accepted':False,'model_approval':False}
    traffic_done=[]
    def sql(query, **kwargs):
        session=trial.get('session')
        nonce=session.nonce if session and not trial['bad_nonce'] else 'swapped'
        rows=copy.deepcopy(trial['history'])
        if trial['accepted']:
            rows=[{'seq':1,'nonce':nonce,'row_data':{'order_id':'o','id':'r'},'items':[]}]
        if 'FROM pg_hba_file_rules' in query:return '0'
        if 'synthetic_capture' in query:
            facts={'controls':trial['controls']}
            if not trial['missing_facts']:facts['remaining']=trial['remaining']
            return json.dumps({'nonce':nonce,'schema_stamp':'changed' if trial['transient_schema'] else 'stable',
                               'history':rows,'facts':facts})
        if query.startswith('SELECT encode'):return 'stable'
        if "'rows'," in query:
            return json.dumps({} if trial['missing_history'] else {'nonce':nonce,'rows':rows})
        if 'FROM pg_trigger t JOIN' in query:return '2'
        if query.startswith('SELECT json_build_object'):
            return json.dumps({'schema':'changed' if trial['drift'] and traffic_done else 'stable'})
        return ''
    def reset(*args, **kwargs):
        session=kwargs['refusal'];trial['session']=session;session.install()
        # This R5-style flag has no authority and is deliberately ignored.
        session.contract={'approved':trial['model_approval']}
        return {'reset_seconds':0}
    def traffic(args, **kwargs):
        session=trial['session']
        before=rpc(session.socket_path,{'event':'before','method':'POST','path':trial['path'],
                   'instance':trial['instance'],'body':{'items':[{'id':'l','quantity':2}]}})
        ident=before['id']
        rpc(session.socket_path,{'event':'after','id':ident,'status':500,
             'transport_error':trial['transport'],'retried':trial['retry']})
        traffic_done.append(True)
        operation={'tag':'excess','order_id':'o','line_id':'l','return_id':'r','quantity':2,
                   'failed_at':'request_items','steps':{'request_items':{'status':500,'judge_request_id':ident}}}
        return json.dumps({'approved':trial['model_approval'],'scenario_records':{'BASE':{'returns':[
            {'tag':'fit','received':trial['fit']},operation]}}})
    check={k:True for k in bench.BASE_CHECKS};check.update(orders={},oversold=False,valid=True)
    runtime=lambda self:[{'image':'SYNTHETIC','instance':0},{'image':'SYNTHETIC','instance':1}]
    original_read_bytes = pathlib.Path.read_bytes
    def source_bytes(path):
        data = original_read_bytes(path)
        if path.name == 'bench_judging.py' and trial['source_drift'] and traffic_done:
            return data + b'\n# synthetic drift\n'
        return data
    with (patch.object(pathlib.Path, 'read_bytes', source_bytes),
          patch.object(bench,'RESULTS',root/'results'),patch.object(bench,'reset',reset),
          patch.object(bench,'command',traffic),patch.object(bench,'sql',sql),
          patch.object(bench,'checker',lambda:copy.deepcopy(check)),patch.object(bench,'score',lambda result:None),
          patch.object(bench.bench_judging,'inventory_judge',return_value={'checks':{},'facts':{},'paths':[],'violated':{},'legit':[0,0]}),
          patch.object(bench,'check_inventory_services',return_value={}),
          patch.object(refusal.BehavioralRefusal,'runtime',runtime),
          patch.object(fairness,'review_attempts',side_effect=AssertionError('SCORING MUST NOT CALL REVIEW'))):
        def run():
            traffic_done.clear()
            return bench.run_once(guard,1,{},scenarios=scenarios)
        first=run();assert first['judge']['pass'],first
        assert 'bench_judging.py' in first['refusal_evidence']['identity']['sources']
        assert not (root/'results/refusal-review').exists()
        case = root / 'case'
        shutil.copytree(base, case / 'base')
        shutil.copytree(q, case / 'scenarios/SYNTHETIC')
        shutil.copytree(guard, case / 'guards/reference')
        (case / 'case.json').write_text('{"promise_checks":["refused"]}')
        (case / 'scenarios/SYNTHETIC/key.json').write_text('{"expected_judge":{"reference":true}}')
        context = types.SimpleNamespace(case=case,work=root/'work',card={},seed=1,
            args=types.SimpleNamespace(runs=1,scenario_runs=1,bench_workers=1))
        context.work.mkdir()
        def checkpoint(c, scenarios, guard, runs, seed, label, **kwargs):
            return {'legit_completion':1,'key_consistent':first['judge']['pass']}, [first]
        with (patch.object(factory_run,'checkpoint',checkpoint),
              patch.object(factory_run,'model_call',side_effect=AssertionError('G5 MUST NOT CALL MODEL'))):
            assert factory_run.g5(context)[0]
        nonce=first['refusal_evidence']['nonce']
        trial['model_approval']=True
        second=run();assert second['judge']['pass']
        assert nonce!=second['refusal_evidence']['nonce']
        # Distinct submitted guard revision needs no approval or model cache.
        (guard/'db.sql').write_text('-- distinct synthetic guard revision\n')
        third=run();assert third['judge']['pass']
        assert third['refusal_identity']!=second['refusal_identity']
        for key,value in [('transport',True),('fit',False),('path','/admin/returns/other/request-items'),
                          ('instance',7),('retry',True),('remaining',2),('missing_facts',True),
                          ('controls',False),('bad_nonce',True),('missing_history',True),
                          ('drift',True),('source_drift',True),('transient_schema',True),('accepted',True)]:
            previous=trial[key];trial[key]=value
            result=run()
            assert result['judge'].get('invalid'),(key,result)
            assert not result['checker']['valid']
            trial[key]=previous
        assert run()['judge']['pass']
    print('deterministic cold-start production seam: positive, ambiguous/fitting/control/transport negatives, fresh guard, ignored approval, swapped/missing history; review driver never called')


def postgres_witness(root, oracle=None):
    if not all(shutil.which(name) for name in ('initdb', 'pg_ctl', 'psql')):
        print('PostgreSQL witness permission check deferred: local PostgreSQL binaries unavailable')
        return
    data = root / 'pgdata'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    def command(args, check=True):
        return subprocess.run(args, capture_output=True, text=True, timeout=30, check=check)
    command(['initdb', '-D', str(data), '-U', 'medusa', '--auth-local=trust', '--auth-host=scram-sha-256', '--no-locale'])
    with tempfile.TemporaryDirectory(prefix='ubr-sock-', dir='/tmp') as unix:
        command(['pg_ctl', '-D', str(data), '-l', str(root / 'postgres.log'), '-o', f'-h 127.0.0.1 -k {unix} -p {port}', '-w', 'start'])
        try:
            def sql(query, check=True, user='medusa'):
                p = subprocess.run(['psql', '-XqAt', '-v', 'ON_ERROR_STOP=1', '-h', unix,
                                    '-p', str(port), '-U', user, '-d', 'postgres'],
                                   input=query, capture_output=True, text=True, timeout=15)
                if check and p.returncode:
                    raise AssertionError(p.stderr)
                return p.stdout.strip() if check else p
            sql('''CREATE ROLE bench_guard LOGIN NOSUPERUSER; CREATE ROLE medusa_app LOGIN NOSUPERUSER;
              CREATE TABLE public.return(id text,order_id text,exchange_id text,requested_at timestamptz);
              CREATE TABLE public.order_change(id text,order_id text,return_id text,exchange_id text,
                change_type text,requested_at timestamptz,confirmed_at timestamptz);
              CREATE TABLE public.return_item(return_id text,item_id text,quantity integer);
              GRANT USAGE ON SCHEMA public TO medusa_app,bench_guard;
              GRANT SELECT,INSERT,UPDATE,DELETE ON public.return,public.return_item,public.order_change TO medusa_app;
              GRANT TRIGGER ON public.return TO bench_guard;''')
            witness = refusal.BehavioralRefusal.__new__(refusal.BehavioralRefusal)
            witness.bench = types.SimpleNamespace(sql=sql); witness.nonce = 'synthetic-nonce'
            witness.install()
            import os
            remote = subprocess.run(['psql', '-XqAt', '-h', '127.0.0.1', '-p', str(port),
                                     '-U', 'medusa', '-d', 'postgres', '-c', 'SELECT 1'],
                                    env={**os.environ, 'PGPASSWORD': 'medusa'}, capture_output=True, timeout=10)
            assert remote.returncode != 0, 'public fixture password must not reach administrator'
            schema_before = json.loads(sql(refusal.schema_sql()))
            sql("INSERT INTO public.return VALUES('r','o',NULL,now()); UPDATE public.return SET requested_at=NULL; DELETE FROM public.return;", user='medusa_app')
            assert sql('SELECT count(*) FROM bench_refusal.history') == '1'
            sql("INSERT INTO order_change VALUES('change','o','r','exchange','exchange',NULL,now()); UPDATE order_change SET confirmed_at=NULL; DELETE FROM order_change;", user='medusa_app')
            assert sql("SELECT count(*) FROM bench_refusal.history WHERE kind='change'") == '1'
            for role in ('medusa_app', 'bench_guard'):
                for attack in ('DELETE FROM bench_refusal.history', 'SELECT * FROM bench_refusal.history',
                               'SELECT nonce FROM bench_refusal.meta', "UPDATE bench_refusal.meta SET nonce='forged'",
                               'SET ROLE medusa', 'TRUNCATE public.return',
                               'TRUNCATE public.order_change',
                               'ALTER TABLE public.order_change DISABLE TRIGGER bench_refusal_change_history',
                               'ALTER TABLE public.return DISABLE TRIGGER bench_refusal_history',
                               'CREATE OR REPLACE TRIGGER bench_refusal_history AFTER INSERT ON public.return FOR EACH ROW EXECUTE FUNCTION bench_refusal.capture()'):
                    assert sql(attack, check=False, user=role).returncode != 0, (role, attack)
            sql('ALTER TABLE public.return ADD CONSTRAINT synthetic_unrelated CHECK(id <> \'backend-failure\')')
            assert schema_before != json.loads(sql(refusal.schema_sql()))
            sql('ALTER TABLE public.return DROP CONSTRAINT synthetic_unrelated; DROP TRIGGER bench_refusal_history ON public.return; DROP SCHEMA bench_refusal CASCADE')
            witness.nonce = 'a-new-trial'
            witness.install()
            assert schema_before == json.loads(sql(refusal.schema_sql())), 'trial nonce must not invalidate immutable review identity'
            if oracle is not None:
                # Synthetic canonical Medusa tables validate the ACTUAL private
                # capture SQL and pack conversion using real PostgreSQL.
                sql('''CREATE TABLE fulfillment(id text,deleted_at timestamp,canceled_at timestamp);
                  CREATE TABLE fulfillment_item(fulfillment_id text,line_item_id text,inventory_item_id text,quantity numeric,deleted_at timestamp);
                  CREATE TABLE order_fulfillment(order_id text,fulfillment_id text);
                  CREATE TABLE order_line_item(id text,variant_id text);
                  CREATE TABLE product_variant_inventory_item(variant_id text,inventory_item_id text,required_quantity numeric,deleted_at timestamp);
                  CREATE TABLE public."order"(id text,status text,deleted_at timestamp);
                  CREATE TABLE order_item(order_id text,item_id text,version int,quantity numeric,fulfilled_quantity numeric,deleted_at timestamp);
                  CREATE TABLE order_change_action(id text,action text);
                  CREATE TABLE inventory_level(id text,inventory_item_id text,stocked_quantity numeric,reserved_quantity numeric,deleted_at timestamp);
                  INSERT INTO fulfillment VALUES('f',NULL,NULL);
                  INSERT INTO fulfillment_item VALUES('f','l','i',4,NULL);
                  INSERT INTO order_fulfillment VALUES('o','f');
                  INSERT INTO order_line_item VALUES('l','v');
                  INSERT INTO product_variant_inventory_item VALUES('v','i',2,NULL);
                  INSERT INTO public."order" VALUES('o','pending',NULL);
                  INSERT INTO order_item VALUES('o','l',1,2,2,NULL);
                  INSERT INTO inventory_level VALUES('level','i',10,0,NULL);''')
                witness.oracle = oracle
                witness.schema_stamp = sql(refusal.schema_stamp_sql())
                captured = witness.snapshot()
                assert captured['facts']['lots'][0]['quantity'] == 2
                assert captured['facts']['obligations'][0]['quantity'] == 0
        finally:
            command(['pg_ctl', '-D', str(data), '-m', 'immediate', '-w', 'stop'])
    print('real PostgreSQL: acceptance retained after cleanup; app/guard cannot modify witness, truncate or disable/replace trigger')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='unbug-refusal-test-') as tmp:
        root=pathlib.Path(tmp)
        production_seam(root)
        postgres_witness(root)
