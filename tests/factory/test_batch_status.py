"""Unmodified saved public-card classification; authored journal/transport bindings.

No real card has the batch release field. Snapshot binding tests explicitly add
case/release metadata in scratch space; they do not qualify a real batch.
"""
from contextlib import redirect_stdout
from copy import deepcopy
import gzip
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'factory'))
import batch
import batch_status as status
import test_batch_service as fixtures

CARDS = [r['card'] for r in json.loads(gzip.decompress(
    (ROOT / 'tests/factory/fixtures/invalid-runs-public-cards.json.gz').read_bytes()))]
SEALED = next(c for c in CARDS if c.get('gates', {}).get('G12') == 'pass'
              and not c.get('failed_gate') and c.get('terminal_stop') in (None, 'complete'))
REJECTED = next(c for c in CARDS if c.get('failed_gate'))
OLD = next(c for c in CARDS if not c.get('failed_gate') and c.get('terminal_stop') in (None, 'paused')
           and 'case_budget' not in c and 'builder_rounds' not in c and 'continuation_budget' not in c)


def row(card=None, phase='stopped', **kwargs):
    return dict(case=(card or {}).get('case', 'case-public'), card=card, phase=phase, **kwargs)


class RenderTests(unittest.TestCase):
    def render(self, rows, workers=set(), progress=None):
        return status.render(3, rows, workers, progress or {}, now=status._stamp('2026-10-30T12:00:00Z'))

    def test_real_sealed_rejected_old_cards_are_not_modified(self):
        original = deepcopy([SEALED, REJECTED, OLD])
        text = self.render([row(SEALED), row(REJECTED), row(OLD)])
        self.assertIn('1 rejected', text)
        self.assertEqual(text.splitlines()[0], 'Sealed ' + str(sum(
            c.get('gates', {}).get('G12') == 'pass' and not c.get('failed_gate')
            and c.get('terminal_stop') in (None, 'complete') for c in original)) + ' / 3')
        self.assertIn('calls —', text)
        self.assertIn('nothing needs you', text)
        self.assertEqual([SEALED, REJECTED, OLD], original)
        stopped_rejection = {**REJECTED, 'terminal_stop': 'freshness_unresolved',
                             'case_budget': {'spent_usd': 99, 'limit_usd': 100}}
        text = self.render([row(stopped_rejection)])
        self.assertIn('Sealed 0', text); self.assertIn('nothing needs you', text)

    def test_real_calls_above_historical_cap_have_no_call_rule(self):
        card = next(c for c in CARDS if c.get('continuation_budget', {}).get('calls', 0) > 300
                    and c.get('terminal_stop') in (None, 'paused') and not c.get('case_budget')
                    and not c.get('recovery_config'))
        text = self.render([row(card)])
        self.assertIn('calls ' + str(card['continuation_budget']['calls']) + ' |', text)
        self.assertNotIn('near limit', text)
        for value in (True, -1, 1.5, '100', None):
            card = {**OLD, 'continuation_budget': {'calls': value}}
            self.assertIn('calls ? |', self.render([row(card)]))

    def test_thresholds_missing_fields_and_unknown_stop_redaction(self):
        cases = [
            ({'terminal_stop': 'freshness_unresolved'}, 'needs ruling'),
            ({'terminal_stop': 'freshness_review_unavailable'}, 'needs ruling'),
            ({'terminal_stop': 'stress_review_unresolved:rounds_exhausted'}, 'needs ruling'),
            ({'terminal_stop': 'Budget ledger stopped: private detail'}, 'check case'),
            ({'case_budget': {'spent_usd': 8, 'limit_usd': 10}}, 'near limit'),
            ({'builder_rounds': 4, 'recovery_config': {'rounds': 5}}, 'near limit'),
            ({'terminal_stop': 'provider_wait_unrecoverable'}, 'top up / re-login'),
            ({'terminal_stop': 'provider_wait', 'provider_wait': {'retry_after': '2026-10-30T11:00:00Z'}},
             'relaunch overdue'),
        ]
        for change, action in cases:
            text = self.render([row({**OLD, 'gates': {}, **change})])
            self.assertIn(action, text); self.assertNotIn('private detail', text)
        for stop in ('paused', 'complete', 'provider_limit:some text', 'call_limit', 'total_call_limit', 'stalled'):
            self.assertIn('nothing needs you', self.render([row({**OLD, 'gates': {}, 'terminal_stop': stop})]))
        self.assertIn('1 waiting', self.render([row({**OLD, 'gates': {}, 'terminal_stop': 'provider_wait'})]))
        self.assertIn('nothing needs you', self.render([row({**OLD, 'case_budget': {'spent_usd': 100},
                             'recovery_config': {}, 'builder_rounds': 100000})]))

    def test_authored_lifecycle_precedence_and_running_stage_age(self):
        running = row({**REJECTED, 'terminal_stop': 'freshness_unresolved'}, phase='running', worker_id='w1')
        progress = {running['case']: {'schema': 1, 'stages': {
            'G10': {'status': 'running', 'updated_at': '2026-10-30T08:00:00Z'},
            'role:reviewer': {'status': 'running', 'updated_at': '2026-10-30T06:00:00Z'}}}}
        text = self.render([running], {'w1'}, progress)
        self.assertIn('1 running', text); self.assertIn('0 rejected', text)
        self.assertIn('G10,role:reviewer | 6h 0m', text)
        self.assertIn('check case', text); self.assertNotIn('needs ruling', text)
        self.assertIn('worker gone', self.render([running], set()))
        text = self.render([running], None)
        self.assertIn('boat unreadable', text); self.assertNotIn('worker gone', text)
        self.assertIn('unreadable', self.render([running], {'w1'}))
        for phase in ('pending', 'failed'):
            text = self.render([row(REJECTED, phase=phase, pending_since='2026-10-30T11:00:00Z')])
            self.assertIn('launch stuck', text); self.assertNotIn('needs ruling', text)
        self.assertNotIn('launch stuck', self.render([row(None, phase='pending')]))
        text = self.render([row(None, phase='not collected')])
        self.assertIn('1 not collected', text); self.assertIn('nothing needs you', text)

    def test_one_list_one_cat_and_incomplete_inventory_no_false_disappearance(self):
        rows = [row(None, 'running', worker_id='w1'),
                dict(case='case-other', phase='running', worker_id='missing'),
                dict(case='case-stopped', phase='stopped', card=OLD)]
        calls = []
        def transport(args):
            calls.append(args)
            return {'pageInfo': {'hasMore': False}, 'sandboxes': [{'id': 'w1'}]} if args[0] == 'list' else {
                'schema': 1, 'stages': {}}
        workers, progress = status.observe(rows, transport)
        self.assertEqual(calls, [['list', '--json'], ['ssh', 'w1', 'cat ~/sealed/case-public.progress.json']])
        self.assertEqual(workers, {'w1'}); self.assertEqual(set(progress), {'case-public'})
        for inventory in ({}, {'pageInfo': {'hasMore': True}, 'sandboxes': []},
                          {'pageInfo': {'hasMore': False}, 'sandboxes': [{'id':'w1'}, {'id':'w1'}]}):
            workers, progress = status.observe(rows, lambda args: inventory)
            self.assertIsNone(workers)
            self.assertNotIn('worker gone', self.render(rows, workers, progress))


class ReadTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ServiceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.home, self.policy = self.fixture.root, self.fixture.home, self.fixture.policy
        self.directory = self.home / 'batches/practice'
        self.directory.mkdir(parents=True)
        (self.directory / 'lock').touch()
        self.journal = dict(schema=1, batch='practice', manifest_sha256=self.policy['batch']['manifest_sha256'],
                            entries={}, derivations={}, queue={}, next_sequence=0)
        self.snapshot('j')

    def snapshot(self, job, generation='b' * 64):
        # Independent authored snapshot schema, not batch_service.collect output.
        case = 'case-practice-' + job
        path = self.directory / 'generations' / case / generation
        path.mkdir(parents=True)
        card = {**SEALED, 'case': case, 'sha256': generation, 'batch_release_sha256': 'a' * 64}
        card_path = path / (case + '.scorecard.json')
        card_path.write_text(json.dumps(card))
        manifest = dict(schema=1, batch='practice', job=job, case=case, generation=generation,
                        batch_release_sha256='a' * 64, files={card_path.name: dict(
                            sha256=hashlib.sha256(card_path.read_bytes()).hexdigest(), size=card_path.stat().st_size)})
        manifest_path = path / 'manifest.json'; manifest_path.write_text(json.dumps(manifest))
        entry = dict(job=job, case=case, generation=generation,
                     manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                     state='pending', facts=None)
        self.journal['entries'][case + '/' + generation] = entry
        self.save()
        return entry, card_path

    def save(self):
        (self.directory / 'journal.json').write_text(json.dumps(self.journal))

    def read(self): return status.read_rows(self.policy, self.root, self.home)

    def test_core_stopped_not_collected_and_no_writes(self):
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        target, rows = self.read()
        self.assertEqual(target, 1)
        self.assertEqual([r['phase'] for r in rows], ['stopped', 'not collected'])
        self.assertEqual(before, {str(p.relative_to(self.root)): p.read_bytes()
                                 for p in self.root.rglob('*') if p.is_file()})

    def test_multiple_generations_need_exact_pointer_then_tampering_refuses(self):
        entry, path = self.snapshot('j', 'c' * 64)
        self.assertEqual(self.read()[1][0]['phase'], 'unreadable')
        current = self.directory / 'current'; current.mkdir()
        pointer = current / (entry['case'] + '.json')
        binding = {k: entry[k] for k in ('generation', 'manifest_sha256')}
        pointer.write_text(json.dumps(binding))
        self.assertEqual(self.read()[1][0]['card']['sha256'], 'c' * 64)
        pointer.write_text(json.dumps({**binding, 'extra': 1}))
        self.assertEqual(self.read()[1][0]['phase'], 'unreadable')
        pointer.unlink(); pointer.symlink_to(path)
        self.assertEqual(self.read()[1][0]['phase'], 'unreadable')
        pointer.unlink(); pointer.write_text(json.dumps(binding))
        path.write_bytes(path.read_bytes() + b' ')
        self.assertEqual(self.read()[1][0]['phase'], 'unreadable')

    def test_missing_sources_and_future_fields_fail_closed_without_flat_fallback(self):
        entry = next(iter(self.journal['entries'].values()))
        path = self.directory / 'generations' / entry['case'] / entry['generation'] / (entry['case'] + '.scorecard.json')
        (self.root / 'sealed').mkdir()
        (self.root / 'sealed' / path.name).write_bytes(path.read_bytes())
        path.unlink()
        self.assertEqual(self.read()[1][0]['phase'], 'unreadable')
        entry['worker_id'] = 'unimplemented'
        self.save()
        with self.assertRaises(ValueError): self.read()
        entry.pop('worker_id'); self.save()
        (self.directory / 'lock').unlink()
        with self.assertRaises(OSError): self.read()
        self.assertFalse((self.directory / 'lock').exists())
        (self.directory / 'journal.json').unlink()
        with self.assertRaises(ValueError): self.read()

    def test_command_reports_missing_policy_without_creating_home(self):
        absent = self.root / 'absent'
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(status.main(['status', '--control-home', str(absent)]), 1)
        self.assertIn('Batch unreadable', out.getvalue())
        self.assertFalse(absent.exists())

    def test_busy_writer_lock_refuses_immediately(self):
        with (self.directory / 'lock').open('rb') as writer:
            fcntl.flock(writer, fcntl.LOCK_EX)
            with self.assertRaises(BlockingIOError): self.read()

    def test_real_entrypoint_does_not_write_import_bytecode(self):
        command = self.root / 'bin/unbug'
        command.parent.mkdir()
        command.write_bytes((ROOT / 'bin/unbug').read_bytes())
        command.chmod(0o755)
        # Trivial imported module isolates the entrypoint's bytecode policy.
        (self.root / 'factory/batch_status.py').write_text('def main(): return 0\n')
        env = {k: v for k, v in os.environ.items() if k not in (
            'PYTHONDONTWRITEBYTECODE', 'PYTHONPYCACHEPREFIX')}
        subprocess.run([str(command), 'status'], check=True, env=env)
        self.assertFalse((self.root / 'factory/__pycache__').exists())

    def test_authored_binding_changes_refuse_even_with_valid_file_hashes(self):
        entry = next(iter(self.journal['entries'].values()))
        folder = self.directory / 'generations' / entry['case'] / entry['generation']
        card_path = folder / (entry['case'] + '.scorecard.json')
        manifest_path = folder / 'manifest.json'
        card = json.loads(card_path.read_text())
        for change in ({'case': 'case-foreign'}, {'sha256': 'f' * 64},
                       {'batch_release_sha256': 'c' * 64}):
            card_path.write_text(json.dumps({**card, **change}))
            manifest = json.loads(manifest_path.read_text())
            manifest['files'][card_path.name]['sha256'] = hashlib.sha256(card_path.read_bytes()).hexdigest()
            manifest['files'][card_path.name]['size'] = card_path.stat().st_size
            manifest_path.write_text(json.dumps(manifest))
            entry['manifest_sha256'] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            self.save()
            self.assertEqual(self.read()[1][0]['phase'], 'unreadable')


if __name__ == '__main__': unittest.main()
