"""Capped Codex route for the strong calibrator (2026-11-08): list-price maximum, no gate, Codex's own
per-request usage booked live so a reserved call stops mid-turn once it passes its maximum."""
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import budget
import model_call_gate
import model_router
from budget import BudgetError
from token_prices import CODEX_PROFILES, codex_cost

CODEX = 'codex/gpt-6.1-sol'


def lease(maximum=None, **fields):
    m = maximum or model_router.route_maximum(CODEX)
    return SimpleNamespace(lease_id=uuid.uuid4().hex, route=CODEX, account='codex-auth.json', pool='codex-auth.json',
                           family='openai', billing='subscription', **{**m, **fields})


def token_count(n, input_tokens, output_tokens, cached=0):
    last = {'input_tokens': input_tokens, 'cached_input_tokens': cached, 'output_tokens': output_tokens}
    return json.dumps({'type': 'event_msg', 'payload': {'type': 'token_count',
                       'info': {'last_token_usage': last, 'total_token_usage': {'n': n}}}})


# A stand-in for `codex exec --json`: it writes one session-log request every `pause` seconds, then ends
# the turn with the sum the real CLI reports.
CLI = r'''
import json, sys, time
log, requests, pause, report = sys.argv[1], json.loads(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
say = lambda e: (print(json.dumps(e)), sys.stdout.flush())
def write(n, i, o):
    with open(log, 'a') as f:
        f.write(json.dumps({'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {
            'last_token_usage': {'input_tokens': i, 'cached_input_tokens': 0, 'output_tokens': o},
            'total_token_usage': {'n': n}}}}) + '\n')
say({'type': 'thread.started', 'thread_id': 't'}); say({'type': 'turn.started'})
total = {'input_tokens': 0, 'cached_input_tokens': 0, 'output_tokens': 0}
for n, (i, o) in enumerate(requests):
    if report == 'live': write(n, i, o)
    total['input_tokens'] += i; total['output_tokens'] += o
    say({'type': 'item.completed', 'item': {'type': 'command_execution'}})
    time.sleep(pause)
say({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'done'}})
say({'type': 'turn.completed', 'usage': total})
if report == 'late':   # the log writer lags the turn's end
    time.sleep(0.3)
    for n, (i, o) in enumerate(requests): write(n, i, o)
    time.sleep(0.5)
'''


class CodexRoute(unittest.TestCase):
    def test_the_route_is_bounded_at_list_price_and_funding_only_lowers_it(self):
        maximum = model_router.route_maximum(CODEX)
        self.assertEqual((maximum['max_usd'], maximum['max_input_tokens'], maximum['max_output_tokens']),
                         (float(CODEX_PROFILES[CODEX]), 12_500_000, 3_333_333))
        self.assertIn('self-reported', maximum['price_source'])
        funded = model_router.funded_maximum(CODEX, '7.5')
        self.assertEqual(funded['max_usd'], 7.5)
        self.assertTrue(model_router.valid_maximum(vars(lease(funded))))
        self.assertEqual(model_router.funded_maximum(CODEX, '500')['max_usd'], 50.0)   # never above the profile
        self.assertFalse(model_router.valid_maximum(vars(lease(max_usd=60.0))))
        # Only the priced Codex model qualifies; any other stays unbounded.
        self.assertIsNone(model_router.route_maximum('codex/gpt-unknown'))
        self.assertEqual([r['route'] for r in model_router._bounded_routes(CODEX, model_router.ACCOUNTS)], [CODEX])

    def test_the_strong_calibrator_is_leased_codex_behind_the_wall(self):
        import model_runtime
        c = SimpleNamespace(models={'builder': ['claude/claude-opus-5-5'], 'attacker': ['opencode/minimax-m3.1-flash-free'],
                                    'strong_calibrator': [CODEX], 'easy_calibrator': ['openrouter/z-ai/glm-5.3-flash'],
                                    'reviewers': [['openrouter/xiaomi/mimo-v2.6-pro']]})
        model_runtime.require_bounded_models(c)
        runtime = model_runtime.ModelRuntime(Path('/nonexistent'), None, None, None, None)
        seen = []
        def await_lease(role, context, deadline=None):
            seen.append((role, getattr(context, 'router_excluded', ())))
            raise RuntimeError('stop before dispatch')
        with mock.patch.object(model_router, 'await_lease', await_lease):
            with self.assertRaisesRegex(RuntimeError, 'stop before dispatch'):
                runtime._call(SimpleNamespace(card={}), [CODEX], 'x', '/', 'strong-calibrator-1', user='pilot')
        self.assertEqual(seen, [('strong_calibrator', ())])
        with tempfile.TemporaryDirectory() as tmp:
            store = model_router.Store(Path(tmp) / 'router.sqlite')
            with mock.patch.object(model_router, 'SECRETS', Path(tmp)):
                (Path(tmp) / 'codex-auth.json').write_text('{}')
                result = store.rpc('acquire', dict(id=uuid.uuid4().hex, model=CODEX, accounts=['codex-auth.json'],
                                                   role='strong_calibrator', deadline=2e9, funding_usd='20'))
        self.assertEqual((result['kind'], result['route'], result['account'], result['max_usd']),
                         ('lease', CODEX, 'codex-auth.json', 20.0))

    def test_enforce_runs_codex_without_a_gate_in_a_clean_environment(self):
        cap = model_call_gate.empty_usage(CODEX)
        env = {'PATH': '/bin', 'HOME': '/h', 'CODEX_HOME': '/scratch', 'OPENAI_API_KEY': 'x', 'OPENROUTER_API_KEY': 'r',
               'CLAUDE_CODE_OAUTH_TOKEN': 'c', 'FACTORY_ROUTER_TOKEN': 't'}
        cancel = threading.Event()
        with model_call_gate.enforce(lease(), env, cap, 5, cancel, user='pilot') as call:   # walled: allowed
            self.assertFalse(call.is_set())
            cancel.set()
            self.assertTrue(call.is_set())
        self.assertEqual(env, {'PATH': '/bin', 'HOME': '/h', 'CODEX_HOME': '/scratch'})
        # Passing the reservation is this call's cap, as a Claude gate's exhaustion is.
        with self.assertRaisesRegex(BudgetError, '^model_call_cap$'):
            with model_call_gate.enforce(lease(), {'CODEX_HOME': '/s'}, cap, 5, None):
                raise BudgetError('usage_reservation_exceeded')
        with self.assertRaisesRegex(BudgetError, '^timeout$'):
            with model_call_gate.enforce(lease(), {'CODEX_HOME': '/s'}, cap, 5, None):
                raise BudgetError('timeout')
        with self.assertRaisesRegex(BudgetError, 'route_feature_unsupported'):
            with model_call_gate.enforce(lease(), {'PATH': '/bin'}, cap, 5, None): pass
        with self.assertRaisesRegex(BudgetError, 'unbounded_route'):
            with model_call_gate.enforce(lease(max_usd=60.0), {'CODEX_HOME': '/s'}, cap, 5, None): pass

    def run_cli(self, tmp, requests, maximum='50', pause=0.0, report='live', poll=0, feed=True):
        tmp = Path(tmp)
        script, log = tmp / 'cli.py', tmp / 'rollout.jsonl'
        script.write_text(CLI)
        log.touch()
        path = tmp / f'ledger-{uuid.uuid4().hex}.json'
        path.write_text(json.dumps({'calls': 0, 'events': [], 'cost': 0}))
        attempt = SimpleNamespace(key='case/1/strong/1', baseline_spent_usd=0, ceiling_usd=Decimal(100))
        held = lease(model_router.funded_maximum(CODEX, maximum))
        row = budget.reserve_invocation(path, held, Decimal(str(held.max_usd)), attempt=attempt,
                                        operation_id=str(uuid.uuid4()), call_name='strong-calibrator-1')
        error = None
        with mock.patch.object(budget, 'CODEX_FEED_SECONDS', poll), mock.patch.object(budget, 'CODEX_TURN_READ_PAUSE', 0):
            try:
                budget.run_budgeted([sys.executable, str(script), str(log), json.dumps(requests), str(pause), report],
                                    str(tmp), {'PATH': '/bin:/usr/bin'}, tmp / 'out.jsonl', path, 60, driver='codex',
                                    configured_model=CODEX, containment=False, concurrent=True, max_calls=1000, max_cost=None,
                                    attempt=attempt, invocation_id=row['invocation_id'], lease_id=row['lease_id'],
                                    usage_feed=(lambda: log.read_text()) if feed else None)
            except BudgetError as caught: error = caught
        ledger = json.loads(path.read_text())
        mine = [e for e in ledger['events'] if e.get('lease_id') == row['lease_id']]
        return error, mine, ledger, row

    def test_a_long_turn_stops_mid_way_once_its_booked_value_passes_the_maximum(self):
        # Each request books $0.30 at list price; a $1 call must stop at the fourth, long before the turn ends.
        with tempfile.TemporaryDirectory() as tmp:
            error, events, ledger, row = self.run_cli(tmp, [[100_000, 10_000]] * 40, maximum='1', pause=0.05)
            self.assertEqual(str(error), 'usage_reservation_exceeded')
            self.assertTrue(all(e.get('codex_request') for e in events))              # no turn ever ended
            self.assertLessEqual(len(events), 6)
            booked = sum(Decimal(str(e['estimated_subscription_cost_usd'])) for e in events)
            self.assertGreater(booked, Decimal(1))
            self.assertNotIn('turn.completed', (Path(tmp) / 'out.jsonl').read_text())
            self.assertEqual(budget.reservation_booked(ledger, row['lease_id'], ledger['invocation_reservations'][row['lease_id']]), booked)

    def test_a_finished_turn_books_each_request_once_at_its_own_tariff(self):
        requests = [[300_000, 20_000], [50_000, 5_000]]   # one long-context request, one short
        with tempfile.TemporaryDirectory() as tmp:
            error, events, ledger, row = self.run_cli(tmp, requests)
            self.assertIsNone(error)
            per_request = sum(Decimal(str(codex_cost(CODEX, {'input_tokens': i, 'cached_input_tokens': 0, 'output_tokens': o})))
                              for i, o in requests)
            booked = sum(budget.event_charge(e) for e in events)
            self.assertEqual(booked, per_request)
            turn = [e for e in events if 'turn_usage' in e]
            self.assertEqual(len(turn), 1)
            self.assertEqual(turn[0]['tokens'], {'input_tokens': 0, 'cached_input_tokens': 0, 'output_tokens': 0})
            self.assertEqual(turn[0]['turn_usage'], {'input_tokens': 350_000, 'cached_input_tokens': 0, 'output_tokens': 25_000})

    def test_tokens_the_session_log_never_showed_are_booked_at_the_long_context_tariff(self):
        with tempfile.TemporaryDirectory() as tmp:
            error, events, *_ = self.run_cli(tmp, [[50_000, 5_000]], report='none')
            self.assertIsNone(error)
            [turn] = events
            self.assertEqual(Decimal(str(turn['estimated_subscription_cost_usd'])),
                             Decimal(str(codex_cost(CODEX, turn['tokens'], True))))
            self.assertGreater(turn['estimated_subscription_cost_usd'], codex_cost(CODEX, turn['tokens']))

    def test_the_cap_crossed_at_a_turns_end_books_each_token_once(self):
        # Review: with no poll during the turn, the end's read crosses the cap; the turn total
        # must not then be booked again on top of the requests.
        with tempfile.TemporaryDirectory() as tmp:
            error, events, *_ = self.run_cli(tmp, [[100_000, 10_000]] * 4, maximum='1', poll=3600)
            self.assertEqual(str(error), 'usage_reservation_exceeded')
            booked = sum(budget.event_charge(e) for e in events)
            self.assertEqual(booked, 4 * Decimal(str(codex_cost(CODEX, {'input_tokens': 100_000, 'cached_input_tokens': 0,
                                                                        'output_tokens': 10_000}))))

    def test_a_log_that_lags_the_turn_is_booked_once_and_is_not_zero_tokens(self):
        requests = [[50_000, 5_000]] * 4
        with tempfile.TemporaryDirectory() as tmp:
            error, events, *_ = self.run_cli(tmp, requests, report='late')
            self.assertIsNone(error)
            turn = [e for e in events if 'turn_usage' in e][0]
            # The turn's end could not see the requests: all of it at the long-context tariff, once.
            self.assertEqual(sum(budget.event_charge(e) for e in events),
                             Decimal(str(codex_cost(CODEX, turn['tokens'], True))))
            self.assertTrue(all(e['tokens']['input_tokens'] == 0 for e in events if e.get('codex_request')))

    def test_an_unreserved_codex_call_is_held_to_its_lease_maximum(self):
        # Review: outside the engine there is no reservation, so the call's own booked value is capped.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            script, log = tmp / 'cli.py', tmp / 'rollout.jsonl'
            script.write_text(CLI); log.touch()
            with mock.patch.object(budget, 'CODEX_FEED_SECONDS', 0):
                with self.assertRaisesRegex(BudgetError, 'usage_reservation_exceeded'):
                    budget.run_budgeted([sys.executable, str(script), str(log), json.dumps([[100_000, 10_000]] * 40), '0.05', 'live'],
                                        str(tmp), {'PATH': '/bin:/usr/bin'}, tmp / 'out.jsonl', tmp / 'ledger.json', 60,
                                        driver='codex', configured_model=CODEX, containment=False, max_calls=1000,
                                        usage_feed=lambda: log.read_text(), call_cap_usd=1.0)
            self.assertLessEqual(len(json.loads((tmp / 'ledger.json').read_text())['events']), 6)
            with self.assertRaisesRegex(BudgetError, 'unbounded_route'):   # live usage with nothing to hold it to
                budget.run_budgeted(['true'], str(tmp), {}, tmp / 'out.jsonl', tmp / 'ledger2.json', 30, driver='codex',
                                    configured_model=CODEX, containment=False, usage_feed=lambda: '')

    def test_an_unreadable_session_log_stops_the_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path = tmp / 'ledger.json'
            path.write_text(json.dumps({'calls': 0, 'events': [], 'cost': 0}))
            attempt = SimpleNamespace(key='case/1/strong/1', baseline_spent_usd=0, ceiling_usd=Decimal(100))
            held = lease()
            row = budget.reserve_invocation(path, held, Decimal(str(held.max_usd)), attempt=attempt,
                                            operation_id=str(uuid.uuid4()), call_name='strong-calibrator-1')
            reads = []
            with mock.patch.object(budget, 'CODEX_FEED_SECONDS', 0):
                with self.assertRaisesRegex(BudgetError, 'missing_usage'):
                    budget.run_budgeted([sys.executable, '-c', 'import time; time.sleep(5)'], str(tmp), {'PATH': '/bin:/usr/bin'},
                                        tmp / 'out.jsonl', path, 30, driver='codex', configured_model=CODEX, max_cost=None,
                                        containment=False, concurrent=True, attempt=attempt, invocation_id=row['invocation_id'],
                                        lease_id=row['lease_id'], usage_feed=lambda: reads.append(1))
            self.assertEqual(len(reads), budget.CODEX_FEED_FAILURES + 1)   # a few misses are tolerated; the last is the stop's read
        with self.assertRaises(ValueError):
            budget.run_budgeted(['true'], '/', {}, '/dev/null', '/tmp/x', 1, driver='opencode', usage_feed=lambda: '')

    def test_the_runtime_feed_reads_the_session_logs_and_tolerates_none_yet(self):
        import model_runtime
        with tempfile.TemporaryDirectory() as tmp:
            feed = model_runtime.codex_usage_feed(Path(tmp))
            self.assertEqual(feed(), '')                                  # no sessions directory yet
            day = Path(tmp) / 'sessions/2026/11/08'; day.mkdir(parents=True)
            (day / 'rollout-a.jsonl').write_text(token_count(0, 1, 2) + '\n')
            (day / 'other.json').write_text('ignored')
            self.assertEqual(budget.codex_request_usages(feed()),
                             [{'input_tokens': 1, 'cached_input_tokens': 0, 'output_tokens': 2}])
            # Review of #50: a log that cannot be read is a failed read, never "no usage yet".
            bin_dir = Path(tmp) / 'bin'; bin_dir.mkdir()
            (bin_dir / 'cat').write_text('#!/bin/sh\necho "cat: permission denied" >&2\nexit 1\n')
            (bin_dir / 'cat').chmod(0o755)
            with mock.patch.dict('os.environ', {'PATH': f"{bin_dir}:{os.environ['PATH']}"}):
                self.assertIsNone(feed())
            if os.geteuid() != 0:                                         # root reads a mode-000 file anyway
                (day / 'rollout-a.jsonl').chmod(0)
                self.assertIsNone(feed())
                (day / 'rollout-a.jsonl').chmod(0o600)
            (day / 'rollout-a.jsonl').write_text('{"type": "event_msg"}\n')   # readable, no usage yet
            self.assertEqual(feed(), '')
        sudo = model_runtime.codex_usage_feed(Path('/home/pilot/.cache/x'), 'pilot')
        with mock.patch.object(model_runtime.subprocess, 'run') as run:
            run.return_value = SimpleNamespace(returncode=1, stdout=b'')
            self.assertIsNone(sudo())                                     # unreadable: the budget stops the call
        self.assertEqual(run.call_args.args[0][:5], ['sudo', '-n', '-H', '-u', 'pilot'])
        # A walled user can't enter the runner's home: find exits non-zero restoring its start directory
        # (10 Nov, 86b100's G16 Codex calls), so the read always starts at /.
        self.assertEqual(run.call_args.kwargs.get('cwd'), '/')


if __name__ == '__main__':
    unittest.main()
