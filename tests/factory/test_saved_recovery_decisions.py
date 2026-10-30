"""Replay untouched, real public cards. No archives, keys, holders or launches."""
import gzip
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'factory'))
import recovery
import founder_ruling
import restore_ledger
import restart
import run
import g11_review
from budget import case_spending
from carry_over import Refused, digest, load

FIXTURES = Path(__file__).parent / 'fixtures'


def cards():
    return json.loads(gzip.decompress((FIXTURES / '20261029-real-public-cards.json.gz').read_bytes()))


def decisions(card):
    argv = [part for key, value in (card.get('recovery_config') or {}).items()
            if key in ('case_budget', 'rounds', 'max_total_calls', 'max_cost', 'max_role_calls')
            for part in ('--' + key.replace('_', '-'), str(value))]
    result = dict(freshness_retry=recovery.freshness_retry_stop(card),
                  gate_only=recovery.gate_only_continuation(card),
                  exhausted_pause=recovery.paused_rounds_exhausted(card),
                  adopter=recovery.adopter_stop_reason(card),
                  spent=case_spending(card.get('continuation_budget'), card.get('models_used')))
    for route in ('restart', 'holder'):
        try:
            value = (recovery.require_restart_stop(card, argv) if route == 'restart' else
                     recovery.require_holder_stop(card, argv, 'review' if card.get('kind') == 'g11-independent-review' else 'case'))
            result[route] = dict(eligible=True, result=value,
                                ledger_agrees=recovery.ledger_agrees(card, route=route))
        except ValueError as error:
            result[route] = dict(eligible=False, reason=str(error))
    try:
        state = load(card)
        result['carry_over'] = state['admission']
    except Refused as error:
        result['carry_over'] = dict(admitted=False, reasons=[str(error)])
    return result


def snapshot():
    return [dict(source=row['source'], name=row['name'], generation=row['card'].get('sha256'),
                 card_sha256=digest(row['card']), decisions=decisions(row['card'])) for row in cards()]


class SavedRecoveryTests(unittest.TestCase):
    def test_all_real_cards_preserve_public_decisions_and_accounting(self):
        expected = json.loads((FIXTURES / '20261029-recovery-before.json').read_text())
        # Stream D's Decimal valuation drops only these three empty legacy
        # labels. Keep the captured evidence/snapshot unchanged and pin the exact
        # migration; all totals and every recovery/scientific decision still match.
        empty_legacy = {
            'case-20261019T061510Z-6a8a7d.scorecard.json': '3aa4b30d5f43251d1f19d3fa0ad60d0a8aaf2b4271f314bb803ad655e23bdc25',
            'case-20261020T094950Z-cae763.scorecard.json': '843a6eb5676bade7bfa8a49424b879237a33b5bdf8b11ebded02a46c1a94e4c7',
            'case-20261020T094956Z-055481.scorecard.json': '65eff8b973c0220a4b69578dbc177c2b68b2c3bb9a8a07d36b414060699236e2'}
        for row in expected:
            if row['name'] in empty_legacy:
                self.assertEqual(row['card_sha256'], empty_legacy[row['name']])
                self.assertEqual(row['decisions']['spent']['breakdown_by_role'].pop('legacy_unattributed'), 0)
        self.assertEqual(snapshot(), expected)

    def test_latest_live_cards_require_a_freshness_ruling(self):
        live = [row['card'] for row in cards() if row['source'] == 'bundles']
        self.assertEqual(len(live), 2)
        for card in live:
            self.assertFalse(recovery.freshness_retry_stop(card))
            self.assertFalse(decisions(card)['restart']['eligible'])
            self.assertFalse(decisions(card)['holder']['eligible'])

    def test_live_applied_authority_carries_without_reinstalling_old_grants(self):
        # Exercise the accounting boundary with real public metadata only.
        # This cannot prove what is inside either encrypted archive.
        for row in cards():
            if row['source'] != 'bundles': continue
            card = row['card']
            with self.subTest(case=card['case']), tempfile.TemporaryDirectory() as temp:
                home = Path(temp)
                work = home / 'work' / card['case']; work.mkdir(parents=True)
                (work / 'scorecard.json').write_text(json.dumps(card))
                applied = card['founder_ruling']
                (work / 'founder-ruling-applied.json').write_text(json.dumps(applied))
                ledger, imported = restore_ledger.authenticate(work, card['case'], card['sha256'], card)
                self.assertEqual(ledger, card['continuation_budget'])
                self.assertTrue(imported['ruling_carried_forward'])
                sealed = home / 'sealed'; sealed.mkdir()
                (sealed / (card['case'] + '.restore-accounting.json')).write_text(json.dumps(imported))
                limits = card['recovery_config']
                c = SimpleNamespace(work=work, case_id=card['case'], card={},
                    ledger=sealed / (card['case'] + '.continuation-budget.json'),
                    args=SimpleNamespace(case_budget=limits['case_budget'], rounds=limits['rounds']))
                self.assertEqual(founder_ruling.context(c), applied)
                # Raw v1/v2 grant installation is retired, even with a matching file pin.
                ruling = home / 'ruling.json'
                ruling.write_text(json.dumps(applied['authorization']['record']))
                import hashlib
                with self.assertRaisesRegex(Refused, 'retired'):
                    founder_ruling.authenticate(ruling, hashlib.sha256(ruling.read_bytes()).hexdigest(),
                                               card['case'], card['sha256'], card)

    def test_planner_uses_real_saved_call_cap_when_flag_was_omitted(self):
        card = next(row['card'] for row in cards()
                    if row['source'] == 'bundles' and row['card']['case'].endswith('e15450'))
        self.assertGreater(card['continuation_budget']['calls'], 1000)
        self.assertEqual(card['recovery_config']['max_total_calls'], 5000)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            public = root / (card['case'] + '.scorecard.json')
            public.write_text(json.dumps(card))
            (root / (card['case'] + '.checkpoint.tar.gz.age')).write_bytes(b'opaque test transport')
            # Isolate the cap check: actual archive authentication and the completed
            # unresolved freshness stop remain blocked in the real-card replay above.
            with patch.object(restart, 'require_restart_stop'), patch.object(restart, 'hashlib') as hashes:
                hashes.sha256.return_value.hexdigest.return_value = card['sha256']
                args = '--case-budget 70 --rounds 10'
                self.assertEqual(restart.plan(public, 0, 7200, args)[0], card['case'])
                with self.assertRaisesRegex(ValueError, 'exhausted cumulative usage'):
                    restart.plan(public, 0, 7200, args + ' --max-total-calls 1000')
                old = {**card, 'recovery_config': {k: v for k, v in card['recovery_config'].items()
                                                if k != 'max_total_calls'}}
                public.write_text(json.dumps(old))
                with self.assertRaisesRegex(ValueError, 'exhausted cumulative usage'):
                    restart.plan(public, 0, 7200, args)

    def test_runner_preserves_saved_or_legacy_cap_before_any_audit_call(self):
        self.assertEqual(run.argument_parser().parse_args([]).max_total_calls, 5000)
        for row in cards():
            if row['source'] != 'bundles': continue
            card = row['card']
            with tempfile.TemporaryDirectory() as temp:
                home = Path(temp); work = home / 'work' / card['case']
                (work / 'case').mkdir(parents=True)
                public = work / 'scorecard.json'
                for saved, flags, expected in ((card, [], 5000), (card, ['--max-total-calls=2000'], 2000),
                        ({**card, 'recovery_config': {}}, [], 1000)):
                    public.write_text(json.dumps(saved))
                    argv = ['run.py', '--source', card['source'], '--resume', card['case'],
                            '--resume-bench-sha', 'trusted', '--audit-g11', *flags]
                    with patch.object(sys, 'argv', argv), patch.object(run, 'HOME', home), \
                         patch.object(run, 'bench_manifest', return_value='trusted'), \
                         patch.object(g11_review, 'review') as audit:
                        run.main()
                        self.assertEqual(audit.call_args.args[0].args.max_total_calls, expected)

    def test_standalone_audit_continuation_uses_its_real_saved_limits(self):
        for row in cards():
            if row['source'] != 'vm' or row['card'].get('kind') != 'g11-independent-review': continue
            card = row['card']
            with tempfile.TemporaryDirectory() as temp:
                home = Path(temp); work = home / 'work' / card['case'] / 'g11-audit'
                (work / 'case').mkdir(parents=True)
                (work / 'scorecard.json').write_text(json.dumps(card))
                argv = ['run.py', '--source', 'port', '--resume', card['case'],
                        '--resume-bench-sha', 'trusted', '--continue-g11-review']
                with patch.object(sys, 'argv', argv), patch.object(run, 'HOME', home), \
                     patch.object(run, 'bench_manifest', return_value='trusted'), \
                     patch.object(g11_review, 'review') as audit:
                    run.main()
                    self.assertEqual(audit.call_args.args[0].args.max_total_calls, card['limits']['max_total_calls'])


if __name__ == '__main__':
    unittest.main()
