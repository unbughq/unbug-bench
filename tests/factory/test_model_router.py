"""Replay real public VM denials and ledgers; no model or cloud call starts."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'factory'))
import copy
import argparse
from dataclasses import asdict
import gzip
import json
import os
import tempfile
import subprocess
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
import urllib.request
import uuid
import model_router as router
import model_runtime
import budget
import run

FIXTURES = Path(__file__).with_name('fixtures')
LIMITS = json.loads(gzip.decompress((FIXTURES / 'router-provider-limits.json.gz').read_bytes()))
PAID = json.loads(gzip.decompress((FIXTURES / 'router-paid-deepseek.json.gz').read_bytes()))


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = [1792510000.0]
        self.store = router.Store(self.root / 'router.sqlite', clock=lambda: self.now[0])

    def acquire(self, model, *, identity=None, accounts=router.ACCOUNTS):
        return self.store.rpc('acquire', dict(id=identity or uuid.uuid4().hex, model=model,
            accounts=list(accounts), role='writer', deadline=self.now[0] + 86400))

    def finish(self, lease, outcome='done'):
        return self.store.rpc('finish', dict(lease_id=lease['lease_id'], outcome=outcome, receipt=None))

    def observe(self, lease, reason, **extra):
        return self.store.rpc('observe', dict(lease_id=lease['lease_id'], reason=reason,
            observation_id=lease['lease_id'] + ':failure', **extra))

    def test_real_claude_reset_shared_switch_expiry_and_restart(self):
        cards = [c for c in LIMITS if c['terminal_stop'].startswith('provider_limit:claude/')]
        reset = cards[0]['continuation_budget']['claude_resets_at']
        self.assertEqual({c['continuation_budget']['claude_resets_at'] for c in cards}, {reset})
        first = self.acquire(cards[0]['terminal_stop'].split(':', 1)[1])
        self.assertEqual(first['account'], 'claude-token')
        self.observe(first, 'quota', reset_at=reset); self.finish(first, 'interrupted')
        second = self.acquire(first['route'])
        self.assertEqual(second['account'], 'claude-factory-token-2')
        self.observe(second, 'quota', reset_at=reset); self.finish(second, 'interrupted')
        waiting = self.acquire(first['route'])
        self.assertEqual((waiting['kind'], waiting['retry_after']), ('wait', reset))
        # A fresh process sees the same limit, rather than a worker-local blacklist.
        self.store = router.Store(self.root / 'router.sqlite', clock=lambda: self.now[0])
        self.assertEqual(self.store.rpc('capacity', {'route': first['route']})['slots'], 0)
        self.now[0] = reset + 1
        self.assertEqual(self.store.rpc('capacity', {'route': first['route']})['slots'], 2)
        self.assertTrue(all(not v['blocked_until'] for v in self.store.rpc('status', {})['health'].values()))
        self.assertEqual(router.retry_at('quota', now=0, reset_at=7 * 3600), 7 * 3600)

    def test_real_paid_deepseek_ledger_is_explicit_and_not_rebooked(self):
        source, target = router.CHAINS[0]
        choices = router.routes(source)
        self.assertEqual([(r['route'], r['billing']) for r in choices], [(source, 'free'), (target, 'paid')])
        first = self.acquire(source); self.observe(first, 'outage'); self.finish(first, 'interrupted')
        selected = self.acquire(source)
        self.assertEqual((selected['route'], selected['account'], selected['family']), (target, 'openrouter-key', 'deepseek'))
        for card in PAID:
            ledger = copy.deepcopy(card['continuation_budget']); before = json.dumps(ledger, sort_keys=True)
            events = [e for e in ledger['events'] if e.get('configured_model') == target]
            self.assertGreater(sum(e['cost'] for e in events), 0)
            self.assertTrue(all(e['id'] and e['tokens'] for e in events))
            self.assertIsNotNone(budget.case_spending(ledger)['spent_usd'])
            self.assertEqual(json.dumps(ledger, sort_keys=True), before)

    def test_wallet_credit_denial_is_shared_and_requires_explicit_topup(self):
        model = next(c['terminal_stop'].split(':', 1)[1] for c in LIMITS if 'openrouter/' in c['terminal_stop'])
        lease = self.acquire(model)
        observation = budget.classify_provider_failure('HTTP 402 insufficient credits', lease['route'])
        self.observe(lease, observation['reason']); self.finish(lease, 'interrupted')
        self.now[0] += 86400
        self.assertEqual(self.store.rpc('capacity', {'route': 'openrouter/deepseek/deepseek-v4.1-flash'})['slots'], 0)
        healthy = dict(pool='openrouter-key', healthy=True, observation_id='verified-topup')
        self.store.rpc('observe', healthy)
        self.store.rpc('observe', healthy)  # Idempotent receipt.
        self.assertGreater(self.store.rpc('capacity', {'route': 'openrouter/deepseek/deepseek-v4.1-flash'})['slots'], 0)
        self.assertEqual(self.acquire('openrouter/deepseek/deepseek-v4.1-flash')['kind'], 'lease')

    def test_credential_renewal_observation_and_unblocked_noop(self):
        lease = self.acquire('codex/gpt-6.1-sol')
        self.observe(lease, 'credential_expiring'); self.finish(lease, 'denied')
        self.now[0] += 4000
        self.assertEqual(self.store.rpc('capacity', {'route': lease['route']})['slots'], 0)
        self.store.rpc('observe', dict(pool='codex-auth.json', healthy=True, observation_id='renewed-login'))
        self.assertEqual(self.store.rpc('capacity', {'route': lease['route']})['slots'], 1)
        self.store.rpc('observe', dict(pool='claude-token', healthy=True, observation_id='unblocked-noop'))
        self.assertNotIn('claude-token', self.store.rpc('status', {})['health'])

    def test_renew_reclaim_and_idempotent_finish(self):
        identity = uuid.uuid4().hex
        first = self.acquire('codex/gpt-6.1-sol', identity=identity)
        self.assertEqual(first, self.acquire(first['route'], identity=identity))
        self.now[0] += 60
        renewed = self.store.rpc('renew', {'lease_id': identity})
        self.assertEqual(renewed['expires_at'], self.now[0] + 180)
        self.now[0] += 179
        self.assertEqual(self.store.rpc('capacity', {'route': first['route']})['slots'], 0)
        self.now[0] += 1
        self.assertEqual(self.store.rpc('capacity', {'route': first['route']})['slots'], 1)
        self.finish(first, 'interrupted'); self.finish(first, 'interrupted')
        with self.assertRaises(ValueError): self.finish(first, 'done')

    def test_chains_preserve_family_billing_and_exam_exclusion(self):
        for chain in router.CHAINS:
            for requested in chain:
                rows = router.routes(requested)
                self.assertEqual(rows[0]['route'], requested)
                self.assertEqual({r['family'] for r in rows}, {model_runtime.family(requested)})
                self.assertTrue(all(r['pool'] and r['billing'] in ('free', 'paid', 'subscription') for r in rows))
        self.assertEqual({r['account'] for r in router.routes('claude/claude-opus-5-5')}, {'claude-token', 'claude-factory-token-2'})
        with self.assertRaises(ValueError): router.routes('claude/claude-opus-5-5', ['claude-token-2'])

    def test_http_auth_and_lost_acquire_response_reuses_lease(self):
        server = router.Server(('127.0.0.1', 0), self.store, 'synthetic-batch-token')
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        env = {'FACTORY_ROUTER_URL': 'http://127.0.0.1:' + str(server.server_port), 'FACTORY_ROUTER_TOKEN': 'synthetic-batch-token'}
        request = dict(id=uuid.uuid4().hex, model='codex/gpt-6.1-sol', accounts=list(router.ACCOUNTS), role='reviewer', deadline=time.time() + 3600)
        with patch.dict(os.environ, env):
            first = router._rpc('acquire', request)
            self.assertEqual(first, router._rpc('acquire', request))
            with patch.dict(os.environ, {'FACTORY_ROUTER_TOKEN': 'wrong'}), self.assertRaises(router.RouterUnavailable):
                router._rpc('status', {})

    def test_unavailable_router_wait_is_bounded_and_recorded(self):
        clock = [1000.0]
        c = SimpleNamespace(work=self.root, case_id=LIMITS[0]['case'], card={},
            batch_id='batch', job_id='job', batch_deadline=20000, router_model=router.CHAINS[0][0])
        def sleep(seconds): clock[0] += seconds
        with patch.dict(os.environ, {'UNBUG_PROVIDER_WAIT': '1'}), patch.object(router, '_rpc', side_effect=router.RouterUnavailable), \
             patch.object(router.time, 'time', side_effect=lambda: clock[0]), patch.object(router.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(router.time, 'sleep', side_effect=sleep):
            with self.assertRaises(router.ProviderWait) as result: router.await_lease('writer', c)
            record = run.write_provider_wait(c, result.exception)
        self.assertEqual(clock[0], 1060)
        self.assertEqual((record['reason'], record['evidence'], record['lease_id'], record['settled']), ('router_unavailable', 'denied_before_work', None, False))
        self.assertTrue((self.root / '.router-wait').exists())
        card = json.loads((self.root / 'scorecard.json').read_text())
        self.assertEqual((card['terminal_stop'], card['provider_wait']['wait_id']), ('provider_wait', record['wait_id']))
        self.assertNotIn('checkpoint_sha256', record)
        self.assertNotIn('parent_generation', record)
        with patch.dict(os.environ, {'UNBUG_PROVIDER_WAIT': '1'}), self.assertRaisesRegex(budget.BudgetError, 'provider_wait_unsettled'):
            router.await_lease('writer', c)

    def test_real_reset_parser_and_credit_scope(self):
        reset = next(c['continuation_budget']['claude_resets_at'] for c in LIMITS if 'claude/' in c['terminal_stop'])
        failure = budget.classify_provider_failure('usage limit reached', 'claude/claude-opus-5-5', reset_at=reset)
        self.assertEqual(failure, dict(reason='quota', scope='account', model='claude/claude-opus-5-5', reset_at=reset))
        self.assertEqual(budget.classify_provider_failure('HTTP 402', 'openrouter/deepseek/deepseek-v4.1-flash')['scope'], 'wallet')
        self.assertEqual(budget.classify_provider_failure('HTTP 429', 'openrouter/deepseek/deepseek-v4.1-flash')['reason'], 'rate')
        self.assertEqual(budget.classify_provider_failure('HTTP 503', 'opencode/deepseek-v4.1-flash-free')['scope'], 'route')

    def context(self):
        card = copy.deepcopy(PAID[0])
        c = SimpleNamespace(work=self.root, case=self.root / 'case', case_id=card['case'], card=card,
            ledger=self.root / 'ledger.json', batch_id='batch', job_id='job', batch_deadline=time.time()+86400,
            args=argparse.Namespace(agent_timeout=10, max_cost=100, max_role_calls=100,
                max_total_calls=10000, no_progress_minutes=1, max_zero_tokens=3, case_budget=1000))
        c.case.mkdir(); (c.work / 'transcripts').mkdir()
        c.ledger.write_text(json.dumps(card['continuation_budget']))
        secrets = self.root / 'ram'; secrets.mkdir()
        for label in router.ACCOUNTS: (secrets / label).write_text('synthetic-only')
        auth = {'auth_mode':'chatgpt','tokens':{'access_token':'e30.eyJleHAiOjk5OTk5OTk5OTl9.synthetic-one',
            'account_id':'synthetic','refresh_token':'synthetic'},'last_refresh':'2026-10-29T00:00:00Z'}
        (secrets / 'codex-auth.json').write_text(json.dumps(auth))
        self.store = router.Store(self.root / 'runtime.sqlite')
        return c, secrets, auth

    def test_all_roles_use_admission_and_preserve_real_ledger(self):
        c, secrets, _ = self.context()
        before = c.ledger.read_bytes()
        calls = [('builder-1','writer'), ('attacker-1','stress_tester'), ('reviewer-1','reviewer'),
            ('strong-calibrator-1','strong_calibrator'), ('easy-calibrator-1','easy_calibrator'),
            ('easy-calibrator-dedup','easy_calibrator'), ('builder-freshness','writer'),
            ('reviewer-owner-1','reviewer'), ('strong-calibrator-G16','strong_calibrator'),
            ('strong-calibrator-G17','strong_calibrator'), ('attacker-provider-preflight','stress_tester')]
        runtime = model_runtime.ModelRuntime(self.root, Mock(), Mock(), Mock(), Mock())
        with patch.dict(os.environ, {'UNBUG_PROVIDER_WAIT':'1'}), patch.object(router, '_rpc', self.store.rpc), \
             patch.object(router, 'SECRETS', secrets), patch.object(model_runtime.ModelRuntime, '_invoke', return_value=0) as execute:
            for name, role in calls:
                runtime.call(c, [c.card['roles'][role]['model']], '', c.case, name)
        self.assertEqual(execute.call_count, len(calls))
        self.assertEqual({r['invocation'] for r in c.card['route_receipts']}, {name for name, _ in calls})
        self.assertEqual(c.ledger.read_bytes(), before)
        self.assertEqual(self.store.rpc('status', {})['leases'], [])
        for receipt in (self.root / 'usage-receipts').glob('*.json'):
            self.assertEqual(json.loads(receipt.read_text())['booked_event_ids'], [])

    def test_codex_rereads_ram_and_missing_file_defers_before_callback(self):
        c, secrets, auth = self.context(); seen = []
        runtime = model_runtime.ModelRuntime(self.root, Mock(), Mock(), lambda p, **kw: __import__('shutil').rmtree(p), Mock())
        def execute(cmd, cwd, env, *args, **kwargs):
            seen.append(json.loads((Path(env['CODEX_HOME'])/'auth.json').read_text())['tokens']['access_token'])
            return SimpleNamespace(returncode=0)
        with patch.dict(os.environ, {'UNBUG_PROVIDER_WAIT':'1'}), patch.object(router, '_rpc', self.store.rpc), \
             patch.object(router, 'SECRETS', secrets), patch.object(router, 'WAIT_SECONDS', 0), \
             patch.object(model_runtime, 'pinned_cli', return_value='synthetic'), patch.object(model_runtime, 'run_budgeted', side_effect=execute):
            runtime.call(c, ['codex/gpt-6.1-sol'], '', c.case, 'strong-calibrator-1')
            auth['tokens']['access_token'] = auth['tokens']['access_token'].replace('synthetic-one', 'synthetic-two')
            (secrets/'codex-auth.json').write_text(json.dumps(auth))
            runtime.call(c, ['codex/gpt-6.1-sol'], '', c.case, 'strong-calibrator-2')
            (secrets/'codex-auth.json').unlink()
            callback = Mock()
            with self.assertRaises(router.ProviderWait) as stopped:
                runtime.call(c, ['codex/gpt-6.1-sol'], '', c.case, 'strong-calibrator-3', before_attempt=callback)
            callback.assert_not_called()
        self.assertEqual(stopped.exception.wait.reason, 'credential_expiring')
        self.assertEqual(stopped.exception.wait.evidence, 'denied_before_work')
        self.assertEqual([s.rsplit('.',1)[1] for s in seen], ['synthetic-one','synthetic-two'])
        self.assertFalse((self.root/'.codex/auth.json').exists())
        self.assertNotIn('cp /dev/shm/secrets/codex-auth.json ~/.codex/auth.json', (ROOT/'factory/launch.sh').read_text())

    def test_uncertain_finish_never_calls_another_model(self):
        c, secrets, _ = self.context()
        def rpc(operation, data):
            result = self.store.rpc(operation, data)
            if operation == 'finish': raise router.RouterUnavailable('lost acknowledgement')
            return result
        runtime = model_runtime.ModelRuntime(self.root, Mock(), Mock(), Mock(), Mock())
        with patch.dict(os.environ, {'UNBUG_PROVIDER_WAIT':'1'}), patch.object(router, '_rpc', side_effect=rpc), \
             patch.object(router, 'SECRETS', secrets), patch.object(router, 'WAIT_SECONDS', 0), \
             patch.object(model_runtime.ModelRuntime, '_invoke', return_value=0) as execute:
            with self.assertRaises(router.ProviderWait) as stopped:
                runtime.call(c, [router.CHAINS[0][0]], '', c.case, 'attacker-1')
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(stopped.exception.wait.reason, 'router_unavailable')
        self.assertIsNotNone(stopped.exception.wait.call_id)
        self.assertEqual(self.store.rpc('status', {})['leases'], [])

    def test_concurrent_wait_merge_keeps_all_usage_receipts(self):
        c, _, _ = self.context()
        (self.root/'usage-receipts').mkdir()
        for number in (1,2):
            event = copy.deepcopy(PAID[0]['continuation_budget']['events'][number])
            (self.root/f'usage-receipts/{number}.json').write_text(json.dumps({'events':[event],
                'final_usage_known':number == 1, 'booked_event_ids':[event['id']]}))
        c.card['router_waits'] = [dict(role='writer', reason='quota', retry_after=time.time()+100,
            evidence='interrupted', route='claude/claude-opus-5-5', account='claude-token', lease_id='a'*32,
            call_id='usage-receipts/1.json'), dict(role='reviewer', reason='outage', retry_after=time.time()+200,
            evidence='interrupted', route='codex/gpt-6.1-sol', account='codex-auth.json', lease_id='b'*32,
            call_id='usage-receipts/2.json')]
        record = run.write_provider_wait(c, budget.BudgetError('cancelled'))
        merged = json.loads((c.work/record['call_id']).read_text())
        self.assertEqual(len(merged['booked_event_ids']), 2)
        self.assertFalse(merged['final_usage_known'])
        self.assertEqual(record['evidence'], 'interrupted')
        self.assertEqual(c.card['terminal_stop'], 'provider_wait')

    def test_wait_uses_normal_runner_checkpoint_and_exit(self):
        # Isolated process because main deliberately redirects its file descriptors.
        script = '''import sys,json,time
from types import SimpleNamespace
from pathlib import Path
sys.path.insert(0,sys.argv[1]); import run,model_router
root=Path(sys.argv[2]); run.HOME=root; run.SEALED=root/'sealed'
run.bench_manifest=lambda:'practice-only'
run.sh=lambda *a,**kw:SimpleNamespace(stdout='synthetic-recipient',returncode=0)
def stop(c):
 c.batch_id='practice-batch'; c.job_id='practice-job'; c.batch_deadline=time.time()+86400
 raise model_router.ProviderWait('writer',model_router.Wait('quota',time.time()+900,route='claude/claude-opus-5-5',account='claude-token'))
def seal(c,checkpoint=False):
 (root/'checkpoint-called.json').write_text(json.dumps({'checkpoint':checkpoint,'record':(c.work/'provider_wait.json').exists()}))
 c.card['sha256']='a'*64
run.build_fixture=stop; run.seal=seal
sys.argv=['factory/run.py','--dry-run']; run.main()
'''
        result = subprocess.run([sys.executable, '-B', '-c', script, str(ROOT/'factory'), str(self.root)],
                                capture_output=True, text=True, env={**os.environ, 'UNBUG_PROVIDER_WAIT':'1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads((self.root/'checkpoint-called.json').read_text())
        self.assertEqual(observed, {'checkpoint':True,'record':True})
        card = json.loads(next((self.root/'sealed').glob('case-*.scorecard.json')).read_text())
        self.assertEqual(card['terminal_stop'], 'provider_wait')
        self.assertEqual(card['provider_wait']['reason'], 'quota')
        self.assertEqual(card['status'], 'stopped')
        self.assertTrue((self.root/'sealed/DONE').is_file())

    def test_parser_observation_survives_real_budget_execution_boundary(self):
        model = next(c['terminal_stop'].split(':',1)[1] for c in LIMITS if 'openrouter/' in c['terminal_stop'])
        event = {'type':'error','error':{'message':'HTTP 402 insufficient credits'}}
        with self.assertRaises(budget.BudgetError) as failure:
            budget.run_budgeted([sys.executable,'-c','print('+repr(json.dumps(event))+')'],
                self.root, os.environ.copy(), self.root/'transcript', self.root/'ledger',10,
                configured_model=model)
        ledger = json.loads((self.root/'ledger').read_text())
        self.assertEqual(ledger['calls'],0)
        self.assertEqual(ledger['provider_failure']['reason'],'credit')
        self.assertEqual(failure.exception.provider_failure, ledger['provider_failure'])

    def test_rollout_flag_off_keeps_waiting_past_sixty_seconds(self):
        clock = [1000.0]
        c = SimpleNamespace(work=self.root, card={}, router_model=router.CHAINS[0][0])
        lease = router.Lease('a'*32, router.CHAINS[0][0], None, 2000, 'free','deepseek','opencode-free')
        attempts = [0]
        def admit(*args):
            attempts[0] += 1
            return lease if attempts[0] == 7 else router.Wait('quota', clock[0]+900)
        with patch.dict(os.environ, {'UNBUG_PROVIDER_WAIT':'0'}), patch.object(router,'_admit',side_effect=admit), \
             patch.object(router.time,'time',side_effect=lambda:clock[0]), patch.object(router.time,'monotonic',side_effect=lambda:clock[0]), \
             patch.object(router.time,'sleep',side_effect=lambda n:clock.__setitem__(0,clock[0]+n)):
            self.assertEqual(router.await_lease('writer', c),lease)
        self.assertEqual(clock[0],1090)
        self.assertFalse((self.root/'provider_wait.json').exists())

    def test_real_limited_pool_waits_without_execution_or_callback(self):
        c, secrets, _ = self.context()
        before = c.ledger.read_bytes(); rounds = c.card.get('builder_rounds')
        model = c.card['roles']['writer']['model']
        for _ in range(2):
            lease = self.store.rpc('acquire', dict(id=uuid.uuid4().hex,model=model,accounts=list(router.ACCOUNTS),role='writer',deadline=time.time()+86400))
            self.store.rpc('observe',dict(lease_id=lease['lease_id'],reason='quota',observation_id=lease['lease_id'],reset_at=time.time()+3600))
            self.store.rpc('finish',dict(lease_id=lease['lease_id'],outcome='interrupted',receipt=None))
        runtime = model_runtime.ModelRuntime(self.root,Mock(),Mock(),Mock(),Mock()); callback=Mock()
        with patch.dict(os.environ,{'UNBUG_PROVIDER_WAIT':'1'}), patch.object(router,'_rpc',self.store.rpc), \
             patch.object(router,'WAIT_SECONDS',0), patch.object(router,'SECRETS',secrets), \
             patch.object(model_runtime.ModelRuntime,'_invoke') as execute:
            with self.assertRaises(router.ProviderWait):
                runtime.call(c,[model],'',c.case,'builder-1',before_attempt=callback)
        callback.assert_not_called(); execute.assert_not_called()
        self.assertEqual(c.ledger.read_bytes(),before)
        self.assertEqual(c.card.get('builder_rounds'),rounds)

    def test_fifo_and_dead_pending_request_expiry(self):
        holder = self.acquire('codex/gpt-6.1-sol')
        first, second = uuid.uuid4().hex, uuid.uuid4().hex
        self.assertEqual(self.acquire(holder['route'],identity=first)['kind'],'wait')
        self.assertEqual(self.acquire(holder['route'],identity=second)['kind'],'wait')
        self.finish(holder)
        self.assertEqual(self.acquire(holder['route'],identity=first)['kind'],'lease')
        self.assertEqual(self.acquire(holder['route'],identity=second)['kind'],'wait')
        self.now[0] += 181
        # Neither a dead lease nor a dead queue head can hold the lane indefinitely.
        self.assertEqual(self.acquire(holder['route'])['kind'],'lease')

    def test_renewal_failure_cancels_and_defers_without_fallback(self):
        c, secrets, _ = self.context(); renewals = [0]
        def rpc(operation,data):
            if operation == 'renew':
                renewals[0] += 1
                if renewals[0] > 1: raise router.RouterUnavailable('synthetic loss')
            return self.store.rpc(operation,data)
        def execute(context,*args,**kwargs):
            self.assertTrue(context.role_cancel.wait(2))
            raise budget.BudgetError('cancelled')
        runtime=model_runtime.ModelRuntime(self.root,Mock(),Mock(),Mock(),Mock())
        with patch.dict(os.environ,{'UNBUG_PROVIDER_WAIT':'1'}), patch.object(router,'_rpc',side_effect=rpc), \
             patch.object(router,'SECRETS',secrets), patch.object(router,'RENEW_SECONDS',.01), patch.object(router,'WAIT_SECONDS',0), \
             patch.object(model_runtime.ModelRuntime,'_invoke',side_effect=execute) as called:
            with self.assertRaises(router.ProviderWait) as stopped:
                runtime.call(c,[router.CHAINS[0][0]],'',c.case,'attacker-1')
        self.assertEqual(called.call_count,1)
        self.assertEqual(stopped.exception.wait.reason,'router_unavailable')
        receipt=json.loads((c.work/stopped.exception.wait.call_id).read_text())
        self.assertFalse(receipt['final_usage_known'])

    def test_receipt_write_error_still_releases_lease(self):
        c,secrets,_=self.context()
        runtime=model_runtime.ModelRuntime(self.root,Mock(),Mock(),Mock(),Mock())
        with patch.dict(os.environ,{'UNBUG_PROVIDER_WAIT':'1'}), patch.object(router,'_rpc',self.store.rpc), \
             patch.object(router,'SECRETS',secrets), patch.object(model_runtime.ModelRuntime,'_invoke',return_value=0), \
             patch.object(model_runtime,'atomic_json',side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError): runtime.call(c,[router.CHAINS[0][0]],'',c.case,'attacker-1')
        self.assertEqual(self.store.rpc('status',{})['leases'],[])


if __name__ == '__main__': unittest.main()
