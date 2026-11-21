"""Neuralwatt lanes for MiMo, GLM and DeepSeek (docs/designs/neuralwatt-routes.md, items 1-2 and "Neuralwatt
first"), on real router state.

router-health-20261119.json holds the router's health rows (health table only, no keys) as read on the
control VM on 2026-11-19, from factory.before-force-lift-20261119.sqlite3: OpenRouter credit-blocked at
$4.38, both Go plans on weekly quota. The Go rows' backoff had lapsed (blocked_until 0), so each acquire
first retries Go; the replay observes Go's quota answer as the router did that day. Reproduce on the VM with
  sqlite3 -json factory.before-force-lift-20261119.sqlite3 'SELECT pool, value FROM health'
(each value parsed as JSON, keyed by pool).

router-approved-config-20261121.json is the control VM's live router config (~/durable-first-case-20261106,
2026-11-20 23:53 UTC, 708 bytes; no secrets: lane keys, accounts and the paid ceiling).

router-request-3dfdde3c-deepseek-20261120.json is a real acquire from a worker on release 3dfdde3c, read
read-only from the router ledger (requests JOIN leases): it offers neuralwatt-key and sends no chain.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'factory'))
from contextlib import closing, redirect_stderr
import io
import os
from decimal import Decimal
import gzip
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid
import budget
import model_router as router
from token_prices import (FREE_ROUTES, GO_ROUTES, GATED_OPENROUTER, NW_OWN_PRICES, NW_TWINS, NW_ROUTES, go_step_cost, nw_maximum, nw_request_worst,
                          openrouter_gate_maximum, runtime_prices)

FIXTURES = Path(__file__).with_name('fixtures')
HEALTH = json.loads((FIXTURES / 'router-health-20261119.json').read_text())
# Neuralwatt's 429 for a full concurrency budget (rollout step 1's capture, body from Neuralwatt's docs).
CONCURRENT = json.loads((FIXTURES / 'neuralwatt-smoke-20261119.json').read_text())['errors']['concurrent']
PRICES = json.loads(gzip.decompress((FIXTURES / 'neuralwatt-price-record-20261119.json.gz').read_bytes()))
CATALOG = json.loads(gzip.decompress((FIXTURES / 'neuralwatt-price-record-20261120.json.gz').read_bytes()))
LIVE_CONFIG = (FIXTURES / 'router-approved-config-20261121.json').read_text()
LEGACY = json.loads((FIXTURES / 'router-request-3dfdde3c-deepseek-20261120.json').read_text())
# Real saved roles: e15450's MiMo reviewer, and GLM as every 2026-10 card saved it (walled easy_calibrator).
# No saved card has a GLM role outside the wall, so the unwalled GLM acquire reuses that saved model id.
CARD = json.loads((FIXTURES / 'e15450-collected-card.json').read_text())['roles']
MIMO = CARD['reviewer']['model']
DEEPSEEK = CARD['stress_tester']['model']           # its walled easy_calibrator has the same DeepSeek model
GLM = next(c['card']['roles']['easy_calibrator']['model']
           for c in json.loads(gzip.decompress((FIXTURES / '20261029-real-public-cards.json.gz').read_bytes())) if 'roles' in c['card'])
OLD = router.ACCOUNTS[:-1]   # what a caller without the Neuralwatt key offers (and every caller before it)
NW_DEEPSEEK = 'neuralwatt/deepseek-v4.1-flash'
# CHAINS as release 3dfdde3c (and 6ed7c545) knows it: git show 3dfdde3c:factory/model_router.py.
CHAINS_3DFDDE3C = (
    ('opencode-go/deepseek-v4.1-flash', 'openrouter/deepseek/deepseek-v4.1-flash', 'opencode/deepseek-v4.1-flash-free'),
    ('opencode-go/minimax-m3.1-flash', 'opencode/minimax-m3.1-flash-free', 'openrouter/minimax/minimax-m3.1-flash:free',
     'openrouter/minimax/minimax-m3.1-flash'),
    ('opencode-go/mimo-v2.6-pro', 'neuralwatt/mimo-v2.6-pro', 'openrouter/xiaomi/mimo-v2.6-pro'),
    ('opencode-go/muse-spark-1.3-contributor', 'openrouter/meta/muse-spark-1.3-contributor'),
    ('opencode-go/glm-5.3-flash', 'neuralwatt/glm-5.3-flash', 'openrouter/z-ai/glm-5.3-flash', 'opencode/glm-5.3-flash-free'))
DEEPSEEK_3DFDDE3C = CHAINS_3DFDDE3C[0]


class RealStateRoutes(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.now = HEALTH['openrouter-key']['observed_at'] + 60
        self.store = router.Store(Path(tmp.name) / 'router.sqlite', clock=lambda: self.now, capacities={'neuralwatt-key': 8})
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.executemany('INSERT INTO health VALUES (?,?)', [(k, json.dumps(v)) for k, v in HEALTH.items()])
        self.assertEqual((MIMO, GLM, DEEPSEEK), ('openrouter/xiaomi/mimo-v2.6-pro', 'opencode/glm-5.3-flash-free',
                                                 'opencode/deepseek-v4.1-flash-free'))

    def acquire(self, model, accounts=router.ACCOUNTS, role='writer', excluded=(), chain=True, **extra):
        data = dict(id=uuid.uuid4().hex, model=model, accounts=list(accounts), role=role, deadline=self.now + 86400,
                    paid_protocol=1, capacity_protocol=1, excluded_lanes=list(excluded), **extra)
        if chain: data['chain'] = router.chain(model)   # what this release's _admit sends
        return self.store.rpc('acquire', data)

    def spend_go(self):
        # Each Go plan answers its weekly quota once more; that blocks its pool for every model.
        for account in router.ACCOUNTS[2:4]:
            lease = self.acquire(MIMO)
            self.assertEqual((lease['kind'], lease['account']), ('lease', account))
            self.store.rpc('observe', dict(lease_id=lease['lease_id'], reason='quota', observation_id=lease['lease_id'] + ':quota'))
            self.store.rpc('finish', dict(lease_id=lease['lease_id'], outcome='interrupted', receipt=None))

    def test_offered_key_gets_the_neuralwatt_lane_where_today_parks_on_credit(self):
        self.spend_go()
        # Without the key the same acquire does what it did on 11-19: MiMo parks on OpenRouter's credit
        # block, and so does DeepSeek (its free lane runs on the quota-blocked Go accounts); GLM falls to its
        # anonymous free lane.
        for model, nw, old in ((MIMO, 'neuralwatt/mimo-v2.6-pro', ('wait', None, 'openrouter-key', 'credit')),
                               (GLM, 'neuralwatt/glm-5.3-flash', ('lease', 'opencode/glm-5.3-flash-free', None, None)),
                               (DEEPSEEK, NW_DEEPSEEK, ('wait', None, 'openrouter-key', 'credit'))):
            with self.subTest(model=model):
                lease = self.acquire(model)
                self.assertEqual((lease['kind'], lease['route'], lease['account'], lease['pool'], lease['billing']),
                                 ('lease', nw, 'neuralwatt-key', 'neuralwatt-key', 'paid'))
                self.assertTrue(router.valid_maximum(lease) and lease['price_source'].startswith('neuralwatt:'))
                result = self.acquire(model, OLD)
                self.assertEqual((result['kind'], result['route'] if result['kind'] == 'lease' else None,
                                  result['account'], result.get('reason')), old)

    def test_a_caller_without_a_chain_never_gets_a_lane_it_does_not_know(self):
        # neuralwatt-first, cross-version: a 3dfdde3c worker offers the key but its DeepSeek chain has no NW
        # lane, so it would reject that lease as invalid and replay it, holding a Neuralwatt seat each time.
        self.spend_go()
        request = dict(LEGACY['request'], id=uuid.uuid4().hex, deadline=self.now + 86400)
        self.assertNotIn('chain', request)
        self.assertIn('neuralwatt-key', request['accounts'])
        self.assertEqual([r for r in router.chain(request['model']) if r not in router.LATE_ROUTES], list(DEEPSEEK_3DFDDE3C))
        self.assertNotIn(NW_DEEPSEEK, DEEPSEEK_3DFDDE3C)
        # LATE_ROUTES is complete: every chain minus it is exactly what a chainless caller knows. A lane added to
        # any chain without LATE_ROUTES would hand old workers a lease they reject (new-neuralwatt-3).
        self.assertEqual(tuple(tuple(r for r in c if r not in router.LATE_ROUTES) for c in router.CHAINS), CHAINS_3DFDDE3C)
        legacy = self.store.rpc('acquire', request)
        self.assertNotEqual(legacy.get('route'), NW_DEEPSEEK)
        # The same request from this release (it sends its chain) gets the lane.
        self.assertEqual(self.acquire(request['model'], request['accounts'], role=request['role'])['route'], NW_DEEPSEEK)
        # A 3dfdde3c caller still gets the Neuralwatt lanes it knows.
        mimo = self.store.rpc('acquire', dict(request, id=uuid.uuid4().hex, model=MIMO))
        self.assertEqual((mimo['kind'], mimo['route']), ('lease', 'neuralwatt/mimo-v2.6-pro'))

    def test_a_waiting_legacy_caller_does_not_queue_ahead_on_a_lane_it_cannot_take(self):
        self.spend_go()
        legacy = self.store.rpc('acquire', dict(LEGACY['request'], id=uuid.uuid4().hex, deadline=self.now + 86400))
        self.assertEqual((legacy['kind'], legacy['reason']), ('wait', 'credit'))   # queued: no lane it knows is open
        lease = self.acquire(MIMO)
        self.assertEqual((lease['kind'], lease['route']), ('lease', 'neuralwatt/mimo-v2.6-pro'))

    def test_the_admission_carries_the_callers_chain(self):
        sent = []
        def rpc(operation, data):
            sent.append(data); return dict(kind='wait', reason='credit', retry_after=self.now + 900, route=DEEPSEEK, account=None)
        case = type('Case', (), dict(card={'roles': {'stress_tester': {'model': DEEPSEEK}}}))()
        with patch.object(router, '_rpc', rpc):
            router._admit('stress_tester', case, self.now + 3600, uuid.uuid4().hex, router.ACCOUNTS)
        self.assertEqual(sent[0]['chain'], list(router.CHAINS[0]))
        self.assertEqual(sent[0]['chain'][1], NW_DEEPSEEK)
        for bad in ('x', [1], ['a b'], ['x/y'] * 17):
            with self.assertRaisesRegex(ValueError, 'invalid chain'):
                self.store.rpc('acquire', dict(LEGACY['request'], id=uuid.uuid4().hex, deadline=self.now + 86400, chain=bad))

    def burst(self, **config):
        # The live config: neuralwatt-key capacity 3 (Basic's guaranteed seats); burst 6 when the provider has room.
        self.store = router.Store(self.store.path, clock=lambda: self.now, capacities={'neuralwatt-key': 3}, **config)
        self.spend_go()
        return lambda: self.store.rpc('capacity', {'route': 'neuralwatt/mimo-v2.6-pro'})['slots']

    def refuse(self, lease, reason=None):
        # Neuralwatt's concurrency 429 as the worker classifies it (or another reason), published before its
        # seat is freed (model_runtime).
        failure = budget.classify_provider_failure(CONCURRENT['body']['error']['message'], lease['route'],
                                                   status_code=CONCURRENT['status'])
        self.store.rpc('observe', dict(lease_id=lease['lease_id'], reason=reason or failure['reason'],
                                       observation_id=lease['lease_id'] + ':failure'))
        self.store.rpc('finish', dict(lease_id=lease['lease_id'], outcome='interrupted', receipt=None))

    def test_a_refusal_above_the_neuralwatt_floor_drops_to_the_floor_without_blocking(self):
        for reason in (None, 'quota'):   # None: the real concurrency 429, classified `rate`
            with self.subTest(reason=reason):
                self.setUp()
                slots = self.burst(burst_capacities={'neuralwatt-key': 6})
                leases = [self.acquire(m) for m in (MIMO, GLM, DEEPSEEK) * 2]
                self.assertEqual({(l['kind'], l['pool']) for l in leases}, {('lease', 'neuralwatt-key')})
                self.assertEqual(slots(), 0)
                self.refuse(leases[5], reason)   # six held: the burst ran out, not the plan
                health = self.store.rpc('status', {})['health']['neuralwatt-key']
                self.assertEqual((health.get('reason'), health.get('blocked_until', 0), health.get('failures', 0)), (None, 0, 0))
                self.assertEqual(health['burst_until'], self.now + router.BURST_COOLDOWN_SECONDS)
                self.assertEqual(slots(), 0)   # five held against the floor of three
                for lease in leases[:3]: self.store.rpc('finish', dict(lease_id=lease['lease_id'], outcome='done', receipt=None))
                self.assertEqual(slots(), 1)
                retry = self.acquire(DEEPSEEK)   # the refused call, on a floor seat
                self.assertEqual((retry['kind'], retry['pool']), ('lease', 'neuralwatt-key'))
                self.assertEqual(slots(), 0)
                self.now += router.BURST_COOLDOWN_SECONDS / 2
                for lease in (*leases[3:5], retry): self.store.rpc('renew', {'lease_id': lease['lease_id']})
                self.assertEqual(slots(), 0)
                self.now += router.BURST_COOLDOWN_SECONDS / 2
                self.assertEqual(slots(), 3)   # the burst is back: 6 less the three held

    def test_a_refusal_at_the_floor_still_blocks_the_pool(self):
        for config in ({'burst_capacities': {'neuralwatt-key': 6}}, {}):   # {}: no burst key, exactly as before
            with self.subTest(config=config):
                self.setUp()
                slots = self.burst(**config)
                leases = [self.acquire(m) for m in (MIMO, GLM, DEEPSEEK)]
                self.assertEqual(slots(), 3 if config else 0)
                self.refuse(leases[0])
                health = self.store.rpc('status', {})['health']['neuralwatt-key']
                self.assertEqual((health['reason'], health['blocked_until'], health['failures']), ('rate', self.now + 900, 1))
                self.assertNotIn('burst_until', health)
                self.assertEqual(slots(), 0)

    def test_a_peer_finishing_before_the_observe_still_counts_as_the_burst(self):
        # OpenCode retries a 429 before its final error event; a peer that finishes meanwhile leaves the
        # floor or fewer held when the worker observes. The pool was above its floor moments ago: no block.
        slots = self.burst(burst_capacities={'neuralwatt-key': 6})
        leases = [self.acquire(m) for m in (MIMO, GLM, DEEPSEEK, MIMO)]
        self.store.rpc('finish', dict(lease_id=leases[0]['lease_id'], outcome='done', receipt=None))
        self.now += 30
        self.refuse(leases[3])   # observed with three held
        health = self.store.rpc('status', {})['health']['neuralwatt-key']
        self.assertEqual((health.get('reason'), health.get('blocked_until', 0)), (None, 0))
        self.assertEqual(slots(), 1)   # capped at the floor: two held
        # A whole window at or below the floor: the next refusal is the plan's, and blocks as before.
        for _ in range(int(router.BURST_COOLDOWN_SECONDS / router.RENEW_SECONDS)):
            self.now += router.RENEW_SECONDS
            for lease in leases[1:3]: self.store.rpc('renew', {'lease_id': lease['lease_id']})
        self.now += 1
        self.refuse(leases[1])
        health = self.store.rpc('status', {})['health']['neuralwatt-key']
        self.assertEqual((health['reason'], health['blocked_until']), ('rate', self.now + 900))
        self.assertEqual(slots(), 0)

    def test_spent_credit_above_the_floor_still_blocks(self):
        # Only a rate or quota refusal is the burst's; a 402 is the wallet, whatever the seats held.
        slots = self.burst(burst_capacities={'neuralwatt-key': 6})
        leases = [self.acquire(m) for m in (MIMO, GLM, DEEPSEEK) * 2]
        self.refuse(leases[5], 'credit')
        health = self.store.rpc('status', {})['health']['neuralwatt-key']
        self.assertEqual((health['reason'], health['blocked_until']), ('credit', self.now + 900))
        self.assertNotIn('burst_until', health)
        self.assertEqual(slots(), 0)

    def test_an_edited_router_config_is_picked_up_without_a_restart(self):
        # A restart waits for zero calls in flight, which 12 live cases never reach: the lane keys reload.
        path = Path(self.store.path).with_name('router-approved-config.json')
        stamp = [1_000_000_000]
        def write(text):
            path.write_text(text); stamp[0] += 1; os.utime(path, ns=(stamp[0], stamp[0]))
        def edit(**changes):
            write(json.dumps(dict(json.loads(LIVE_CONFIG), **changes)))
        write(LIVE_CONFIG)
        live = json.loads(LIVE_CONFIG)
        self.store = router.Store(self.store.path, clock=lambda: self.now, capacities=live['capacities'],
                                  disabled_routes=live['disabled_routes'], config_path=path)   # as main() builds it
        slots = lambda: self.store.rpc('capacity', {'route': 'neuralwatt/mimo-v2.6-pro'})['slots']
        leases = [self.acquire(m) for m in (MIMO, GLM, DEEPSEEK)]   # Go and OpenRouter twins are disabled live
        self.assertEqual({l['route'].split('/')[0] for l in leases}, {'neuralwatt'})
        self.assertEqual(slots(), 0)
        edit(burst_capacities={'neuralwatt-key': 6})
        self.assertEqual(slots(), 3)
        edit(capacities=dict(live['capacities'], **{'neuralwatt-key': 4}))   # the floor too
        self.assertEqual(slots(), 1)
        edit(burst_capacities={'neuralwatt-key': 6}, disabled_routes=live['disabled_routes'] + ['neuralwatt/'])
        self.assertEqual(slots(), 0)
        self.assertEqual(self.acquire(MIMO)['kind'], 'wait')
        # An edit startup would refuse is logged by kind only and the running config kept, whole, until the
        # file changes again: even when its lane keys are valid.
        burst = {'neuralwatt-key': 6}
        for text in ('{"capacities": ', json.dumps(dict(live, burst_capacities={'neuralwatt-key': 2})),
                     json.dumps(dict(live, disabled_routes='opencode-go/')), '[]',
                     json.dumps(dict(live, burst_capacities={'neuralwatt-key': 5}, accounts=['bogus'])),
                     json.dumps(dict(live, burst_capacities={'neuralwatt-key': 5}, paid_ceiling_usd='not-a-number')),
                     json.dumps(dict(live, burst_capacities={'neuralwatt-key': 5}, database='/elsewhere.sqlite3'))):
            with self.subTest(text=text[:40]):
                edit(burst_capacities={'neuralwatt-key': 6})
                self.assertEqual(slots(), 3)
                log = io.StringIO()
                with redirect_stderr(log):
                    write(text)
                    self.assertEqual(slots(), 3)
                    self.assertEqual(slots(), 3)
                self.assertEqual(log.getvalue().count('router config not reloaded, keeping the running one'), 1)
                self.assertNotIn('neuralwatt-key', log.getvalue())
                with self.assertRaises(Exception):   # what startup does with the same file
                    config = json.loads(text)
                    router.config_lanes(config); router.production_database(config)
                    router.Store(Path(self.store.path).with_name('startup.sqlite3'), accounts=config['accounts'],
                                 paid_ceiling_usd=config.get('paid_ceiling_usd'))
        path.unlink()
        with redirect_stderr(io.StringIO()):
            self.assertEqual(slots(), 3)
        log = io.StringIO()
        with redirect_stderr(log):
            write(LIVE_CONFIG)   # back to the live file: no burst key, the floor of 3 is all
            self.assertEqual(slots(), 0)
        self.assertEqual(log.getvalue(), 'router config reloaded\n')
        # A ceiling below the spending the router has booked is refused at startup, so on reload too.
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute("INSERT INTO paid_requests (id,lease_id,route,profile,hold,charge,state,settled_at) "
                       "VALUES ('x','y','r','{}',?,?,'reconciled',?)", (10**9, 10**9, self.now))   # $1 booked
        log = io.StringIO()
        with redirect_stderr(log):
            edit(burst_capacities=burst, paid_ceiling_usd='0.5')
            self.assertEqual(slots(), 0)
        self.assertIn('not reloaded', log.getvalue())
        with redirect_stderr(io.StringIO()):
            edit(burst_capacities=burst, paid_ceiling_usd='1')   # covers it: reloads
            self.assertEqual(slots(), 3)

    def test_a_burst_capacity_below_the_floor_or_not_an_int_is_refused(self):
        for burst in ({'neuralwatt-key': 2}, {'neuralwatt-key': 101}, {'neuralwatt-key': '6'}, {'neuralwatt': 6}):
            with self.subTest(burst=burst), self.assertRaisesRegex(ValueError, 'invalid burst capacity'):
                router.Store(self.store.path, capacities={'neuralwatt-key': 3}, burst_capacities=burst)

    def test_the_off_switch_keeps_an_offered_key_on_the_openrouter_twin(self):
        # Rollout step 3 ships the lane off (disabled_routes); the key offered changes nothing until step 6.
        self.store = router.Store(self.store.path, clock=lambda: self.now, capacities={'neuralwatt-key': 8},
                                  disabled_routes=('neuralwatt/',))   # the router config path (main())
        self.spend_go()
        wait = self.acquire(MIMO)
        self.assertEqual((wait['kind'], wait['account'], wait['reason']), ('wait', 'openrouter-key', 'credit'))

    def test_walled_roles_take_the_neuralwatt_lane_first_then_the_twin_and_never_go_or_free(self):
        # neuralwatt-walled-gate (founder 2026-11-20): on 11-19's state (Go on quota, OpenRouter credit-blocked)
        # a walled calibrator used to park on credit. Neuralwatt now has a gate for it, so it leases Neuralwatt
        # first; when Neuralwatt's credit runs out it waits on the OpenRouter twin. A lane with no gate (Go plan,
        # free) is still never leased to it.
        for model, nw, twin in ((GLM, 'neuralwatt/glm-5.3-flash', 'openrouter/z-ai/glm-5.3-flash'),
                                (DEEPSEEK, NW_DEEPSEEK, 'openrouter/deepseek/deepseek-v4.1-flash')):
            with self.subTest(model=model):
                self.setUp(); self.spend_go()
                excluded = router.ungated_lanes(model, router.ACCOUNTS)
                self.assertNotIn('neuralwatt-key/' + nw, excluded)
                rows = router.routes(model, router.ACCOUNTS)
                ungated = {r['pool'] + '/' + r['route'] for r in rows if r['route'] in FREE_ROUTES or r['route'] in GO_ROUTES}
                self.assertTrue(ungated and set(excluded) == ungated)
                lease = self.acquire(model, role='easy_calibrator', excluded=excluded)
                self.assertEqual((lease['kind'], lease['route'], lease['account']), ('lease', nw, 'neuralwatt-key'))
                self.store.rpc('observe', dict(lease_id=lease['lease_id'], reason='credit', observation_id=lease['lease_id'] + ':credit'))
                self.store.rpc('finish', dict(lease_id=lease['lease_id'], outcome='interrupted', receipt=None))
                wait = self.acquire(model, role='easy_calibrator', excluded=excluded)
                self.assertEqual((wait['kind'], wait['reason'], wait['route']), ('wait', 'credit', twin))
                # Unwalled, the same state still hands out a lane with no gate: only the exclusion keeps it away.
                free = self.acquire(model, role='writer')
                if model == GLM: self.assertEqual((free['kind'], free['route']), ('lease', 'opencode/glm-5.3-flash-free'))

    def test_old_accounts_see_no_neuralwatt_lane_anywhere(self):
        for chain in router.CHAINS:
            for model in chain:
                rows = router.routes(model, OLD)
                self.assertFalse([r for r in rows if r['route'] in NW_ROUTES or r['pool'] == 'neuralwatt-key'])
                self.assertFalse([l for l in router.ungated_lanes(model, OLD) if 'neuralwatt' in l])
                # The same lanes, in the same order, as the chain without its Neuralwatt member.
                self.assertEqual([r['route'] for r in rows if r['account'] != 'opencode-go-key-2'],
                                 [r for r in chain if r not in NW_ROUTES])


class Maximum(unittest.TestCase):
    def test_a_twin_priced_nw_maximum_is_byte_identical_to_3dfdde3c(self):
        # A worker on 3dfdde3c validates leases from this router: MiMo and GLM must not move by one byte.
        self.assertEqual(set(NW_TWINS) - set(NW_OWN_PRICES), {'neuralwatt/mimo-v2.6-pro', 'neuralwatt/glm-5.3-flash'})
        self.assertEqual(nw_maximum('neuralwatt/mimo-v2.6-pro'), dict(max_usd=1.7104906, max_input_tokens=3932162, max_output_tokens=1966081,
            price_source='neuralwatt:mimo-v2.6-pro:twin=token_prices:2026-10-30:openrouter:xiaomi/mimo-v2.6-pro:xiaomi/fp8:0.435,0.0036,0.87:joint-gate-v1'))
        self.assertEqual(nw_maximum('neuralwatt/glm-5.3-flash'), dict(max_usd=1.2582918, max_input_tokens=8388612, max_output_tokens=2516583,
            price_source='neuralwatt:glm-5.3-flash:twin=token_prices:2026-11-06:openrouter:z-ai/glm-5.3-flash:deepinfra/fp4:0.15,0.03,0.5:joint-gate-v1'))
        for route in set(NW_TWINS) - set(NW_OWN_PRICES):
            twin = NW_TWINS[route]
            theirs = openrouter_gate_maximum(twin)
            self.assertEqual(nw_maximum(route), dict(theirs, price_source='neuralwatt:' + route.partition('/')[2] + ':twin=' + theirs['price_source']))
            self.assertEqual(runtime_prices(route), runtime_prices(twin))
            tokens = dict(input=1000, output=200, reasoning=50, cache=dict(read=40000, write=0))
            self.assertEqual(go_step_cost(route, tokens), go_step_cost(twin, tokens))
        self.assertEqual(nw_request_worst('neuralwatt/mimo-v2.6-pro'), Decimal('0.5701632'))
        self.assertEqual(nw_request_worst('neuralwatt/glm-5.3-flash'), Decimal('0.6291454'))
        self.assertIsNone(nw_maximum('openrouter/xiaomi/mimo-v2.6-pro'))

    def test_deepseek_is_bounded_and_booked_at_neuralwatts_own_list(self):
        listed = {m['id']: m for m in CATALOG['response']['data']}['deepseek-v4.1-flash']
        pricing = listed['metadata']['pricing']
        own = tuple(Decimal(str(pricing[k])) for k in ('input_per_million', 'cached_input_per_million', 'output_per_million'))
        self.assertEqual(own, tuple(map(Decimal, NW_OWN_PRICES[NW_DEEPSEEK])))
        twin = NW_TWINS[NW_DEEPSEEK]
        self.assertTrue(all(o >= t for o, t in zip(own, map(Decimal, GATED_OPENROUTER[twin]['prices']))))   # why it has its own
        self.assertEqual(runtime_prices(NW_DEEPSEEK), dict(input=0.15, output=0.6, cache_read=0.015, cache_write=0))
        tokens = dict(input=1000, output=200, reasoning=50, cache=dict(read=40000, write=0))
        self.assertAlmostEqual(go_step_cost(NW_DEEPSEEK, tokens), (1000 * 0.15 + 250 * 0.6 + 40000 * 0.015) / 1e6, places=15)
        self.assertGreater(go_step_cost(NW_DEEPSEEK, tokens), go_step_cost(twin, tokens))
        maximum = nw_maximum(NW_DEEPSEEK)
        self.assertEqual(maximum, dict(max_usd=1.572865, max_input_tokens=10485766, max_output_tokens=2621441,
            price_source='neuralwatt:deepseek-v4.1-flash:own=token_prices:2026-11-20:neuralwatt:deepseek-v4.1-flash:standard:0.15,0.015,0.6:joint-gate-v1'))
        self.assertEqual(router.route_maximum(NW_DEEPSEEK), maximum)
        # One request: the bound holds because OpenCode sends max_tokens <= limit.output (N8); Neuralwatt
        # itself allows 393216 output tokens.
        worst = nw_request_worst(NW_DEEPSEEK)
        self.assertEqual(worst, Decimal('0.786432'))
        self.assertEqual((listed['max_model_len'], listed['metadata']['limits']['max_output_tokens']), (1048560, 393216))
        self.assertGreaterEqual(worst, (listed['max_model_len'] * own[0] + 32768 * own[2]) / 1_000_000)
        funded = router.funded_maximum(NW_DEEPSEEK, '12.5')
        self.assertEqual(funded['max_usd'], 12.5)
        self.assertTrue(router.valid_maximum(dict(route=NW_DEEPSEEK, **funded)))
        self.assertFalse(router.valid_maximum(dict(route=NW_DEEPSEEK, **dict(funded, price_source=funded['price_source'].replace(':own=', ':twin=')))))

    def test_saved_price_records_match_and_name_no_speed_or_flex_lane(self):
        self.assertIn('never costs more than its listed token price', PRICES['pricing_page']['statement'])
        self.assertIn('no standard or flex request costs more than its listed token price', CATALOG['pricing_page']['statement'])
        old = {m['id']: m for m in PRICES['models']}
        new = {m['id']: m for m in CATALOG['response']['data']}
        for route, twin in NW_TWINS.items():
            name = route.partition('/')[2]
            # The provider-block id is the base model: never a -speed lane (priced above list) nor -flex.
            self.assertFalse(name.endswith(('-speed', '-flex')))
            pricing = new[name]['metadata']['pricing']
            self.assertEqual(pricing['service_tier'], 'standard')
            self.assertEqual((new[name]['max_model_len'], new[name]['metadata']['limits']['max_context_length']), (1048560, 1048560))
            listed = tuple(Decimal(str(pricing[k])) for k in ('input_per_million', 'cached_input_per_million', 'output_per_million'))
            self.assertEqual(listed, tuple(map(Decimal, NW_OWN_PRICES.get(route, GATED_OPENROUTER[twin]['prices']))))
            if route in NW_OWN_PRICES: continue
            pin = tuple(map(Decimal, GATED_OPENROUTER[twin]['prices']))
            self.assertEqual(tuple(Decimal(PRICES['pricing_page']['listed_per_million'][name][k]) for k in ('input', 'cached', 'output')), pin)
            pricing = old[name]['metadata']['pricing']
            self.assertEqual(tuple(Decimal(str(pricing[k])) for k in ('input_per_million', 'cached_input_per_million', 'output_per_million')), pin)
            self.assertEqual(pricing['service_tier'], 'standard')


if __name__ == '__main__':
    unittest.main()
