"""Real public prices/receipts plus offline protocol faults; no model/provider call."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'factory'), str(ROOT/'bin')]
import argparse
import copy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import shutil
import signal
import ssl
import subprocess
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import calibration
import budget
import model_call_gate as gate
import model_router as router
import model_runtime
import run
from token_prices import GATED_CLAUDE, CLAUDE_PROFILES, CLAUDE_GATE_FIELDS, claude_gate_cost, claude_cost, claude_profile, GATED_CLAUDE45

LEGACY_CLAUDE_PROFILES = {k:v for k,v in CLAUDE_PROFILES.items() if k.startswith(GATED_CLAUDE)}
MINIMAX = 'openrouter/minimax/minimax-m3.1-flash'

FIXTURES = Path(__file__).with_name('fixtures')
PAID = json.loads(gzip.decompress((FIXTURES/'router-paid-deepseek.json.gz').read_bytes()))
LIMITS = json.loads(gzip.decompress((FIXTURES/'router-provider-limits.json.gz').read_bytes()))


def real_iterations():
    rows = {}
    cards = json.loads(gzip.decompress((FIXTURES/'20261029-real-public-cards.json.gz').read_bytes()))
    def walk(value):
        if isinstance(value, dict):
            if value.get('configured_model') == GATED_CLAUDE and value.get('id') and isinstance(value.get('tokens'), dict):
                rows[value['id']] = value
            for item in value.values(): walk(item)
        elif isinstance(value, list):
            for item in value: walk(item)
    walk(cards)
    return rows


def lease(route=GATED_CLAUDE):
    return router.Lease(uuid.uuid4().hex, route, 'claude-token', time.time()+180,
                        'subscription', 'anthropic', 'claude-token', **router.route_maximum(route))


def body(**extra):
    return dict(model=GATED_CLAUDE.partition('/')[2], max_tokens=65536,
                messages=[{'role':'user', 'content':'synthetic protocol probe'}], **extra)


def sse(usage, *, stop=True, model='claude-opus-5-5'):
    start = dict(usage, output_tokens=0)
    events = [{'type':'message_start','message':{'model':model, 'usage':start}},
              {'type':'message_delta','delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':usage['output_tokens']}}]
    if stop: events.append({'type':'message_stop'})
    return b''.join(b'data: '+json.dumps(e).encode()+b'\n\n' for e in events)


class MaximaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_oauth_geo_omission_keeps_regional_ceiling_and_explicit_global_receipts(self):
        self.assertNotIn('inference_geo', gate.request_body(json.dumps(body())))
        usage = dict(input_tokens=100, cache_read_input_tokens=0,
                     cache_creation_input_tokens=0, output_tokens=10)
        base = claude_gate_cost(usage | {'inference_geo': 'global'})
        for mode in ({}, {'inference_geo': 'not_available'}):
            self.assertEqual(claude_gate_cost(usage | mode), base * Decimal('1.1'))
        self.assertIsNone(claude_gate_cost(usage | {'inference_geo': 'us'}))
        for streaming in (False, True):
            parser = gate.Usage(32768, streaming)
            value = usage | {'inference_geo': 'global'}
            payload = sse(value) if streaming else json.dumps(dict(type='message',
                model='claude-opus-5-5', stop_reason='end_turn', usage=value)).encode()
            parser.feed(payload)
            self.assertEqual(parser.final()['inference_geo'], 'global')
            self.assertEqual(claude_gate_cost(parser.final()), base)
        state = gate.Allowance(lease(GATED_CLAUDE + ':small'))
        identity = state.reserve(32768)
        self.assertIsNotNone(identity)
        state.finish(identity, None)
        self.assertEqual(Decimal(state.snapshot()['held_usd']), Decimal('9.520896'))
        self.assertIsNone(state.reserve(0))

    def test_codex_batch_call_currently_waits_unbounded(self):
        # Real attempt grant, runtime and router; no CLI/provider call.
        deadline = float(int(time.time()) + 3600)
        channel = dict(schema=1, batch='synthetic', job='job', case='case-synthetic',
            reservation_id=str(uuid.uuid4()), revision=1, source_generation=None,
            committed_total_usd='50.000000000', batch_deadline=router.utc(deadline))
        path = self.root / 'ledger.json'
        path.write_text(json.dumps({'cost': 0, 'calls': 0, 'events': []}))
        model = 'codex/gpt-6.1-sol'
        c = SimpleNamespace(work=self.root, case=self.root, ledger=path,
            args=run.argument_parser().parse_args(['--source', 'hunt']),
            card={'roles': {'strong_calibrator': {'model': model}}},
            case_id=channel['case'], batch_id=channel['batch'], job_id=channel['job'],
            batch_deadline=deadline, source_generation=None, engine=SimpleNamespace(key="attempt", baseline_spent_usd=0, ceiling_usd=Decimal(channel["committed_total_usd"])),
            router_accounts=('codex-auth.json',))
        store = router.Store(self.root / 'router.sqlite')
        runtime = model_runtime.ModelRuntime(self.root, Mock(), Mock(), Mock(), Mock())
        with patch.dict(os.environ, {'UNBUG_PROVIDER_WAIT': '1'}), \
             patch.object(router, '_rpc', store.rpc), patch.object(router, 'WAIT_SECONDS', 0), \
             patch.object(router, 'SECRETS', self.root / 'empty'), \
             patch.object(model_runtime.ModelRuntime, '_invoke') as invoke:
            with self.assertRaises(router.ProviderWait) as caught:
                runtime.call(c, [model], 'synthetic', self.root, 'strong-calibrator-1')
        self.assertEqual(caught.exception.wait.reason, 'unbounded_route')
        invoke.assert_not_called()
        self.assertEqual(store.rpc('status', {})['leases'], [])

    def test_real_routes_fail_closed_except_exact_qualified_profiles(self):
        store = router.Store(self.root/'router.sqlite')
        from token_prices import GATED_OPENROUTER
        qualified = {*CLAUDE_PROFILES, *GATED_OPENROUTER,
                     'opencode/deepseek-v4.1-flash-free', 'opencode-go/mimo-v2.6-pro'}
        models = {r for c in router.CHAINS for r in c} | {'codex/gpt-6.1-sol', 'claude/unknown', 'unknown/model'}
        models |= {*CLAUDE_PROFILES, GATED_CLAUDE + ':large'}
        models |= {c['terminal_stop'].partition(':')[2] for c in LIMITS}
        # OpenCode's free routes are bounded at $0 (founder 2026-11-08), so a chain reaching one qualifies.
        from token_prices import FREE_ROUTES
        def reaches_free(model):
            try: return any(r['route'] in FREE_ROUTES for r in router.routes(model, router.ACCOUNTS))
            except ValueError: return False
        qualified |= {m for m in models if reaches_free(m)}
        for model in models:
            result = store.rpc('acquire', dict(paid_protocol=1,id=uuid.uuid4().hex, model=model, accounts=list(router.ACCOUNTS),
                role='writer', deadline=time.time()+3600))
            if model not in qualified:
                self.assertEqual((result['kind'], result['reason']), ('wait','unbounded_route'))
                self.assertEqual(store.rpc('capacity', {'route':model})['slots'], 0)
            else:
                actual = router.Lease(**{k:v for k,v in result.items() if k != 'kind'})
                self.assertTrue(router.valid_lease(actual, model))
                if actual.route in CLAUDE_PROFILES:
                    cap = CLAUDE_PROFILES[actual.route]
                    self.assertEqual((actual.max_usd, actual.max_input_tokens, actual.max_output_tokens),
                                     (float(cap), int(cap * (2000000 if actual.route.startswith(GATED_CLAUDE45) else 5000000)),
                                      int(cap * (40000 if actual.route.startswith(GATED_CLAUDE45) else 50000))))
                elif actual.route in FREE_ROUTES:
                    self.assertEqual(actual.max_usd, 0.0)        # free: nothing held, any booked cost stops it
                else:
                    self.assertIn(actual.route, GATED_OPENROUTER)
                store.rpc('finish',dict(lease_id=actual.lease_id,outcome='denied',receipt=None))
        self.assertEqual(store.rpc('status', {})['leases'], [])
        for card in PAID:
            raw = json.dumps(card['continuation_budget'], sort_keys=True)
            events = [e for e in card['continuation_budget']['events'] if e.get('configured_model','').startswith('openrouter/deepseek/')]
            self.assertGreater(sum(e['cost'] for e in events), 0)
            self.assertIsNotNone(router.route_maximum(events[0]['configured_model']))
            self.assertEqual(json.dumps(card['continuation_budget'],sort_keys=True),raw)

    def test_small_profiles_fit_real_writer_envelopes_and_retain_unknowns(self):
        cases = [('small','252e6df1-f899-427e-aa07-7b98ba7eb156:result',35),
                 ('medium','0d4adf8f-0ef4-4cef-aeb0-c974454eaee8:result',62)]
        events = {e['id']:e for card in PAID for e in card['continuation_budget']['events']}
        worst = Decimal('9.520896')
        for name,identity,calls in cases:
            model = GATED_CLAUDE + ':' + name
            event = events[identity]; usage = event['tokens']
            self.assertEqual((event['role'],event['calls']),('writer',calls))
            cost = max(Decimal(str(event['list_cost_usd'])),claude_gate_cost(usage))
            fits = cost + worst + gate.HEADROOM < CLAUDE_PROFILES[model]
            self.assertEqual(fits, name == 'medium')
            self.assertEqual(claude_cost(model,usage),claude_cost(GATED_CLAUDE,usage))
            for unknowns in (0,1):
                state = gate.Allowance(lease(model))
                state.settled = [cost,sum(usage[k] for k in CLAUDE_GATE_FIELDS[:3]),usage['output_tokens']]
                token = state.reserve(32768)
                if not fits:
                    self.assertIsNone(token); state.close(); continue
                self.assertIsNotNone(token)
                if unknowns:
                    state.finish(token,None)
                    self.assertIsNone(state.reserve(0))
                    self.assertTrue(state.exhaustion.is_set())
                    self.assertEqual(Decimal(state.snapshot()['held_usd']),worst)
                state.close()
            state = gate.Allowance(lease(model))
            state.settled[0] = CLAUDE_PROFILES[model] - worst
            self.assertIsNone(state.reserve(32768))
            self.assertTrue(state.exhaustion.is_set())
            original = lease(model)
            forged = replace(original,**router.route_maximum(GATED_CLAUDE))
            self.assertFalse(router.valid_lease(forged,model))
            with self.assertRaisesRegex(budget.BudgetError,'unbounded_route'):
                with gate.enforce(forged,{'CLAUDE_CODE_OAUTH_TOKEN':'synthetic'}, {},1):
                    self.fail('forged maximum entered gate')
            store = router.Store(self.root/(name+'.sqlite'))
            record = store.rpc('acquire',dict(paid_protocol=1,id=uuid.uuid4().hex,model=model,
                accounts=['claude-token','claude-factory-token-2'],role='writer',deadline=time.time()+60))
            self.assertEqual((record['route'],record['account']),(model,'claude-factory-token-2'))
            self.assertTrue(record['price_source'].endswith(f':profile={name}:usd={CLAUDE_PROFILES[model]}'))
            store.rpc('finish',dict(lease_id=record['lease_id'],outcome='denied',receipt=None))

    def test_small_profiles_serialize_even_zero_output_requests(self):
        for model in LEGACY_CLAUDE_PROFILES.keys() - {GATED_CLAUDE}:
            state = gate.Allowance(lease(model),deadline=time.monotonic()+5)
            first = state.reserve(0); self.assertIsNotNone(first)
            waited = threading.Event(); original = state.condition.wait
            def wait(timeout): waited.set(); return original(timeout)
            with patch.object(state.condition,'wait',side_effect=wait), ThreadPoolExecutor() as pool:
                next_request = pool.submit(state.reserve,0)
                try:
                    self.assertTrue(waited.wait(2))
                    self.assertFalse(next_request.done())
                    state.finish(first,dict.fromkeys(CLAUDE_GATE_FIELDS,0))
                    self.assertIsNotNone(next_request.result(timeout=2))
                finally: state.close()

    def test_real_aggregate_exam_and_more_than_eight_validated_requests(self):
        events = real_iterations(); self.assertEqual(len(events),153)
        costs = [claude_gate_cost(e['tokens']) for e in events.values()]
        worst = Decimal('9.520896')
        self.assertEqual((sum(c+worst < 50 for c in costs),sum(c>50 for c in costs),
                          sum(c<=50 and c+worst>=50 for c in costs)), (153,0,0))
        allowance = gate.Allowance(lease())
        samples = [i for e in events.values() for i in e['tokens'].get('iterations', [])][:20]
        for usage in samples:
            identity = allowance.reserve(32768); self.assertIsNotNone(identity)
            parser = gate.Usage(32768, True)
            for byte in sse(usage): parser.feed(bytes([byte]))
            self.assertIsNotNone(parser.final())
            allowance.finish(identity, parser.final())
        allowance.close(); result = allowance.snapshot()
        self.assertEqual(result['validated_requests'],20)
        self.assertEqual(result['forwarded_requests'],20)
        self.assertEqual(result['unknown_requests'],0)
        self.assertLess(Decimal(result['settled_usd']),50)

    def test_real_writer_envelopes_fit_with_bounded_unknown_attempts(self):
        # Conditional envelope, not a reconstructed HTTP trace: recorded aggregate
        # bounds validated usage; unrecorded unknown attempts are limited below.
        events = {e['id']: e for c in PAID for e in c['continuation_budget']['events']
                  if e.get('configured_model') == GATED_CLAUDE}
        self.assertEqual(len(events),32)
        self.assertTrue(all(e['tokens']['speed']=='standard' and e['tokens']['inference_geo']=='global'
                            for e in events.values()))
        cases = [('b741739e-bdec-4272-8b41-4a7703b02d52:result',110,2),
                 ('013eaa17-daa9-49f9-9ad5-c88288cd5d11:result',135,2)]
        worst = dict.fromkeys(CLAUDE_GATE_FIELDS,0) | {'cache_creation_input_tokens':1000000,'output_tokens':32768}
        for identity,calls,tolerated in cases:
            with self.subTest(writer=identity):
                event=events[identity];usage=event['tokens'];self.assertEqual(event['calls'],calls)
                # Test-only conservative upper bound; production never reads the CLI cost here.
                settled=[max(Decimal(str(event['list_cost_usd'])),claude_gate_cost(usage)),
                         sum(usage[k] for k in CLAUDE_GATE_FIELDS[:3]),usage['output_tokens']]
                for unknowns in (0,tolerated,tolerated+1):
                    allowance=gate.Allowance(lease());allowance.settled=settled.copy()
                    allowance.retained=[unknowns*claude_gate_cost(worst),unknowns*1000000,unknowns*32768]
                    request=allowance.reserve(32768)
                    if unknowns<=tolerated:self.assertIsNotNone(request)
                    else:self.assertIsNone(request)
                    allowance.close()

    def test_mode_metadata_is_strict_and_parser_invalidity_is_sticky(self):
        usage=dict(input_tokens=100,cache_read_input_tokens=50,cache_creation_input_tokens=25,output_tokens=10)
        self.assertEqual(claude_gate_cost(usage),Decimal('0.000891'))
        for fields in ({},{'speed':'standard','inference_geo':'global'}):
            self.assertEqual(claude_cost(GATED_CLAUDE,usage|fields),0.00081)
            self.assertEqual(claude_gate_cost(usage|fields), Decimal('0.00081' if fields else '0.000891'))
        for key,values in [('speed',('fast','',None,False,{})),('inference_geo',('us','',None,False,{}))]:
            for value in values:
                with self.subTest(key=key,value=value):
                    invalid=usage|{key:value}
                    self.assertIsNone(claude_gate_cost(invalid));self.assertIsNone(claude_cost(GATED_CLAUDE,invalid))
                    for streaming in (False,True):
                        parser=gate.Usage(32768,streaming)
                        # SSE's final update omits the mode: it must not erase invalidity.
                        payload=sse(invalid) if streaming else json.dumps(dict(type='message',model='claude-opus-5-5',
                            stop_reason='end_turn',usage=invalid)).encode()
                        parser.feed(payload);self.assertIsNone(parser.final())
                    allowance=gate.Allowance(lease());request=allowance.reserve(32768)
                    allowance.finish(request,invalid);allowance.close()
                    self.assertEqual(allowance.snapshot()['unknown_requests'],1)
                    self.assertEqual(Decimal(allowance.snapshot()['held_usd']),Decimal('9.520896'))
        parser=gate.Usage(32768,True)
        payload=sse(usage).replace(b'"output_tokens": 10}',b'"output_tokens": 10,"speed":"fast"}')
        parser.feed(payload);self.assertIsNone(parser.final())

    def test_real_writer_partial_estimator_uses_captured_cli_mode_surface(self):
        for model in LEGACY_CLAUDE_PROFILES:
            capture=json.loads(gzip.decompress((FIXTURES/'router-claude-mode-cli.json.gz').read_bytes()))
            wanted={'b741739e-bdec-4272-8b41-4a7703b02d52:result','013eaa17-daa9-49f9-9ad5-c88288cd5d11:result'}
            writers=[e for c in PAID for e in c['continuation_budget']['events'] if e['id'] in wanted]
            for record in capture['records']:
                shape=record['capture']['assistant_usage'][0]
                for writer in writers:
                    for complete in (False,True):
                        with self.subTest(mode=record['upstream_mode_fields'],writer=writer['id'],complete=complete):
                            # Transport-only envelope: real counters in the actual captured CLI shape.
                            usage=shape|{k:writer['tokens'][k] for k in CLAUDE_GATE_FIELDS}
                            plain={k:usage[k] for k in CLAUDE_GATE_FIELDS}
                            events=[{'type':'system','subtype':'init','session_id':'captured-shape'},
                                    {'type':'assistant','message':{'id':'m','usage':usage,'content':[]}},
                                    {'type':'assistant','message':{'id':'m','usage':plain,'content':[]}}]
                            if complete:events.append(dict(type='result',session_id='captured-shape',is_error=False,
                                total_cost_usd=writer['list_cost_usd'],usage=usage))
                            ledger=self.root/(uuid.uuid4().hex+'.json')
                            command=[sys.executable,'-c','import json,sys; [print(json.dumps(e),flush=True) for e in json.loads(sys.argv[1])]',json.dumps(events)]
                            invoke=lambda:budget.run_budgeted(command,self.root,dict(os.environ),self.root/'mode-transcript',ledger,5,
                                containment=False, driver='claude',configured_model=model,role='writer',invocation_name='builder-mode',
                                max_cost=100,max_calls=1000,max_total_calls=1000,case_budget=1000)
                            if complete:invoke()
                            else:
                                with self.assertRaises(budget.BudgetError):invoke()
                            saved=json.loads(ledger.read_text())
                            if complete:self.assertEqual(saved['list_cost_usd'],writer['list_cost_usd'])
                            elif record['upstream_mode_fields'].get('speed')=='fast':
                                self.assertTrue(saved.get('unpriced_invocations'))
                                self.assertEqual(saved.get('estimated_subscription_cost_usd',0),0)
                            else:
                                self.assertEqual(saved['estimated_subscription_cost_usd'],claude_cost(GATED_CLAUDE,usage))
                                self.assertLessEqual(saved['estimated_subscription_cost_usd'],50)

    def test_concurrent_reservations_and_close_never_refund_unknown(self):
        allowance = gate.Allowance(lease())
        ids = [allowance.reserve(32768) for _ in range(5)]
        waited = threading.Event(); original = allowance.condition.wait
        def wait(timeout): waited.set(); return original(timeout)
        with patch.object(allowance.condition, 'wait', side_effect=wait), ThreadPoolExecutor() as pool:
            third = pool.submit(allowance.reserve,32768)
            self.assertTrue(waited.wait(2));self.assertFalse(third.done())
            self.assertFalse(allowance.is_set());self.assertEqual(allowance.forwarded,5)
            allowance.finish(ids[0],dict.fromkeys(CLAUDE_GATE_FIELDS,0))
            ids.append(third.result(timeout=2));self.assertIsNotNone(ids[-1])
        self.assertFalse(allowance.is_set())
        allowance.close(); before = allowance.snapshot()
        self.assertEqual((before['forwarded_requests'],before['unknown_requests'],before['in_flight_requests']), (6,5,0))
        self.assertEqual(Decimal(before['held_usd']),Decimal('47.604480'))
        for identity in ids:
            if identity: allowance.finish(identity,dict.fromkeys(CLAUDE_GATE_FIELDS,0))
        self.assertEqual(allowance.snapshot(),before)
        self.assertIsNone(allowance.reserve(1))  # Closed, and late handlers cannot refund.
        # Separate token admission, even when money is available.
        constrained = gate.Allowance(replace(lease(), max_output_tokens=32768))
        identity=constrained.reserve(32768)
        constrained.finish(identity,dict.fromkeys(CLAUDE_GATE_FIELDS,0)|{'output_tokens':32768})
        self.assertIsNone(constrained.reserve(1));self.assertTrue(constrained.is_set())
        sticky=gate.Allowance(lease());sticky.settled[0]=Decimal('42')
        self.assertIsNone(sticky.reserve(32768))  # W9.520896 does not fit the remaining8.
        self.assertIsNone(sticky.reserve(1))  # Exhaustion is terminal even for a smaller output request.
        self.assertEqual(sticky.forwarded,0)
        cancel=threading.Event();cancel.set();cancelled=gate.Allowance(lease(),cancel)
        self.assertIsNone(cancelled.reserve(1));self.assertFalse(cancelled.exhaustion.is_set())

    def test_waiting_request_rechecks_unknowns_close_cancel_and_deadline(self):
        for stop in ('unknown','close','cancel','deadline'):
            cancel=threading.Event()
            allowance=gate.Allowance(lease(),cancel,time.monotonic()+(.2 if stop=='deadline' else 3))
            ids=[allowance.reserve(32768) for _ in range(5)]
            waited=threading.Event();original=allowance.condition.wait
            def wait(timeout):waited.set();return original(timeout)
            with patch.object(allowance.condition,'wait',side_effect=wait),ThreadPoolExecutor() as pool:
                third=pool.submit(allowance.reserve,32768)
                self.assertTrue(waited.wait(1));self.assertFalse(allowance.is_set())
                if stop=='unknown':
                    for identity in ids:allowance.finish(identity,None)
                elif stop=='close':allowance.close()
                elif stop=='cancel':cancel.set()
                self.assertIsNone(third.result(timeout=2))
            self.assertEqual(allowance.exhaustion.is_set(),stop=='unknown')
            self.assertEqual(allowance.forwarded,5)
            if stop=='unknown':
                self.assertIsNone(allowance.reserve(1));self.assertEqual(allowance.unknown,5)
            allowance.close()

    def test_usage_only_refunds_complete_unambiguous_provider_controls(self):
        usage = dict(input_tokens=100,cache_read_input_tokens=50,cache_creation_input_tokens=25,output_tokens=10)
        good = sse(usage)
        bad = [sse(usage,stop=False),sse(usage,model='other'),good+good,
               good.replace(b'"output_tokens": 10',b'"output_tokens": -1'),
               good.replace(b'"input_tokens": 100',b'"input_tokens": true'),
               good.replace(b'"input_tokens": 100',b'"input_tokens": 1e999'),
               good.replace(b'"input_tokens": 100',b'"input_tokens": 1000001'),
               good.replace(b'"input_tokens": 100',b'"input_tokens": 100,"input_tokens":100'),
               good.replace(b'"output_tokens": 10',b'"output_tokens": 32769')]
        initial={'type':'message_start','message':{'model':'claude-opus-5-5','usage':dict(usage,output_tokens=0)}}
        missing_final=[initial,{'type':'content_block_delta','delta':{'type':'text_delta','text':'not final usage'}},
                       {'type':'message_stop'}]
        empty_final=[initial,{'type':'message_delta','delta':{'stop_reason':'end_turn'},'usage':{}},{'type':'message_stop'}]
        errored=[initial,{'type':'error','error':{'type':'api_error'}},{'type':'message_stop'}]
        bad.extend(b''.join(b'data: '+json.dumps(e).encode()+b'\n\n' for e in events)
                   for events in (missing_final,empty_final,errored))
        for payload in bad:
            parser = gate.Usage(32768,True); parser.feed(payload)
            self.assertIsNone(parser.final(),payload[:100])
            allowance = gate.Allowance(lease()); identity = allowance.reserve(32768)
            allowance.finish(identity,parser.final()); allowance.close()
            self.assertEqual(allowance.snapshot()['unknown_requests'],1)
            self.assertEqual(allowance.snapshot()['held_usd'],'9.520896')
        parser = gate.Usage(32768,True);parser.feed(good)
        self.assertEqual(parser.final(),usage)
        for stop in (None, '', 'unknown'):
            parser=gate.Usage(32768,False)
            parser.feed(json.dumps({'type':'message','model':'claude-opus-5-5','usage':usage,'stop_reason':stop}).encode())
            self.assertIsNone(parser.final())
        parser=gate.Usage(32768,False)
        parser.feed(json.dumps({'type':'message','model':'claude-opus-5-5','usage':usage,'stop_reason':'end_turn'}).encode())
        self.assertEqual(parser.final(),usage)

    def test_client_and_supplied_tampering_denies_before_callbacks(self):
        original = lease()
        for fields in ({'max_usd':51.0},{'max_usd':True},{'max_usd':float('nan')},
                       {'max_input_tokens':True},{'max_output_tokens':9999999},{'price_source':'caller'}):
            changed = replace(original,**fields)
            self.assertFalse(router.valid_lease(changed,GATED_CLAUDE))
            c = SimpleNamespace(work=self.root, case_id='synthetic',card={'roles':{'writer':{'model':GATED_CLAUDE}}},
                batch_id='b',job_id='j',batch_deadline=time.time()+3600)
            runtime = model_runtime.ModelRuntime(self.root,Mock(),Mock(),Mock(),Mock())
            callback = Mock()
            with patch.dict(os.environ,{'UNBUG_PROVIDER_WAIT':'1'}), patch.object(router,'WAIT_SECONDS',0), \
                 patch.object(router,'finish'),patch.object(router,'_rpc',return_value={'cancelled':True}), \
                 patch.object(model_runtime.ModelRuntime,'_invoke') as invoke:
                with self.assertRaises(router.ProviderWait) as error:
                    runtime.call(c,[GATED_CLAUDE],'',self.root,'builder-1',lease=changed,before_attempt=callback)
            self.assertEqual(error.exception.wait.reason,'unbounded_route')
            callback.assert_not_called();invoke.assert_not_called()
        spoof = {'kind':'lease',**asdict(original)};spoof.pop('max_usd')
        c=SimpleNamespace(router_model=GATED_CLAUDE)
        with patch.object(router,'_rpc',return_value=spoof),patch.object(router,'finish'):
            result=router._admit('writer',c,time.time()+3600,original.lease_id,router.ACCOUNTS)
        self.assertEqual(result.reason,'unbounded_route')

    def test_execution_start_is_one_use_across_store_restart(self):
        path=self.root/'router.sqlite';store=router.Store(path)
        result=store.rpc('acquire',dict(paid_protocol=1,id=uuid.uuid4().hex,model=GATED_CLAUDE,accounts=list(router.ACCOUNTS),role='writer',deadline=time.time()+3600))
        identity=result['lease_id'];store.rpc('start',{'lease_id':identity})
        store=router.Store(path)
        with self.assertRaisesRegex(ValueError,'already started'):store.rpc('start',{'lease_id':identity})
        with self.assertRaises(ValueError):store.rpc('observe',dict(observation_id='/execution/'+identity,healthy=True,pool='claude-token'))
        # A real old lease row lacks caps; neither renewal nor replay grants work.
        db=sqlite3.connect(path)
        with db:
            row=json.loads(db.execute('SELECT route FROM leases WHERE id=?',(identity,)).fetchone()[0])
            for key in router.MAXIMUM_FIELDS:row.pop(key)
            db.execute('UPDATE leases SET route=? WHERE id=?',(json.dumps(row),identity))
        db.close()
        with self.assertRaisesRegex(ValueError,'unbounded'):store.rpc('renew',{'lease_id':identity})
        store.rpc('finish',dict(lease_id=identity,outcome='denied',receipt=None))

    def test_real_route_maximum_fits_attempt_grant_and_unknown_settlement_once(self):
        # Synthetic B binding/interrupt, actual A policy and D reader/accountant.
        # B's installer is separate; D admission uses the validated Lease maximum.
        store=router.Store(self.root/'router.sqlite')
        deadline=float(int(time.time())+3600)
        for suffix,limit in (('short','49.999999999'),('fit','50.000000000')):
            work=self.root/suffix;work.mkdir();path=work/'ledger.json'
            path.write_text(json.dumps({'cost':0,'calls':0,'events':[]}));before=path.read_bytes()
            record=store.rpc('acquire',dict(paid_protocol=1,id=uuid.uuid4().hex,model=GATED_CLAUDE,
                accounts=list(router.ACCOUNTS),role='writer',deadline=deadline))
            actual=router.Lease(**{k:v for k,v in record.items() if k!='kind'})
            self.assertTrue(router.valid_lease(actual,GATED_CLAUDE))
            channel=dict(schema=1,batch='synthetic',job=suffix,case='case-'+suffix,
                reservation_id=str(uuid.uuid4()),revision=1,source_generation=None,
                committed_total_usd=limit,batch_deadline=datetime.fromtimestamp(deadline,timezone.utc).isoformat())
            c=SimpleNamespace(card={},case_id=channel['case'],batch_id=channel['batch'],job_id=suffix,
                batch_deadline=deadline,source_generation=None,engine=SimpleNamespace(key="attempt", baseline_spent_usd=0, ceiling_usd=Decimal(channel["committed_total_usd"])))
            attempt=c.engine;operation=str(uuid.uuid4())
            if suffix=='short':
                with self.assertRaisesRegex(budget.BudgetError,'grant_insufficient'):
                    budget.reserve_invocation(path,actual,model_runtime.invocation_maximum(c,actual),attempt=attempt,
                        operation_id=operation,call_name='builder-1')
                self.assertEqual(path.read_bytes(),before)
            else:
                row=budget.reserve_invocation(path,actual,model_runtime.invocation_maximum(c,actual),attempt=attempt,
                    operation_id=operation,call_name='builder-1')
                self.assertEqual(row['maximum_usd'],'50.000000000')
                self.assertEqual(budget.outstanding_reservations(json.loads(path.read_text())),Decimal(50))
                held=gate.Allowance(actual);self.assertIsNotNone(held.reserve(32768));held.close()
                (work/'usage-receipts').mkdir();relative='usage-receipts/'+actual.lease_id+'.json'
                (work/relative).write_text(json.dumps(dict(lease_id=actual.lease_id,invocation='builder-1',
                    **{k:getattr(actual,k) for k in router.MAXIMUM_FIELDS},cap_used=held.snapshot(),
                    events=[],booked_event_ids=[],usage_delta={},final_usage_known=False)))
                wait=dict(wait_id=str(uuid.uuid4()),lease_id=actual.lease_id,call_id=relative,settled=False)
                # Stream D money: unknown usage is charged at the closed gate's bound
                # (one request's hold), below the $50 route maximum.
                snap=held.snapshot();bound=Decimal(str(snap['settled_usd']))+Decimal(str(snap['held_usd']))
                self.assertTrue(0<bound<50)
                self.assertEqual(Decimal(str(budget.settle(wait,work=work,ledger_path=path))),bound)
                self.assertEqual(budget.settle(wait,work=work,ledger_path=path),0)
                ledger=json.loads(path.read_text())
                self.assertEqual(Decimal(str(budget.case_spending(ledger)['total_spent_usd'])),bound)
                self.assertEqual(Decimal(ledger['invocation_reservations'][actual.lease_id]['estimated_gap_usd']),bound)
                self.assertEqual(ledger['events'],[])  # Settlement never invents billed events.
                attempt.ceiling_usd = Decimal(51)
                with self.assertRaisesRegex(budget.BudgetError, 'reservation_mismatch'):
                    budget.attempt_limit(ledger, attempt)
            store.rpc('finish',dict(lease_id=actual.lease_id,outcome='denied',receipt=None))

    def test_fractional_lease_maximum_reserves_upward_to_nine_places(self):
        actual = replace(lease(), max_usd=0.1234567891)
        # Synthetic tariff exercises rounding; real Lease validation stays active.
        maximum = {k: getattr(actual, k) for k in router.MAXIMUM_FIELDS}
        with patch.object(router, 'route_maximum', return_value=maximum):
            rounded = model_runtime.invocation_maximum(SimpleNamespace(), actual)
        self.assertEqual(rounded, Decimal('0.123456790'))
        attempt = SimpleNamespace(key='rounding', baseline_spent_usd=0, ceiling_usd=50)
        path = self.root / 'ledger.json'
        path.write_text(json.dumps({'cost': 0, 'calls': 0, 'events': []}))
        for amount in (rounded, actual.max_usd):
            with self.subTest(amount=amount):
                row = budget.reserve_invocation(path, replace(actual, lease_id=uuid.uuid4().hex), amount,
                    attempt=attempt, operation_id=str(uuid.uuid4()), call_name='builder-rounding')
                self.assertEqual(row['maximum_usd'], '0.123456790')

    def test_factory_dispatch_preserves_lease_maximum_gate_and_invocation_identity(self):
        # Actual router policy, runtime gate and D accountant; fake process boundary.
        # Neither a CLI nor an upstream connection is launched.
        store = router.Store(self.root / 'router.sqlite', credit_reader=lambda: Decimal('11.63'))
        secrets = self.root / 'secrets'; secrets.mkdir()
        (secrets / 'claude-factory-token-2').write_text('synthetic-only')
        runtime = model_runtime.ModelRuntime(self.root, Mock(), Mock(),
            lambda path, **kw: shutil.rmtree(path), Mock())
        for outcome in ('done', 'interrupted', 'denied', 'containment_denied'):
            with self.subTest(outcome=outcome):
                work = self.root / outcome; work.mkdir(); (work / 'transcripts').mkdir()
                path = work / 'ledger.json'
                path.write_text(json.dumps({'cost': 0, 'calls': 0, 'events': []}))
                deadline = float(int(time.time()) + 3600)
                channel = dict(schema=1, batch='synthetic', job=outcome, case='case-'+outcome,
                    reservation_id=str(uuid.uuid4()), revision=1, source_generation=None,
                    committed_total_usd='50.000000000', batch_deadline=router.utc(deadline))
                c = SimpleNamespace(work=work, case=work, ledger=path,
                    args=run.argument_parser().parse_args(['--source', 'hunt']),
                    card={'roles': {'writer': {'model': GATED_CLAUDE}}},
                    case_id=channel['case'], batch_id=channel['batch'], job_id=outcome,
                    batch_deadline=deadline, source_generation=None,
                    engine=SimpleNamespace(key="attempt", baseline_spent_usd=0, ceiling_usd=Decimal(channel["committed_total_usd"])),
                    router_accounts=('claude-factory-token-2',))
                def process(cmd, cwd, env, transcript, ledger, timeout, **kw):
                    row = json.loads(path.read_text())['invocation_reservations'][kw['lease_id']]
                    self.assertEqual(row['maximum_usd'], '50.000000000')
                    self.assertEqual(kw['invocation_id'], row['invocation_id'])
                    self.assertIs(kw['attempt'], c.engine)
                    self.assertIsNone(kw['max_cost']); self.assertTrue(kw['concurrent'])
                    self.assertTrue(env['ANTHROPIC_BASE_URL'].startswith('http://127.0.0.1:'))
                    self.assertIsNotNone(kw['cancel'])
                    if outcome == 'containment_denied':
                        self.assertTrue(kw['containment'])
                        with patch.dict(os.environ, UNBUG_MODEL_CGROUP_ROOT=''):
                            return budget.run_budgeted(cmd, cwd, env, transcript, ledger, timeout, **kw)
                    if outcome == 'denied': raise OSError('synthetic setup failure')
                    kw['on_started']()
                    if outcome == 'interrupted': raise budget.BudgetError('model_call_cap')
                    return SimpleNamespace(returncode=0)
                with patch.object(router, '_rpc', store.rpc), patch.object(router, 'SECRETS', secrets), \
                     patch.object(model_runtime, 'pinned_cli', return_value='synthetic-no-cli'), \
                     patch.object(model_runtime, 'run_budgeted', side_effect=process) as called:
                    if outcome == 'done':
                        self.assertEqual(runtime.call(c, [GATED_CLAUDE], 'synthetic', work, 'builder-1'), 0)
                    else:
                        label = ('containment_unavailable' if outcome == 'containment_denied' else
                                 'model_call_cap' if outcome == 'interrupted' else 'usage_monitor:OSError')
                        with self.assertRaisesRegex(budget.BudgetError, '^'+label+'$'):
                            runtime.call(c, [GATED_CLAUDE], 'synthetic', work, 'builder-1')
                    called.assert_called_once()
                ledger = json.loads(path.read_text())
                row, = ledger['invocation_reservations'].values()
                # Stream D money: an interrupted call is estimated when it ends, not left pending.
                self.assertEqual(row['state'], 'estimated' if outcome == 'interrupted' else 'settled')
                receipt = json.loads((work / 'usage-receipts' / (row['lease_id']+'.json')).read_text())
                self.assertEqual(receipt['outcome'], 'denied' if outcome == 'containment_denied' else outcome)
                if outcome == 'containment_denied':
                    self.assertIn({'stage': 'model_containment', 'error': 'containment_unavailable'},
                                  c.card['cleanup_errors'])
                    self.assertEqual(budget.case_spending(ledger)['total_spent_usd'], 0)
                self.assertEqual(receipt['max_usd'], 50.0)
                self.assertEqual(receipt['final_usage_known'], outcome != 'interrupted')
                budget.reconcile_reservations(work, path)
                row = json.loads(path.read_text())['invocation_reservations'][row['lease_id']]
                self.assertEqual(Decimal(row['estimated_gap_usd']), 50 if outcome == 'interrupted' else 0)
                before = path.read_bytes(); budget.reconcile_reservations(work, path)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(store.rpc('status', {})['leases'], [])
        for changed in ({'max_usd': 1.0}, {'max_input_tokens': 1}, {'max_output_tokens': 1},
                        {'price_source': 'caller'}, {'expires_at': 1}, {'account': 'claude-factory-token-2-2'}):
            with self.subTest(changed=changed), self.assertRaisesRegex(budget.BudgetError, '^route_maximum_unknown$'):
                model_runtime.invocation_maximum(c, replace(lease(), **changed))

    def test_cap_stop_is_not_preflight_failure_optional_skip_or_scientific_try(self):
        c=SimpleNamespace(case=self.root,card={},args=SimpleNamespace(bench_workers=1),
            models={'attacker':[GATED_CLAUDE],'reviewers':[[GATED_CLAUDE]],
                    'strong_calibrator':[GATED_CLAUDE],'easy_calibrator':[GATED_CLAUDE]})
        with patch.object(run,'opencode',side_effect=budget.BudgetError('model_call_cap')) as call:
            with self.assertRaisesRegex(budget.BudgetError,'^model_call_cap$'):run.provider_preflight(c)
            self.assertEqual(call.call_count,1)
        with patch.object(run,'g10_overlap_reason',return_value=None),patch.object(run,'make_pilots'), \
             patch.object(calibration,'isolated_attempt_context',return_value=nullcontext(c)), \
             patch.object(run,'calibrate',side_effect=budget.BudgetError('model_call_cap')), \
             patch.object(run,'pilot_home',return_value=self.root/'not-created'):
            with self.assertRaisesRegex(budget.BudgetError,'^model_call_cap$'):run.early_probe(c)
        self.assertEqual(calibration.interruption_label(budget.BudgetError('model_call_cap')),'model_call_cap')
        runtime=model_runtime.ModelRuntime(self.root,Mock(),Mock(),Mock(),Mock())
        with self.assertRaises(router.ProviderWait):
            runtime._invoke(SimpleNamespace(model_lease=lease()),[GATED_CLAUDE],'',self.root,'builder-1')

    def test_lost_cli_final_after_all_real_responses_complete_keeps_booked_estimate_within_cap(self):
        allowance=gate.Allowance(lease());emitted=[]
        for n,event in enumerate(real_iterations().values()):
            for usage in event['tokens'].get('iterations',[]):
                identity=allowance.reserve(32768)
                if identity is None:break
                allowance.finish(identity,{k:usage[k] for k in CLAUDE_GATE_FIELDS})
                emitted.append({'type':'assistant','message':{'id':'synthetic-wrap-'+str(n),
                    'model':'claude-opus-5-5','usage':usage,'content':[]}})
            if allowance.exhaustion.is_set():break
        allowance.close()
        self.assertGreater(len(emitted),8)
        self.assertEqual(allowance.snapshot()['unknown_requests'],0)
        ledger=self.root/'ledger.json'
        command=[sys.executable,'-c','import json,sys; [print(json.dumps(e),flush=True) for e in json.loads(sys.argv[1])]',json.dumps(emitted)]
        with self.assertRaises(budget.BudgetError):
            budget.run_budgeted(command,self.root,dict(os.environ),self.root/'transcript',ledger,5,
                containment=False, driver='claude',configured_model=GATED_CLAUDE,role='writer',invocation_name='builder-partial',
                max_cost=100,max_calls=10000,max_total_calls=10000,case_budget=1000)
        saved=json.loads(ledger.read_text())
        self.assertGreater(saved['estimated_subscription_cost_usd'],0)
        self.assertLessEqual(saved['estimated_subscription_cost_usd'],50.0)  # exact, no epsilon.
        self.assertTrue(all(e.get('estimated_from_partial_usage') for e in saved['events']))

    def test_near_ceiling_float_booking_and_reserved_numerical_headroom(self):
        # Synthetic boundary arithmetic supplements, never replaces, the real-usage replay.
        worst=dict(input_tokens=0,cache_read_input_tokens=0,cache_creation_input_tokens=1000000,output_tokens=32768)
        usages=[worst]*4+[dict(input_tokens=0,cache_read_input_tokens=34,
                             cache_creation_input_tokens=272217,output_tokens=0),worst]
        allowance=gate.Allowance(lease());events=[]
        for index,usage in enumerate(usages):
            identity=allowance.reserve(32768);self.assertIsNotNone(identity)
            allowance.finish(identity,usage)
            events.append({'type':'assistant','message':{'id':'boundary-'+str(index),'usage':usage,'content':[]}})
        self.assertGreater(allowance.settled[0],Decimal('49.99999'))
        self.assertIsNone(allowance.reserve(1));allowance.close()
        command=[sys.executable,'-c','import json,sys; [print(json.dumps(e),flush=True) for e in json.loads(sys.argv[1])]',json.dumps(events)]
        ledger=self.root/'near.json'
        with self.assertRaises(budget.BudgetError):
            budget.run_budgeted(command,self.root,dict(os.environ),self.root/'near-transcript',ledger,5,
                containment=False, driver='claude',configured_model=GATED_CLAUDE,role='writer',invocation_name='builder-boundary',
                max_cost=100,max_calls=100,max_total_calls=100,case_budget=1000)
        self.assertLessEqual(json.loads(ledger.read_text())['estimated_subscription_cost_usd'],50.0)
        tight=gate.Allowance(lease())
        tight.settled[0]=Decimal('50')-Decimal('9.520896')-Decimal('0.0000005')
        self.assertIsNone(tight.reserve(32768));self.assertEqual(tight.forwarded,0)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.seen=[];self.failure=False;self.malformed=False;self.stalled=None;self.responses=None
        self.https_connection=http.client.HTTPSConnection
        owner=self
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_POST(self):
                raw=self.rfile.read(int(self.headers['Content-Length']))
                owner.seen.append((self.path,json.loads(raw),dict(self.headers)))
                usage=dict(input_tokens=1,cache_read_input_tokens=0,cache_creation_input_tokens=0,output_tokens=1)
                data=owner.responses.pop(0) if owner.responses else b'not valid usage' if owner.malformed else sse(usage)
                self.send_response(503 if owner.failure else 200)
                self.send_header('Content-Type','text/event-stream')
                if owner.stalled is None or owner.stalled.content_length:
                    self.send_header('Content-Length',str(len(data)))
                if owner.stalled is not None and owner.stalled.close_header:
                    self.send_header('Connection','close')
                self.send_header('anthropic-ratelimit-requests-reset','2030-01-01T00:00:00Z')
                self.send_header('Retry-After','17');self.end_headers()
                if owner.stalled is None:
                    self.wfile.write(data)
                else:
                    stall=owner.stalled
                    self.wfile.write(stall.prefix);self.wfile.flush()
                    if not stall.release.wait(stall.wait_seconds):return
                    try:
                        self.wfile.write(data[len(stall.prefix):]);self.wfile.flush()
                    except OSError:pass  # The real gate has already shut down this socket.
                    finally:stall.attempted.set()
        self.upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
        threading.Thread(target=self.upstream.serve_forever,daemon=True).start()
        self.addCleanup(self.upstream.server_close);self.addCleanup(self.upstream.shutdown)
        def connect(host,**kwargs):
            self.assertIn(host,('api.anthropic.com','openrouter.ai'))
            return http.client.HTTPConnection('127.0.0.1',self.upstream.server_port,**kwargs)
        mock=patch.object(gate.http.client,'HTTPSConnection',side_effect=connect);mock.start();self.addCleanup(mock.stop)

    def post(self, env, value, **headers):
        from urllib.parse import urlsplit
        url=urlsplit(env['ANTHROPIC_BASE_URL']);conn=http.client.HTTPConnection(url.hostname,url.port,timeout=3)
        conn.request('POST','/v1/messages?beta=true',json.dumps(value),
            {'Authorization':'Bearer synthetic','Content-Type':'application/json',**headers})
        response=conn.getresponse();result=(response.status,response.read(),dict(response.getheaders()));conn.close();return result

    def test_authenticated_normalisation_header_preservation_and_nonfatal_rejections(self):
        env={'PATH':os.environ['PATH'],'CLAUDE_CODE_OAUTH_TOKEN':'synthetic','ANTHROPIC_AUTH_TOKEN':'must-drop',
             'HTTPS_PROXY':'must-drop','CLAUDE_CODE_USE_BEDROCK':'1','FACTORY_STRATEGY_WORKERS':'2'}
        cap={}
        with gate.enforce(lease(),env,cap,3) as active:
            self.assertNotIn('ANTHROPIC_AUTH_TOKEN',env);self.assertNotIn('HTTPS_PROXY',env)
            self.assertNotIn('CLAUDE_CODE_USE_BEDROCK',env)
            self.assertEqual(self.post(env,body(),Authorization='Bearer stranger')[0],401)
            self.assertEqual(self.post(env,body(inference_geo='us'))[0],400)
            self.assertEqual(self.post(env,body(tools=[{'type':'web_search_20250305','name':'web_search'}]))[0],400)
            status,_,headers=self.post(env,body(context_management={},thinking={'type':'adaptive','display':'updates'}),
                **{'anthropic-beta':'fast-mode-bad','anthropic-workspace-id':'must-drop'})
            self.assertEqual(status,200);self.assertEqual(headers['Retry-After'],'17')
            self.assertFalse(active.is_set())
        self.assertEqual(len(self.seen),1)
        sent=self.seen[0][1];headers={k.lower():v for k,v in self.seen[0][2].items()}
        self.assertNotIn('inference_geo',sent)
        self.assertEqual(sent['max_tokens'],32768);self.assertNotIn('context_management',sent)
        self.assertEqual(sent['thinking'],{'type':'adaptive'});self.assertEqual(sent['service_tier'],'standard_only')
        self.assertEqual(headers['anthropic-beta'],gate.BETAS);self.assertNotIn('anthropic-workspace-id',headers)
        self.assertEqual(cap['validated_requests'],1);self.assertEqual(cap['unsupported_requests'],2)
        self.assertEqual(cap['forwarded_requests'],cap['validated_requests']+cap['unknown_requests']+cap['in_flight_requests'])

    def test_uncertain_requests_hold_full_w_and_exhaustion_stops_before_network(self):
        self.failure=True;env={'CLAUDE_CODE_OAUTH_TOKEN':'synthetic'};cap={}
        with self.assertRaisesRegex(budget.BudgetError,'^model_call_cap$'):
            with gate.enforce(lease(),env,cap,3) as active:
                for _ in range(5): self.assertEqual(self.post(env,body())[0],503)
                self.assertEqual(self.post(env,body())[0],400)
                self.assertTrue(active.is_set())
        self.assertEqual(len(self.seen),5)
        self.assertEqual((cap['forwarded_requests'],cap['unknown_requests'],cap['in_flight_requests']),(5,5,0))
        self.assertEqual(Decimal(cap['held_usd']),Decimal('47.604480'))

    def test_parent_cancel_and_cleanup_failure_are_not_monetary_labels(self):
        cancel=threading.Event();cancel.set();cap={};env={'CLAUDE_CODE_OAUTH_TOKEN':'synthetic'}
        with gate.enforce(lease(),env,cap,3,cancel):
            status,data,_=self.post(env,body())
            self.assertEqual(status,400);self.assertIn(b'invocation_stopped',data)
        self.assertFalse(cap['exhausted']);self.assertEqual(self.seen,[])
        with self.assertRaisesRegex(budget.BudgetError,'^cancellation_failed$'):
            with gate.enforce(lease(),env,cap,3) as active:
                active.state.settled[0]=Decimal('42')
                self.assertIsNone(active.state.reserve(32768))
                raise budget.BudgetError('cancellation_failed')
        self.assertTrue(cap['exhausted']);self.assertTrue(cap['closed'])

    def test_close_between_connect_and_request_cannot_reconnect_or_forward(self):
        paused,release=threading.Event(),threading.Event()
        class Paused(http.client.HTTPConnection):
            def request(self,*args,**kwargs):
                paused.set()
                if not release.wait(3):raise AssertionError('test request was not released')
                return super().request(*args,**kwargs)
        def connect(host,**kwargs):
            self.assertEqual(host,'api.anthropic.com')
            return Paused('127.0.0.1',self.upstream.server_port,**kwargs)
        env={'CLAUDE_CODE_OAUTH_TOKEN':'synthetic'};cap={}
        with patch.object(gate.http.client,'HTTPSConnection',side_effect=connect):
            with gate.enforce(lease(),env,cap,3) as active,ThreadPoolExecutor() as pool:
                future=pool.submit(self.post,env,body())
                try:
                    self.assertTrue(paused.wait(2));active.close()
                    before=active.state.snapshot()
                finally:release.set()
                self.assertEqual(future.result(timeout=3)[0],502)
                self.assertEqual(active.state.snapshot(),before)
        self.assertEqual(self.seen,[])
        self.assertEqual((cap['unknown_requests'],cap['in_flight_requests']),(1,0))

    def test_runtime_close_mid_response_retains_hold_once(self):
        for route in [*CLAUDE_PROFILES, MINIMAX]:
            for protocol,close_header in (('HTTP/1.1',False),('HTTP/1.1',True),('HTTP/1.0',False)):
                with self.subTest(route=route,protocol=protocol,close_header=close_header):
                    self.upstream.RequestHandlerClass.protocol_version=protocol
                    self._runtime_close_mid_response_retains_hold_once(close_header,route)

    def test_real_process_tls_cancellation_settles_unknown_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            cert,key=Path(temporary)/'cert.pem',Path(temporary)/'key.pem'
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes',
                '-keyout',str(key),'-out',str(cert),'-subj','/CN=localhost',
                '-addext','subjectAltName=DNS:localhost','-days','1'],
                check=True,capture_output=True,timeout=10)
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
            self.upstream.socket=context.wrap_socket(self.upstream.socket,server_side=True)
            trust=ssl.create_default_context(cafile=str(cert))
            def connect(host,**kwargs):
                self.assertEqual(host,'api.anthropic.com')
                return self.https_connection('localhost',self.upstream.server_port,context=trust,**kwargs)
            # CPython HTTPSConnection uses super(HTTPSConnection, self): keep
            # its module global a real class; redirect only the gate's namespace.
            transport=SimpleNamespace(client=SimpleNamespace(HTTPSConnection=connect,
                HTTPException=http.client.HTTPException))
            with patch.object(http.client,'HTTPSConnection',self.https_connection), \
                 patch.object(gate,'http',transport):
                for route in CLAUDE_PROFILES:
                    for protocol,close_header,length in (('HTTP/1.1',False,True),
                            ('HTTP/1.1',True,True),('HTTP/1.0',False,True),('HTTP/1.0',False,False)):
                        with self.subTest(route=route,protocol=protocol,close_header=close_header,content_length=length):
                            self.upstream.RequestHandlerClass.protocol_version=protocol
                            self._runtime_close_mid_response_retains_hold_once(close_header,route,
                                real_cli=True,content_length=length)

    def _runtime_close_mid_response_retains_hold_once(self,close_header,model,*,real_cli=False,content_length=True):
        # Synthetic transport fault through the real gate, runtime receipt writer
        # and accountant. Optional real local client process, never a provider CLI
        # or live worker. Protocol bytes and attempt grants are synthetic.
        paid = model == MINIMAX
        maximum = Decimal(str(router.route_maximum(model)['max_usd'])) if paid else CLAUDE_PROFILES[model]
        hold = Decimal('0.4718592' if paid else '2.409600' if model.startswith(GATED_CLAUDE45) else '9.520896')
        provider = model.partition('/')[2] if paid else claude_profile(model)['model'].partition('/')[2]
        prefix=sse(dict(input_tokens=1,cache_read_input_tokens=0,
                        cache_creation_input_tokens=0,output_tokens=1),model=provider).split(b'\n\n')[0]+b'\n\n'
        if paid: prefix=b'data: '+json.dumps(dict(id='synthetic',model=provider,choices=[])).encode()+b'\n\n'
        self.stalled=SimpleNamespace(prefix=prefix,release=threading.Event(),attempted=threading.Event(),
                                     close_header=close_header,content_length=content_length,
                                     wait_seconds=60 if real_cli else 30)
        received,handler_done=threading.Event(),threading.Event()
        observed={};cancel_started=threading.Event()
        original=gate.Handler.do_POST
        def handle(handler):
            try:return original(handler)
            except Exception as error:
                observed['handler_error']=repr(error)
                raise
            finally:handler_done.set()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'transcripts').mkdir();ram=root/'ram';ram.mkdir()
            account = 'openrouter-key' if paid else 'claude-factory-token-2'
            (ram/account).write_text('synthetic-only')
            deadline=float(int(time.time())+3600)
            channel=dict(schema=1,batch='synthetic',job='interrupt',case='case-interrupt',
                reservation_id=str(uuid.uuid4()),revision=1,source_generation=None,
                committed_total_usd=f'{maximum:.9f}',batch_deadline=router.utc(deadline))
            c=SimpleNamespace(work=root,case=root,ledger=root/'ledger.json',
                args=run.argument_parser().parse_args(['--source','hunt']),
                card={'roles':{'writer':{'model':model}}},
                case_id=channel['case'],batch_id=channel['batch'],job_id=channel['job'],
                batch_deadline=deadline,source_generation=None,
                engine=SimpleNamespace(key="attempt", baseline_spent_usd=0, ceiling_usd=Decimal(channel["committed_total_usd"])),
                router_accounts=(account,))
            c.role_cancel=threading.Event()
            c.ledger.write_text(json.dumps({'cost':0,'calls':0,'events':[]}))
            store=router.Store(root/'router.sqlite', credit_reader=lambda: Decimal('11.63'))
            runtime=model_runtime.ModelRuntime(root,Mock(),Mock(),lambda p,**kw:shutil.rmtree(p),Mock())
            def client(env):
                from urllib.parse import urlsplit
                cfg=json.loads(env['OPENCODE_CONFIG_CONTENT'])['provider']['openrouter']['options'] if paid else None
                url=urlsplit(cfg['baseURL'] if paid else env['ANTHROPIC_BASE_URL'])
                request = dict(model=provider,messages=[{'role':'user','content':'synthetic'}],stream=True) if paid else body()
                request['model']=provider
                path='/api/v1/chat/completions' if paid else '/v1/messages'
                bearer=cfg['apiKey'] if paid else 'synthetic-only'
                connection=http.client.HTTPConnection(url.hostname,url.port,timeout=30)
                try:
                    connection.request('POST',path,json.dumps(request),
                        {'Authorization':'Bearer '+bearer,'Content-Type':'application/json'})
                    response=connection.getresponse();self.assertEqual(response.status,200)
                    first=response.read(len(prefix));self.assertEqual(first,prefix)
                    received.set()
                    return first+response.read()  # Must reach EOF before upstream release.
                finally:connection.close()
            ready,pids,heartbeat=root/'ready',root/'pids.json',root/'heartbeat'
            executable=root/'local-client'
            if real_cli:
                child=("import pathlib,time; p=pathlib.Path("+repr(str(heartbeat))+")\n"
                       "while True:\n p.write_text(str(time.monotonic_ns())); time.sleep(.02)")
                executable.write_text(f"#!{sys.executable}\n"+
                    "import http.client,json,os,pathlib,subprocess,sys,time\n"
                    "from urllib.parse import urlsplit\n"+
                    f"child=subprocess.Popen([sys.executable,'-c',{child!r}])\n"+
                    f"pathlib.Path({str(pids)!r}).write_text(json.dumps([os.getpid(),child.pid]))\n"+
                    "url=urlsplit(os.environ['ANTHROPIC_BASE_URL'])\n"
                    "conn=http.client.HTTPConnection(url.hostname,url.port,timeout=60)\n"
                    "try:\n"+
                    f" conn.request('POST','/v1/messages',{json.dumps(dict(body(),model=provider))!r},"+
                    "{'Authorization':'Bearer '+os.environ['CLAUDE_CODE_OAUTH_TOKEN'],"+
                    "'Content-Type':'application/json'})\n"
                    " response=conn.getresponse()\n"+
                    f" assert response.status==200 and response.read({len(prefix)})=={prefix!r}\n"+
                    f" pathlib.Path({str(ready)!r}).touch()\n"
                    " response.read()\n"
                    f"except Exception as error: pathlib.Path({str(root/'client-error')!r}).write_text(repr(error))\n"
                    "while True: time.sleep(.05)\n")
                executable.chmod(0o755)
            def state(pid):
                result=subprocess.run(['ps','-o','stat=','-p',str(pid)],
                    capture_output=True,text=True,timeout=5)
                self.assertIn(result.returncode,(0,1),result.stderr)
                return result.stdout.strip()
            def execute(cmd,cwd,env,*args,**kw):
                self.assertEqual(cmd[cmd.index('-m' if paid else '--model')+1],model if paid else provider)
                if paid: self.assertNotIn('OPENROUTER_API_KEY',env)
                else: self.assertEqual(env['CLAUDE_CODE_OAUTH_TOKEN'],'synthetic-only')
                self.assertEqual(c.model_lease.route,model)
                observed['gate']=kw['cancel']
                if real_cli:
                    kw["containment"] = False  # synthetic same-group TLS evidence, not O7
                    try:return budget.run_budgeted(cmd,cwd,env,*args,**kw)
                    except budget.BudgetError as error:
                        self.assertEqual(str(error),'cancelled')
                        parent,child=json.loads(pids.read_text())
                        # run_budgeted must already have reaped its direct child.
                        with self.assertRaises(ChildProcessError):os.waitpid(parent,os.WNOHANG)
                        self.assertEqual(state(parent),'')
                        child_state=state(child)
                        self.assertTrue(not child_state or child_state.startswith('Z'),child_state)
                        before=heartbeat.read_bytes();time.sleep(.15)
                        self.assertEqual(heartbeat.read_bytes(),before)
                        # Gate close and runtime reservation settlement happen later.
                        self.assertFalse(kw['cancel'].state.snapshot()['closed'])
                        reservation,=json.loads(c.ledger.read_text())['invocation_reservations'].values()
                        self.assertEqual(reservation['state'],'pending')
                        observed['process_checked']=True
                        raise
                kw['on_started']()
                observed['client']=pool.submit(client,env.copy())
                self.assertTrue(received.wait(10),'client never received the relayed prefix')
                observed['cancelled_at']=time.monotonic();cancel_started.set()
                raise budget.BudgetError('cancelled')
            pool=ThreadPoolExecutor(max_workers=2)
            try:
                with patch.object(router,'_rpc',store.rpc),patch.object(router,'SECRETS',ram), \
                     patch.object(model_runtime,'pinned_cli',return_value=str(executable) if real_cli else 'synthetic-no-cli'), \
                     patch.object(model_runtime,'_opencode_flags',return_value=[]), \
                     (patch.object(gate.sys,'platform','linux') if paid else nullcontext()), \
                     patch.object(model_runtime,'run_budgeted',side_effect=execute), \
                     patch.object(gate.Handler,'do_POST',handle):
                    future=pool.submit(runtime.call,c,[model],'synthetic',root,'builder-1',
                                       timeout=60 if real_cli else 30)
                    if real_cli:
                        until=time.monotonic()+20
                        while not (ready.exists() and heartbeat.exists()):
                            if future.done():future.result()  # expose admission/startup errors
                            self.assertFalse((root/'client-error').exists(),
                                ((root/'client-error').read_text(),observed.get('handler_error')) if (root/'client-error').exists() else '')
                            self.assertLess(time.monotonic(),until,'local client never became ready')
                            time.sleep(.02)
                        parent,child=json.loads(pids.read_text())
                        self.assertEqual(os.getpgid(parent),parent)
                        self.assertEqual(os.getpgid(child),parent)
                        observed['cancelled_at']=time.monotonic()
                        c.role_cancel.set()
                    else:
                        self.assertTrue(received.wait(10),'request did not reach the relay')
                        self.assertTrue(cancel_started.wait(5),'simulated cancellation never started')
                    end=observed['cancelled_at']+(15 if real_cli else 5)
                    with self.assertRaisesRegex(budget.BudgetError,'^cancelled$'):
                        future.result(timeout=max(0,end-time.monotonic()))
                    self.assertTrue(handler_done.wait(max(0,end-time.monotonic())))
                    if real_cli:self.assertTrue(observed['process_checked'])
                    else:self.assertEqual(observed['client'].result(timeout=max(0,end-time.monotonic())),prefix)
                    self.assertLess(time.monotonic(),end)
                    self.assertFalse(self.stalled.release.is_set())
                    active=observed['gate']
                    snapshot=json.dumps(active.state.snapshot(),sort_keys=True)
                    route,=c.card['route_receipts'];receipt_path=root/route['call_id']
                    receipt_bytes=receipt_path.read_bytes();receipt=json.loads(receipt_bytes)
                    cap=receipt['cap_used']
                    self.assertEqual(route['route'],model)
                    self.assertEqual(c.card['models_used']['builder-1'],model)
                    self.assertEqual(receipt['outcome'],'interrupted');self.assertFalse(receipt['final_usage_known'])
                    self.assertEqual([cap[k] for k in ('forwarded_requests','validated_requests',
                        'unknown_requests','in_flight_requests')],[1,0,1,0])
                    self.assertEqual(Decimal(cap['settled_usd']),0)
                    self.assertEqual(Decimal(cap['held_usd']),hold)
                    self.assertTrue(cap['closed']);self.assertFalse(cap['exhausted'])
                    ledger=json.loads(c.ledger.read_text());row,=ledger['invocation_reservations'].values()
                    self.assertEqual(row['maximum_usd'],f'{maximum:.9f}')
                    self.assertEqual(row['state'],'estimated')
                    self.assertEqual(row['estimated_gap_usd'],f'{hold:.9f}')
                    self.assertEqual(Decimal(str(budget.case_spending(ledger)['total_spent_usd'])),hold)
                    self.assertEqual(ledger['events'],[])
                    before=c.ledger.read_bytes()
                    self.stalled.release.set();self.assertTrue(self.stalled.attempted.wait(5))
                    self.assertEqual(c.ledger.read_bytes(),before)
                    self.assertEqual(json.dumps(active.state.snapshot(),sort_keys=True),snapshot)
                    self.assertEqual(receipt_path.read_bytes(),receipt_bytes)
                    self.assertIsNone(active.state.reserve(32768))
                    for _ in range(2):
                        budget.reconcile_reservations(root,c.ledger)
                        self.assertEqual(c.ledger.read_bytes(),before)
                    self.assertEqual(store.rpc('status',{})['leases'],[])
                    if paid:
                        self.assertEqual(Decimal(store.rpc('status',{})['paid']['total_usd']),hold)
                        self.assertEqual(Decimal(store.rpc('status',{})['paid']['outstanding_usd']),hold)
                    interrupted,=c.router_interrupted_calls
                    self.assertEqual(interrupted['lease_id'],row['lease_id'])
                    self.assertEqual(interrupted['call_id'],route['call_id'])
            finally:
                c.role_cancel.set()
                self.stalled.release.set()
                if 'gate' in observed:observed['gate'].state.close()
                pool.shutdown(wait=True)
                if real_cli and pids.exists() and not observed.get('process_checked'):
                    parent,_=json.loads(pids.read_text())
                    try:os.killpg(parent,signal.SIGKILL)
                    except ProcessLookupError:pass

    def test_successful_cli_cannot_hide_gate_unknown_usage_in_real_runtime_receipt(self):
        for model in LEGACY_CLAUDE_PROFILES:
            with tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);(root/'transcripts').mkdir();ram=root/'ram';ram.mkdir()
                (ram/'claude-factory-token-2').write_text('synthetic-oauth-only')
                c=SimpleNamespace(work=root,case=root,case_id='synthetic',
                    card={'roles':{'writer':{'model':model}}},ledger=root/'ledger.json',
                    batch_id='b',job_id='j',batch_deadline=time.time()+3600,
                    args=argparse.Namespace(agent_timeout=5,max_cost=100,max_role_calls=1000,
                        max_total_calls=10000,no_progress_minutes=1,max_zero_tokens=3,case_budget=1000,resume=None))
                c.ledger.write_text(json.dumps({'cost':0,'calls':0,'events':[]}));before=c.ledger.read_bytes()
                store=router.Store(root/'router.sqlite', credit_reader=lambda: Decimal('11.63'));self.malformed=True
                def execute(cmd,cwd,env,*args,**kwargs):
                    self.assertEqual(cmd[cmd.index('--model')+1],GATED_CLAUDE.partition('/')[2])
                    url=__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(env['ANTHROPIC_BASE_URL'])
                    connection=http.client.HTTPConnection(url.hostname,url.port,timeout=3)
                    connection.request('POST','/v1/messages',json.dumps(body()),
                        {'Authorization':'Bearer synthetic-oauth-only','Content-Type':'application/json'})
                    response=connection.getresponse();self.assertEqual(response.status,200);response.read();connection.close()
                    return SimpleNamespace(returncode=0)
                runtime=model_runtime.ModelRuntime(root,Mock(),Mock(),lambda p,**kw:shutil.rmtree(p),Mock())
                with patch.dict(os.environ,{'UNBUG_PROVIDER_WAIT':'1'}),patch.object(router,'_rpc',store.rpc), \
                     patch.object(router,'SECRETS',ram),patch.object(model_runtime,'pinned_cli',return_value='synthetic'), \
                     patch.object(model_runtime,'run_budgeted',side_effect=execute):
                    self.assertEqual(runtime.call(c,[model],'',root,'builder-1'),0)
                receipt=json.loads((root/c.card['route_receipts'][0]['call_id']).read_text())
                self.assertFalse(receipt['final_usage_known'])
                self.assertEqual(receipt['cap_used']['unknown_requests'],1)
                self.assertTrue(receipt['cap_used']['closed'])
                self.assertEqual({k:receipt[k] for k in router.MAXIMUM_FIELDS},router.route_maximum(model))
                self.assertNotIn('synthetic-oauth-only',json.dumps(receipt));self.assertEqual(c.ledger.read_bytes(),before)
                self.assertEqual(store.rpc('status',{})['leases'],[])


if __name__=='__main__':unittest.main()
