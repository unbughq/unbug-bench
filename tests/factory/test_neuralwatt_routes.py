"""Neuralwatt lanes for MiMo and GLM (docs/designs/neuralwatt-routes.md, items 1-2), on real router state.

router-health-20261119.json holds the router's health rows (health table only, no keys) as read on the
control VM on 2026-11-19, from factory.before-force-lift-20261119.sqlite3: OpenRouter credit-blocked at
$4.38, both Go plans on weekly quota. The Go rows' backoff had lapsed (blocked_until 0), so each acquire
first retries Go; the replay observes Go's quota answer as the router did that day. Reproduce on the VM with
  sqlite3 -json factory.before-force-lift-20261119.sqlite3 'SELECT pool, value FROM health'
(each value parsed as JSON, keyed by pool).
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'factory'))
from contextlib import closing
from decimal import Decimal
import gzip
import json
import sqlite3
import tempfile
import unittest
import uuid
import model_router as router
from token_prices import (GATED_OPENROUTER, NW_TWINS, NW_ROUTES, go_step_cost, nw_maximum, nw_request_worst,
                          openrouter_gate_maximum, runtime_prices)

FIXTURES = Path(__file__).with_name('fixtures')
HEALTH = json.loads((FIXTURES / 'router-health-20261119.json').read_text())
PRICES = json.loads(gzip.decompress((FIXTURES / 'neuralwatt-price-record-20261119.json.gz').read_bytes()))
# Real saved roles: e15450's MiMo reviewer, and GLM as every 2026-10 card saved it (walled easy_calibrator).
# No saved card has a GLM role outside the wall, so the unwalled GLM acquire reuses that saved model id.
MIMO = json.loads((FIXTURES / 'e15450-collected-card.json').read_text())['roles']['reviewer']['model']
GLM = next(c['card']['roles']['easy_calibrator']['model']
           for c in json.loads(gzip.decompress((FIXTURES / '20261029-real-public-cards.json.gz').read_bytes())) if 'roles' in c['card'])
OLD = router.ACCOUNTS[:-1]   # what a caller without the Neuralwatt key offers (and every caller before it)


class RealStateRoutes(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.now = HEALTH['openrouter-key']['observed_at'] + 60
        self.store = router.Store(Path(tmp.name) / 'router.sqlite', clock=lambda: self.now, capacities={'neuralwatt-key': 8})
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.executemany('INSERT INTO health VALUES (?,?)', [(k, json.dumps(v)) for k, v in HEALTH.items()])
        self.assertEqual((MIMO, GLM), ('openrouter/xiaomi/mimo-v2.6-pro', 'opencode/glm-5.3-flash-free'))

    def acquire(self, model, accounts=router.ACCOUNTS, role='writer', excluded=()):
        return self.store.rpc('acquire', dict(id=uuid.uuid4().hex, model=model, accounts=list(accounts), role=role,
            deadline=self.now + 86400, paid_protocol=1, capacity_protocol=1, excluded_lanes=list(excluded)))

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
        # block, GLM falls to its anonymous free lane.
        for model, twin, old in ((MIMO, 'neuralwatt/mimo-v2.6-pro', ('wait', None, 'openrouter-key', 'credit')),
                                 (GLM, 'neuralwatt/glm-5.3-flash', ('lease', 'opencode/glm-5.3-flash-free', None, None))):
            lease = self.acquire(model)
            self.assertEqual((lease['kind'], lease['route'], lease['account'], lease['pool'], lease['billing']),
                             ('lease', twin, 'neuralwatt-key', 'neuralwatt-key', 'paid'))
            self.assertTrue(router.valid_maximum(lease) and lease['price_source'].startswith('neuralwatt:'))
            result = self.acquire(model, OLD)
            self.assertEqual((result['kind'], result['route'] if result['kind'] == 'lease' else None,
                              result['account'], result.get('reason')), old)

    def test_the_off_switch_keeps_an_offered_key_on_the_openrouter_twin(self):
        # Rollout step 3 ships the lane off (disabled_routes); the key offered changes nothing until step 6.
        self.store = router.Store(self.store.path, clock=lambda: self.now, capacities={'neuralwatt-key': 8},
                                  disabled_routes=('neuralwatt/',))   # the router config path (main())
        self.spend_go()
        wait = self.acquire(MIMO)
        self.assertEqual((wait['kind'], wait['account'], wait['reason']), ('wait', 'openrouter-key', 'credit'))

    def test_walled_roles_never_take_the_neuralwatt_lane(self):
        self.spend_go()
        excluded = router.ungated_lanes(GLM, router.ACCOUNTS)
        self.assertIn('neuralwatt-key/neuralwatt/glm-5.3-flash', excluded)
        wait = self.acquire(GLM, role='easy_calibrator', excluded=excluded)
        self.assertEqual((wait['kind'], wait['reason'], wait['route']), ('wait', 'credit', 'openrouter/z-ai/glm-5.3-flash'))

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
    def test_nw_maximum_is_the_twins_with_its_own_source(self):
        for route, twin in NW_TWINS.items():
            theirs, ours = openrouter_gate_maximum(twin), nw_maximum(route)
            self.assertEqual(ours, dict(theirs, price_source='neuralwatt:' + route.partition('/')[2] + ':twin=' + theirs['price_source']))
            self.assertEqual(router.route_maximum(route), ours)
            funded = router.funded_maximum(route, '5')
            self.assertEqual(funded['max_usd'], 5.0)
            self.assertTrue(router.valid_maximum(dict(route=route, **funded)))
            self.assertFalse(router.valid_maximum(dict(route=route, **dict(funded, max_usd=50.0))))
            self.assertEqual(runtime_prices(route), runtime_prices(twin))
            tokens = dict(input=1000, output=200, reasoning=50, cache=dict(read=40000, write=0))
            self.assertEqual(go_step_cost(route, tokens), go_step_cost(twin, tokens))
        self.assertIsNone(nw_maximum('openrouter/xiaomi/mimo-v2.6-pro'))
        self.assertEqual(nw_request_worst('neuralwatt/mimo-v2.6-pro'), Decimal('0.5701632'))
        self.assertEqual(nw_request_worst('neuralwatt/glm-5.3-flash'), Decimal('0.6291454'))

    def test_saved_price_record_matches_the_twin_pins(self):
        self.assertIn('never costs more than its listed token price', PRICES['pricing_page']['statement'])
        listed = PRICES['pricing_page']['listed_per_million']
        models = {m['id']: m for m in PRICES['models']}
        for route, twin in NW_TWINS.items():
            name = route.partition('/')[2]
            pin = tuple(map(Decimal, GATED_OPENROUTER[twin]['prices']))
            self.assertEqual(tuple(Decimal(listed[name][k]) for k in ('input', 'cached', 'output')), pin)
            pricing = models[name]['metadata']['pricing']
            self.assertEqual(tuple(Decimal(str(pricing[k])) for k in ('input_per_million', 'cached_input_per_million', 'output_per_million')), pin)
            self.assertEqual(pricing['service_tier'], 'standard')   # list price, not a speed lane's
            self.assertEqual((models[name]['max_model_len'], models[name]['metadata']['limits']['max_context_length']), (1048560, 1048560))


if __name__ == '__main__':
    unittest.main()
