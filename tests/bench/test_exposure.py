"""Pure Python exposure contracts; no Docker or model calls."""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import asyncio
import unittest
import claims
import exposure
from live_shop import LiveShop
from silent_window import readers


class ExposureTests(unittest.TestCase):
    def test_live_verdict_cross_checks_confirmed_receipts(self):
        from unittest.mock import patch
        import bench
        checker = {'orders': {'o1': {'deleted': False, 'draft': False, 'status': 'pending',
                                    'items': {'variant_bench_x_single': 1}}}, 'valid': True}
        traffic = {'normal': [{'requested': {'variant_bench_x_single': 1}, 'response': {
            'status': 200, 'data': {'order': {'id': 'o1', 'items': [
                {'variant_id': 'variant_bench_x_single', 'quantity': 1}]}}}}]}
        shop = LiveShop(None, {})
        def verdict(result, *args, **kwargs): return result['checker']
        with patch.object(bench, 'judge_checkpoint', verdict):
            result = shop.judge({'checker': checker, 'errors': []}, traffic)
            self.assertTrue(result['confirmed_orders_ok'])
            checker['orders'] = {}
            result = shop.judge({'checker': checker, 'errors': []}, traffic)
            self.assertFalse(result['confirmed_orders_ok'])
            self.assertEqual(result['confirmed_problems'][0]['problem'], 'missing from database')
        self.assertNotIn('confirmed_orders_ok', checker, 'probes keep raw facts unchanged')

    def test_claim_changes_and_unknown_time(self):
        samples = [dict(elapsed_sec=t, paths={'shop': state}, claims={'shop': status})
                   for t, state, status in [(0, True, 'protected'), (2, True, 'unknown'), (4, False, 'protected')]]
        e = exposure.integrate(samples, 6, 2, ['shop'])
        self.assertEqual(e['paths']['shop'], dict(unsafe_seconds=4, unsafe_claimed_protected_seconds=2, unknown_seconds=0))
        self.assertTrue(e['valid'])
        samples[1]['paths'] = {}
        e = exposure.integrate(samples, 6, 2, ['shop'])
        self.assertEqual(e['paths']['shop']['unknown_seconds'], 2)
        self.assertFalse(e['valid'])
        self.assertFalse(exposure.integrate([], 6, 2, ['shop'])['valid'])

    def test_scheduler_and_probe_failure(self):
        now = [0.]
        async def sleep(n): now[0] += n
        async def report(): return {'claims': [{'path': 'shop', 'status': 'protected'}]}
        calls = []
        async def probe():
            calls.append(now[0])
            if now[0] == 2: raise RuntimeError('blind')
            return {'shop': True}
        e = asyncio.run(exposure.observe(dict(duration_sec=6, interval_sec=2), ['shop'], probe, report,
                       clock=lambda: now[0], sleep=sleep))
        self.assertEqual(calls, [0, 2, 4])
        self.assertEqual(now[0], 6)
        self.assertEqual(e['paths']['shop']['unsafe_seconds'], 4)
        self.assertEqual(e['paths']['shop']['unknown_seconds'], 2)
        self.assertFalse(e['valid'])

    def test_additive_claims_and_unchanged_prices(self):
        report = {'response': 'keep', 'claims': [{'rule': 'never-oversell', 'path': 'shop', 'status': 'protected'}]}
        e = exposure.integrate([{'elapsed_sec': 0, 'paths': {'shop': True}, 'claims': {'shop': 'protected'}}], 10, 10, ['shop'])
        cp = exposure.checkpoint(e, report, {'correct_responses': ['keep']})
        result = cp['claims_score']
        ordinary = dict(cp); ordinary.pop('exposure'); ordinary.pop('delivery')
        legacy = claims.score(report, ordinary, cp['key'])
        self.assertEqual({k:v for k,v in result.items() if k not in ('delivery','exposure')}, legacy)
        self.assertEqual(result['human_minutes']['total'], 60)
        self.assertTrue(result['unsafe_checkpoint'])
        self.assertEqual(result['exposure']['paths']['shop']['unsafe_claimed_protected_seconds'], 10)
        self.assertEqual(claims.score({}, cp, cp['key']), result, 'a later file cannot rewrite the window report')

    def test_window_validation(self):
        for config in [None, [], '120']:
            with self.assertRaises(ValueError): exposure.window_config({'window': config})
        for duration, interval in [(0, 1), (1, 2), (True, 1), (float('inf'), 1), (1, float('nan'))]:
            with self.assertRaises(ValueError): exposure.window_config({'window': dict(duration_sec=duration, interval_sec=interval)})

    def test_private_service_reader_and_invalid_facts(self):
        class Reader:
            quantity = 7
            async def sql(self, query):
                import json
                return json.dumps({'valid': True, 'checker_ok': True, 'orders': {'medusa': {
                    'deleted': False, 'draft': False, 'status': 'pending', 'items': {'variant_bench_s_single': 5}}}})
            async def sqlite(self, name, path, query, table=None): return [[1, 's', self.quantity]]
        source = '''async def read(reader,name):
 rows=await reader.sqlite(name,'/data/channel.sqlite','SELECT id,kit,quantity FROM orders',table='orders')
 return {'orders':{str(i):{'units':{k:q},'canceled':False} for i,k,q in rows}}
'''
        reader = Reader()
        shop = LiveShop(None, {'inventory_services': [{'name': 'channel', 'project': 'not-present-on-host',
                                                       'reader_source': source}]}, reader)
        paths = asyncio.run(shop.probe())
        self.assertTrue(paths['service:channel'])
        self.assertFalse(paths['store-checkout'])
        reader.quantity = float('nan')
        with self.assertRaises(ValueError): asyncio.run(shop.probe())

    def test_deleted_or_invalid_file_does_not_withdraw_latest_claim(self):
        import json
        from types import SimpleNamespace
        protected = {'response': 'keep', 'claims': [{'path': 'shop', 'status': 'protected'}]}
        withdrawn = {'response': 'escalate', 'claims': [{'path': 'shop', 'status': 'unknown'}]}
        class Environment:
            outputs = iter([json.dumps(protected), '{}', 'truncated json', json.dumps(withdrawn)])
            async def exec(self, *args, **kwargs):
                return SimpleNamespace(return_code=0, stdout=next(self.outputs), stderr='')
        _, _, report, _ = readers(Environment(), {})
        async def read(): return [await report() for _ in range(4)]
        self.assertEqual(asyncio.run(read()), [protected, protected, protected, withdrawn])


if __name__ == '__main__': unittest.main()
