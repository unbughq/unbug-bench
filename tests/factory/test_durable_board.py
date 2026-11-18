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
    return SimpleNamespace(workflow_id=f'{case}/{seq}/{step}/{n}', name='attempt_workflow', status=status, created_at=created * 1000,
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
        self.steps = {}

    def client(self):
        def rows(workflow_ids=None, workflow_id_prefix=None, **kwargs):
            if workflow_ids:
                return [self.workflows[w] for w in workflow_ids if w in self.workflows]
            return list(self.attempts[workflow_id_prefix.rstrip('/')])
        def event(workflow_id, key, **kwargs):
            if key == 'cases': return self.members.get(workflow_id)
            if key == 'card': return self.cards.get(workflow_id)
            return None
        def steps(workflow_id, **kwargs):
            return self.steps.get(workflow_id, [])
        return SimpleNamespace(list_workflows=rows, get_event=event, list_workflow_steps=steps, destroy=lambda: None)

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

    def test_money_rebooked_as_waste_leaves_the_case_on_the_board_as_in_the_ledger(self):
        # A factory_bug resume rebooks the diagnosed step's money (SqlLedger.book_waste): the board
        # must show it as waste and not as the case's, the same as the ledger's own case balance.
        self.assertTrue(self.ledger.book_waste('case-alpha/1/admit/1', 'factory_bug'))
        alpha = self.read()['cases'][0]
        self.assertEqual(alpha['spend_usd_micros'], {'spent': 3 * M, 'held': 5 * M, 'waste': 3 * M,
                                                    'case_used': 5 * M, 'list_price': 6 * M, 'calls': 5})
        self.assertEqual(alpha['spend_usd_micros']['case_used'],
                         self.ledger.case_balance('b-live', 'case-alpha', 50 * M)['used'])

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

    def test_an_operator_override_and_its_reason_show_on_the_board(self):
        # Founder 2026-11-11: an override resume (engine resume_point) is visible later. Its reason
        # stays on the operator board; the published scorecard row carries none of it.
        self.cards['case-alpha']['override'] = 'factory bug fixed in #122'
        board = self.read()
        alpha, beta = board['cases']
        self.assertEqual((alpha['override'], 'override' in beta), ('factory bug fixed in #122', False))
        self.assertIn('[operator override: factory bug fixed in #122]', render_board(board))
        from durable.report import case_entry
        self.assertNotIn('override', case_entry(self.cards['case-alpha']))

    def test_a_founder_stop_and_its_reason_show_on_the_board(self):
        # A founder stop (engine Engine.reply, FounderAction.STOP) names why the case was retired,
        # on the operator board only.
        self.cards['case-alpha'].update(status='retired', founder_stop='superseded by r2')
        board = self.read()
        alpha, beta = board['cases']
        self.assertEqual((alpha['founder_stop'], 'founder_stop' in beta), ('superseded by r2', False))
        self.assertIn('[stopped by the founder: superseded by r2]', render_board(board))
        from durable.report import case_entry
        self.assertNotIn('founder_stop', case_entry(self.cards['case-alpha']))

    def test_a_raised_case_money_ceiling_and_its_reason_show_on_the_board(self):
        # Founder 2026-11-13: `--extra-case-money` (engine lineage_case_money_extra) is visible later,
        # on the operator board only.
        grant = {'usd_micros': 45 * M, 'reason': 'founder 2026-11-13: let it finish'}
        self.cards['case-alpha']['case_money_extra'] = grant
        board = self.read()
        alpha, beta = board['cases']
        self.assertEqual((alpha['case_money_extra'], 'case_money_extra' in beta), (grant, False))
        self.assertIn('[case money ceiling +$45.00: founder 2026-11-13: let it finish]', render_board(board))
        from durable.report import case_entry
        self.assertNotIn('case_money_extra', case_entry(self.cards['case-alpha']))

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

    def resumed_case(self):
        """case-gamma ran in b-r1, stopped on infra, and resumed in b-r2 under the same case id;
        case-delta sealed in b-r2 and gives the fleet its medians for GATES and SEAL."""
        for batch in ('b-r1', 'b-r2'):
            self.ledger.open(batch, 50 * M)
            self.workflows[batch] = SimpleNamespace(status='PENDING', created_at=0, updated_at=0, input={'args': [{'spec': {}}]})
        self.workflows['b-r1'].status = 'SUCCESS'
        self.before = self.ledger.rows()
        self.members.update({'b-r1': ['case-gamma'], 'b-r2': ['case-gamma@b-r2', 'case-delta']})
        card = dict(passed=[], failed_gate=None, extensions=0, replacement_of=None, reason=None)
        self.cards.update({
            'case-gamma': dict(card, case_id='case-gamma', status='held', stage='writer:1', writer_rounds=1),
            'case-gamma@b-r2': dict(card, case_id='case-gamma', status='running', stage='gates:1', writer_rounds=1),
            'case-delta': dict(card, case_id='case-delta', status='sealed', stage='sealed', writer_rounds=1, hard=False)})
        def run(case, batch, seq, step, n, status, created, started_at, updated, outcome=None, started=True):
            output = {'started': started, 'started_at': started_at}
            if outcome:
                output['result'] = {'outcome': outcome, 'reason': None}
            return attempt(case, batch, seq, step, n, status, created, updated, output if status == 'SUCCESS' else None)
        self.attempts['case-gamma'] = [
            run('case-gamma', 'b-r1', 1, 'admit', 1, 'SUCCESS', 0, 100, 1000, 'ok'),               # setup 100, admit 900
            run('case-gamma', 'b-r1', 2, 'writer:1', 1, 'SUCCESS', 1500, 1500, 4000, 'infra_error'),  # wait 500, lost 2500
            run('case-gamma', 'b-r2', 2, 'writer:1', 2, 'SUCCESS', 10000, 10200, 20000, 'ok'),     # human 6000 (resume)
            run('case-gamma', 'b-r2', 3, 'stress:1', 1, 'SUCCESS', 20000, 20000, 21000, 'provider_limit'),
            run('case-gamma', 'b-r2', 3, 'stress:1', 2, 'SUCCESS', 22000, None, 22500, started=False),  # bound wait
            run('case-gamma', 'b-r2', 3, 'stress:1', 3, 'SUCCESS', 23000, 23000, 26000, 'ok'),
            attempt('case-gamma', 'b-r2', 4, 'gates:1', 1, 'PENDING', 26000, 26000)][::-1]       # running at 30000
        lease = lambda name, at: SimpleNamespace(function_name=name, completed_at_epoch_ms=at)
        self.steps['case-gamma/4/gates:1/1'] = [lease('reserve_step', 26_000_000), lease('lease_step', 26_100_000),
                                                lease('attempt_step', None)]   # leased at 26100, still running
        self.attempts['case-alpha'] = []   # keep the fleet to the two cases below
        self.attempts['case-delta'] = [
            run('case-delta', 'b-r2', 1, 'gates:1', 1, 'SUCCESS', 0, 0, 7000, 'ok'),
            run('case-delta', 'b-r2', 2, 'seal', 1, 'SUCCESS', 7000, 7000, 7200, 'ok')]
        with patch('durable.observation._controller', return_value={'state': 'active'}):
            return read_board(self.config, client=self.client(), now=30_000)

    def test_time_to_seal_spans_resume_batches_and_splits_where_time_went(self):
        board = self.resumed_case()
        rows = [r for r in board['cases'] if r['case'] == 'case-gamma']
        self.assertEqual(sorted(r['batch'] for r in rows), ['b-r1', 'b-r2'])
        t = rows[0]['time_to_seal']
        self.assertTrue(all(r['time_to_seal'] == t for r in rows))   # one clock per case id, not per batch
        self.assertEqual((t['first_attempt_at'], t['elapsed_s']), (0, 30000))
        self.assertEqual(t['steps'], {'admit': {'result': 900}, 'writer': {'lost': 2500, 'result': 9800},
                                      'stress': {'lost': 1000, 'result': 3000}, 'gates': {'running': 3900}})
        self.assertEqual((t['setup_s'], t['wait_s'], t['human_s']), (400, 2500, 6000))
        parts = t['setup_s'] + t['wait_s'] + t['human_s'] + sum(v for p in t['steps'].values() for v in p.values())
        self.assertEqual(parts, t['elapsed_s'])                       # every second is accounted for once
        # GATES median 7000 less the 3900 already running, then SEAL's median 200.
        self.assertEqual((t['projected_remaining_s'], t['budget']), (3300, 'over'))
        delta = next(r for r in board['cases'] if r['case'] == 'case-delta')['time_to_seal']
        self.assertEqual((delta['elapsed_s'], delta['budget']), (7200, 'met'))
        fleet = board['fleet']
        self.assertEqual((fleet['sealed'], fleet['median_s'], fleet['p90_s'], fleet['within_budget']), (1, 7200, 7200, 1))
        self.assertEqual([x['sink'] for x in fleet['top_sinks']],
                         ['writer (result)', 'gates (result)', 'human', 'gates (running)', 'stress (result)'])
        text = render_board(board)
        for expected in ('to seal', '8h20m', 'OVER (+55m)', 'MET', 'TIME TO SEAL (target 6h00m',
                         'median 2h00m', 'Top time sinks: writer (result) 2h43m',
                         'case-gamma: 8h20m = admit 15m, writer 2h43m (lost 41m)'):
            self.assertIn(expected, text)
        self.assertEqual(self.before, self.ledger.rows())   # nothing written

    def test_held_cases_accrue_human_time_and_older_boards_still_render(self):
        from durable.board import _time_to_seal
        span = dict(batch='b', kind='gates', status='SUCCESS', started=True, created_at=0, started_at=0,
                    updated_at=100, outcome='needs_founder', seq=1, attempt=1)
        t = _time_to_seal([span], 'escalated', 'gates:1', 500, {'gates': 50, 'seal': 10})
        self.assertEqual((t['human_s'], t['wait_s'], t['steps'], t['budget']), (400, 0, {'gates': {'result': 100}}, 'on_track'))
        self.assertEqual(t['projected_remaining_s'], 60)
        self.assertIsNone(_time_to_seal([], 'running', 'admit', 500, {}))
        board = self.read()
        for row in board['cases']:
            row.pop('time_to_seal')
        board.pop('fleet')
        self.assertIn('case-alpha', render_board(board))   # a controller without these fields

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
