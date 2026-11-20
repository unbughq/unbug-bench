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


def admit(store, model=MINIMAX, identity=None, protocol=True, accounts=None):
    # The paid protocol's own tests: without the Go and Neuralwatt accounts a chain starts at OpenRouter (founder 2026-11-09).
    data = dict(id=identity or uuid.uuid4().hex, model=model, accounts=accounts or [a for a in router.ACCOUNTS if not a.startswith(('opencode-go', 'neuralwatt'))],
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

    def test_a_paid_request_reads_the_cached_balance_and_still_counts_every_hold_since(self):
        """19 November: each paid_reserve read /credits inline; on a CPU-bound control VM that read pushed requests
        past the 4 s rule and 16 calls ended on one refused request. The background pass reads it instead."""
        reads = []
        def provider(): reads.append(1); time.sleep(.5); return Decimal('.69')   # three $0.23 holds
        self.store.credit_reader = provider
        self.store.refresh_credit()
        self.assertEqual(len(reads), 1)
        lease = admit(self.store)
        usage = dict(prompt_tokens=1000000, completion_tokens=900000)   # the whole $0.23 window
        for _ in range(2):
            started = time.monotonic()
            data, result = self.reserve(lease)
            self.assertTrue(result['granted']); self.assertLess(time.monotonic() - started, .5)
            self.assertTrue(self.store.rpc('paid_settle', data | {'usage': usage})['settled'])
            self.now[0] += 50                      # still fresh; the provider has not shown these charges
        self.assertTrue(self.reserve(lease)[1]['granted'])
        self.assertEqual(len(reads), 1)            # no provider round trip on the request path
        # The cached $0.69 never pays for a fourth: every hold granted since the read counts against it.
        # A refusal parks the case, so it is confirmed with one live read first.
        self.assertEqual(self.reserve(lease)[1], dict(granted=False, reason='credit'))
        self.assertEqual(len(reads), 2)
        self.assertEqual(self.status()['total_usd'], '0.690000000')

    def test_a_stale_or_missing_cached_balance_is_read_live(self):
        reads = []
        self.store.credit_reader = lambda: reads.append(1) or Decimal('11.63')
        lease = admit(self.store)
        self.assertTrue(self.reserve(lease)[1]['granted']); self.assertEqual(len(reads), 1)   # never refreshed
        self.store.refresh_credit(); self.assertEqual(len(reads), 2)
        self.assertTrue(self.reserve(lease)[1]['granted']); self.assertEqual(len(reads), 2)
        self.now[0] += router.CREDIT_FRESH_SECONDS + 1
        self.assertTrue(self.reserve(lease)[1]['granted']); self.assertEqual(len(reads), 3)
        self.store.credit_reader = lambda: None    # a failed background read keeps nothing new
        self.store.refresh_credit()
        self.assertEqual(self.reserve(lease)[1], dict(granted=False, reason='credit'))   # live read, unknown: refused

    def test_the_background_pass_refreshes_the_balance_before_reconciling(self):
        stopped, seen = threading.Event(), []
        self.store.reconcile = lambda **kw: (seen.append(getattr(self.store, 'balance', None)), stopped.set())
        thread = threading.Thread(target=router.reconcile_forever, args=(self.store, stopped), kwargs=dict(interval=.01), daemon=True)
        thread.start(); thread.join(5); stopped.set()
        self.assertEqual(seen, [(router._nano('11.63'), self.now[0])])

    def test_a_cached_balance_counts_charges_from_before_its_own_read_not_before_now(self):
        """The provider's balance may lag our charges by CREDIT_OVERLAP (900 s), counted back from when the
        balance was read. A charge settled 850 s before the read is still outstanding 100 s later."""
        usage = dict(prompt_tokens=1000000, completion_tokens=900000)   # the whole $0.23 window
        data, _ = self.reserve(admit(self.store))
        self.assertTrue(self.store.rpc('paid_settle', data | {'usage': usage})['settled'])
        self.now[0] += 850
        self.credit = Decimal('.46')               # the balance does not show that $0.23 yet
        self.store.refresh_credit()
        self.now[0] += 100                         # fresh, but the charge is now 950 s old
        self.credit = Decimal('.23')               # by now the provider shows it (a live read would see this)
        lease = admit(self.store)
        self.assertTrue(self.reserve(lease)[1]['granted'])   # cached $0.46 less the $0.23 still outstanding at the read
        self.assertEqual(self.reserve(lease)[1], dict(granted=False, reason='credit'))

    def test_a_short_cached_balance_is_confirmed_live_before_it_parks_anything(self):
        lease = admit(self.store)
        self.credit = Decimal('.1')
        self.store.refresh_credit()                # read before a top-up
        self.credit = Decimal('11.63')             # the operator tops up
        self.assertTrue(self.reserve(lease)[1]['granted'])
        self.assertTrue(self.credit_clear())       # no credit block from the old balance
        self.credit = Decimal('.1')
        self.store.refresh_credit()
        self.assertEqual(self.reserve(lease)[1], dict(granted=False, reason='credit'))   # really short: final
        self.assertFalse(self.credit_clear())

    def credit_clear(self):
        return router.credit_ready(self.path)   # what a case parked on router:credit polls

    def refused(self, model=MINIMAX, accounts=None):
        """A provider 402 on a running call: model_runtime observes it, then finishes the lease."""
        lease = admit(self.store, model, accounts=accounts)
        self.store.rpc('observe', dict(pool=None, healthy=False, observation_id=uuid.uuid4().hex,
                                       lease_id=lease.lease_id, reason='credit', reset_at=None))
        self.store.rpc('finish', dict(lease_id=lease.lease_id, outcome='interrupted', receipt=None))

    def test_a_low_credit_refusal_parks_the_pool_until_a_top_up_lifts_it_once(self):
        """The router's own pre-check refusal (the gate's 503 shared_paid_spend_wait) used to leave no
        trace: the case slept 15 minutes and tried again, and again, holding its worker."""
        self.credit = Decimal('.2299999999')          # below one request's $0.23 hold
        lease = admit(self.store)
        self.assertEqual(self.reserve(lease)[1], dict(granted=False, reason='credit'))
        self.store.rpc('finish', dict(lease_id=lease.lease_id, outcome='interrupted', receipt=None))
        self.assertFalse(self.credit_clear())          # the parked case keeps waiting...
        waiting = uuid.uuid4().hex                     # ...and no other call starts on the pool
        self.assertEqual(admit(self.store, identity=waiting)['reason'], 'credit')
        self.store.rpc('cancel', {'id': waiting})      # that call parks too (await_lease cancels its request)
        self.store.lift_credit()
        self.assertFalse(self.credit_clear())          # still short: nothing to wake for
        self.credit = Decimal('100')                   # the operator tops up
        self.store.lift_credit()
        self.assertTrue(self.credit_clear())
        lease = admit(self.store)
        self.assertTrue(self.reserve(lease)[1]['granted'])
        for _ in range(3):                             # it stays clear: one wake, not a loop of them
            self.store.lift_credit()
            self.assertTrue(self.credit_clear())

    def test_a_provider_402_block_lifts_on_a_top_up_after_its_backoff_and_backs_off_if_it_recurs(self):
        self.refused()
        self.store.lift_credit()
        self.assertFalse(self.credit_clear())          # inside its 15-minute backoff
        self.now[0] += 901
        self.credit = None                             # an unreadable balance never lifts it
        self.store.lift_credit()
        self.assertFalse(self.credit_clear())
        self.credit = Decimal('100')
        self.store.lift_credit()
        self.assertTrue(self.credit_clear())
        # The provider refuses again although the balance reads enough: the next lift waits twice as
        # long, so a reader that disagrees with the provider cannot wake the cases every minute.
        self.refused()
        self.now[0] += 901
        self.store.lift_credit()
        self.assertFalse(self.credit_clear())
        self.now[0] += 900
        self.store.lift_credit()
        self.assertTrue(self.credit_clear())

    def test_three_402s_despite_the_balance_stop_lifting_and_alert_until_the_operator_lifts(self):
        from durable.guard import router_spend
        self.credit = Decimal('100')
        for backoff in (901, 1801):
            self.refused()
            self.now[0] += backoff
            self.store.lift_credit()
            self.assertTrue(self.credit_clear())
        self.refused()                                 # the third refusal in a row with money there
        self.now[0] += 3601
        self.store.lift_credit()
        self.assertFalse(self.credit_clear())          # the key's own limit, most likely: no more wakes
        self.assertTrue(router_spend(self.path)[3])    # the guard's alert
        self.assertEqual(self.store.lift_credit(force=True), 'lifted')   # the operator, after fixing the key
        self.assertTrue(self.credit_clear())
        self.assertFalse(router_spend(self.path)[3])
        self.refused()                                 # a fresh count: one refusal backs off 15 minutes
        self.now[0] += 901
        self.store.lift_credit()
        self.assertTrue(self.credit_clear())

    def test_a_credit_block_on_another_pool_expires_like_a_402_and_never_stops_a_wake(self):
        """Only the paid pool's balance can be read, so a credit block anywhere else (an OpenCode
        402) must not park the paid pool's cases for good, nor last itself."""
        from durable.guard import router_clear
        go = ['opencode-go-key']
        self.refused('opencode-go/mimo-v2.6-pro', go)
        self.assertTrue(self.credit_clear())
        self.assertFalse(router_clear(self.path, now=self.now[0]))
        self.assertEqual(admit(self.store, 'opencode-go/mimo-v2.6-pro', accounts=go)['reason'], 'credit')
        self.now[0] += 901
        self.assertTrue(router_clear(self.path, now=self.now[0]))
        self.assertIsInstance(admit(self.store, 'opencode-go/mimo-v2.6-pro', accounts=go), router.Lease)

    def test_a_low_balance_block_never_wins_over_a_seat_wait_on_a_subscription_route(self):
        model, everyone = 'opencode-go/mimo-v2.6-pro', [a for a in router.ACCOUNTS if a != 'neuralwatt-key']   # a box without the key
        seats = [admit(self.store, model, accounts=everyone) for _ in range(2)]
        self.assertEqual({l.pool for l in seats}, {'opencode-go-key', 'opencode-go-key-2'})
        self.credit = Decimal('.2')
        paid = admit(self.store, model, accounts=everyone)
        self.assertEqual(paid.pool, 'openrouter-key')
        self.assertFalse(self.reserve(paid)[1]['granted'])   # the paid pool is now credit-blocked
        self.store.rpc('finish', dict(lease_id=paid.lease_id, outcome='interrupted', receipt=None))
        self.assertEqual(admit(self.store, model, accounts=everyone)['reason'], 'rate')   # a Go seat frees soon

    def margin(self):   # what a lift needs above the holds in flight: the margin and one dearest call
        return router.LIFT_MARGIN_USD + Decimal(max(map(router._hold, GATED_OPENROUTER))) / 10**9

    def test_a_credit_block_lifts_on_a_margin_above_the_holds_not_when_holds_settle(self):
        """Goldfish 16 November (wake churn): headroom that grows only because holds settle must not
        wake every parked case into another refusal."""
        self.credit = Decimal('1')
        lease = admit(self.store)
        granted = [self.reserve(lease) for _ in range(4)]   # $0.92 of holds on a $1 balance
        self.assertTrue(all(result['granted'] for _, result in granted))
        self.assertFalse(self.reserve(lease)[1]['granted'])  # short: the pool blocks
        for data, _ in granted:                              # the calls finish cheaply: holds near zero
            self.assertTrue(self.store.rpc('paid_settle', data | {'usage': dict(prompt_tokens=1000, completion_tokens=1000)})['settled'])
        self.store.lift_credit()
        self.assertFalse(self.credit_clear())
        self.now[0] += 901                                   # past the window: nothing in flight
        self.credit = self.margin()                          # a top-up to $5 and one call
        self.assertEqual(self.store.lift_credit(), 'lifted')
        self.assertTrue(self.credit_clear())

    def test_a_stale_high_balance_reading_never_blocks_a_lift(self):
        self.credit = Decimal('100')
        self.assertTrue(self.reserve(admit(self.store))[1]['granted'])   # the router last read $100
        self.now[0] += 901
        self.refused()                                       # a 402: the balance was really gone
        self.now[0] += 901
        self.credit = Decimal('50')                          # the top-up, below that stale reading
        self.assertEqual(self.store.lift_credit(), 'lifted')

    def test_a_429_on_a_call_in_flight_never_ends_a_credit_block(self):
        self.credit = Decimal('100')
        other = admit(self.store)                            # in flight before the block
        lease = admit(self.store)
        self.credit = Decimal('.1')
        self.assertFalse(self.reserve(lease)[1]['granted'])  # short: the pool blocks
        for reason in ('rate', 'quota'):
            self.store.rpc('observe', dict(pool=None, healthy=False, observation_id=uuid.uuid4().hex,
                                           lease_id=other.lease_id, reason=reason, reset_at=None))
            self.assertFalse(self.credit_clear())            # no top-up, no wake

    def test_concurrent_402s_are_one_refusal_and_a_top_up_lifts_them(self):
        from durable.guard import router_spend
        self.credit = Decimal('50')
        leases = [admit(self.store) for _ in range(3)]
        for lease in leases:                                 # one run-out, three calls refused together
            self.store.rpc('observe', dict(pool=None, healthy=False, observation_id=uuid.uuid4().hex,
                                           lease_id=lease.lease_id, reason='credit', reset_at=None))
        self.assertFalse(router_spend(self.path)[3])
        self.now[0] += 4000
        self.credit = Decimal('500')
        self.assertEqual(self.store.lift_credit(), 'lifted')

    def test_low_balance_refusals_never_reach_the_cap(self):
        from durable.guard import router_spend
        for _ in range(4):                                   # under-funded top-ups: refused again each time
            self.credit = Decimal('.1')
            lease = admit(self.store)
            self.assertFalse(self.reserve(lease)[1]['granted'])
            self.store.rpc('finish', dict(lease_id=lease.lease_id, outcome='interrupted', receipt=None))
            self.credit = self.margin()
            self.assertEqual(self.store.lift_credit(), 'lifted')
        self.assertFalse(router_spend(self.path)[3])

    def test_an_operator_lift_says_why_it_did_not_lift(self):
        self.assertEqual(self.store.lift_credit(force=True), 'no_block')
        self.refused()
        self.credit = None
        self.assertIn('balance_unreadable', self.store.lift_credit(force=True))
        self.assertIn('OPENROUTER_API_KEY', self.store.lift_credit(force=True))
        self.credit = Decimal('.1')
        self.assertEqual(self.store.lift_credit(force=True), 'short_by $0.53')   # the dearest call, $0.63

    def test_rate_limits_never_count_toward_the_credit_refusal_cap(self):
        from durable.guard import router_spend
        self.credit = Decimal('100')
        for _ in range(4):                                   # 429s on the paid pool
            lease = admit(self.store)
            self.store.rpc('observe', dict(pool=None, healthy=False, observation_id=uuid.uuid4().hex,
                                           lease_id=lease.lease_id, reason='rate', reset_at=None))
            self.store.rpc('finish', dict(lease_id=lease.lease_id, outcome='interrupted', receipt=None))
            self.now[0] += 3601
        self.refused()                                       # the first credit refusal
        self.assertFalse(router_spend(self.path)[3])         # no "refused 3x" alert
        self.now[0] += 901                                   # one refusal's backoff
        self.assertEqual(self.store.lift_credit(), 'lifted')
        self.assertTrue(self.credit_clear())

    def test_unreadable_books_read_as_no_credit_block(self):
        """On entry and on wake a case checks only for the block; books it cannot read are no block
        (it keeps its worker and its short sleep, as before)."""
        self.assertTrue(router.credit_ready(Path(self.tmp.name) / 'missing.sqlite'))
        garbage = Path(self.tmp.name) / 'garbage.sqlite'
        garbage.write_bytes(b'not a database' * 100)
        self.assertTrue(router.credit_ready(garbage))
        self.refused()
        self.assertFalse(self.credit_clear())

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
        # The refusal blocked the pool at this balance; only a top-up or the operator lifts it.
        self.assertEqual(self.store.lift_credit(force=True), 'lifted')
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

    def test_a_call_the_ceiling_cannot_fund_is_refused_before_it_starts(self):
        """Nov 6-11: calls past the ceiling were leased, started, then refused at their first request."""
        self.store = router.Store(self.path, clock=lambda: self.now[0], capacities={'openrouter-key': 100},
                                  credit_reader=lambda: self.credit, paid_ceiling_usd='.5')
        running = admit(self.store)
        for _ in range(2): self.assertTrue(self.reserve(running)[1]['granted'])   # $0.46 of $0.50
        identity = uuid.uuid4().hex
        refused = admit(self.store, identity=identity)
        self.assertEqual((refused['kind'], refused['reason']), ('wait', 'credit'))
        self.assertGreater(refused['retry_after'], self.now[0])
        self.store = router.Store(self.path, clock=lambda: self.now[0], capacities={'openrouter-key': 100},
                                  credit_reader=lambda: self.credit, paid_ceiling_usd='1')   # an operator raise
        self.assertIsInstance(admit(self.store, identity=identity), router.Lease)   # the waiting caller's retry

    def test_an_older_unfundable_request_does_not_block_a_fundable_one(self):
        """Near the ceiling a request for a dear route waits; a cheaper route in the same pool still leases."""
        self.store = router.Store(self.path, clock=lambda: self.now[0], capacities={'openrouter-key': 100},
                                  credit_reader=lambda: self.credit, paid_ceiling_usd='1')
        running = admit(self.store)
        for _ in range(2): self.assertTrue(self.reserve(running)[1]['granted'])   # $0.46: GLM's $0.63 hold no longer fits
        def acquire(model, identity):
            return self.store.rpc('acquire', dict(id=identity, model=model, accounts=['openrouter-key'], role='writer',
                deadline=self.now[0] + 3600, paid_protocol=1, excluded_lanes=['opencode-free/opencode/glm-5.3-flash-free']))
        older = acquire('openrouter/z-ai/glm-5.3-flash', 'a' * 32)
        self.assertEqual((older['kind'], older['reason']), ('wait', 'credit'))
        newer = acquire('openrouter/meta/muse-spark-1.3-contributor', 'b' * 32)   # $0.29 hold fits
        self.assertEqual((newer['kind'], newer['route']), ('lease', 'openrouter/meta/muse-spark-1.3-contributor'))

    def test_a_refused_request_still_records_the_balance_it_saw(self):
        lease = admit(self.store)
        self.assertTrue(self.reserve(lease)[1]['granted'])
        self.credit = Decimal('.1')
        self.assertFalse(self.reserve(lease)[1]['granted'])
        self.assertEqual(self.status()['available_credit_usd'], '0.100000000')   # the guard's low-credit alert reads this

    def test_a_request_is_charged_what_the_provider_reports(self):
        """A real MiniMax request of 7 November: 306,502 prompt tokens, mostly cached."""
        profile = {'prices': ['0.15', '0.015', '0.6'], 'context': 1048576, 'output': 524288}
        usage = {'prompt_tokens': 306502, 'completion_tokens': 558, 'cost': 0.00499362}
        self.assertEqual(router._paid_charge(profile, usage), 4993620)              # $0.004993620
        estimate = dict(usage); del estimate['cost']
        self.assertEqual(router._paid_charge(profile, estimate), 46310100)          # the old $0.0463101
        self.assertIsNone(router._paid_charge(profile, dict(usage, cost=1.0)))      # past its maximum: refused
        self.assertIsNone(router._paid_charge(profile, dict(usage, cost=-0.01)))

    def test_settled_spend_follows_the_provider_cost(self):
        self.credit = Decimal('100')
        data, result = self.reserve(admit(self.store))
        self.assertTrue(result['granted'])
        usage = dict(prompt_tokens=1000000, completion_tokens=900000, cost=0.05)   # the hold's full shape, cached
        self.assertTrue(self.store.rpc('paid_settle', data | {'usage': usage})['settled'])
        self.assertEqual(self.status()['total_usd'], '0.050000000')

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
        # Without the paid protocol a paid route is never leased; MiniMax's chain now leases its Go plan route.
        lease = admit(self.store, protocol=False, accounts=list(router.ACCOUNTS))
        self.assertEqual((lease.route, lease.billing), ('opencode-go/minimax-m3.1-flash', 'subscription'))
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

    def unknown_with_generation(self, generation=None):
        data, result = self.reserve(admit(self.store))
        self.assertTrue(result['granted'])
        extra = {} if generation is False else {'generation': generation}
        self.assertFalse(self.store.rpc('paid_settle', data | {'usage': None} | extra)['settled'])
        return data

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT id,charge,hold,state,generation FROM paid_requests ORDER BY rowid').fetchall()

    def test_unknown_call_settles_at_its_generation_cost(self):
        """10 November: 51 unconfirmed calls booked at their maximum; one GLM call that cost
        $0.0015 sat at $0.63. The provider's own report for the generation is the charge."""
        self.credit = Decimal('100')
        data = self.unknown_with_generation('gen-1762780000-Synthetic')
        self.assertEqual(self.status()['total_usd'], '0.230000000')
        asked = []
        reader = lambda g: asked.append(g) or (Decimal('0.0015'), 'minimax/minimax-m3.1-flash')
        result = self.store.reconcile(cost_reader=reader)
        self.assertEqual(asked, ['gen-1762780000-Synthetic'])
        self.assertEqual((result['generations'], result['released_usd']), (1, '0.228500000'))
        self.assertEqual(self.status()['total_usd'], '0.001500000')
        self.assertEqual(self.rows()[0][1:4], (1500000, 230000000, 'settled'))
        # Settled once: later passes neither ask again nor change it, and the worker cannot re-settle it.
        self.assertEqual(self.store.reconcile(cost_reader=reader)['generations'], 0)
        self.assertEqual(len(asked), 1)
        self.assertFalse(self.store.rpc('paid_settle', data | {'usage': dict(prompt_tokens=0, completion_tokens=0)})['settled'])
        self.assertEqual(self.status()['total_usd'], '0.001500000')

    def test_generation_reports_that_do_not_fit_keep_the_hold(self):
        self.credit = Decimal('100')
        self.unknown_with_generation('gen-other-model')
        self.unknown_with_generation('gen-too-dear')
        self.unknown_with_generation('gen-unread')
        self.unknown_with_generation('gen-raises')
        self.unknown_with_generation(None)
        self.unknown_with_generation(False)            # a gate from before this change
        replies = {'gen-other-model': (Decimal('0.001'), 'z-ai/glm-5'),
                   'gen-too-dear': (Decimal('0.2300000001'), 'minimax/minimax-m3.1-flash'),
                   'gen-unread': None}
        def reader(g):
            if g == 'gen-raises': raise OSError('synthetic sensitive provider message')
            return replies[g]
        self.assertEqual(self.store.reconcile(cost_reader=reader)['generations'], 0)
        self.assertEqual([r[3] for r in self.rows()], ['unknown'] * 6)
        self.assertEqual(self.status()['total_usd'], '1.380000000')
        self.assertEqual(self.status()['unknown_requests'], 6)

    def test_one_generation_settles_one_request(self):
        self.credit = Decimal('100')
        self.unknown_with_generation('gen-shared')
        self.unknown_with_generation('gen-shared')
        reader = lambda g: (Decimal('0.01'), 'minimax/minimax-m3.1-flash')
        self.assertEqual(self.store.reconcile(cost_reader=reader)['generations'], 1)
        self.assertEqual(sorted(r[3] for r in self.rows()), ['settled', 'unknown'])
        self.assertEqual(self.status()['total_usd'], '0.240000000')

    def test_zero_usage_generations_settle_at_the_dated_model_report(self):
        """11 November: mimo reviews answered with no usage. OpenRouter reports a generation's model
        by its dated permaslug, the exact slug check refused every one, and each stayed at its hold."""
        self.credit = Decimal('100')
        self.unknown_with_generation('gen-zero')
        self.unknown_with_generation('gen-charged')
        replies = {'gen-zero': (Decimal('0'), 'minimax/minimax-m3.1-flash-20261106'),
                   'gen-charged': (Decimal('0.0123'), 'minimax/minimax-m3.1-flash-20261106')}
        result = self.store.reconcile(cost_reader=replies.get)
        self.assertEqual(result['generations'], 2)
        self.assertEqual(sorted((r[4], r[1], r[3]) for r in self.rows()),
                         [('gen-charged', 12300000, 'settled'), ('gen-zero', 0, 'settled')])
        self.assertEqual(self.status()['total_usd'], '0.012300000')

    def test_a_lookalike_model_never_settles_a_row(self):
        self.credit = Decimal('100')
        for model in ('minimax/minimax-m3.1-flash-extended', 'minimax/minimax-m3.1-flash-2026110',
                      'minimax/minimax-m3.1-flash:free', 'xminimax/minimax-m3.1-flash', 'z-ai/glm-5.3-flash-20261106'):
            self.assertFalse(router.served_by(model, MINIMAX), model)
        self.unknown_with_generation('gen-lookalike')
        self.store.reconcile(cost_reader=lambda g: (Decimal('0'), 'minimax/minimax-m3.1-flash-extended'))
        self.assertEqual([r[3] for r in self.rows()], ['unknown'])

    def test_a_bounded_row_still_settles_at_its_generation_cost(self):
        """The ~$149 already bounded on 11 November: its generation report still decides the charge."""
        self.credit = Decimal('100')
        self.unknown_with_generation('gen-bounded')
        self.now[0] += 901
        self.store.reconcile(usage_reader=lambda: Decimal('0.2'))
        self.assertEqual([r[3] for r in self.rows()], ['reconciled'])
        self.store.reconcile(cost_reader=lambda g: (Decimal('0'), 'minimax/minimax-m3.1-flash-20261106'))
        self.assertEqual(self.rows()[0][1:4], (0, 230000000, 'settled'))
        self.assertEqual(self.status()['total_usd'], '0.000000000')

    def test_unreadable_generations_do_not_starve_later_rows(self):
        """Oldest-first, rows whose report never fits held all 25 places of every pass."""
        self.credit = Decimal('100')
        for i in range(30): self.unknown_with_generation('gen-dead-%d' % i)
        self.unknown_with_generation('gen-live')
        reader = lambda g: (Decimal('0'), 'minimax/minimax-m3.1-flash') if g == 'gen-live' else None
        for _ in range(20):
            if self.store.reconcile(cost_reader=reader)['generations']: break
        self.assertEqual([r[3] for r in self.rows() if r[4] == 'gen-live'], ['settled'])

    def test_invalid_generation_ids_are_refused(self):
        data, _ = self.reserve(admit(self.store))
        for bad in ('', 'gen-', 'not-a-generation', 'gen-' + 'a' * 121, 'gen-a/b', 7, True, ['gen-a']):
            with self.assertRaises(ValueError):
                self.store.rpc('paid_settle', data | {'usage': None, 'generation': bad})
        self.assertEqual(self.rows()[0][3], 'pending')

    def test_account_usage_bounds_old_unknown_holds(self):
        """Rows from before generation ids were recorded: the account's all-time usage, less the
        provider-reported costs of settled calls, is the most those unknown calls can have cost."""
        self.credit = Decimal('100')
        data, _ = self.reserve(admit(self.store))
        self.assertTrue(self.store.rpc('paid_settle', data | {'usage': dict(prompt_tokens=1000000, completion_tokens=0, cost=0.04)})['settled'])
        estimate, _ = self.reserve(admit(self.store))    # settled from tokens alone: an upper bound, not subtracted
        self.assertTrue(self.store.rpc('paid_settle', estimate | {'usage': dict(prompt_tokens=1000, completion_tokens=10)})['settled'])
        self.unknown_holds(10)                           # 10 x $0.23 = $2.30 booked
        self.assertEqual(self.status()['total_usd'], '2.340052000')
        # Inside the billing window the provider may not show them yet: nothing changes.
        self.assertEqual(self.store.reconcile(usage_reader=lambda: Decimal('0.10'))['bounded'], 0)
        self.now[0] += 901
        recent = self.unknown_with_generation(False)     # a fresh unknown call stays at its hold
        result = self.store.reconcile(usage_reader=lambda: Decimal('0.10'))
        self.assertEqual(result['bounded'], 10)
        # $0.10 account usage - $0.04 reported = $0.06 for the ten old unknown calls.
        rows = self.rows()
        old = [r for r in rows if r[3] == 'reconciled']
        self.assertEqual(len(old), 10)
        self.assertTrue(all(0 <= r[1] <= r[2] for r in old))
        self.assertEqual(sum(r[1] for r in old), 60000000)
        self.assertEqual([r[3] for r in rows if r[0] == recent['request_id']], ['unknown'])
        self.assertEqual(self.status()['total_usd'], '0.330052000')
        self.assertEqual(self.status()['reconciled_requests'], 10)
        self.assertEqual(self.status()['outstanding_usd'], '0.230000000')
        # A later, larger observation never raises a bound; a smaller one lowers it again.
        self.assertEqual(self.store.reconcile(usage_reader=lambda: Decimal('5'))['bounded'], 0)
        self.assertEqual(self.status()['total_usd'], '0.330052000')
        self.store.reconcile(usage_reader=lambda: Decimal('0.07'))
        self.assertEqual(sum(r[1] for r in self.rows() if r[3] == 'reconciled'), 30000000)
        # The guard's read of the books sees the same spend.
        from durable.guard import router_spend
        self.assertEqual(self.status()['total_usd'], '0.300052000')
        self.assertAlmostEqual(router_spend(self.path)[0], 0.300052)

    def test_account_usage_above_the_books_changes_nothing(self):
        self.unknown_holds(3)
        self.now[0] += 901
        before = self.rows()
        for reader in (lambda: Decimal('100'), lambda: None, lambda: Decimal('-1'), lambda: float('nan')):
            self.assertEqual(self.store.reconcile(usage_reader=reader)['bounded'], 0)
        def broken(): raise OSError('synthetic')
        self.store.reconcile(usage_reader=broken)
        self.assertEqual(self.rows(), before)

    def test_reconciled_spend_frees_the_ceiling(self):
        """The 10 November refusal: the ceiling was full of unknown holds the provider never charged."""
        self.store = router.Store(self.path, clock=lambda: self.now[0], capacities={'openrouter-key': 100},
                                  credit_reader=lambda: self.credit, paid_ceiling_usd='0.92')
        self.unknown_holds(4)                            # $0.92: the whole ceiling
        self.assertEqual(admit(self.store, identity='e' * 32)['reason'], 'credit')   # refused before it starts
        self.now[0] += 901
        self.store.reconcile(usage_reader=lambda: Decimal('0.02'))
        self.assertEqual(self.status()['total_usd'], '0.020000000')
        self.assertEqual(self.status()['ceiling_usd'], '0.920000000')   # the ceiling itself is unchanged
        for _ in range(3): self.assertTrue(self.reserve(admit(self.store))[1]['granted'])
        self.assertEqual(admit(self.store)['reason'], 'credit')

    def test_rows_from_before_the_generation_column_still_load(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('DROP TABLE paid_requests; CREATE TABLE paid_requests (id TEXT PRIMARY KEY, lease_id TEXT, '
                             'route TEXT, profile TEXT, hold INTEGER, charge INTEGER, state TEXT, settled_at REAL, usage TEXT);')
        self.store = router.Store(self.path, clock=lambda: self.now[0], capacities={'openrouter-key': 100},
                                  credit_reader=lambda: self.credit)
        self.unknown_with_generation('gen-after-upgrade')
        self.assertEqual(self.rows()[0][4], 'gen-after-upgrade')

    def test_generation_adapter_synthetic_schema_and_no_diagnostics(self):
        for payload, expected in (
            (b'{"data":{"id":"gen-a","model":"minimax/minimax-m3.1-flash","total_cost":0.0015}}',
             (Decimal('0.0015'), 'minimax/minimax-m3.1-flash')),
            (b'{"data":{"id":"gen-b","model":"minimax/minimax-m3.1-flash","total_cost":0.0015}}', None),
            (b'{"data":{"id":"gen-a","model":"minimax/minimax-m3.1-flash","total_cost":-1}}', None),
            (b'{"data":{"id":"gen-a","model":"minimax/minimax-m3.1-flash","total_cost":true}}', None),
            (b'{"data":{"id":"gen-a","total_cost":0.1}}', None), (b'not-json', None), (b'x'*16385, None)):
            with patch.dict(os.environ, {'OPENROUTER_API_KEY':'synthetic'}), patch.object(router.urllib.request, 'build_opener') as make:
                make.return_value.open.return_value = io.BytesIO(payload)
                self.assertEqual(router.generation_cost('gen-a'), expected)
                self.assertTrue(make.return_value.open.call_args.args[0].full_url.endswith('/generation?id=gen-a'))
        with patch.object(router.urllib.request, 'build_opener') as make:
            self.assertIsNone(router.generation_cost('gen-a&x=1'))
            make.assert_not_called()
        with patch.dict(os.environ, {'OPENROUTER_API_KEY':'synthetic'}), patch.object(router.urllib.request, 'build_opener') as make:
            make.return_value.open.return_value = io.BytesIO(b'{"data":{"total_credits":20,"total_usage":8.25}}')
            self.assertEqual(router.account_usage(), Decimal('8.25'))

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

    def test_unconfirmed_call_records_its_generation_for_reconciliation(self):
        import test_model_call_maxima as core
        event = dict(id='gen-1762780000-Synthetic', model='minimax/minimax-m3.1-flash',
                     choices=[dict(index=0, finish_reason='stop')])
        payload = b'data: ' + json.dumps(event).encode() + b'\n\n'     # cut before its usage frame
        self.responses = [payload]
        actual = core.lease(MINIMAX)
        with authority(actual) as store, patch.object(gate.sys, 'platform', 'linux'):
            with gate.enforce(actual, self.env(), {}, 3) as active:
                self.assertEqual(self.post(active), (200, payload))
                self.assertEqual(active.state.snapshot()['unknown_requests'], 1)
            self.assertEqual(store.rpc('status', {})['paid']['total_usd'], '0.230000000')
            with closing(sqlite3.connect(store.path)) as db:
                self.assertEqual(db.execute('SELECT state,generation FROM paid_requests').fetchall(),
                                 [('unknown', 'gen-1762780000-Synthetic')])
            store.reconcile(cost_reader=lambda g: (Decimal('0.0004'), 'minimax/minimax-m3.1-flash'))
            self.assertEqual(store.rpc('status', {})['paid']['total_usd'], '0.000400000')

    def test_an_error_frame_still_records_its_generation(self):
        import test_model_call_maxima as core
        event = dict(id='gen-1762780000-Errored', model='minimax/minimax-m3.1-flash',
                     error=dict(code=502, message='synthetic'), choices=[dict(index=0, finish_reason='error')])
        payload = b'data: ' + json.dumps(event).encode() + b'\n\n'
        self.responses = [payload]
        actual = core.lease(MINIMAX)
        with authority(actual) as store, patch.object(gate.sys, 'platform', 'linux'):
            with gate.enforce(actual, self.env(), {}, 3) as active:
                self.assertEqual(self.post(active), (200, payload))
            with closing(sqlite3.connect(store.path)) as db:
                self.assertEqual(db.execute('SELECT state,generation FROM paid_requests').fetchall(),
                                 [('unknown', 'gen-1762780000-Errored')])
            store.reconcile(cost_reader=lambda g: (Decimal('0'), 'minimax/minimax-m3.1-flash-20261106'))
            self.assertEqual(store.rpc('status', {})['paid']['total_usd'], '0.000000000')

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
                with patch.object(router, '_rpc', rpc), patch.object(gate, 'PAID_RESERVE_PAUSE_SECONDS', .05), \
                        self.assertRaisesRegex(BudgetError, 'shared_paid_spend_wait'):
                    with gate.enforce(actual, self.env(), {}, 3) as active:
                        for _ in range(3): self.assertEqual(self.post(active)[0], 503)
                # A credit refusal is final at once; a reply lost every time is retried, with one request id.
                if lost: self.assertGreater(len(reads), 1)
                else: self.assertEqual(len(reads), 1)
                self.assertEqual(self.seen, [])
                self.assertEqual(store.rpc('status', {})['paid']['total_usd'], '0.230000000' if lost else '0.000000000')

    def test_a_lost_or_late_reserve_reply_is_asked_again_and_booked_once(self):
        """f46dac-h6 / cae763-h4, 19 November: one paid_reserve past the 4 s rule (binding) or past the client's
        5 s (no reply) ended reviewer calls that had forwarded 48-69 requests (~$13 of work thrown away)."""
        import test_model_call_maxima as core
        for first in ('late', 'lost'):
            self.seen, self.responses = [], [self.payload()]
            actual = core.lease(MINIMAX)
            with authority(actual) as store, patch.object(gate.sys, 'platform', 'linux'):
                asked = []
                def rpc(op, data):
                    if op != 'paid_reserve': return store.rpc(op, data)
                    asked.append(data['request_id'])
                    if len(asked) > 1: return store.rpc(op, data)
                    if first == 'late':    # the router's own answer when handling took 4 s or more
                        return store.rpc(op, data, handling_started=time.monotonic() - 4)
                    store.rpc(op, data)   # granted, but the reply never arrived
                    raise router.RouterUnavailable('router response unavailable')
                with patch.object(router, '_rpc', rpc), patch.object(gate, 'PAID_RESERVE_PAUSE_SECONDS', .05):
                    with gate.enforce(actual, self.env(), {}, 3) as active:
                        self.assertEqual(self.post(active)[0], 200)
                self.assertEqual(len(asked), 2); self.assertEqual(len(set(asked)), 1)   # one request id
                self.assertEqual(len(self.seen), 1)                                     # forwarded once
                with closing(sqlite3.connect(store.path)) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*),state FROM paid_requests').fetchone(), (1, 'settled'))

    def test_a_router_reply_slowed_by_its_write_lock_is_retried_over_real_http(self):
        """The real router and client: a write lock held 6 s (the 19 November CPU-bound VM) makes the first reply
        miss the client's 5 s; the retry with the same request id is granted and the call goes on."""
        import test_model_call_maxima as core
        self.responses = [self.payload()]
        actual = core.lease(MINIMAX)
        with tempfile.TemporaryDirectory() as root:
            store = router.Store(Path(root) / 'router.sqlite', credit_reader=lambda: Decimal('11.63'))
            admit(store, actual.route, actual.lease_id)
            server = router.Server(('127.0.0.1', 0), store, 'synthetic-token')
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
            locked = threading.Event()
            def hold():
                with closing(sqlite3.connect(store.path)) as db:
                    db.execute('BEGIN IMMEDIATE'); locked.set(); time.sleep(6); db.rollback()
            env = {'FACTORY_ROUTER_URL': f'http://127.0.0.1:{server.server_port}', 'FACTORY_ROUTER_TOKEN': 'synthetic-token'}
            with patch.dict(os.environ, env), patch.object(gate.sys, 'platform', 'linux'):
                with gate.enforce(actual, self.env(), {}, 30) as active:
                    threading.Thread(target=hold, daemon=True).start(); self.assertTrue(locked.wait(2))
                    import http.client
                    connection = http.client.HTTPConnection('127.0.0.1', active.server.server_port, timeout=30)
                    body = dict(model='minimax/minimax-m3.1-flash', messages=[dict(role='user', content='synthetic')], stream=True)
                    started = time.monotonic()
                    connection.request('POST', '/api/v1/chat/completions', json.dumps(body), {'Authorization': 'Bearer ' + active.token})
                    response = connection.getresponse(); response.read(); connection.close()
                    self.assertEqual(response.status, 200)
                    self.assertGreater(time.monotonic() - started, 5)   # the first reply really was lost
            self.assertEqual(len(self.seen), 1)
            with closing(sqlite3.connect(store.path)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM paid_requests').fetchone()[0], 1)

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
                # A third funded Engine attempt cannot replenish the shared provider wallet, and
                # with the ceiling spent it is refused at its lease, before any process starts.
                c = context(3)
                with self.assertRaises(router.ProviderWait):
                    runtime.call(c,[MINIMAX],'synthetic',c.work,'builder-1')
            self.assertEqual(calls,[('builder-1',False),('diagnosis-synthetic',True)])
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
