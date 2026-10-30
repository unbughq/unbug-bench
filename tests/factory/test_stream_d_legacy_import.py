"""Unwired import replay on real saved ledgers; authored restore-layout controls.

No manifest approval, decryption, cloud or model is exercised. These tests do
not close Murphy rows or qualify B's future adoption of the proposed record.
"""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import budget
import carry_over as migration
import diagnosis
import restore_ledger


def card(name='canary6-collected-card.json'):
    return json.loads((ROOT / 'tests/factory/fixtures' / name).read_text())


def authorized(source):
    # Authored exact approval input; this is not a real founder authorization.
    result = migration.legacy_import_dry_run(source)
    result['founder_authorized_total_usd'] = result['estimated_total_usd']
    return result


class LegacyImportTests(unittest.TestCase):
    def test_real_anonymous_markers_charge_once_preserving_ledger_and_calls(self):
        for name, known, final in (
                ('canary6-collected-card.json', '27.072383602', '60.072383602'),
                ('c7d405-collected-card.json', '38.942747230', '71.942747230')):
            with self.subTest(card=name):
                source = card(name); before = copy.deepcopy(source)
                proposal = migration.legacy_import_dry_run(source)
                self.assertEqual((proposal['known_total_usd'], proposal['estimated_total_usd']), (known, final))
                self.assertEqual(proposal['unresolved_invocation_count'], 1)
                self.assertIsNone(proposal['founder_authorized_total_usd'])
                with self.assertRaises(migration.Refused): migration.migrate_legacy_import(source, proposal)
                record = authorized(source)
                result = migration.migrate_legacy_import(source, record)
                self.assertEqual(migration.migrate_legacy_import(source, record), result)
                self.assertEqual(source, before)
                old, new = source['continuation_budget'], result['continuation_budget']
                self.assertEqual(new['events'][:-1], old['events'])
                self.assertEqual(new['calls'], old['calls'])
                self.assertEqual(new.get('infrastructure_waste'), old.get('infrastructure_waste'))
                self.assertEqual(result['builder_rounds'], source['builder_rounds'])
                self.assertEqual(new['events'][-1], dict(
                    id='legacy-import:' + record['import_id'] + ':' + record['unresolved_invocations'][0]['invocation_id'],
                    kind='legacy_import_estimate', role='legacy_import', configured_model='legacy-unknown',
                    cost=0, list_cost_usd=33, estimated_subscription_cost_usd=0, calls=0))
                migration.usage_facts(new)
                self.assertEqual(format(budget.usd(budget.case_spending(new)['total_spent_usd']), '.9f'), final)
                self.assertEqual(result['case_budget'], budget.case_spending(new))
                self.assertEqual(result['terminal_stop'], 'retired_import_estimate')
                self.assertEqual(result['status'], 'retired')
                self.assertIsNone(diagnosis.pending_projection(result))
                self.assertNotIn('job_money', result)

    def test_real_resolved_waste_markers_are_not_estimated_again(self):
        for name, known in (
                ('canary6-confirm-timeout-card.json', '43.091763729'),
                ('c7d405-confirm-timeout-card.json', '59.241735101'),
                ('canary6-last-legacy-card.json', '43.166938577')):
            with self.subTest(card=name):
                source = card(name); record = authorized(source)
                self.assertEqual(record['known_total_usd'], known)
                self.assertEqual(record['unresolved_invocation_count'], 0)
                result = migration.migrate_legacy_import(source, record)
                self.assertEqual(result['continuation_budget'], source['continuation_budget'])
                self.assertEqual(result['terminal_stop'], 'retired_import_history_unknown')
                self.assertEqual(result['status'], 'retired')
                self.assertEqual(result['case_budget']['total_spent_usd'], float(known))
                self.assertIn('legacy_import', migration.FACTS)

    def test_dry_run_shows_330_and_separates_refused_cases_and_duplicate_generations(self):
        source = card(); source['continuation_budget']['unpriced_invocations'] *= 10
        proposal = migration.legacy_import_dry_run(source)
        self.assertEqual(proposal['unresolved_invocation_count'], 10)
        self.assertEqual(proposal['estimated_added_usd'], '330.000000000')
        self.assertEqual(len({r['invocation_id'] for r in proposal['unresolved_invocations']}), 10)
        invalid = card('c7d405-collected-card.json')
        invalid['continuation_budget']['active'] = ['unidentified-process']
        batch = migration.legacy_import_batch_dry_run([source, invalid])
        self.assertEqual(len(batch['accepted']), 1); self.assertEqual(len(batch['refused']), 1)
        self.assertEqual(batch['totals']['estimated_added_usd'], '330.000000000')
        other_generation = copy.deepcopy(source); other_generation['sha256'] = 'f' * 64
        duplicate = migration.legacy_import_batch_dry_run([source, other_generation])
        self.assertEqual(duplicate['accepted'], []); self.assertEqual(len(duplicate['refused']), 2)

    def test_unpriceable_usage_unknown_count_history_and_second_import_refuse(self):
        source = card(); original = copy.deepcopy(source)
        for mutate in (
            lambda c: c['continuation_budget'].update(cost=None),
            lambda c: c['continuation_budget']['events'][0].update(cost=None),
            lambda c: c['continuation_budget'].update(terminal_stop='running'),
            lambda c: c['continuation_budget'].update(invocation_reservations={'unknown': {}}),
            lambda c: c['continuation_budget'].setdefault('resolved_unpriced_invocations', []).append({'import_id': 'old'}),
        ):
            altered = copy.deepcopy(source); mutate(altered)
            with self.assertRaises(migration.Refused): migration.legacy_import_dry_run(altered)
        record = authorized(source)
        for field, value in (('lifetime_history', {}), ('founder_authorized_total_usd', '999.000000000'),
                             ('schema_version', True), ('legacy_generation_sha256', 'f' * 64)):
            altered = copy.deepcopy(record); altered[field] = value
            with self.assertRaises(migration.Refused): migration.migrate_legacy_import(source, altered)
        result = migration.migrate_legacy_import(source, record)
        result['sha256'] = 'f' * 64
        with self.assertRaises(migration.Refused): migration.legacy_import_dry_run(result)
        result.pop('legacy_import')
        with self.assertRaises(migration.Refused): migration.legacy_import_dry_run(result)
        self.assertEqual(source, original)

    def test_worker_uses_authenticated_source_and_never_writes(self):
        source = card(); record = authorized(source)
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / source['case']; work.mkdir()
            practice = json.loads(gzip.decompress((ROOT / 'tests/factory/fixtures/invalid-runs-practice.json.gz').read_bytes()))
            for name, content in practice['files'].items():
                data = content.encode(); self.assertEqual(hashlib.sha256(data).hexdigest(), practice['sha256'][name])
                path = work / 'case' / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
            archived = copy.deepcopy(source); archived['sha256'] = '0' * 64
            (work / 'scorecard.json').write_text(json.dumps(archived))
            ledger_path = work / 'continuation-budget.json'
            ledger_path.write_text(json.dumps(source['continuation_budget']))
            before = {p.relative_to(work).as_posix(): p.read_bytes() for p in work.rglob('*') if p.is_file()}
            def validate(value=source, incoming=record, generation=source['sha256'], digest=None):
                return restore_ledger.validate_legacy_import(work, source['case'], generation, value,
                    incoming, migration.digest(incoming) if digest is None else digest)
            self.assertEqual(validate(), migration.migrate_legacy_import(source, record))
            self.assertEqual(before, {p.relative_to(work).as_posix(): p.read_bytes() for p in work.rglob('*') if p.is_file()})
            with self.assertRaises(migration.Refused): validate(digest='f' * 64)
            with self.assertRaises(migration.Refused): validate(generation='f' * 64)
            changed = copy.deepcopy(source); changed['continuation_budget']['cost'] += 1
            with self.assertRaises(migration.Refused): validate(value=changed)
            ledger_path.write_text(json.dumps(changed['continuation_budget']))
            with self.assertRaises(migration.Refused): validate()
            ledger_path.write_text(json.dumps(source['continuation_budget']))
            (work / 'job-money.json').write_text('{}')
            with self.assertRaises(migration.Refused): validate()


if __name__ == '__main__': unittest.main()
