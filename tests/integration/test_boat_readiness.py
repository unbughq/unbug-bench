"""Public-only readiness checks. No provider, credentials or real cases."""
import datetime
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
from deployment_fixture import folding_sequence

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('readiness', ROOT / 'tools/boat_readiness.py')
ready = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ready)


def info(**changes):
    value = dict(id='bx_fixture', type='default', ttlSeconds=1800,
        archiveAfter=datetime.datetime.fromtimestamp(2800, datetime.timezone.utc).isoformat(),
        holdsCreatorLogins=False, monitoring=False, snapshots=False,
        state='idle', health='ok', error=None, setupError=None, setupStatus=None,
        degradedSince=None, hydrated=True, hydration=None)
    value.update(changes)
    return {'sandbox': value}


class ReadinessTests(unittest.TestCase):
    def run_gate(self, responses, *, now=None, requested=100, margin=420, elapsed=0):
        clock = [100 + elapsed]
        processes = []
        def process(*args, **kw):
            self.assertEqual(args[0], ['fake', 'info', 'bx_fixture', '--json'])
            self.assertLessEqual(float(kw['env']['BOAT_COMMAND_TIMEOUT_SECONDS']), 120)
            response = responses.pop(0) if len(responses) > 1 else responses[0]
            proc = mock.Mock(returncode=0)
            def communicate(timeout=None):
                if now: clock[0] += now
                return (json.dumps(response) if not isinstance(response, str) else response, '')
            proc.communicate.side_effect = communicate
            processes.append(proc)
            return proc
        def sleep(seconds): clock[0] += seconds
        self.receipt = self.home / 'receipt.json'
        with mock.patch.object(ready.subprocess, 'Popen', side_effect=process), \
             mock.patch.object(ready.time, 'monotonic', side_effect=lambda: clock[0]), \
             mock.patch.object(ready.time, 'sleep', side_effect=sleep):
            return ready.wait_ready('fake', 'bx_fixture', 'default', 1800,
                requested, 1000, margin, self.receipt)

    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)

    def test_delayed_hydration_and_unknown_progress(self):
        result = self.run_gate([info(hydrated=False), info(hydrated=False,
            hydration=dict(phase='dvol', entriesDone=26, entriesTotal=100, percent=26)),
            info(hydrated=False, hydration=dict(phase='sysdelta', entriesDone=0, entriesTotal=None, percent=None)), info()])
        self.assertEqual(result['attempts'], 4)
        self.assertEqual(result['outcome'], 'ready')

    def test_booted_ready_state_waits_for_hydration(self):
        # Live from the control VM 2026-10-23: a fresh healthy sandbox reports state 'ready'.
        result = self.run_gate([info(state='ready', hydrated=False), info(state='ready')])
        self.assertEqual(result['outcome'], 'ready')

    def test_folding_sequence_waits_for_strict_completion(self):
        responses = [{'sandbox': row} for row in folding_sequence(
            'bx_fixture', info()['sandbox']['archiveAfter'])]
        result = self.run_gate(responses)
        self.assertEqual(result['attempts'], 6)
        self.assertEqual(result['outcome'], 'ready')

    def test_incomplete_phases_are_bounded_and_failures_refused(self):
        for phase in ('folding', 'future-provider-phase'):
            with self.subTest(phase=phase):
                with self.assertRaises(TimeoutError):
                    self.run_gate([info(hydrated=False, hydration=dict(
                        phase=phase, entriesDone=0, entriesTotal=None, percent=None))])
                self.assertEqual(json.loads(self.receipt.read_text())['attempts'], 60)
                self.receipt.unlink()
        for phase in ('failed', 'error', 'degraded', 'cancelled'):
            with self.subTest(phase=phase):
                with self.assertRaises(ValueError):
                    self.run_gate([info(hydrated=False, hydration=dict(
                        phase=phase, entriesDone=0, entriesTotal=None, percent=None))])
                self.assertEqual(json.loads(self.receipt.read_text())['attempts'], 1)
                self.receipt.unlink()

    def test_refusals_retain_receipt(self):
        cases = [info(id='other'), info(hydrated='true'), info(hydrated=1),
            info(hydration={}), info(error='private provider details'), info(setupError='failed'),
            info(health='degraded'), info(state='stopped'), info(setupStatus='failed'),
            info(degradedSince='now'), info(monitoring=True), info(type='large'),
            info(ttlSeconds=3600), info(archiveAfter='bad'), 'not JSON', {'sandbox': []}]
        for field in ('hydrated', 'hydration', 'error', 'health', 'archiveAfter'):
            case = info(); del case['sandbox'][field]; cases.append(case)
        for phase in ('degraded', 'stuck', 'unknown'):
            cases.append(info(hydrated=False, hydration={'phase': phase}))
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises((ValueError, KeyError, TypeError)):
                    self.run_gate([case])
                receipt = self.receipt.read_text()
                self.assertEqual(json.loads(receipt)['outcome'], 'refused')
                self.assertNotIn('private provider details', receipt)
                self.receipt.unlink()

    def test_deadlines_include_slow_create_query_and_provider_expiry(self):
        for response, kw in [(info(hydrated=False), {}), (info(), {'now':601}),
                             (info(), {'elapsed':1381}),
                             (info(archiveAfter=datetime.datetime.fromtimestamp(1410, datetime.timezone.utc).isoformat()), {})]:
            with self.subTest(kw=kw):
                with self.assertRaises(TimeoutError): self.run_gate([response], **kw)
                self.assertEqual(json.loads(self.receipt.read_text())['outcome'], 'refused')
                self.receipt.unlink()

    def test_query_failure_and_hang(self):
        for hangs in (False, True):
            self.receipt = self.home / ('hang' if hangs else 'error')
            proc = mock.Mock(returncode=1)
            proc.communicate.side_effect = [subprocess.TimeoutExpired('fake', 1), ('', '')] if hangs else [('', '')]
            with mock.patch.object(ready.subprocess, 'Popen', return_value=proc):
                with self.assertRaises((ValueError, TimeoutError)):
                    ready.wait_ready('fake', 'bx_fixture', 'default', 1800,
                        ready.time.monotonic(), ready.time.time(), 420, self.receipt)
            if hangs: proc.terminate.assert_called_once()
            self.assertEqual(json.loads(self.receipt.read_text())['outcome'], 'refused')


if __name__ == '__main__': unittest.main()
