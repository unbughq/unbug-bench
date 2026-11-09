"""A wait for one of our own router seats is not a provider rate limit.

9 November: 7-9 cases shared 4 OpenRouter seats. A call that found every seat held
waited WAIT_SECONDS, then left with the pool's reason 'rate' and slept the 15-minute
provider backoff, although no provider had limited anything.
"""
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'factory'))
os.environ.setdefault('BENCH', str(ROOT))

import model_call_gate
import model_router as router
from durable import classify as wp4
from durable.contract import Outcome, StepKind
from router_test_support import synthetic_enforcement, synthetic_maximum

PAID = 'openrouter/xiaomi/mimo-v2.6-pro'  # Its other lane needs an OpenCode Go key; these calls offer none.
NOW = 1_792_510_000.0


class SeatsBusy(unittest.TestCase):
    def setUp(self):
        for target, name, value in ((router, 'route_maximum', synthetic_maximum),
                                    (model_call_gate, 'enforce', synthetic_enforcement)):
            p = patch.object(target, name, value); p.start(); self.addCleanup(p.stop)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.clock = [NOW]
        self.store = router.Store(self.root / 'router.sqlite', clock=lambda: self.clock[0])

    def acquire(self, wait_protocol=1, identity=None):
        data = dict(paid_protocol=1, id=identity or uuid.uuid4().hex, model=PAID, accounts=['openrouter-key'],
                    role='writer', deadline=self.clock[0] + 86400)
        if wait_protocol is not None: data['wait_protocol'] = wait_protocol
        return self.store.rpc('acquire', data)

    def test_full_seats_wait_seconds_and_record_no_provider_health(self):
        held = self.acquire()
        self.assertEqual(held['kind'], 'lease')
        busy = self.acquire()
        self.assertEqual(busy['kind'], 'wait')
        self.assertEqual(busy['reason'], 'seats_busy')
        self.assertLessEqual(busy['retry_after'], NOW + router.SEATS_BUSY_SECONDS)
        self.assertEqual(self.store.rpc('status', {})['health'], {})
        # Our queue is never stored as a pool limit.
        with self.assertRaisesRegex(ValueError, 'invalid provider reason'):
            self.store.rpc('observe', dict(lease_id=held['lease_id'], reason='seats_busy',
                                           observation_id=held['lease_id'] + ':failure'))

    def test_workers_on_an_older_release_still_get_a_reason_they_know(self):
        self.acquire()
        self.assertEqual(self.acquire(wait_protocol=None)['reason'], 'rate')

    def test_a_recorded_provider_limit_keeps_its_own_reason_and_reset(self):
        held = self.acquire()
        reset = NOW + 600
        self.store.rpc('observe', dict(lease_id=held['lease_id'], reason='rate', reset_at=reset,
                                       observation_id=held['lease_id'] + ':failure'))
        self.store.rpc('finish', dict(lease_id=held['lease_id'], outcome='interrupted', receipt=None))
        limited = self.acquire()
        self.assertEqual((limited['kind'], limited['reason'], limited['retry_after']), ('wait', 'rate', reset))

    def test_await_lease_leaves_with_seats_busy_and_the_step_retries_in_seconds(self):
        self.acquire()   # Another case holds the only seat for the whole wait.
        c = SimpleNamespace(work=self.root, card={}, batch_id='batch', job_id='job',
                            batch_deadline=NOW + 86400, router_model=PAID, router_accounts=('openrouter-key',))
        def sleep(seconds): self.clock[0] += seconds
        def tick(): return self.clock[0]
        with patch.dict(os.environ, {'UNBUG_PROVIDER_WAIT': '1'}), \
             patch.object(router, '_rpc', side_effect=self.store.rpc), \
             patch.object(router.time, 'time', side_effect=tick), \
             patch.object(router.time, 'monotonic', side_effect=tick), \
             patch.object(router.time, 'sleep', side_effect=sleep):
            with self.assertRaises(router.ProviderWait) as caught:
                router.await_lease('writer', c)
        self.assertEqual(self.clock[0], NOW + router.WAIT_SECONDS)
        self.assertEqual(caught.exception.wait.reason, 'seats_busy')
        now = self.clock[0]
        result, details = wp4.classify_wait(caught.exception, step=StepKind.WRITER, now=now)
        self.assertEqual((result.outcome, result.reason), (Outcome.PROVIDER_LIMIT, 'router:seats_busy'))
        self.assertEqual(result.retry_at, now + wp4.SEATS_BUSY_RETRY_S)
        self.assertIn('router:seats_busy', wp4.PUBLISHED_REASONS)
        self.assertEqual(details['waits'][-1]['reason'], 'seats_busy')

    def test_classification_keeps_real_limits_on_the_provider_backoff(self):
        seats = router.ProviderWait('writer', router.Wait('seats_busy', NOW + 15))
        result, _ = wp4.classify_wait(seats, step=StepKind.ADMIT, now=NOW)
        self.assertEqual(result.retry_at, NOW + wp4.SEATS_BUSY_RETRY_S)
        # A seat wait that follows a stale or missing reset still never takes the 900 s backoff.
        stale = router.ProviderWait('writer', router.Wait('seats_busy', NOW - 5))
        self.assertEqual(wp4.classify_wait(stale, step=StepKind.ADMIT, now=NOW)[0].retry_at,
                         NOW + wp4.SEATS_BUSY_RETRY_S)
        # A real rate limit in the same logical call keeps its own reset.
        mixed = router.ProviderWait('writer', router.Wait('seats_busy', NOW + 15))
        mixed.previous_waits = [{'reason': 'rate', 'retry_after': NOW + 600}]
        result, _ = wp4.classify_wait(mixed, step=StepKind.ADMIT, now=NOW)
        self.assertEqual(result.retry_at, NOW + 600)
        # A plain rate limit with no reset is unchanged.
        rate = router.ProviderWait('writer', router.Wait('rate', NOW - 5))
        result, _ = wp4.classify_wait(rate, step=StepKind.ADMIT, now=NOW)
        self.assertEqual((result.reason, result.retry_at), ('router:rate', NOW + wp4.BACKOFF_S))
        self.assertEqual(router.retry_at('seats_busy', now=NOW), NOW + router.SEATS_BUSY_SECONDS)


if __name__ == '__main__':
    unittest.main()
