"""The Sealing Board is generated from engine and ledger records, read-only, across batches (O8)."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'factory'))
sys.path.insert(0, str(ROOT / 'control' / 'campaign'))
from durable.board import read_board, render_board
from durable.contract import Usage
from durable.ledger import SqlLedger

M = 1_000_000


def attempt(case, batch, seq, step, n, status, created, updated, output=None):
    kind, _, rnd = step.partition(':')
    return SimpleNamespace(workflow_id=f'{case}/{seq}/{step}/{n}', status=status, created_at=created * 1000,
        updated_at=updated * 1000, output=output,
        input={'args': [{'input': {'batch_id': batch, 'case_id': case, 'seq': seq, 'attempt': n,
                                   'step': {'kind': kind, 'round': int(rnd or 0)}}}]})


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {'database_url': 'sqlite:///' + str(self.root / 'db'), 'state_dir': str(self.root)}
        ledger = SqlLedger(self.config['database_url']); self.addCleanup(ledger.close)
        ledger.open('b-live', 50 * M)
        ledger.reserve('b-live', 'case-alpha', 'case-alpha/1/admit/1', 2 * M, 50 * M)
        ledger.settle('case-alpha/1/admit/1', Usage(3, 1 * M, 4 * M))
        ledger.reserve('b-live', 'case-alpha', 'case-alpha/2/writer:1/1', 3 * M, 50 * M)
        ledger.settle('case-alpha/2/writer:1/1', Usage(2, 2 * M, 2 * M), waste=True)
        ledger.reserve('b-live', 'case-alpha', 'case-alpha/3/gates:1/1', 5 * M, 50 * M)   # still held
        ledger.open('b-old', 50 * M)
        ledger.reserve('b-old', 'case-beta', 'case-beta/1/admit/1', 1 * M, 50 * M)
        ledger.settle_lost('case-beta/1/admit/1')
        self.ledger = ledger
        self.before = ledger.rows()
        pool = self.root / 'pool'; pool.mkdir()
        (pool / 'case-alpha.json').write_text(json.dumps({'worker': 'bx_abcdefgh'}))
        self.workflows = {
            'b-live': SimpleNamespace(status='PENDING', created_at=1000, updated_at=1000, input={'args': [{'spec': {}}]}),
            'b-old': SimpleNamespace(status='SUCCESS', created_at=500, updated_at=900, input={'args': [{'spec': {}}]}),
            'case-alpha': SimpleNamespace(status='PENDING', created_at=1000, updated_at=7000),
            'case-beta': SimpleNamespace(status='SUCCESS', created_at=500, updated_at=900)}
        self.attempts = {
            'case-alpha': [attempt('case-alpha', 'b-live', 3, 'gates:1', 1, 'PENDING', 9000, 9000),
                           attempt('case-alpha', 'b-live', 2, 'writer:1', 1, 'SUCCESS', 3000, 8000,
                                   {'result': {'outcome': 'ok', 'reason': None}})],
            'case-beta': []}
        self.cards = {
            'case-alpha': dict(case_id='case-alpha', status='running', stage='gates:1', passed=['G1', 'G2', 'G4'],
                               failed_gate=None, writer_rounds=1, extensions=0, replacement_of=None, reason=None),
            'case-beta': dict(case_id='case-beta', status='not_admitted', stage='admit', passed=[],
                              failed_gate='G2', writer_rounds=0, extensions=0, replacement_of=None, reason=None)}
        self.members = {'b-live': ['case-alpha'], 'b-old': ['case-beta']}

    def client(self):
        def rows(workflow_ids=None, workflow_id_prefix=None, **kwargs):
            if workflow_ids:
                return [self.workflows[w] for w in workflow_ids if w in self.workflows]
            return list(self.attempts[workflow_id_prefix.rstrip('/')])
        def event(workflow_id, key, **kwargs):
            if key == 'cases': return self.members.get(workflow_id)
            if key == 'card': return self.cards.get(workflow_id)
            return None
        return SimpleNamespace(list_workflows=rows, get_event=event, destroy=lambda: None)

    def read(self, **kwargs):
        with patch('durable.observation._controller', return_value={'state': 'active'}) as run, \
             patch('durable.ledger._create_schema', side_effect=AssertionError('the board must not create schema')):
            board = read_board(self.config, client=self.client(), now=10_000, **kwargs)
        self.systemctl_calls = run.call_count
        return board

    def test_every_batch_appears_with_stage_round_gates_spend_and_last_event(self):
        board = self.read()
        self.assertEqual([r['case'] for r in board['cases']], ['case-alpha', 'case-beta'])
        alpha, beta = board['cases']
        self.assertEqual((alpha['batch'], alpha['status'], alpha['stage'], alpha['writer_round']),
                         ('b-live', 'running', 'gates:1', 1))
        self.assertEqual((alpha['gates_passed'], alpha['failed_gate']), (['G1', 'G2', 'G4'], None))
        self.assertEqual(alpha['spend_usd_micros'], {'spent': 3 * M, 'held': 5 * M, 'waste': 2 * M,
                                                    'case_used': 6 * M, 'list_price': 6 * M, 'calls': 5})
        self.assertEqual((alpha['last_event_at'], alpha['quiet_for_s']), (9000, 1000))
        self.assertEqual(alpha['latest_attempt'], '3/gates:1/1 PENDING')
        self.assertEqual(alpha['last_result'], 'ok')
        self.assertTrue(alpha['live'])
        self.assertEqual((beta['status'], beta['failed_gate'], beta['live']), ('not_admitted', 'G2', False))
        self.assertEqual(beta['spend_usd_micros']['spent'], 1 * M)   # a lost hold is spent and waste
        self.assertEqual(board['spend_usd_micros'], {'spent': 4 * M, 'held': 5 * M, 'waste': 3 * M})
        self.assertEqual((board['sealed'], board['live'], board['totals']), (0, 1, {'running': 1, 'not_admitted': 1}))
        self.assertEqual(board['unavailable'], [])
        self.assertEqual(self.systemctl_calls, 1)          # one controller read covers every batch
        self.assertEqual(self.before, self.ledger.rows())  # nothing written

    def test_board_follows_the_records_instead_of_going_stale(self):
        first = self.read()['cases'][0]
        self.cards['case-alpha'].update(status='sealed', stage='sealed', hard=False, passed=[f'G{i}' for i in range(1, 18)])
        self.workflows['case-alpha'].updated_at = 9500 * 1000
        self.attempts['case-alpha'] = []
        second = self.read()
        row = next(r for r in second['cases'] if r['case'] == 'case-alpha')
        self.assertNotEqual(first['status'], row['status'])
        self.assertEqual((row['status'], row['live'], row['hard'], len(row['gates_passed'])), ('sealed', False, False, 17))
        self.assertEqual(second['sealed'], 1)

    def test_live_filter_and_text_board(self):
        board = self.read(live_only=True)
        self.assertEqual([r['case'] for r in board['cases']], ['case-alpha'])
        text = render_board(self.read())
        for expected in ('SEALING BOARD', 'do not edit by hand', 'case-alpha', 'gates:1', 'G1 G2 G4',
                         '$3.00', 'not_admitted', '(G2 failed)', '16m', '1 live'):
            self.assertIn(expected, text)

    def test_unreadable_sections_are_named_not_guessed(self):
        def broken(*a, **k): raise RuntimeError('private detail')
        client = self.client(); client.get_event = broken
        unit = {'state': 'unavailable'}
        with patch('durable.observation._controller', return_value=unit):
            board = read_board(self.config, client=client, now=10_000)
        self.assertEqual((board['cases'], board['unavailable']), ([], ['b-live', 'b-old']))
        self.assertIn('Unavailable', render_board(board))
        self.assertNotIn('private', json.dumps(board))
        with patch('durable.board._ledger', side_effect=RuntimeError('private dsn')), \
             patch('durable.observation._controller', return_value=unit):
            board = read_board(self.config, client=self.client(), now=10_000)
        self.assertEqual(board['unavailable'], ['ledger'])
        self.assertNotIn('private', json.dumps(board))

    def test_an_unread_batch_workflow_is_unknown_not_ended(self):
        client = self.client(); rows = client.list_workflows
        def flaky(workflow_ids=None, **kwargs):
            if workflow_ids == ['b-live']:
                raise TimeoutError('observability query timed out')
            return rows(workflow_ids=workflow_ids, **kwargs)
        client.list_workflows = flaky
        with patch('durable.observation._controller', return_value={'state': 'active'}):
            board = read_board(self.config, client=client, now=10_000)
            live = read_board(self.config, client=client, now=10_000, live_only=True)
        alpha = next(r for r in board['cases'] if r['case'] == 'case-alpha')
        self.assertEqual((alpha['batch_workflow'], alpha['live']), ('UNKNOWN', True))
        self.assertEqual((board['live'], board['unavailable']), (1, ['b-live:workflows']))
        self.assertEqual([r['case'] for r in live['cases']], ['case-alpha'])
        text = render_board(board)
        self.assertIn('[batch state unknown]', text)
        self.assertNotIn('batch ended', text)
        self.assertIn('b-live:workflows', text)
        self.workflows['b-live'].status = 'SUCCESS'   # a batch that really ended is still shown as ended
        with patch('durable.observation._controller', return_value={'state': 'active'}):
            ended = read_board(self.config, client=self.client(), now=10_000)
        self.assertIn('[batch ended]', render_board(ended))
        self.assertEqual(ended['live'], 0)

    def test_campaign_script_reads_the_campaign_config(self):
        import campaign_board
        dsn = self.root / 'dsn'; dsn.write_text(self.config['database_url'] + '\n')
        (self.root / 'config.json').write_text(json.dumps({'state_dir': str(self.root), 'database_url_file': str(dsn)}))
        out = io.StringIO()
        with patch('dbos.DBOSClient', return_value=self.client()), contextlib.redirect_stdout(out), \
             patch('durable.observation._controller', return_value={'state': 'active'}) as run:
            self.assertEqual(campaign_board.main(['--root', str(self.root), '--live']), 0)
        self.assertEqual([r['case'] for r in json.loads(out.getvalue())['cases']], ['case-alpha'])
        self.assertEqual(run.call_args[0][0]['status_service_unit'], 'unbug-durable-case-campaign.service')


if __name__ == '__main__': unittest.main()
