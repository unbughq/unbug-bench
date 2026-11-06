"""Status reads real accounting without schema changes or execution side effects."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'factory'))
from durable.contract import Usage
from durable.ledger import SqlLedger
from durable.observation import observe, read_status
from durable.report import render_status


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {'database_url': 'sqlite:///' + str(self.root / 'db'), 'state_dir': str(self.root)}
        self.ledger = SqlLedger(self.config['database_url']); self.addCleanup(self.ledger.close)
        self.ledger.open('b-one', 10_000_000)
        self.ledger.reserve('b-one', 'case-one', 'case-one/1/admit/1', 2_000_000, 10_000_000)
        self.ledger.settle('case-one/1/admit/1', Usage(7, 1_000_000, 2_000_000), waste=True)
        self.ledger.reserve('b-one', 'case-one', 'case-one/1/admit/2', 3_000_000, 10_000_000)
        self.before = self.ledger.rows()
        self.card = {'batch': 'b-one', 'sealed': 0, 'target_sealed': None, 'cases': [{
            'case': 'case-one', 'status': 'running', 'stage': 'admit', 'reason': None,
            'writer_rounds': 0, 'extensions': 0, 'replacement_of': None, 'gates': {'G1': 'pass'}}]}
        pool = self.root / 'pool'; pool.mkdir()
        (pool / 'case-one.json').write_text(json.dumps({'worker': 'bx_abcdefgh', 'intent': None, 'deleting': None}))
        self.batch = SimpleNamespace(status='PENDING', created_at=1000, updated_at=2000,
            input={'args': [{'spec': {'target_sealed': 2, 'max_cases_started': 3, 'max_concurrency': 1,
                                     'deadline_epoch': 5000, 'private': 'must not leave controller'}}]})
        self.case = SimpleNamespace(status='PENDING', created_at=1000, updated_at=2000)
        self.active = SimpleNamespace(workflow_id='case-one/1/admit/2/admit', status='PENDING',
            created_at=4000, updated_at=4000, output=None,
            input={'args': [{'input': {'batch_id': 'b-one', 'case_id': 'case-one', 'seq': 1,
                'attempt': 2, 'step': {'kind': 'admit', 'round': 0}}}]})
        self.finished = SimpleNamespace(workflow_id='case-one/1/admit/1/admit', status='SUCCESS',
            created_at=2000, updated_at=3000, output={'result': {'outcome': 'provider_limit',
                'reason': 'router:credit', 'retry_at': 10, 'snapshot': {'digest': 'a'*64},
                'private': 'must not leave controller'}},
            input={'args': [{'input': {'batch_id': 'b-one', 'case_id': 'case-one', 'seq': 1,
                'attempt': 1, 'step': {'kind': 'admit', 'round': 0}}}]})

    def client(self):
        def rows(**kwargs):
            if kwargs.get('workflow_ids') == ['b-one']: return [self.batch]
            if kwargs.get('workflow_ids') == ['case-one']: return [self.case]
            return [self.active, self.finished]
        def event(workflow_id, key, **kwargs):
            if key == 'cases': return ['case-one']
            if key == 'card':
                return dict(case_id='case-one', status='running', stage='admit', passed=['G1'],
                            writer_rounds=0, extensions=0, replacement_of=None, reason=None)
            return None
        client = SimpleNamespace(list_workflows=rows, get_event=event, destroy=lambda: None)
        return patch('dbos.DBOSClient', return_value=client)

    def test_budget_latest_attempt_and_last_result_remain_distinct_and_read_only(self):
        original = copy.deepcopy(self.card)
        with self.client(), patch('durable.ledger._create_schema', side_effect=AssertionError('status must not initialize schema')):
            result = observe(self.config, self.card)
        budget = result['observation']['budget']
        self.assertEqual((budget['bound'], budget['spent'], budget['held'], budget['remaining']),
                         (10_000_000, 1_000_000, 3_000_000, 6_000_000))
        self.assertEqual((budget['waste'], budget['settled_calls']), (1_000_000, 7))
        self.assertEqual(result['target_sealed'], 2)
        operation = result['cases'][0]['operation']
        self.assertEqual(operation['latest_attempt']['attempt'], 2)
        self.assertEqual(operation['last_result']['attempt'], 1)
        self.assertEqual(operation['worker'], {'id': 'bx_abcdefgh', 'state': 'assigned'})
        self.assertEqual(self.before, self.ledger.rows())
        self.assertEqual(original, self.card)
        self.assertNotIn('must not leave controller', json.dumps(result))
        text = render_status(result)
        for expected in ('BATCH BUDGET', '$10.00', '$3.00', 'Settled calls', 'G1=PASS',
                         'newer attempt is recorded', 'historical', 'liveness is not polled'):
            self.assertIn(expected, text)

    def test_missing_metadata_keeps_the_scorecard_and_reports_unavailable(self):
        with patch('durable.observation._budget', side_effect=RuntimeError('private database detail')), \
             patch('dbos.DBOSClient', side_effect=RuntimeError('private credential detail')):
            result = observe(self.config, self.card)
        self.assertEqual(result['cases'], self.card['cases'])
        self.assertEqual(result['observation']['unavailable'], ['budget', 'workflows'])
        self.assertIn('BATCH BUDGET: unavailable', render_status(result))
        self.assertNotIn('private', json.dumps(result))

    def test_worker_absence_does_not_hide_provider_retry_and_private_reason_is_withheld(self):
        (self.root / 'pool/case-one.json').unlink()
        self.active = self.finished
        self.finished.output['result']['reason'] = 'secret:private_data'
        with self.client(): result = observe(self.config, self.card)
        operation = result['cases'][0]['operation']
        self.assertEqual(operation['worker']['state'], 'unassigned')
        self.assertIsNone(operation['last_result']['reason'])
        self.assertIn('waiting or queued for retry', render_status(result))
        self.assertNotIn('secret:', json.dumps(result))

    def test_generated_non_admit_id_and_sealed_cleanup_warning_are_preserved(self):
        self.active.workflow_id = 'case-one/2/writer:1/1-1'
        self.active.input['args'][0]['input'].update(seq=2, attempt=1, step={'kind': 'writer', 'round': 1})
        self.card['cases'][0].update(status='sealed', stage='sealed', hard=True, cleanup_error=True,
                                     replacement_of='case-previous')
        with self.client(): result = observe(self.config, self.card)
        attempt = result['cases'][0]['operation']['latest_attempt']
        self.assertEqual((attempt['seq'], attempt['step'], attempt['attempt']), (2, 'writer:1', 1))
        text = render_status(result)
        self.assertIn('Seal cleanup unconfirmed', text)
        self.assertIn('Hard case', text)
        self.assertIn('case-previous', text)
        self.active.input['args'][0]['input']['case_id'] = 'case-other'
        with self.client(): result = observe(self.config, self.card)
        self.assertIsNone(result['cases'][0]['operation']['latest_attempt'])

    def test_status_survives_controller_shutdown_and_reports_the_service_failure(self):
        import subprocess
        result = subprocess.CompletedProcess([], 0, 'LoadState=loaded\nActiveState=failed\nResult=timeout\n', '')
        with self.client(), patch('socket.socket', side_effect=AssertionError('no operator socket')), \
             patch('durable.observation.subprocess.run', return_value=result):
            card = read_status(self.config, 'b-one')
        text = render_status(card)
        self.assertIn('FAILED (timeout)', text)
        self.assertIn('Controller is stopped', text)
        self.assertEqual(card['observation']['budget']['spent'], 1_000_000)
        self.assertEqual(self.before, self.ledger.rows())


if __name__ == '__main__': unittest.main()
