"""Real retained batch smoke at the launcher's admission boundary; no provider calls."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/factory/fixtures/practice3-transfer'
CASE = 'case-b-plumbing-practice-3-smoke'
sys.path.insert(0, str(ROOT / 'factory'))
from statement_round import prepare_restore
from registry import Registry


class BatchRestoreAdmissionTests(unittest.TestCase):
    def run_boundary(self, change=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'root'; (root / 'sealed').mkdir(parents=True)
            state = Path(tmp) / 'launch'; state.mkdir()
            source = Path(tmp) / 'verified-generation'; source.mkdir()
            card = source / (CASE + '.scorecard.json')
            archive = source / (CASE + '.checkpoint.tar.gz.age')
            shutil.copyfile(FIXTURE / card.name, card)
            shutil.copyfile(FIXTURE / archive.name, archive)
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), json.loads(card.read_text())['sha256'])
            frozen = state / 'restore-input-scorecard.json'; shutil.copyfile(card, frozen)
            if change == 'source-card-replaced': card.write_text('{"terminal_stop":"statement-ready"}')  # AUTHORED concurrent collection control.
            elif change == 'global-card-conflict': (root / 'sealed' / card.name).write_text('{"terminal_stop":"statement-ready"}')
            elif change == 'frozen-card-symlink': frozen.unlink(); frozen.symlink_to(card)
            elif change == 'missing-frozen-card': frozen.unlink()
            script = (ROOT / 'factory/launch.sh').read_text()
            start = script.index('admission_snapshot=""')
            block = script[start:script.index('\nif [ -n "$reuse_worker" ]; then', start)]
            env = {**os.environ, 'root': str(root), 'admission_root': str(root), 'source_dir': str(source),
                   'restore': CASE, 'ckpt': str(archive), 'card': str(frozen), 'state': str(state),
                   'here': str(ROOT / 'factory'), 'secrets': '', 'args': '--dry-run',
                   'audit_g11': 'no', 'sealed_audit': ''}
            result = subprocess.run(['/bin/sh', '-c', 'set -eu\n' + block +
                                     '\nguard_new() { touch "$state/creation-boundary"; }; guard_new\n'],
                                    env=env, capture_output=True, text=True)
            return result, (state / 'creation-boundary').exists()

    def test_real_batch_restore_without_global_card_reaches_creation_boundary(self):
        result, created = self.run_boundary()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(created)

    def test_selected_frozen_card_controls_classification(self):
        for change in ('source-card-replaced', 'global-card-conflict'):
            with self.subTest(change=change):
                result, created = self.run_boundary(change)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(created)

    def test_missing_or_symlink_frozen_card_refuses_before_creation(self):
        for change in ('frozen-card-symlink', 'missing-frozen-card'):
            with self.subTest(change=change):
                result, created = self.run_boundary(change)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(created)


class CandidateContextTests(unittest.TestCase):
    """AUTHORED candidate metadata/interleavings over retained encrypted artifacts."""
    def selected(self, tmp):
        root = Path(tmp) / 'history'; history = root / 'sealed'; history.mkdir(parents=True)
        source = Path(tmp) / 'selected'; source.mkdir()
        case = 'case-batch-context'
        archive = source / (case + '.checkpoint.tar.gz.age')
        shutil.copyfile(FIXTURE / (CASE + '.checkpoint.tar.gz.age'), archive)
        ciphertexts = sorted((ROOT / 'sealed').glob('*.statement.age'))
        self.assertGreaterEqual(len(ciphertexts), 2)
        shutil.copyfile(ciphertexts[0], source / (case + '.statement.age'))
        shutil.copyfile(ciphertexts[1], history / 'case-previous.statement.age')
        card = dict(case=case, status='stopped', terminal_stop='admission_registry_unavailable',
                    statement_sha256=hashlib.sha256(b'AUTHORED candidate').hexdigest(),
                    statement_cipher_sha256=hashlib.sha256(ciphertexts[0].read_bytes()).hexdigest(),
                    sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
        mutable = source / (case + '.scorecard.json'); mutable.write_text(json.dumps(card))
        frozen = Path(tmp) / 'frozen.json'; frozen.write_text(json.dumps(card))
        return root, source, case, archive, mutable, frozen, card

    def test_selected_source_uses_authoritative_history_and_preserves_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, source, case, archive, mutable, frozen, card = self.selected(tmp)
            one = prepare_restore(root, case, archive, Path(tmp) / 'one', source_sealed=source,
                                  card_path=frozen, history_root=root)
            two = prepare_restore(root, case, archive, Path(tmp) / 'two', source_sealed=source,
                                  card_path=frozen, history_root=root)
            self.assertTrue((one / 'case-previous.statement.age').is_file())
            self.assertEqual((one / 'admission.json').read_bytes(), (two / 'admission.json').read_bytes())
            self.assertTrue((root / 'sealed/statement-registry/registry.json').is_file())
            self.assertFalse((source / 'statement-registry').exists())

    def test_changed_source_card_cannot_authorize_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, source, case, archive, mutable, frozen, card = self.selected(tmp)
            registry = Registry(root / 'sealed/statement-registry')
            old_digest = hashlib.sha256(b'AUTHORED previous candidate').hexdigest()
            registry.reserve(case, old_digest, source / (case + '.statement.age'))
            card['rejected_candidates'] = [{'statement_sha256': old_digest}]
            mutable.write_text(json.dumps(card))
            with self.assertRaisesRegex(ValueError, 'different content'):
                prepare_restore(root, case, archive, Path(tmp) / 'rejected', source_sealed=source,
                                card_path=frozen, history_root=root)
            state = json.loads((root / 'sealed/statement-registry/registry.json').read_text())
            self.assertEqual(state['entries'][case]['statement_sha256'], old_digest)
            self.assertEqual(state['entries'][case]['status'], 'screening')

    def test_frozen_search_binding_survives_source_card_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, source, case, archive, mutable, frozen, card = self.selected(tmp)
            registry = Registry(root / 'sealed/statement-registry')
            entry = registry.reserve(case, card['statement_sha256'], source / (case + '.statement.age'))
            search = source / (case + '.search.age')
            shutil.copyfile(source / (case + '.statement.age'), search)
            card['public_search'] = {'binding': {'case_id': case, 'statement_sha256': card['statement_sha256'],
                                    'reservation': {k: entry[k] for k in ('reservation', 'registry_revision')}},
                                    'cipher_sha256': hashlib.sha256(search.read_bytes()).hexdigest()}
            frozen.write_text(json.dumps(card))
            card.pop('public_search'); mutable.write_text(json.dumps(card))
            result = prepare_restore(root, case, archive, Path(tmp) / 'search', source_sealed=source,
                                     card_path=frozen, history_root=root)
            self.assertEqual((result / 'search.age').read_bytes(), search.read_bytes())


if __name__ == '__main__': unittest.main()
