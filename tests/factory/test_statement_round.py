"""Coordinator/worker admission transport checks with synthetic ciphertext and a fake backend."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import hashlib
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import admission
import statement_round


class StatementRoundTests(unittest.TestCase):
    def collected_candidate(self, root):
        sealed = root / 'sealed'; sealed.mkdir()
        case, statement = 'case-restored', 'synthetic candidate'
        archive = sealed / (case + '.checkpoint.tar.gz.age')
        archive.write_bytes(b'age-encryption.org/v1\nsynthetic sealed checkpoint')
        ciphertext = sealed / (case + '.statement.age')
        ciphertext.write_bytes(b'age-encryption.org/v1\nsynthetic statement ciphertext')
        card = {'case': case, 'status': 'stopped', 'terminal_stop': 'admission_registry_unavailable',
                'statement_sha256': hashlib.sha256(statement.encode()).hexdigest(),
                'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
        (sealed / (case + '.scorecard.json')).write_text(json.dumps(card))
        return case, statement, archive, card

    def test_restore_preflight_imports_history_and_preserves_reservation_on_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            case, statement, archive, card = self.collected_candidate(root)
            for previous in ('case-old', 'case-other'):
                (root / 'sealed' / (previous + '.statement.age')).write_bytes(b'age-encryption.org/v1\nhistorical ciphertext')
            first = statement_round.prepare_restore(root, case, archive, root / 'first')
            self.assertEqual(set(admission.registry_snapshot(first, case, statement)), {'case-old', 'case-other'})
            repeated = statement_round.prepare_restore(root, case, archive, root / 'retry')
            self.assertEqual((first / 'admission.json').read_bytes(), (repeated / 'admission.json').read_bytes())
            calls = []
            with patch.object(statement_round, 'command', side_effect=lambda args, capture=False, **kwargs: calls.append(args)):
                statement_round.install('fake-boat-call', 'worker-synthetic', first, provider='boat')
            self.assertEqual([args[1] for args in calls], ['--stdin', 'ssh'])
            self.assertIn('actual == expected', calls[-1][-1])
            self.assertFalse(any('exec' in args or 'age -d' in str(args) for args in calls))

    def test_restore_preflight_rejects_missing_mismatched_and_ambiguous_artifacts(self):
        for change in ('missing-cipher', 'plaintext-cipher', 'missing-card', 'card-case', 'card-conflict',
                       'card-digest', 'archive-digest', 'plaintext-archive', 'cipher-digest', 'cipher-symlink'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                case, statement, archive, card = self.collected_candidate(root)
                card_path = root / 'sealed' / (case + '.scorecard.json')
                cipher = root / 'sealed' / (case + '.statement.age')
                if change == 'missing-cipher': cipher.unlink()
                elif change == 'plaintext-cipher': cipher.write_text('unencrypted synthetic text')
                elif change == 'card-case': card['case'] = 'case-other'
                elif change == 'card-conflict': card['case_id'] = 'case-other'
                elif change == 'card-digest': card['statement_sha256'] = 'invalid'
                elif change == 'archive-digest': card['sha256'] = 'a' * 64
                elif change == 'plaintext-archive':
                    archive.write_bytes(b'unencrypted synthetic archive')
                    card['sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
                elif change == 'cipher-digest': card['statement_cipher_sha256'] = 'b' * 64
                elif change == 'cipher-symlink':
                    other = root / 'other.age'; cipher.rename(other); cipher.symlink_to(other)
                card_path.write_text(json.dumps(card))
                if change == 'missing-card': card_path.unlink()
                with patch.object(statement_round, 'command') as transport:
                    with self.assertRaises((ValueError, OSError)):
                        statement_round.prepare_restore(root, case, archive, root / 'snapshot')
                    transport.assert_not_called()
                self.assertFalse((root / 'sealed/statement-registry').exists())

    def test_restore_preflight_rejects_conflicting_registry_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            case, statement, archive, card = self.collected_candidate(root)
            statement_round.prepare_restore(root, case, archive, root / 'first')
            card['statement_sha256'] = 'b' * 64
            (root / 'sealed' / (case + '.scorecard.json')).write_text(json.dumps(card))
            with self.assertRaisesRegex(ValueError, 'different content'):
                statement_round.prepare_restore(root, case, archive, root / 'conflicting')

    def test_other_restore_stops_keep_existing_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            case, statement, archive, card = self.collected_candidate(root)
            card['terminal_stop'] = 'timeout'
            (root / 'sealed' / (case + '.scorecard.json')).write_text(json.dumps(card))
            self.assertIsNone(statement_round.prepare_restore(root, case, archive, root / 'unused'))
            self.assertFalse((root / 'sealed/statement-registry').exists())

    def test_launcher_preflights_before_creation_and_installs_before_execution(self):
        script = (pathlib.Path(__file__).resolve().parents[2] / "factory" / 'launch.sh').read_text()
        self.assertLess(script.index('snapshot = prepare_restore('), script.index('if ! guard_new;'))
        self.assertLess(script.index("install(*sys.argv[1:], provider='boat')"), script.index('boat exec "$id" --detach'))
        self.assertIn('[ "$audit_g11" = no ] && [ -z "$sealed_audit" ]', script)

    def test_launcher_preflight_shell_stops_before_creation_on_missing_inputs(self):
        source = (pathlib.Path(__file__).resolve().parents[2] / "factory" / 'launch.sh').read_text()
        start = source.index('admission_snapshot=""')
        preflight = source[start:source.index('\nif [ -n "$reuse_worker" ]; then', start)]
        for mode in ('ready', 'missing-cipher', 'missing-key'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                case, statement, archive, card = self.collected_candidate(root)
                state = root / 'state'; state.mkdir()
                if mode == 'missing-cipher':
                    (root / 'sealed' / (case + '.statement.age')).unlink()
                shell = ('set -eu\nroot=$1; restore=$2; ckpt=$3; state=$4; here=$5; secrets=$6\n'
                         'audit_g11=no; sealed_audit=""; args=""; admission_root=$root; card=$root/sealed/$restore.scorecard.json; admission_archive=$ckpt\n' + preflight +
                         '\nguard_new() { touch "$state/created"; }; guard_new\n')
                result = subprocess.run(['/bin/sh', '-c', shell, 'synthetic-launch', str(root), case,
                                         str(archive), str(state), str((pathlib.Path(__file__).resolve().parents[2] / "factory")),
                                         'statements-key' if mode != 'missing-key' else ''],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, mode == 'ready', result.stderr)
                self.assertEqual((state / 'created').exists(), mode == 'ready')

    def test_serial_reservations_include_all_collected_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); sealed = root / 'sealed'; sealed.mkdir()
            texts = {'case-first': 'first candidate', 'case-second': 'second candidate'}
            for case in ('case-history', *texts):
                (sealed / (case + '.statement.age')).write_bytes(b'age-encryption.org/v1\n' + case.encode())
            candidates = {case: hashlib.sha256(text.encode()).hexdigest() for case, text in texts.items()}
            snapshots = statement_round.prepare(sealed, root / 'registry', candidates, root / 'snapshots')
            self.assertEqual(set(admission.registry_snapshot(snapshots['case-first'], 'case-first', texts['case-first'])), {'case-history'})
            self.assertEqual(set(admission.registry_snapshot(snapshots['case-second'], 'case-second', texts['case-second'])), {'case-history', 'case-first'})
            state = json.loads((root / 'registry/registry.json').read_text())
            self.assertIsNone(state['entries']['case-history']['statement_sha256'])
            self.assertEqual(state['entries']['case-history']['status'], 'completed')
            # Same wave retry is idempotent and retains each immutable reservation snapshot.
            repeated = statement_round.prepare(sealed, root / 'registry', candidates, root / 'retry')
            self.assertEqual(json.loads((repeated['case-first'] / 'admission.json').read_text()),
                             json.loads((snapshots['case-first'] / 'admission.json').read_text()))

    def test_new_launcher_requires_complete_board_before_creating_worker(self):
        source = (pathlib.Path(__file__).resolve().parents[2] / "factory" / 'launch.sh').read_text()
        start = source.index('admission_snapshot=""')
        preflight = source[start:source.index('\nif [ -n "$reuse_worker" ]; then', start)]
        for ready in (False, True):
            with self.subTest(ready=ready), tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp); (root/'state').mkdir(); (root/'sealed').mkdir()
                if ready:
                    r = statement_round.Registry(root/'sealed/statement-registry')
                    f = root/'old.age'; f.write_bytes(b'age-encryption.org/v1\nsynthetic')
                    r.import_historical('case-old', f)
                shell = ('set -eu\nroot=$1; admission_root=$1; state=$1/state; here=$2; restore=""\n'
                         'audit_g11=no; sealed_audit=""; args=""; secrets="statements-key"\n' + preflight +
                         '\ntouch "$state/created"\n')
                result = subprocess.run(['/bin/sh','-c',shell,'synthetic',str(root),str((pathlib.Path(__file__).resolve().parents[2] / "factory"))],capture_output=True,text=True)
                self.assertEqual(result.returncode==0, ready, result.stderr)
                self.assertEqual((root/'state/created').exists(), ready)

    def test_reencrypted_statements_keep_immutable_reservations_and_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); sealed = root / 'sealed'; sealed.mkdir()
            for case in ('case-history', 'case-new'):
                (sealed / (case + '.statement.age')).write_bytes(b'age-encryption.org/v1\nfirst synthetic ciphertext')
            (sealed / 'case-history.scorecard.json').write_text(json.dumps({'statement_sha256': 'b' * 64}))
            first = statement_round.prepare(sealed, root / 'registry', {'case-new': 'a' * 64}, root / 'first')
            old = json.loads((first['case-new'] / 'admission.json').read_text())
            for case in ('case-history', 'case-new'):
                (sealed / (case + '.statement.age')).write_bytes(b'age-encryption.org/v1\nreencrypted synthetic ciphertext')
            second = statement_round.prepare(sealed, root / 'registry', {'case-new': 'a' * 64}, root / 'second')
            self.assertEqual(json.loads((second['case-new'] / 'admission.json').read_text()), old)
            self.assertEqual((first['case-new'] / 'case-history.statement.age').read_bytes(),
                             (second['case-new'] / 'case-history.statement.age').read_bytes())
            with self.assertRaisesRegex(ValueError, 'different content'):
                statement_round.prepare(sealed, root / 'registry', {'case-new': 'c' * 64}, root / 'changed')

    def test_unknown_history_reencryption_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); sealed = root / 'sealed'; sealed.mkdir()
            for case in ('case-history', 'case-new'):
                (sealed / (case + '.statement.age')).write_bytes(b'age-encryption.org/v1\nfirst synthetic ciphertext')
            statement_round.prepare(sealed, root / 'registry', {'case-new': 'a' * 64}, root / 'first')
            (sealed / 'case-history.statement.age').write_bytes(b'age-encryption.org/v1\nchanged synthetic ciphertext')
            with self.assertRaisesRegex(ValueError, 'different content'):
                statement_round.prepare(sealed, root / 'registry', {'case-new': 'a' * 64}, root / 'changed')

    def test_explicit_rejected_candidate_gets_new_bound_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); sealed = root / 'sealed'; sealed.mkdir()
            cipher = sealed / 'case-new.statement.age'; cipher.write_bytes(b'age-encryption.org/v1\nfirst')
            first = statement_round.prepare(sealed, root / 'registry', {'case-new': 'a' * 64}, root / 'first')
            old = json.loads((first['case-new'] / 'admission.json').read_text())
            (sealed / 'case-new.scorecard.json').write_text(json.dumps({'rejected_candidates': [{'statement_sha256': 'a' * 64}]}))
            cipher.write_bytes(b'age-encryption.org/v1\nsecond')
            second = statement_round.prepare(sealed, root / 'registry', {'case-new': 'b' * 64}, root / 'second')
            new = json.loads((second['case-new'] / 'admission.json').read_text())
            self.assertNotEqual(old['reservation'], new['reservation'])
            self.assertGreater(new['registry_revision'], old['registry_revision'])
            self.assertEqual(new['statement_sha256'], 'b' * 64)

    def test_opaque_search_receipt_requires_exact_reservation_and_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); sealed = root / 'sealed'; sealed.mkdir()
            (sealed / 'case-new.statement.age').write_bytes(b'age-encryption.org/v1\nstatement')
            first = statement_round.prepare(sealed, root / 'registry', {'case-new': 'a' * 64}, root / 'first')
            entry = json.loads((first['case-new'] / 'admission.json').read_text())
            search = sealed / 'case-new.search.age'; search.write_bytes(b'age-encryption.org/v1\nopaque search verdict')
            metadata = {'binding': {'case_id': 'case-new', 'statement_sha256': 'a' * 64,
                        'reservation': {k: entry[k] for k in ('reservation', 'registry_revision')}},
                        'cipher_sha256': hashlib.sha256(search.read_bytes()).hexdigest()}
            card = sealed / 'case-new.scorecard.json'; card.write_text(json.dumps({'public_search': metadata}))
            second = statement_round.prepare(sealed, root / 'registry', {'case-new': 'a' * 64}, root / 'second')
            self.assertEqual((second['case-new'] / 'search.age').read_bytes(), search.read_bytes())
            self.assertEqual(json.loads((second['case-new'] / 'admission.json').read_text())['search_sha256'], metadata['cipher_sha256'])
            metadata['binding']['reservation']['registry_revision'] += 1
            card.write_text(json.dumps({'public_search': metadata}))
            with self.assertRaisesRegex(ValueError, 'stale search receipt'):
                statement_round.prepare(sealed, root / 'registry', {'case-new': 'a' * 64}, root / 'stale')

    def test_failed_or_incomplete_transfer_never_swaps_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'admission.json').write_text('{}')
            (root / 'case-history.statement.age').write_bytes(b'age-encryption.org/v1\nsynthetic ciphertext')
            calls = []
            def backend(args, capture=False, **kwargs):
                calls.append(args)
                if args[1] == 'scp': raise OSError('synthetic transport unavailable')
            with patch.object(statement_round, 'command', backend):
                with self.assertRaises(OSError): statement_round.install('fake-boat', '123', root)
            self.assertFalse(any('python3 -c' in args[-1] for args in calls))
            self.assertFalse(any('resume' in str(args) for args in calls))

    def test_install_uploads_ciphertext_and_attestation_then_swaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); (root / 'admission.json').write_text('{}')
            (root / 'case-history.statement.age').write_bytes(b'age-encryption.org/v1\nsynthetic ciphertext')
            calls = []
            with patch.object(statement_round, 'command', side_effect=lambda args, capture=False: calls.append(args)):
                statement_round.install('fake-boat', '123', root)
            self.assertEqual([args[1] for args in calls], ['ssh', 'scp', 'scp', 'ssh'])
            self.assertIn('s.rename(p)', calls[-1][-1])
            self.assertIn('actual == expected', calls[-1][-1])
            self.assertTrue(all('statement.md' not in str(args) for args in calls))

    def wave(self, provider):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); (root / 'sealed').mkdir()
            (root / 'sealed/case-new.statement.age').write_bytes(b'age-encryption.org/v1\nsynthetic ciphertext')
            calls = []
            def backend(args, capture=False, **kwargs):
                calls.append(args)
                if args[0] == 'hcloud':
                    return json.dumps([{'id': 123, 'labels': {'parked': 'case-new'}},
                                       {'id': 456, 'labels': {}}])
                if capture:
                    return json.dumps([{'case_id': 'case-new', 'statement_sha256': 'a' * 64}])
            argv = ['--root', str(root)]
            if provider == 'boat': argv += ['--provider', 'boat', '--worker-id', 'worker-explicit']
            with patch.object(statement_round, 'command', backend), patch('builtins.print') as report:
                statement_round.main(argv)
            status = json.loads(report.call_args.args[0])
            self.assertEqual(status['status'], 'ready_for_authorized_resume')
            self.assertEqual(status['provider'], provider)
            self.assertFalse(any('resume-in-place' in str(args) or 'exec' in args for args in calls))
            remote = [args for args in calls if args[0] != 'hcloud']
            expected = root / ('bin/boat-call' if provider == 'boat' else 'bin/hcloud-boat')
            self.assertTrue(all(args[0] == str(expected) for args in remote))
            self.assertTrue(all('DONE' in args[-1] for args in remote if 'pgrep' in args[-1]))
            if provider == 'boat':
                self.assertFalse(any(args[0] == 'hcloud' for args in calls))
                self.assertTrue(all(args[2].split(':')[0] == 'worker-explicit' for args in remote if args[1] == 'ssh'))

    def test_boat_explicit_worker_delivery_uses_bounded_adapter_without_resuming(self):
        self.wave('boat')

    def test_default_hetzner_discovery_delivers_without_resetting_run_settings(self):
        self.wave('hetzner')

    def test_boat_rejects_missing_duplicate_or_unsafe_worker_ids_before_transport(self):
        for workers in ([], ['duplicate', 'duplicate'], ['-flag'], ['id; echo unsafe']):
            args = ['--provider', 'boat']
            for worker in workers: args += ['--worker-id=' + worker]
            with self.subTest(workers=workers), patch.object(statement_round, 'command') as backend:
                with self.assertRaises((SystemExit, ValueError)):
                    statement_round.main(args)
                backend.assert_not_called()

    def test_snapshot_rejects_plaintext_and_extra_files_before_transport(self):
        for name in ('case-old.statement.age', 'statement.md', 'key.txt'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp); (root / 'admission.json').write_text('{}')
                (root / name).write_text('synthetic unencrypted bytes')
                with patch.object(statement_round, 'command') as backend:
                    with self.assertRaises(ValueError):
                        statement_round.install('boat-call', 'worker-explicit', root, 'boat')
                    backend.assert_not_called()


if __name__ == '__main__': unittest.main()
