"""Offline metadata observations; reconstructed layouts are not live cleanup proof."""
import datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'factory'))
import deployment_inventory as inv

FIXTURES = ROOT / 'tests/factory/fixtures/isolation-timeouts'
NOW = datetime.datetime(2026, 10, 31, tzinfo=datetime.timezone.utc)
POISON = 'do-not-report-synthetic-secret'


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.home = self.base / 'control'
        self.home.mkdir()
        self.root = self.base / 'source'
        for name in inv.SOURCES:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)

    def report(self):
        return inv.inventory(self.root, self.home, NOW)

    def ledger(self, entries):
        (self.home / 'boat-reservations.json').write_text(json.dumps(dict(version=1, reservations=entries)))

    def hold(self, status='reserved', usd='0.036', expires_at=None):
        return dict(status=status, usd=usd, expires_at=NOW.timestamp() - 1 if expires_at is None else expires_at)

    def launch(self, name='a' * 32):
        target = self.home / 'launches' / name
        target.mkdir(parents=True)
        return target

    def cli(self, *args):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'factory/deployment_inventory.py'),
                               *args], capture_output=True, text=True)

    def test_saved_legacy_layout_and_no_mutation_across_processes(self):
        preflight = json.loads((ROOT / 'docs/reports/stream-b-preparation-preflight-20261031.json').read_text())
        old = preflight['unresolved_launch']
        state = self.launch(old['id'])
        # Only layout is retained from VM preflight; file contents are not its provenance.
        for name in old['files']:
            if name == 'launch.json':
                shutil.copyfile(FIXTURES / name, state / name)
            else:
                (state / name).write_text(POISON)
        def snapshot():
            return {str(p.relative_to(self.base)): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
                    for p in self.base.rglob('*')}
        before = snapshot()
        for _ in range(2):
            run = self.cli('--root', str(self.root), '--control-home', str(self.home))
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stderr, '')
            self.assertNotIn(POISON, run.stdout)
            result = json.loads(run.stdout)
            item = result['launches']['items'][0]
            self.assertEqual(item['id'], old['id'])
            self.assertEqual(item['creations'], [])
            self.assertEqual(item['files']['complete'], {'state': 'missing'})
            self.assertFalse(result['activation_authorized'])
            self.assertFalse(result['snapshot_atomic'])
            self.assertEqual(result['ledger']['state'], 'missing')
            for name in inv.SOURCES:
                self.assertEqual(result['sources'][name]['sha256'], hashlib.sha256((ROOT / name).read_bytes()).hexdigest())
        self.assertEqual(snapshot(), before)

    def test_guard_layout_states_markers_and_secret_contents_never_read(self):
        state = self.launch()
        for name in inv.FILES:
            (state / name).write_text(POISON)
        shutil.copyfile(FIXTURES / 'created.json', state / 'new.1')
        shutil.copyfile(FIXTURES / 'created.json', state / 'new.01')
        (state / 'new.01.pending').write_text(POISON)
        (state / 'new.2.pending').write_text(POISON)
        for suffix in ('deleted', 'parked', 'keep'):
            (state / ('bx_saved.' + suffix)).write_text(POISON)
        for name in ('restore-casekey.age', 'restore-input.age', 'founder-ruling.json',
                     'initial.accounts.json', POISON, 'bx_saved.admission-key'):
            (state / name).write_text(POISON)
        self.ledger({POISON: {**self.hold(), 'secret': POISON}})
        original = inv.read_regular
        def restricted(path):
            self.assertNotIn(state, path.parents, 'launch contents must not be read')
            return original(path)
        with patch.object(inv, 'read_regular', side_effect=restricted):
            result = self.report()
        self.assertNotIn(POISON, json.dumps(result))
        self.assertEqual(result['errors'], [])
        item = result['launches']['items'][0]
        self.assertEqual([(x['serial'], x['label']) for x in item['creations']],
                         [('01', 'response-and-intent'), ('1', 'response-without-marker'), ('2', 'intent-only')])
        self.assertEqual(item['creation_counts'], dict.fromkeys(inv.LABELS, 1))
        self.assertEqual(item['unknown_entries'], 6)
        for suffix in ('deleted', 'parked', 'keep'):
            self.assertEqual(item[suffix + '_markers']['file'], 1)

    def test_empty_and_cumulative_hold_observation_with_expiry_boundary(self):
        self.ledger({})
        self.assertEqual(self.report()['ledger']['reserved_usd'], '0')
        self.ledger({'old': self.hold(), 'equal': self.hold(usd='1E+2', expires_at=NOW.timestamp()),
                     'finished': self.hold('finished', '7'),
                     'released': self.hold('reconciled_expired', '8')})
        result = self.report()['ledger']
        self.assertEqual(result['state'], 'ok')
        self.assertEqual(result['reserved_usd'], '100.036')
        self.assertEqual(result['expired_reserved'], 1)
        self.assertEqual(result['counts'], {'reserved': 2, 'finished': 1, 'reconciled_expired': 1})

    def test_invalid_records_never_produce_partial_totals(self):
        for value in ('-1', 'NaN', 'Infinity', '1e999999999', '1e-19', True, None, [], '9' * 33):
            with self.subTest(value=value):
                self.ledger({'good': self.hold(), POISON: self.hold(usd=value)})
                result = self.report()['ledger']
                self.assertEqual(result['state'], 'invalid')
                self.assertIsNone(result['reserved_usd'])
                self.assertEqual(result['malformed_records'], 1)
                self.assertEqual(result['counts']['reserved'], 2)
                self.assertEqual(result['expired_reserved'], 1)
        self.ledger({'unknown': self.hold(status=POISON), 'bad': None})
        result = self.report()
        self.assertEqual(result['ledger']['unknown_statuses'], 1)
        self.assertEqual(result['ledger']['malformed_records'], 1)
        self.assertEqual(result['errors'], ['ledger-invalid'])
        self.assertNotIn(POISON, json.dumps(result))
        self.ledger({'bad-expiry': self.hold(expires_at=-1)})
        self.assertEqual(self.report()['ledger']['malformed_records'], 1)

    def test_invalid_envelopes_and_bounded_reads(self):
        path = self.home / 'boat-reservations.json'
        for data in (b'not-json', b'[]', b'{"version":true,"reservations":{}}',
                     b'{"version":1,"reservations":[],"secret":"hidden"}',
                     b'{"version":1,"version":1,"reservations":{}}',
                     b'{"version":1,"reservations":{"a":NaN}}', b'\xff', b' ' * (inv.LIMIT + 1)):
            path.write_bytes(data)
            result = self.report()['ledger']
            self.assertEqual(result['state'], 'invalid')
            self.assertIsNone(result['reserved_usd'])
            self.assertEqual(result['counts'], dict.fromkeys(inv.STATUSES, 0))
        path.unlink()
        path.symlink_to(self.root / inv.SOURCES[0])
        self.assertEqual(self.report()['ledger']['state'], 'invalid')

    def test_symlink_and_nonregular_metadata_never_followed(self):
        state = self.launch()
        outside = self.base / POISON
        outside.mkdir()
        (outside / POISON).write_text(POISON)
        (state / 'new.1.pending').symlink_to(outside)
        (state / 'new.2').mkdir()
        (state / 'complete').symlink_to(outside / 'absent')
        (state / 'worker.deleted').symlink_to(outside)
        (self.home / 'launches' / ('b' * 32)).symlink_to(outside)
        (self.home / 'launches' / POISON).mkdir()
        (self.home / 'launches' / ('c' * 32)).write_text(POISON)
        result = self.report()
        self.assertEqual(result['errors'], ['launch-scan-error'])
        self.assertEqual(result['launches']['invalid_entries'], 3)
        item = result['launches']['items'][0]
        self.assertEqual(item['state'], 'error')
        self.assertEqual(item['files']['complete']['type'], 'symlink')
        self.assertEqual(item['deleted_markers']['symlink'], 1)
        self.assertEqual(item['creation_counts']['intent-only'], 1)
        self.assertEqual(item['creation_counts']['response-without-marker'], 1)
        self.assertNotIn(POISON, json.dumps(result))

    def test_root_source_and_launch_directory_errors_are_generic(self):
        link = self.base / 'link'
        link.symlink_to(self.home)
        self.assertEqual(inv.inventory(self.root, link)['errors'], ['invalid-root'])
        (self.home / 'launches').symlink_to(self.base)
        self.assertEqual(self.report()['errors'], ['launch-scan-error'])
        (self.home / 'launches').unlink()
        source = self.root / inv.SOURCES[0]
        source.unlink()
        source.symlink_to(self.base / POISON)
        result = self.report()
        self.assertEqual(result['sources'][inv.SOURCES[0]], {'state': 'unsupported'})
        self.assertEqual(result['errors'], ['source-scan-error'])
        source.unlink()
        source.write_bytes(b' ' * (inv.LIMIT + 1))
        self.assertEqual(self.report()['sources'][inv.SOURCES[0]]['state'], 'unsupported')
        with patch.object(inv.os, 'open', side_effect=PermissionError(POISON)):
            result = self.report()
            self.assertNotIn(POISON, json.dumps(result))
            self.assertIn('source-scan-error', result['errors'])

    def test_read_change_and_cli_errors(self):
        source = self.root / inv.SOURCES[0]
        actual = inv.signature
        calls = []
        def changed(info):
            calls.append(1)
            return actual(info) + (len(calls),)
        with patch.object(inv, 'signature', side_effect=changed):
            self.assertEqual(inv.read_regular(source), ('changed', None))
        for args in ([], ['--bogus', POISON], ['--root', POISON, '--root', POISON]):
            run = self.cli(*args)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(run.stderr, '')
            self.assertEqual(json.loads(run.stdout), {'error': 'invalid-arguments'})
        run = self.cli('--root', str(self.base / POISON), '--control-home', str(self.home))
        self.assertEqual(run.returncode, 1)
        self.assertNotIn(POISON, run.stdout + run.stderr)


if __name__ == '__main__':
    unittest.main()
