"""Sealed inventory on the real saved public cards, reports and registry index only."""

# Keep direct execution independent of the working directory.
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))

import builtins
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import sealed_inventory as inv

LEGACY = ('case-20261017T114426Z-fcde6b', 'case-20261017T120256Z-86b100', 'case-20261017T125556Z-18681d')
DRY = 'case-20261014T130816Z-a869de'
SMOKE_DIR = ROOT / 'docs/reports/provisioning-startup-smoke/local-startup'
REPORT = ROOT / 'docs/reports/sealed-audit-20261104.md'
PROPOSAL = ROOT / 'docs/designs/production-manifest-proposal.json'
PACKAGING = ROOT / 'docs/exam-packaging.md'
RESULT = inv.inventory()
BY_CASE = {c['case']: c for c in RESULT['hidden']}


def forbidden(path):
    name = Path(os.fsdecode(path)).name if isinstance(path, (str, bytes, os.PathLike)) else ''
    return name.endswith('.age') or 'key' in name.lower()


@contextlib.contextmanager
def no_secret_reads():
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open
    real_bytes, real_text = Path.read_bytes, Path.read_text
    seen = []

    def guard(original):
        def wrapper(path, *args, **kwargs):
            if forbidden(path):
                raise AssertionError('opened forbidden file: %s' % path)
            seen.append(os.fsdecode(path) if isinstance(path, (str, bytes, os.PathLike)) else path)
            return original(path, *args, **kwargs)
        return wrapper

    with patch('builtins.open', guard(real_open)), patch('io.open', guard(real_io_open)), \
            patch('os.open', guard(real_os_open)), patch.object(Path, 'read_bytes', guard(real_bytes)), \
            patch.object(Path, 'read_text', guard(real_text)):
        yield seen


def round_file(directory, cases):
    path = Path(directory) / 'round.json'
    path.write_text(json.dumps({'arms': ['B', 'C'], 'tries': 2,
                                'cases': [{'archive': f'sealed/{c}.tar.gz.age'} for c in cases]}))
    return path


class InventoryTests(unittest.TestCase):
    def test_counts_and_hashes_match_saved_records(self):
        self.assertEqual(RESULT['counts'], {'hidden': 50, 'excluded': 1, 'public_eligible': 0, 'qualified': 0})
        self.assertEqual([(e['case'], e['reason'], e['hashes']) for e in RESULT['excluded']],
                         [(DRY, 'dry_run', {'vm_20261029': 'match'})])
        self.assertEqual({c['hashes']['vm_20261029'] for c in RESULT['hidden']}, {'match'})  # All 51 cards.
        for row in RESULT['hidden'] + RESULT['excluded']:
            self.assertEqual(row['card_sha256'], hashlib.sha256(
                (ROOT / 'sealed' / (row['case'] + '.scorecard.json')).read_bytes()).hexdigest())
        self.assertNotIn('differs', {c['hashes']['card_20261030'] for c in RESULT['hidden']})
        listed = json.loads((ROOT / 'docs/reports/batch-service-inventory-20261030.json').read_text())
        listed = {e['case'] for side in ('mac', 'vm') for e in listed[side]['checkpoints']}
        self.assertEqual({c['case'] for c in RESULT['hidden'] if c['hashes']['card_20261030'] == 'match'},
                         listed & set(BY_CASE))
        self.assertEqual(RESULT['recorded_elsewhere_20261029'], [
            'case-20261023T223056Z-c7d405', 'case-20261024T043353Z-e15450', 'case-20261024T085209Z-873d7f'])

    def test_legacy_candidates_are_not_eligible(self):
        for case in LEGACY:
            card = BY_CASE[case]
            self.assertFalse(card['public_eligible'] or card['qualified'])
            self.assertEqual(card['metadata'], 'exam requires the same completed fairness checks for every case')
            self.assertIn('fail:metadata', card['findings']['complete_evidence'])
            self.assertEqual(card['criteria']['discoverable'], 'missing:G16')
            self.assertEqual(card['criteria']['complete_evidence'], 'missing:G17')
            self.assertIn('missing:dedup', card['findings']['distinct_bug'])
            self.assertIn('missing:registry-screening', card['findings']['distinct_bug'])
            self.assertEqual(card['hashes']['ciphertext_20261030'], ['mac', 'vm'])
            for key in ('reference_fix', 'legitimate_behavior', 'deterministic_scorer', 'adversarial_checks'):
                self.assertEqual(card['criteria'][key], 'pass')
        self.assertEqual(BY_CASE[LEGACY[0]]['g11_reviews'], [{'status': 'complete', 'verdict': 'checker_false_positive'}])

    def test_rules_on_real_cards_and_registry_entries(self):
        self.assertIn('fail:duplicate_of=case-20261017T212115Z-8acb5c',
                      BY_CASE['case-20261019T022248Z-953035']['findings']['distinct_bug'])
        self.assertEqual(BY_CASE['case-20261018T144339Z-e5caf7']['criteria']['distinct_bug'],
                         'missing:registry-screening')
        self.assertEqual(BY_CASE['case-20261018T144339Z-8f9762']['criteria']['separation'], 'missing:wipe-record')
        self.assertIn('missing:ciphertext-inventory',
                      BY_CASE['case-20261017T212118Z-1ad7fa']['findings']['complete_evidence'])
        entries = json.loads((ROOT / 'sealed/statement-registry/registry.json').read_text())['entries']
        self.assertEqual(inv.registry_cell(entries['case-20261022T223056Z-a4e4d9']), 'fail:registry-released')
        self.assertEqual(inv.registry_cell(entries['case-20261023T081248Z-a36ad8']), 'missing:registry-screening')
        self.assertEqual(inv.registry_cell(None), 'missing:registry-entry')
        for card in RESULT['hidden']:  # Public files can never supply these parts.
            self.assertEqual(card['findings']['separation'][-1], 'unavailable:no-exposure-attestation')
            self.assertEqual(card['findings']['complete_evidence'][-1], 'unavailable:archive-backed-verify_exam')

    def test_snapshot_paths_are_honoured(self):
        # Derived from the real snapshots by removing one case: a case absent from a
        # stale inventory or registry stays non-eligible, never passes.
        case = LEGACY[0]
        inventory = json.loads(inv.CIPHERTEXTS.read_text())
        for side in ('mac', 'vm'):
            inventory[side]['checkpoints'] = [e for e in inventory[side]['checkpoints'] if e['case'] != case]
        registry = json.loads(inv.REGISTRY.read_text())
        del registry['entries'][case]
        with tempfile.TemporaryDirectory() as directory:
            paths = Path(directory) / 'inventory.json', Path(directory) / 'registry.json'
            paths[0].write_text(json.dumps(inventory))
            paths[1].write_text(json.dumps(registry))
            result = inv.inventory(ciphertexts=paths[0], registry_path=paths[1])
            with contextlib.redirect_stdout(io.StringIO()) as out:
                inv.main(['--inventory', str(paths[0]), '--registry', str(paths[1])])
            spec = round_file(directory, [case])
            seen = []
            real = inv.inventory
            with patch.object(inv, 'inventory', lambda *a: seen.append(a) or real(*a)), \
                    contextlib.redirect_stdout(io.StringIO()) as round_out:
                code = inv.main(['--round', str(spec), '--expect', '1',
                                 '--inventory', str(paths[0]), '--registry', str(paths[1])])
        # The round check judges exactly the snapshots it is given, not the dated defaults.
        self.assertEqual(seen, [(inv.ROOT / 'sealed', paths[0], paths[1])])
        self.assertEqual((code, round_out.getvalue()), (1, f'not eligible {case}: missing:dedup\n'))
        self.assertEqual(json.loads(out.getvalue())['inputs']['registry']['path'], str(paths[1]))
        card = {c['case']: c for c in result['hidden']}[case]
        self.assertIn('missing:ciphertext-inventory', card['findings']['complete_evidence'])
        self.assertIn('missing:registry-entry', card['findings']['distinct_bug'])
        self.assertEqual(card['hashes']['card_20261030'], 'not-recorded')
        self.assertNotIn('missing:ciphertext-inventory', BY_CASE[case]['findings']['complete_evidence'])
        self.assertEqual(result['inputs']['ciphertext_inventory']['path'], str(paths[0]))
        self.assertEqual(RESULT['inputs']['ciphertext_inventory']['sha256'],
                         'c59a07542dcf4f0d69ea1390e2045c346d11ab7db57fe4b9fd24be9e7338a928')

    def test_real_smoke_card_is_excluded(self):
        result = inv.inventory(SMOKE_DIR)
        self.assertEqual(result['counts']['hidden'], 0)
        self.assertEqual([(e['case'], e['reason']) for e in result['excluded']],
                         [('case-20261103T220109Z-391cbc', 'dry_run')])

    def test_never_opens_ciphertext_or_key_files(self):
        with no_secret_reads() as seen:
            result = inv.inventory()
            inv.markdown(result)
        self.assertEqual(result['counts'], RESULT['counts'])
        self.assertTrue(any(str(p).endswith('.scorecard.json') for p in seen))
        with self.assertRaises(AssertionError):  # The guard itself works on a real ciphertext.
            with no_secret_reads():
                (ROOT / 'sealed/case-20261017T212118Z-1ad7fa.casekey.age').read_bytes()

    def test_report_table_matches_generated_output(self):
        text = REPORT.read_text()
        table = text.split('<!-- inventory:begin -->\n', 1)[1].split('<!-- inventory:end -->', 1)[0]
        self.assertEqual(table, inv.markdown(RESULT))
        self.assertIn('0 qualified hidden cases', text)

    def test_production_proposal_stays_inactive(self):
        proposal = json.loads(PROPOSAL.read_text())
        self.assertEqual((proposal['status'], proposal['launch_authority']), ('inactive-proposal', False))
        for key in ('money_limit_usd', 'batch_deadline', 'completion_timeouts'):
            self.assertIsNone(proposal[key])
            self.assertIn(key, proposal['founder_required'])
        self.assertEqual(proposal['max_worker_creations_including_retries'], 48)
        self.assertEqual((proposal['per_case_limits']['extensions'], proposal['per_case_limits']['factory_bug_resumes']),
                         (5, 3))
        self.assertEqual(proposal['qualified_hidden_cases_at_proposal'], RESULT['counts']['qualified'])
        self.assertEqual(proposal['historical_yield']['hidden_cards'], RESULT['counts']['hidden'])
        self.assertNotIn('jobs', proposal)
        batches = list((ROOT / 'factory/batches').glob('*.json'))
        self.assertTrue(batches)
        for path in batches:  # Never a loadable batch manifest, nor referenced by one.
            self.assertNotIn(proposal['id'], path.read_text())

    def test_round_check_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            def errors(cases, expect=len(LEGACY)):
                return inv.check_round(round_file(directory, cases), RESULT, expect)
            self.assertEqual(errors(LEGACY), [f'not eligible {c}: missing:dedup' for c in LEGACY])
            self.assertEqual(errors([DRY], 1), [f'not hidden {DRY}: dry_run'])
            self.assertEqual(errors(['case-unknown'], 1), ['unknown case case-unknown'])
            self.assertEqual(errors([LEGACY[0], LEGACY[0]], 2),
                             [f'not eligible {LEGACY[0]}: missing:dedup', f'duplicate {LEGACY[0]}'])
            self.assertEqual(errors(LEGACY, 24)[-1], 'expected 24 cases, got 3')
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(inv.main(['--round', str(round_file(directory, [DRY])), '--expect', '1']), 1)
            self.assertEqual(out.getvalue(), f'not hidden {DRY}: dry_run\n')

    def test_freeze_blocker_list_matches_real_refusal(self):
        loader = importlib.machinery.SourceFileLoader('freeze_under_test', str(ROOT / 'bin/freeze'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        freeze = importlib.util.module_from_spec(spec)
        loader.exec_module(freeze)
        # Same predicate as bin/freeze source_files, without hashing any input, over the
        # committed tree's top-level names so untracked local names (e.g. .claude/) do not count.
        tracked = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True, check=True).stdout
        top = {name.split('/')[0] for name in tracked.decode().split('\0') if name}
        unclassified = sorted(n for n in top
                              if n not in set(freeze.INPUTS) | freeze.EXCLUDED | {'.git', 'results', 'sealed'}
                              and not n.startswith('._'))
        section = PACKAGING.read_text().split('## Known blockers', 1)[1].split('\n- **', 2)[1]
        documented = sorted(re.findall(r'^  - `([^`]+)`$', section, re.M))
        self.assertEqual(unclassified, documented)
        self.assertTrue(unclassified, 'bin/freeze now accepts this tree: remove its Known blockers entry')


if __name__ == '__main__':
    unittest.main()
