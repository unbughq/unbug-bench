"""Offline cutover checks: release inventory and retained scientific contracts."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import diagnosis
import extensions
import launch_manifest
import worker_release
from budget import BudgetError


class CandidateLifecycleTests(unittest.TestCase):
    def test_candidate_release_includes_durable_sources_and_preserves_policy(self):
        before = worker_release.POLICY.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'manifest.json'
            worker_release.stamp(ROOT, target)
            stamped = json.loads(target.read_bytes())
        self.assertEqual(worker_release.POLICY.read_bytes(), before)
        self.assertEqual(stamped['release'], json.loads(before)['release'] + '-durable-candidate-v1')
        from durable.workers import build_bundle, check_bundle
        self.assertEqual(check_bundle(build_bundle(ROOT))['release'], stamped['release'])
        for name in ('factory/durable/worker_step.py', 'factory/durable/steps/admit.py',
                     'factory/durable/steps/diagnosis.py', 'factory/durable/contract.py'):
            self.assertEqual(stamped['files'][name], hashlib.sha256((ROOT / name).read_bytes()).hexdigest())
        for name in ('factory/launch.sh', 'factory/key_holder.py', 'factory/recovery.py',
                     'factory/job_authority.py', 'factory/restore_bundle.py'):
            self.assertNotIn(name, stamped['files'])
            self.assertFalse((ROOT / name).exists())

    def test_retained_modules_do_not_import_deleted_lifecycle(self):
        retired = {'key_holder', 'batch', 'batch_holder', 'batch_service', 'recovery',
                   'restart', 'job_authority', 'job_config', 'statement_round',
                   'late_recovery', 'durable_checkpoint', 'restore_ledger'}
        for path in (ROOT / 'factory').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                names = ([node.module] if isinstance(node, ast.ImportFrom) else
                         [a.name for a in node.names] if isinstance(node, ast.Import) else [])
                self.assertFalse(retired.intersection(names), str(path))

    def test_progress_requires_same_versions_and_no_regression(self):
        with patch.object(extensions, 'stages', return_value=('stress', 'G1', 'G2')):
            def snapshot(frontier):
                rows = [dict(stage=stage, version='a' * 64,
                             status='pass' if i < frontier else 'fail',
                             binding_sha256='b' * 64, evidence_sha256='c' * 64)
                        for i, stage in enumerate(extensions.stages())]
                return dict(source_generation='d' * 64, case_sha256='e' * 64,
                            stages=rows, frontier=frontier, evidence={'proof.json': 'c' * 64})
            entry, outcome = snapshot(1), snapshot(2)
            self.assertEqual(extensions.progress(entry, outcome), 'progress')
            self.assertEqual(extensions.progress(outcome, entry), 'regression')
            changed = copy.deepcopy(outcome)
            changed['stages'][0]['version'] = 'f' * 64
            self.assertEqual(extensions.progress(entry, changed), 'pending')
            self.assertEqual(extensions.progress(entry, entry), 'no_progress')

    def test_diagnosis_evidence_is_bound_to_regular_unchanged_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proof = root / 'proof.json'
            proof.write_bytes(b'authored proof')
            result = dict(schema_version=1, case_id='case-test', checkpoint_sha256='a' * 64,
                          outcome='not_converging', reason='authored finding', factory_bug=None,
                          evidence=[dict(path=proof.name, sha256=hashlib.sha256(proof.read_bytes()).hexdigest(),
                                         finding='authored observation')])
            def validate():
                return diagnosis.validate_result(result, case='case-test', generation='a' * 64,
                                                 evidence_root=root)
            self.assertEqual(validate(), result)
            proof.write_bytes(b'changed proof')
            with self.assertRaises(BudgetError):
                validate()
            proof.unlink()
            proof.symlink_to(root / 'missing')
            with self.assertRaises(BudgetError):
                validate()


if __name__ == '__main__':
    unittest.main()
