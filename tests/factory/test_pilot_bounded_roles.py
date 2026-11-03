"""Offline pilot plan admission; saved public material, synthetic authority and transport."""
import contextlib
from copy import deepcopy
from decimal import Decimal
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import batch_holder as holder
import batch_money as money
import diagnosis_dispatch
import fairness
import model_router as router
import model_runtime
import pilot
import run
import test_batch_holder as fixtures
import token_prices

spec = importlib.util.spec_from_file_location('pilot_qualifier', ROOT / 'tools/qualify-batch-inputs.py')
qualifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualifier)

ROLES = {
    '--builder': 'openrouter/minimax/minimax-m3.1-flash',
    '--attacker': 'openrouter/deepseek/deepseek-v4.1-flash',
    '--reviewer1': 'openrouter/xiaomi/mimo-v2.6-pro',
    '--strong-calibrator': 'claude/claude-opus-4-5-20251101:compact',
    '--easy-calibrator': 'openrouter/deepseek/deepseek-v4.1-flash',
}
CODEX = 'codex/gpt-6.1-sol'


def arguments():
    return ['1', '--source', 'hunt', '--rotation-slot', '1',
            *(item for pair in ROLES.items() for item in pair), '--ttl-hours', '1', '--max-spend', '5']


def worker_args(args):
    """launch.sh consumes the worker count and these host-only pairs."""
    result = []
    iterator = iter(args[1:])
    for arg in iterator:
        if arg in ('--ttl-hours', '--max-spend', '--stall-minutes'):
            next(iterator)
        else:
            result.append(arg)
    return result


def snapshot(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob('*') if p.is_file()}


class PilotRolesTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.HolderTests('test_lifecycle_status_ack_retirement_source_and_replay')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        h = self.h
        h.record['id'] = 'b-real-pilot'
        h.record['replacement_policy']['enabled'] = False
        h.record['money_limit_usd'] = '60.000000000'
        now = datetime.now(timezone.utc)
        h.record.update(target_slots=3, max_concurrency=1,
            batch_deadline=(now + timedelta(hours=5)).isoformat(),
            pilot_admission=dict(schema=1, starts_at=(now - timedelta(minutes=30)).isoformat(),
                max_lifecycles=6, max_lifecycles_per_case=2, infrastructure_limit_usd='5.000000000'))
        environment = patch.dict(os.environ, {})
        environment.start(); self.addCleanup(environment.stop)
        h.record['jobs']['third'] = deepcopy(h.record['jobs']['j'])
        for name, job in h.record['jobs'].items():
            job.update(case='case-b-real-pilot-' + name, requested_total_usd='20.000000000', args=arguments())
        h.policy['jobs'] = deepcopy(h.record['jobs'])
        h.policy['batch'].update(id='b-real-pilot', manifest_path='factory/batches/b-real-pilot.json')
        self.pin()
        with money.locked(h.home, 'b-real-pilot'): pass

    def pin(self):
        h = self.h
        h.policy['jobs'] = deepcopy(h.record['jobs'])
        path = h.root / h.policy['batch']['manifest_path']
        path.write_text(json.dumps(h.record))
        pin = hashlib.sha256(path.read_bytes()).hexdigest()
        h.policy['batch']['manifest_sha256'] = pin
        os.environ['UNBUG_PILOT_PIN'] = pilot.pin(h.policy)
        (h.release / 'source-manifest.json').write_text(json.dumps({'files': {h.policy['batch']['manifest_path']: pin}}))

    def test_all_roles_resolve_to_real_bounded_leases_and_dedup(self):
        args = run.argument_parser().parse_args(worker_args(arguments()))
        args.batch_release_sha256 = 'offline'
        c = SimpleNamespace(args=args, card={})
        models = model_runtime.select_models(c, log=lambda *a: None)
        self.assertEqual(models['builder'], [ROLES['--builder']])
        self.assertEqual(models['easy_calibrator'], [ROLES['--easy-calibrator']])
        self.assertEqual(diagnosis_dispatch.reviewer(c)[0], ROLES['--reviewer1'])
        c.models = models
        fairness.independent(c, run)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); store = router.Store(root / 'router.sqlite', credit_reader=lambda: Decimal('11.63'))
            for role in c.card['roles'].values():
                route = role['model']
                result = store.rpc('acquire', dict(paid_protocol=1, id=uuid.uuid4().hex, model=route,
                    accounts=list(router.ACCOUNTS), role='writer', deadline=time.time() + 3600))
                self.assertEqual(result['kind'], 'lease')
                actual = router.Lease(**{k: v for k, v in result.items() if k != 'kind'})
                self.assertTrue(router.valid_lease(actual, route))
                store.rpc('finish', dict(lease_id=actual.lease_id, outcome='denied', receipt=None))
            c.case = root / 'case'; c.case.mkdir(); c.work = root; c.case_id = 'case-new'
            (c.case / 'statement.md').write_text('Synthetic candidate for dedup.')
            prior = ROOT / 'cases/medusa-oversell-v2/contestant.md'  # Retained public text, authored prior binding.
            with patch.object(run, 'prior_statements', return_value={'case-old': str(prior)}), \
                 patch.object(run, 'retained_answer', return_value={'duplicate_of': None, 'reason': 'distinct'}) as answer, \
                 patch.object(run, 'ensure_freshness', return_value=(True, {})), \
                 patch.object(run, 'idea_realism', return_value=True):
                self.assertTrue(run.statement_precheck(c))
            self.assertEqual(answer.call_args.args[1], [ROLES['--easy-calibrator']])
            self.assertEqual(c.card['dedup']['checked_against'], 1)

    def test_parser_alias_and_override_matrix(self):
        base = arguments()
        cases = [
            ([], True),
            (['--builder-effort', 'high', '--pilot-tries', '2', '--reviewer2-e', 'high'], True),
            (['--writer', CODEX], False), (['--writer=' + CODEX], False), (['--wri', CODEX], False),
            (['--stress-tester', CODEX], False), (['--stress-tester=' + CODEX], False), (['--stress-t', CODEX], False),
            (['--pilot', CODEX], False), (['--pilot=' + CODEX], False), (['--pilo', CODEX], False),
            (['--reviewer2', CODEX], False), (['--reviewer2=' + CODEX], False),
            (['--reviewer2=' + ROLES['--reviewer1']], False), (['--reviewer', CODEX], False),
            (['--builder', CODEX], False), (['--builder=' + CODEX], False), (['--buil', CODEX], False),
            (['--strong-cal', CODEX], False), (['--easy-calibrator', CODEX], False), (['--'], False),
        ]
        for extra, accepted in cases:
            with self.subTest(extra=extra):
                candidate = base + extra
                with contextlib.redirect_stderr(io.StringIO()):
                    try: parsed = run.argument_parser().parse_args(worker_args(candidate))
                    except SystemExit: parsed = None
                if accepted:
                    holder._pilot_roles(candidate)
                    self.assertIsNotNone(parsed)
                    self.assertIsNone(parsed.reviewer2)
                    self.assertEqual((parsed.builder, parsed.attacker, parsed.strong_calibrator, parsed.easy_calibrator),
                        (ROLES['--builder'], ROLES['--attacker'], ROLES['--strong-calibrator'], ROLES['--easy-calibrator']))
                else:
                    with self.assertRaisesRegex(ValueError, '^pilot roles must use pinned bounded routes$'):
                        holder._pilot_roles(candidate)
        for flag in ROLES:
            candidate = base.copy(); candidate[candidate.index(flag) + 1] = CODEX
            parsed = run.argument_parser().parse_args(worker_args(candidate))
            self.assertIn(CODEX, vars(parsed).values())
            with self.assertRaisesRegex(ValueError, '^pilot roles must use pinned bounded routes$'):
                holder._pilot_roles(candidate)

    def test_all_templates_checked_before_first_authority(self):
        h = self.h; base = deepcopy(h.record)
        cases = []
        for flag in ROLES:
            bad = deepcopy(base); args = bad['jobs']['k']['args']; args[args.index(flag) + 1] = CODEX
            cases.append((flag, bad))
        bad = deepcopy(base); args = bad['jobs']['k']['args']; i = args.index('--builder'); del args[i:i+2]
        cases.append(('missing', bad))
        bad = deepcopy(base); del bad['jobs']['k']['args']
        cases.append(('missing args', bad))
        bad = deepcopy(base); bad['jobs']['k']['args'] = None
        cases.append(('invalid args', bad))
        bad = deepcopy(base); del bad['jobs']['k']
        cases.append(('wrong job count', bad))
        bad = deepcopy(base); bad['jobs']['k']['args'] += ['--reviewer2', CODEX]
        cases.append(('reviewer2', bad))
        for label, record in cases:
            with self.subTest(label=label):
                h.record = record; self.pin(); before = snapshot(h.home)
                report = qualifier.qualify(h.policy, h.root, h.home, 'j')
                shape_error = label in ('missing args', 'invalid args', 'wrong job count')
                self.assertFalse(report['eligible'])
                self.assertEqual(report['observation'], 'journal_absent' if shape_error else holder.PILOT_ROLE_ERROR)
                with self.assertRaisesRegex(ValueError, '^request_refused$' if shape_error else '^pilot roles must use pinned bounded routes$'):
                    holder.reserve(h.policy, h.root, h.home, 'j', None)
                self.assertEqual(snapshot(h.home), before)
        h.record = base; self.pin()
        before = snapshot(h.home)
        with patch.object(router, 'route_maximum', return_value=None):
            self.assertEqual(qualifier.qualify(h.policy, h.root, h.home, 'j')['observation'], holder.PILOT_ROLE_ERROR)
            with self.assertRaisesRegex(ValueError, '^pilot roles must use pinned bounded routes$'):
                holder.reserve(h.policy, h.root, h.home, 'j', None)
        self.assertEqual(snapshot(h.home), before)
        self.assertTrue(qualifier.qualify(h.policy, h.root, h.home, 'j')['eligible'])
        op = holder.reserve(h.policy, h.root, h.home, 'j', None)
        self.assertEqual(op['authority']['committed_total_usd'], '20.000000000')
        self.assertEqual(holder.reserve(h.policy, h.root, h.home, 'j', None), op)
        directory = h.home / 'batches/b-real-pilot'
        ops = holder._operations(directory, h.record, h.policy)
        state = money.load_locked(directory, h.record, h.policy['batch']['manifest_sha256'])
        bad = deepcopy(h.record); bad['jobs']['k']['args'] += ['--reviewer2', CODEX]
        before_state = deepcopy(state); before = snapshot(h.home)
        with self.assertRaisesRegex(ValueError, '^pilot roles must use pinned bounded routes$'):
            holder._admit(directory, bad, h.policy, h.root, h.home, ops, state, 'j', None)
        self.assertEqual(state, before_state); self.assertEqual(snapshot(h.home), before)
        real_resolve = holder.service.resolve_job
        def changed_selected(record, name):
            resolved = real_resolve(record, name)
            resolved['template']['args'] += ['--reviewer2', CODEX]
            return resolved
        with patch.object(holder.service, 'resolve_job', side_effect=changed_selected), \
             self.assertRaisesRegex(ValueError, '^pilot roles must use pinned bounded routes$'):
            holder._admit(directory, h.record, h.policy, h.root, h.home, ops, state, 'j', None)
        self.assertEqual(state, before_state); self.assertEqual(snapshot(h.home), before)

    def test_legacy_authorizer_refuses_pilot_without_optional_schema(self):
        h = self.h
        self.assertNotIn('practice_admission', h.record)
        with self.assertRaises(money.MoneyWait):
            money.authorize(h.policy, 'j', None, h.root, h.home)
        # No unrelated legacy batch is narrowed by the pilot rule.
        h.record['id'] = 'legacy'
        for name, job in h.record['jobs'].items(): job['case'] = 'case-legacy-' + name
        h.policy['batch'].update(id='legacy', manifest_path='factory/batches/legacy.json')
        self.pin()
        self.assertEqual(money.authorize(h.policy, 'j', None, h.root, h.home)['committed_total_usd'], '20.000000000')

    def test_saved_preflight_receipt_price_illustration(self):
        card = json.loads((ROOT / 'tests/factory/fixtures/canary6-round8-collected-card.json').read_text())
        event, = [e for e in card['continuation_budget']['events'] if e.get('invocation') == 'strong-calibrator-provider-preflight']
        tokens = event['tokens']; incoming = tokens['input_tokens']; cached = tokens['cached_input_tokens']
        codex = Decimal(str(token_prices.codex_cost(CODEX, tokens))).quantize(Decimal('.0000000001'))
        claude = (Decimal(incoming - cached) * 5 + Decimal(cached) * Decimal('.5') + Decimal(tokens['output_tokens']) * 25) / 1_000_000
        self.assertEqual(codex, Decimal('0.0042488'))
        self.assertEqual(claude - codex, Decimal('0.0086452'))


if __name__ == '__main__': unittest.main()
