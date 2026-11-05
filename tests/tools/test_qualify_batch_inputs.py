"""Real saved opaque bytes, authored bindings; no live authentication/row closure."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tests/factory'), str(ROOT / 'factory')]
import test_batch_holder as holder_fixtures
import batch
import batch_holder as holder
import batch_money as money
from launch_manifest import collection_files


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


q = module('qualify_inputs', 'tools/qualify-batch-inputs.py')
m = module('migration_qualification', 'tools/migrate-legacy-checkpoints.py')
CIPHER = (ROOT / 'sealed/case-20261017T212118Z-1ad7fa.statement.age').read_bytes()
KEY = (ROOT / 'sealed/case-20261017T212118Z-1ad7fa.casekey.age').read_bytes()


def snapshot(root):
    return {str(p.relative_to(root)): (p.lstat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() and not p.is_symlink() else None)
            for p in root.rglob('*')}


class InputTests(unittest.TestCase):
    def setUp(self):
        self.h = holder_fixtures.HolderTests('test_lifecycle_status_ack_retirement_source_and_replay')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)

    def qualify(self, source=None):
        h = self.h
        before = snapshot(h.root)
        with patch.object(holder, 'HOLDER_ENABLED', False):
            result = q.qualify(h.policy, h.root, h.home, 'j', source)
        self.assertEqual(snapshot(h.root), before)
        return result

    def test_empty_no_state_and_replay_are_read_only(self):
        self.assertEqual(self.qualify()['observation'], 'batch_absent')
        self.assertTrue(self.qualify()['eligible'])
        op = self.h.reserve()
        self.assertEqual(self.qualify()['admission'], 'replay')
        self.assertEqual(self.h.reserve(), op)
        self.assertFalse(self.qualify()['launch_ready'])

    def test_checkpoint_missing_ack_and_real_lifecycle_contract(self):
        self.assertFalse(self.qualify('a' * 64)['eligible'])
        h = self.h; op = h.started(h.reserve()); card = h.output(op); h.publish(op)
        self.assertFalse(self.qualify(card['sha256'])['eligible'])
        # Empty replay after output is still a lookup, not another launch.
        self.assertEqual(h.reserve()['operation_id'], op['operation_id'])
        h.retirement(op); h.reconcile()
        self.assertTrue(self.qualify(card['sha256'])['eligible'])
        successor = h.reserve(source=card['sha256'])
        self.assertEqual(self.qualify(card['sha256'])['admission'], 'replay')
        self.assertFalse(self.qualify()['eligible'])
        # Exercise the existing post-advance freshness branch without a replay op.
        record = money.manifest(h.policy, h.root); state = h.money(); ops = h.ops()
        del ops[successor['operation_id']]
        state['jobs']['j']['sources'][-2] = 'f' * 64
        with self.assertRaises(ValueError):
            holder._admit(h.directory, record, h.policy, h.root, h.home, ops, state, 'j', card['sha256'])

    def test_all_exact_names_and_namespaces_refuse_empty_without_money(self):
        h = self.h; case = h.record['jobs']['j']['case']
        common = h.root / 'common/sealed'
        paths = [h.directory / 'generations' / case, h.directory / 'current' / (case + '.json')]
        for sealed in (h.root / 'sealed', common):
            paths += [sealed / name for name in collection_files(case)]
            paths.append(sealed / 'generations' / case)
        with patch.object(batch, 'sealed_directories', return_value=[h.root / 'sealed', common]):
            for path in paths:
                with self.subTest(path=path):
                    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(CIPHER)
                    self.assertFalse(self.qualify()['eligible'])
                    with self.assertRaises(ValueError): h.reserve()
                    self.assertFalse((h.directory / 'money.json').exists())
                    self.assertFalse((h.directory / 'reservations.json').exists())
                    path.unlink()
            nearby = h.root / 'sealed' / (case + '0.statement.age'); nearby.write_bytes(CIPHER)
            self.assertTrue(self.qualify()['eligible'])
            collision = h.root / 'sealed' / (case + '.casekey.age')
            collision.symlink_to('absent-target')
            self.assertFalse(self.qualify()['eligible']); collision.unlink()
            parent = h.directory / 'generations' / case; parent.mkdir()
            self.assertFalse(self.qualify()['eligible'])

    def test_existing_directory_without_lock_refuses_read_only(self):
        self.h.directory.mkdir(parents=True)
        result = self.qualify()
        self.assertFalse(result['eligible']); self.assertEqual(result['observation'], 'state_unlocked')

    def test_collision_after_reserve_is_terminal_before_dispatch(self):
        h = self.h; op = h.reserve()
        path = h.root / 'sealed' / (op['case'] + '.casekey.age')
        path.parent.mkdir(); path.write_bytes(KEY)
        h.policy.update(code_sha256='fingerprint', path='/usr/bin:/bin')
        with patch('key_holder.fingerprint', return_value='fingerprint'), patch.object(holder.subprocess, 'Popen') as spawn:
            with self.assertRaises(ValueError):
                holder.dispatch(h.policy, h.root, h.home, op['operation_id'], b'')
            spawn.assert_not_called()
        saved = h.ops()[op['operation_id']]
        self.assertEqual((saved['state'], saved['incident'], saved['dispatch_started']),
                         ('failed', 'preflight_refused', False))

    def test_collision_during_preflight_is_caught_at_second_check(self):
        h = self.h; op = h.reserve()
        original = holder.empty_input; calls = []
        def observe(root, directory, case):
            original(root, directory, case)
            calls.append(case)
            if len(calls) == 1:
                path = root / 'sealed' / (case + '.statement.age')
                path.parent.mkdir(); path.write_bytes(CIPHER)
        with patch.object(holder, 'empty_input', side_effect=observe):
            result, spawns = h.preflight(op)
        self.assertIsInstance(result, ValueError); self.assertEqual(spawns, [])
        self.assertEqual(h.ops()[op['operation_id']]['incident'], 'preflight_refused')
        self.assertFalse(h.ops()[op['operation_id']]['dispatch_started'])

    def test_git_lookup_failures_refuse_every_admission_surface(self):
        h = self.h
        errors = [FileNotFoundError(), subprocess.CalledProcessError(128, 'git'),
                  subprocess.TimeoutExpired('git', 10)]
        metadata = h.root / '.git'; metadata.symlink_to('absent-git-metadata')
        for error in errors:
            with self.subTest(error=type(error).__name__), patch.object(batch.subprocess, 'check_output', side_effect=error) as call:
                with self.assertRaisesRegex(ValueError, 'request_refused'):
                    holder.empty_input(h.root, h.directory, 'case-practice-j')
                self.assertFalse(self.qualify()['eligible'])
                with self.assertRaises(ValueError): h.reserve()
                self.assertFalse((h.directory / 'money.json').exists())
                self.assertFalse((h.directory / 'reservations.json').exists())
                self.assertEqual(call.call_args.kwargs['timeout'], 10)
                self.assertEqual(batch.restore_inventory(h.root), [])  # Legacy fallback only.
        metadata.unlink()
        for error in errors:
            # Separate operation fixture so a previous terminal failure cannot mask the guard.
            fresh = holder_fixtures.HolderTests('test_lifecycle_status_ack_retirement_source_and_replay')
            fresh.setUp()
            try:
                op = fresh.reserve()
                (fresh.root / '.git').symlink_to('absent-git-metadata')
                with patch.object(batch.subprocess, 'check_output', side_effect=error):
                    result, spawns = fresh.preflight(op)
                self.assertIsInstance(result, ValueError); self.assertEqual(spawns, [])
                saved = fresh.ops()[op['operation_id']]
                self.assertEqual((saved['state'], saved['incident'], saved['dispatch_started']),
                                 ('failed', 'preflight_refused', False))
            finally: fresh.doCleanups()

    def test_permission_error_is_refusal(self):
        with patch.object(Path, 'lstat', side_effect=PermissionError):
            with self.assertRaisesRegex(ValueError, 'request_refused'):
                holder.empty_input(self.h.root, self.h.directory, 'case-practice-j')


class MigrationQualificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        path = ROOT / 'tests/factory/fixtures/retained-evidence/batch-service-migration-plan-20261030.json'
        self.plan = json.loads(path.read_bytes()); self.pin = hashlib.sha256(path.read_bytes()).hexdigest()

    def test_real_plan_missing_store_never_skips_or_claims_remote_proof(self):
        before = snapshot(self.root)
        result = m.qualify(self.plan, self.root / 'absent', self.pin)
        self.assertEqual(len(result['entries']), 64)
        self.assertEqual(result['counts']['divergent_checkpoint'], 1)
        self.assertEqual(result['counts']['card_bound_absent'], 1)
        self.assertEqual({r['local_integrity'] for r in result['entries']}, {'missing'})
        for field in ('qualified', 'local_integrity_passed', 'vm_unwrap_verified', 'r2_verified'):
            self.assertFalse(result[field])
        self.assertEqual(snapshot(self.root), before)

    def authored_output(self):
        row = deepcopy(self.plan['entries'][0])
        card = (ROOT / 'tests/factory/fixtures/isolation-timeouts/scorecard.json').read_bytes()
        row['card_sha256'] = hashlib.sha256(card).hexdigest()
        sha = hashlib.sha256(CIPHER).hexdigest(); path = self.root / row['case'] / sha; path.mkdir(parents=True)
        files = {'archive.age': CIPHER, 'casekey.age': KEY, 'original-card.json': card,
                 'projected-card.json': card, 'migration.json': json.dumps(dict(plan_sha256=self.pin,
                    source_sha256=row['archive_sha256'], case=row['case'], kind=row['kind'], archive_sha256=sha)).encode()}
        for name, data in files.items(): (path / name).write_bytes(data)
        (path / 'manifest.json').write_text(json.dumps(dict(schema=1,
            files={name: hashlib.sha256(data).hexdigest() for name, data in files.items()})))
        return row, path

    def test_authored_integrity_contract_tamper_missing_and_symlink(self):
        row, path = self.authored_output(); plan = dict(self.plan, entries=[row])
        before = snapshot(self.root); result = m.qualify(plan, self.root, self.pin)
        self.assertTrue(result['local_integrity_passed']); self.assertFalse(result['qualified'])
        self.assertEqual(snapshot(self.root), before)
        (path / 'original-card.json').write_bytes(b'changed')
        self.assertEqual(m.qualify(plan, self.root, self.pin)['entries'][0]['local_integrity'], 'invalid')
        (path / 'original-card.json').unlink()
        self.assertFalse(m.qualify(plan, self.root, self.pin)['local_integrity_passed'])
        metadata = path / 'migration.json'; data = metadata.read_bytes(); metadata.unlink()
        outside = self.root / 'outside'; outside.write_bytes(data); metadata.symlink_to(outside)
        self.assertFalse(m.qualify(plan, self.root, self.pin)['local_integrity_passed'])

    def test_cli_missing_store_no_preflight_or_identity(self):
        plan = deepcopy(self.plan); plan['mac_root'] = str(self.root / 'sealed')
        plan['output_root'] = str(self.root / 'sealed/generations')
        path = self.root / 'plan.json'; path.write_text(json.dumps(plan)); pin = m.file_sha(path)
        before = snapshot(self.root)
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/migrate-legacy-checkpoints.py'),
            '--plan', str(path), '--plan-sha256', pin, '--qualify'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)['qualified'])
        self.assertEqual(snapshot(self.root), before)


if __name__ == '__main__':
    unittest.main()
