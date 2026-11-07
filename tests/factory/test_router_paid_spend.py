"""Real SQLite/gate execution under a frozen historical tariff; no provider calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from decimal import Decimal
import io
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'factory'))
import model_router as router
import model_call_gate as gate
from router_test_support import historical_minimax_profile
from token_prices import GATED_OPENROUTER

MINIMAX = 'openrouter/minimax/minimax-m3.1-flash'


def admit(store, model=MINIMAX, identity=None, protocol=True):
    data = dict(id=identity or uuid.uuid4().hex, model=model, accounts=list(router.ACCOUNTS),
                role='writer', deadline=store.clock() + 3600)
    if protocol: data['paid_protocol'] = 1
    value = store.rpc('acquire', data)
    if value['kind'] == 'lease':
        store.rpc('start', {'lease_id': value['lease_id']})
        return router.Lease(**{k: v for k, v in value.items() if k != 'kind'})
    return value


@contextmanager
def authority(lease):
    """Existing synthetic HTTP tests now use actual admission/paid transactions."""
    with tempfile.TemporaryDirectory() as root:
        store = router.Store(Path(root) / 'router.sqlite', credit_reader=lambda: Decimal('11.63'))
        actual = admit(store, lease.route, lease.lease_id)
        assert actual.route == lease.route
        with patch.object(router, '_rpc', store.rpc): yield store


def parallel_reserve(path, lease_id, barrier, results):
    with historical_minimax_profile():
        store = router.Store(path, credit_reader=lambda: Decimal('.46'))
        barrier.wait()
        results.put(store.rpc('paid_reserve', dict(lease_id=lease_id, request_id=uuid.uuid4().hex)))


class PaidTests(unittest.TestCase):
    def setUp(self):
        historical = historical_minimax_profile(); historical.start(); self.addCleanup(historical.stop)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'router.sqlite'
        self.now = [time.time()]
        self.credit = Decimal('11.63')
        self.store = router.Store(self.path, clock=lambda: self.now[0],
            capacities={'openrouter-key': 100}, credit_reader=lambda: self.credit)

    def reserve(self, lease, identity=None):
        data = dict(lease_id=lease.lease_id, request_id=identity or uuid.uuid4().hex)
        return data, self.store.rpc('paid_reserve', data)

    def status(self): return self.store.rpc('status', {})['paid']

    def test_global_concurrent_processes_and_restart_do_not_regrant(self):
        leases = [admit(self.store) for _ in range(6)]
        ctx = multiprocessing.get_context('spawn')
        barrier, results = ctx.Barrier(6), ctx.Queue()
        processes = [ctx.Process(target=parallel_reserve, args=(str(self.path), l.lease_id, barrier, results)) for l in leases]
        for p in processes: p.start()
        values = [results.get(timeout=15) for p in processes]
        for p in processes: p.join(15); self.assertEqual(p.exitcode, 0)
        self.assertEqual(sum(v['granted'] for v in values), 2)
        self.assertEqual(self.status()['total_usd'], '0.460000000')
        self.store = router.Store(self.path, credit_reader=lambda: Decimal('100'))
        self.assertFalse(self.reserve(leases[0])[1]['granted'])
        self.assertEqual(self.status()['ceiling_usd'], '0.460000000')

    def test_settled_spend_is_not_permanently_double_debited(self):
        lease = admit(self.store)
        # Frozen full-window charge, then allow provider accounting overlap to pass.
        for n in range(45):
            self.credit = Decimal('11.63') - Decimal('.23') * n
            data, result = self.reserve(lease)
            self.assertTrue(result['granted'], n)
            usage = dict(prompt_tokens=1000000, completion_tokens=900000)
            self.assertTrue(self.store.rpc('paid_settle', data | {'usage': usage})['settled'])
            self.now[0] += 901
            # Keep a real active lease as time advances; new batches share history.
            lease = admit(self.store)
        self.assertEqual(self.status()['total_usd'], '10.350000000')
        self.credit = Decimal('100')
        for _ in range(5): self.assertTrue(self.reserve(lease)[1]['granted'])
        self.assertFalse(self.reserve(lease)[1]['granted'])
        self.assertEqual(self.status()['total_usd'], '11.500000000')

    def test_operator_ceiling_change_preserves_spending_and_unknown_holds(self):
        self.credit = Decimal('.46')
        lease = admit(self.store)
        settled, _ = self.reserve(lease)
        self.store.rpc('paid_settle', settled | {'usage': dict(prompt_tokens=1000000, completion_tokens=900000)})
        unknown, _ = self.reserve(lease)
        self.store.rpc('paid_settle', unknown | {'usage': None})
        self.credit = Decimal('100')
        self.assertFalse(self.reserve(lease)[1]['granted'])  # More wallet credit cannot raise the limit.
        with closing(sqlite3.connect(self.path)) as db:
            before = db.execute('SELECT * FROM paid_requests ORDER BY id').fetchall()
        self.store = router.Store(self.path, clock=lambda: self.now[0], credit_reader=lambda: self.credit,
                                  paid_ceiling_usd='1.15')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT * FROM paid_requests ORDER BY id').fetchall(), before)
        self.assertEqual(self.status()['total_usd'], '0.460000000')
        for _ in range(3): self.assertTrue(self.reserve(lease)[1]['granted'])
        self.assertFalse(self.reserve(lease)[1]['granted'])
        self.store = router.Store(self.path, credit_reader=lambda: self.credit)
        self.assertEqual(self.status()['ceiling_usd'], '1.150000000')
        self.assertEqual(self.status()['total_usd'], '1.150000000')
        self.assertFalse(self.reserve(lease)[1]['granted'])

    def test_explicit_limit_does_not_freeze_to_initial_credit_and_still_checks_wallet(self):
        self.credit = Decimal('.23')
        self.store = router.Store(self.path, credit_reader=lambda: self.credit, paid_ceiling_usd='1')
        lease = admit(self.store)
        self.assertTrue(self.reserve(lease)[1]['granted'])
        self.assertFalse(self.reserve(lease)[1]['granted'])
        self.credit = Decimal('1')
        self.assertTrue(self.reserve(lease)[1]['granted'])
        self.assertEqual(self.status()['ceiling_usd'], '1.000000000')
        for bad in (True, -1, 'NaN', 'Infinity', '10000000000', 'bad'):
            with self.assertRaises(ValueError):
                router.Store(self.path, paid_ceiling_usd=bad)
        with self.assertRaisesRegex(ValueError, 'below retained spending'):
            router.Store(self.path, paid_ceiling_usd='.45')
        self.assertEqual(self.status()['ceiling_usd'], '1.000000000')
        self.assertEqual(self.status()['total_usd'], '0.460000000')

    def test_unknown_credit_low_credit_and_deadline_fail_closed(self):
        lease = admit(self.store)
        for bad in (None, -1, float('nan'), float('inf'), True, 'no'):
            self.credit = bad
            self.assertEqual(self.reserve(lease)[1], dict(granted=False, reason='credit'))
        self.credit = Decimal('.2299999999')
        self.assertFalse(self.reserve(lease)[1]['granted'])
        self.assertEqual(self.status()['total_usd'], '0.000000000')
        self.credit = Decimal('.23')
        data = dict(lease_id=lease.lease_id, request_id=uuid.uuid4().hex)
        self.assertFalse(self.store.rpc('paid_reserve', data, handling_started=time.monotonic()-4)['granted'])
        self.assertTrue(self.reserve(lease)[1]['granted'])
        self.credit = None
        self.assertFalse(self.reserve(lease)[1]['granted'])

    def unknown_holds(self, n):
        self.credit = Decimal('100')
        for _ in range(n):
            lease = admit(self.store)
            data, result = self.reserve(lease)
            self.assertTrue(result['granted'])
            self.store.rpc('paid_settle', data | {'usage': None})   # an interrupted call: cost never confirmed

    def test_stale_unknown_holds_stop_blocking_calls_the_balance_can_pay(self):
        """7 November: unconfirmed holds from interrupted calls counted against the balance forever,
        though the provider had long since billed them, and a call the balance could pay was refused."""
        self.unknown_holds(15)                       # 15 interrupted calls at this profile's $0.23 hold: $3.45
        self.credit = Decimal('3.60')                # the provider balance, which already includes them
        lease = admit(self.store)
        self.assertFalse(self.reserve(lease)[1]['granted'])   # inside the billing window: still counted
        self.now[0] += 901                            # past the window
        lease = admit(self.store)
        self.assertTrue(self.reserve(lease)[1]['granted'])
        self.assertEqual(self.status()['total_usd'], '3.680000000')   # spend history keeps every hold

    def test_rows_from_before_the_timestamp_age_by_their_lease_end(self):
        self.unknown_holds(15)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE paid_requests SET settled_at=NULL WHERE state='unknown'")
        self.credit = Decimal('3.60')
        self.now[0] += 901 + router.LEASE_SECONDS
        self.assertTrue(self.reserve(admit(self.store))[1]['granted'])

    def test_a_balance_that_cannot_pay_is_still_refused(self):
        self.unknown_holds(2)
        self.now[0] += 901
        self.credit = Decimal('.20')                  # less than one request's $0.23 hold
        self.assertFalse(self.reserve(admit(self.store))[1]['granted'])

    def test_unknown_cancellation_expiry_finish_and_replay_count_once(self):
        for operation in ('cancel', 'expire', 'finish', 'unknown'):
            lease = admit(self.store)
            data, result = self.reserve(lease)
            self.assertTrue(result['granted'])
            self.assertEqual(self.store.rpc('paid_reserve', data), dict(granted=False, reason='duplicate'))
            if operation == 'cancel': self.store.rpc('cancel', {'id': lease.lease_id})
            elif operation == 'expire': self.now[0] += 181
            elif operation == 'finish': self.store.rpc('finish', dict(lease_id=lease.lease_id, outcome='interrupted', receipt=None))
            else: self.store.rpc('paid_settle', data | {'usage': None})
            for _ in range(2):
                self.assertFalse(self.store.rpc('paid_settle', data | {'usage': dict(prompt_tokens=0, completion_tokens=0)})['settled'])
        self.assertEqual(self.status()['total_usd'], '0.920000000')

    def test_settlement_frozen_tariff_duplicate_changed_and_invalid(self):
        lease = admit(self.store)
        data, _ = self.reserve(lease)
        usage = dict(prompt_tokens=1, completion_tokens=1, cost=.00000025)
        with patch.dict(GATED_OPENROUTER, {MINIMAX: dict(GATED_OPENROUTER[MINIMAX], prices=('9','9','9'))}):
            self.assertTrue(self.store.rpc('paid_settle', data | {'usage': usage})['settled'])
        self.assertTrue(self.store.rpc('paid_settle', data | {'usage': usage})['settled'])
        self.assertFalse(self.store.rpc('paid_settle', data | {'usage': dict(prompt_tokens=0, completion_tokens=0)})['settled'])
        self.assertEqual(self.status()['total_usd'], '0.000000250')
        for usage in ({'prompt_tokens': True, 'completion_tokens': 1},
                      {'prompt_tokens': 1000001, 'completion_tokens': 0},
                      {'prompt_tokens': 0, 'completion_tokens': 0, 'cost': 1}):
            data, _ = self.reserve(lease)
            self.assertFalse(self.store.rpc('paid_settle', data | {'usage': usage})['settled'])
        self.assertEqual(self.status()['total_usd'], '0.690000250')

    def test_credit_fetch_does_not_block_subscription_renewal(self):
        paid = admit(self.store)
        subscription = admit(self.store, 'claude/claude-opus-4-5-20251101:compact')
        entered, release = threading.Event(), threading.Event()
        def slow(): entered.set(); release.wait(3); return Decimal('11.63')
        self.store.credit_reader = slow
        with ThreadPoolExecutor() as pool:
            pending = pool.submit(self.reserve, paid)
            self.assertTrue(entered.wait(1))
            renewal = pool.submit(self.store.rpc, 'renew', {'lease_id': subscription.lease_id})
            try: self.assertEqual(renewal.result(timeout=.5)['route'], subscription.route)
            finally: release.set()
            self.assertTrue(pending.result()[1]['granted'])

    def test_protocol_binding_subscription_exclusion_and_canonical_path(self):
        self.assertEqual(admit(self.store, protocol=False)['kind'], 'wait')
        subscription = admit(self.store, 'claude/claude-opus-4-5-20251101:compact', protocol=False)
        self.assertEqual(self.reserve(subscription)[1], dict(granted=False, reason='binding'))
        self.assertEqual(self.status()['total_usd'], '0.000000000')
        with self.assertRaises(ValueError): router.production_database({'database': 'another.sqlite'})
        with patch.dict(os.environ, {'UNBUG_CONTROL_HOME': '/tmp/new'}):
            with self.assertRaises(ValueError): router.production_database({})
        # No paid counter is created merely for a subscription lease.
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM paid_account').fetchone()[0], 0)

    def test_new_client_old_server_fails_closed(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from types import SimpleNamespace
        class OldServer(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                # The exact pre-increment acquire field rule, over real HTTP.
                rejected = set(data) - {'excluded_lanes'} != {'id','model','accounts','role','deadline'}
                self.send_response(400 if rejected else 200)
                self.send_header('Content-Length','2'); self.end_headers(); self.wfile.write(b'{}')
        server = ThreadingHTTPServer(('127.0.0.1',0), OldServer)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        case = SimpleNamespace(router_model='claude/claude-opus-4-5-20251101:compact')
        with patch.dict(os.environ, {'FACTORY_ROUTER_TOKEN':'synthetic',
                'FACTORY_ROUTER_URL':'http://127.0.0.1:'+str(server.server_port)}):
            with self.assertRaises(router.RouterUnavailable):
                router._admit('writer',case,time.time()+30,uuid.uuid4().hex,router.ACCOUNTS)

    def test_credit_adapter_synthetic_schema_and_no_diagnostics(self):
        class Response(io.BytesIO):
            def read(self, size): self.requested = size; return super().read(size)
        for payload, expected in (
            (b'{"data":{"total_credits":20,"total_usage":8.373872605}}', Decimal('11.626127395')),
            (b'{"data":{"total_credits":true,"total_usage":0}}', None),
            (b'{"data":{"total_credits":1,"total_usage":2}}', None),
            (b'{"data":{"total_credits":NaN,"total_usage":0}}', None),
            (b'not-json', None), (b'x'*16385, None)):
            response = Response(payload)
            with patch.dict(os.environ, {'OPENROUTER_API_KEY':'synthetic'}), patch.object(router.urllib.request, 'build_opener') as make:
                make.return_value.open.return_value = response
                self.assertEqual(router.available_credit(), expected)
                self.assertEqual(response.requested, 16385)
                self.assertEqual(make.return_value.open.call_args.kwargs['timeout'], 2)
        with patch.dict(os.environ, {'OPENROUTER_API_KEY':'synthetic'}), patch.object(router.urllib.request, 'build_opener') as make:
            make.return_value.open.side_effect = OSError('synthetic sensitive provider message')
            self.assertIsNone(router.available_credit())


class PaidWireTests(unittest.TestCase):
    def setUp(self):
        historical = historical_minimax_profile(); historical.start(); self.addCleanup(historical.stop)
        import test_model_call_maxima as core
        core.ProtocolTests.setUp(self)

    def env(self):
        return dict(OPENROUTER_API_KEY='synthetic', XDG_CONFIG_HOME='/synthetic/config',
                    XDG_DATA_HOME='/synthetic/data', XDG_CACHE_HOME='/synthetic/cache')

    def post(self, active):
        import http.client
        connection = http.client.HTTPConnection('127.0.0.1', active.server.server_port, timeout=5)
        body = dict(model='minimax/minimax-m3.1-flash', messages=[dict(role='user', content='synthetic')], stream=True)
        connection.request('POST', '/api/v1/chat/completions', json.dumps(body),
                           {'Authorization': 'Bearer ' + active.token})
        response = connection.getresponse()
        status, data = response.status, response.read()
        connection.close()
        return status, data

    def payload(self):
        event = dict(id='synthetic', model='minimax/minimax-m3.1-flash',
                     choices=[dict(index=0, finish_reason='stop')],
                     usage=dict(prompt_tokens=1, completion_tokens=1, total_tokens=2))
        return b'data: ' + json.dumps(event).encode() + b'\n\ndata: [DONE]\n\n'

    def test_terminal_accounting_frame_refunds_the_real_shared_hold(self):
        import test_model_call_maxima as core
        terminal=dict(id='synthetic',model='minimax/minimax-m3.1-flash',choices=[dict(index=0,
            delta={'content':'','role':'assistant'},finish_reason='stop',native_finish_reason='stop')])
        usage=dict(prompt_tokens=1,completion_tokens=1,total_tokens=2)
        frames=[terminal,dict(terminal,usage=usage)]
        payload=b''.join(b'data: '+json.dumps(f).encode()+b'\n\n' for f in frames)+b'data: [DONE]\n\n'
        self.responses=[payload]
        actual=core.lease(MINIMAX);cap={}
        with authority(actual) as store,patch.object(gate.sys,'platform','linux'):
            with gate.enforce(actual,self.env(),cap,3) as active:
                self.assertEqual(self.post(active),(200,payload))
                self.assertEqual(active.state.snapshot()['validated_requests'],1)
                self.assertEqual(active.state.snapshot()['unknown_requests'],0)
                self.assertEqual(store.rpc('status',{})['paid']['total_usd'],'0.000000250')
        self.assertTrue(cap['closed'])

    def test_refusal_latch_and_lost_reserve_ack_never_connect(self):
        import test_model_call_maxima as core
        from budget import BudgetError
        for lost in (False, True):
            actual = core.lease(MINIMAX)
            with authority(actual) as store, patch.object(gate.sys, 'platform', 'linux'):
                reads = []
                store.credit_reader = lambda: reads.append(1) or (Decimal('11.63') if lost else None)
                def rpc(op, data):
                    result = store.rpc(op, data)
                    if lost and op == 'paid_reserve': raise router.RouterUnavailable('lost response')
                    return result
                with patch.object(router, '_rpc', rpc), self.assertRaisesRegex(BudgetError, 'shared_paid_spend_wait'):
                    with gate.enforce(actual, self.env(), {}, 3) as active:
                        for _ in range(3): self.assertEqual(self.post(active)[0], 503)
                self.assertEqual(len(reads), 1)
                self.assertEqual(self.seen, [])
                self.assertEqual(store.rpc('status', {})['paid']['total_usd'], '0.230000000' if lost else '0.000000000')

    def test_worker_and_diagnosis_runtime_share_one_ledger_across_batches(self):
        import shutil
        from types import SimpleNamespace
        from unittest.mock import Mock
        import test_model_call_maxima as core
        import diagnosis_task
        from budget import BudgetError
        runtime_module = core.model_runtime
        # Only OS isolation and the CLI process are doubles. ModelRuntime.call,
        # _invoke, enforce, request parsing and central Store all execute normally.
        @contextmanager
        def offline_wall(active, lease, user):
            try: yield
            finally: active.close()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ram = root/'ram'; ram.mkdir(); (ram/'openrouter-key').write_text('synthetic-only')
            store = router.Store(root/'router.sqlite', credit_reader=lambda: Decimal('.46'))
            command = Mock()
            runtime = runtime_module.ModelRuntime(root, command, Mock(),
                lambda path, **kw: shutil.rmtree(path), lambda user: root/'pilot')
            calls = []
            def execute(cmd, cwd, env, *args, **kwargs):
                kwargs['on_started']()
                calls.append((kwargs['invocation_name'], 'pilot' in cmd))
                self.assertNotIn('OPENROUTER_API_KEY', env)
                if 'pilot' in cmd:
                    self.assertNotIn('OPENCODE_ENABLE_EXA', env)
                    config = json.loads(env['OPENCODE_CONFIG_CONTENT'])
                    self.assertEqual(config['permission']['webfetch'], 'deny')
                status, _ = self.post(kwargs['cancel'])
                if status != 200: raise BudgetError('process_error')
                return SimpleNamespace(returncode=0)
            def context(index):
                work = root/str(index); work.mkdir(); (work/'transcripts').mkdir()
                from durable.contract import ArtifactKind, Ref, Step, StepInput, StepKind
                batch, case_id = 'b-paid-' + str(index), 'case-' + str(index)
                step = Step(StepKind.DIAGNOSIS) if index == 2 else Step(StepKind.WRITER, 1)
                maximum = Decimal(str(router.route_maximum(MINIMAX)['max_usd']))
                si = StepInput(batch, case_id, 1, step, 1, 'a' * 64, 'b' * 64,
                    Ref('a' * 64, ArtifactKind.INPUTS), Ref('b' * 64, ArtifactKind.CASE_SNAPSHOT),
                    3600, int(maximum * 1_000_000) + 1)
                attempt = core.run.EngineStep(si, 0)
                c = SimpleNamespace(work=work, case=work, ledger=work/'ledger.json',
                    args=core.run.argument_parser().parse_args(['--source','hunt']),
                    card={'roles': {role: {'model': MINIMAX} for role in ('writer', 'reviewer')}},
                    case_id=case_id, batch_id=batch, job_id=case_id,
                    batch_deadline=attempt.deadline_epoch, engine=attempt,
                    router_accounts=('openrouter-key',))
                c.ledger.write_text(json.dumps({'cost':0,'calls':0,'events':[]}))
                return c
            event = dict(id='synthetic',model='minimax/minimax-m3.1-flash',
                choices=[dict(index=0,finish_reason='stop')],
                usage=dict(prompt_tokens=1000000,completion_tokens=900000,total_tokens=1900000))
            payload = b'data: '+json.dumps(event).encode()+b'\n\ndata: [DONE]\n\n'
            self.responses = [payload, payload]
            with patch.object(router,'_rpc',store.rpc), patch.object(router,'SECRETS',ram), \
                 patch.object(runtime_module,'_opencode_flags',return_value=[]), \
                 patch.object(runtime_module,'run_budgeted',side_effect=execute), \
                 patch.object(gate,'_wall_access',offline_wall), patch.object(gate.sys,'platform','linux'), \
                 patch.object(runtime_module.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=1234)), \
                 patch.object(diagnosis_task,'_quiet'), patch.dict(os.environ,{'UNBUG_PROVIDER_WAIT':'0'}):
                for index, name, user in ((1,'builder-1',None),(2,'diagnosis-synthetic','pilot')):
                    c = context(index)
                    self.assertEqual(runtime.call(c,[MINIMAX],'synthetic',c.work,name,user=user),0)
                    self.assertEqual(store.rpc('status',{})['paid']['total_usd'],f'{Decimal(".23")*index:.9f}')
                # A third funded Engine attempt cannot replenish the shared provider wallet.
                c = context(3)
                with self.assertRaises(router.ProviderWait):
                    runtime.call(c,[MINIMAX],'synthetic',c.work,'builder-1')
            self.assertEqual(calls,[('builder-1',False),('diagnosis-synthetic',True),('builder-1',False)])
            self.assertEqual(len(self.seen),2)
            self.assertEqual(store.rpc('status',{})['paid']['total_usd'],'0.460000000')
            with closing(sqlite3.connect(store.path)) as db:
                self.assertEqual(db.execute('SELECT COUNT(DISTINCT lease_id) FROM paid_requests').fetchone()[0],2)

    def test_settlement_precedes_downstream_eof_and_transport_loss_retains(self):
        import test_model_call_maxima as core
        for lost in (False, True):
            actual = core.lease(MINIMAX)
            self.responses = [self.payload()]
            before = len(self.seen)
            with authority(actual) as store, patch.object(gate.sys, 'platform', 'linux'):
                def rpc(op, data):
                    if lost and op == 'paid_settle': raise router.RouterUnavailable('lost settlement')
                    return store.rpc(op, data)
                with patch.object(router, '_rpc', rpc), gate.enforce(actual, self.env(), {}, 3) as active:
                    self.assertEqual(self.post(active)[0], 200)
                    self.assertEqual(len(self.seen)-before, 1)
                    # HTTP read reached EOF: settlement has already been attempted.
                    self.assertEqual(store.rpc('status', {})['paid']['total_usd'], '0.230000000' if lost else '0.000000250')
                store.rpc('finish', dict(lease_id=actual.lease_id, outcome='done', receipt=None))
                self.assertEqual(store.rpc('status', {})['paid']['total_usd'], '0.230000000' if lost else '0.000000250')


if __name__ == '__main__': unittest.main()
