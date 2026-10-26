"""Canary preflight stays local and refuses resources owned by another run."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import importlib.util
import json
import io
import subprocess
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('public_smoke', (Path(__file__).resolve().parents[2] / "factory" / 'public_fixture_smoke.py'))
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class PublicPreflightTests(unittest.TestCase):
    def test_preflight_is_read_only_and_labels_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('scenarios/dev/S0-null/scenario.json', 'scenarios/dev/S0-null/key.json',
                         'guards/reference/db.sql', 'bin/checkpoint', 'bin/checkpoint_evidence.py', 'bin/bench.py', 'bin/bench_judging.py'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            commands = []
            def output(command):
                commands.append(command)
                if command[:3] == ['docker', 'context', 'inspect']: return 'unix:///synthetic-docker.sock'
                if command[:2] == ['docker', 'info']:
                    return json.dumps({'version': 'synthetic', 'memory_bytes': 8 * 1024 ** 3, 'architecture': 'amd64', 'cpus': 8})
                if command[:3] == ['docker', 'image', 'inspect']:
                    return json.dumps({'id': 'sha256:' + 'a' * 64, 'architecture': 'amd64'})
                return ''
            class Socket:
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def bind(self, address): pass
            with patch.dict(smoke.os.environ, {}, clear=True), patch.object(smoke, 'output', output), \
                 patch.object(smoke.shutil, 'which', return_value='/synthetic/tool'), \
                 patch.object(smoke.socket, 'socket', Socket), patch.object(smoke.subprocess, 'run'):
                report = smoke.preflight(root, 89)
                (root / 'bin/bench_judging.py').unlink()
                with self.assertRaisesRegex(ValueError, 'missing public fixture source: bin/bench_judging.py'):
                    smoke.preflight(root, 89)
            self.assertEqual(report['model_calls'], 0)
            self.assertFalse(report['full_factory_qualified'])
            self.assertTrue(all(c[1] in ('context', 'container', 'volume', 'info', 'image') for c in commands))
            self.assertFalse((root / 'results').exists())

    def test_remote_docker_context_refused(self):
        with patch.dict(smoke.os.environ, {}, clear=True), patch.object(smoke, 'output', return_value='ssh://worker'):
            with self.assertRaisesRegex(ValueError, 'local Unix Docker'):
                smoke.preflight(Path('/public-fixture'), 89)

    def test_missing_image_preflight_exits_nonzero(self):
        missing = subprocess.CalledProcessError(1, ['docker', 'image', 'inspect', 'unbug-bench-medusa:latest'])
        with patch.object(smoke.sys, 'argv', ['public_fixture_smoke.py']), \
             patch.object(smoke, 'preflight', side_effect=missing), patch.object(smoke.sys, 'stderr', io.StringIO()):
            self.assertEqual(smoke.main(), 1)

    def test_existing_project_refused(self):
        with patch.dict(smoke.os.environ, {}, clear=True), patch.object(smoke, 'output', side_effect=['unix:///socket', 'existing-resource']):
            with self.assertRaisesRegex(ValueError, 'already in use'):
                smoke.preflight(Path('/public-fixture'), 89)

    def test_full_smoke_records_verified_evidence_paths_and_cleans_its_project(self):
        # Run the real smoke loop and evidence reader, with Docker replaced by a
        # local command adapter. Temporary receipts are complete checkpoint data.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            images = {name: {'id': 'sha256:synthetic', 'architecture': 'amd64'} for name in smoke.IMAGES}
            bench = types.SimpleNamespace(ROOT=root, FACTORY_SLOT=89,
                load_scenario=lambda path: {'dir': path},
                inventory_services=lambda scenarios: [], app_patches=lambda *args: [],
                resolve_guard=lambda guard: guard, setup=Mock(), dc=Mock(), command=Mock())
            docker = bench.dc
            expected = []
            def checkpoint(command, **kwargs):
                guard = command[command.index('--guard') + 1]
                directory = root / guard; directory.mkdir()
                passed = guard == 'reference'
                record = {'run': 1, 'errors': [], 'checker': {'valid': True},
                          'judge': {'pass': passed, 'paths': {'shop': guard == 'none'},
                                    'checks': {'legit': guard != 'refuse-all'}}}
                summary = {'runs': 1, 'pass_runs': int(passed), 'error_runs': 0, 'invalid_runs': 0,
                           'legit_completion': 0 if guard == 'refuse-all' else 1,
                           'key_consistent': True,
                           'paths': {'shop': {'runs': 1, 'violated_runs': int(guard == 'none')}},
                           'checks': {'legit': {'runs': 1, 'ok_runs': int(guard != 'refuse-all')}}}
                (directory / '01.json').write_text(json.dumps(record))
                evidence = directory / 'checkpoint.json'; evidence.write_text(json.dumps(summary))
                expected.append(str(evidence.resolve()))
                receipt = {'version': 1, 'path': str(evidence), 'requested_runs': 1}
                return subprocess.CompletedProcess(command, 0, 'UNBUG_CHECKPOINT=' + json.dumps(receipt), '')
            # Import only the transport module from the real source; the bench
            # module is synthetic and cannot start or modify any Docker resource.
            source_bin = str(Path(__file__).resolve().parents[2] / 'bin')
            with patch.object(smoke, 'preflight', return_value={'images': images}), \
                 patch.dict(smoke.sys.modules, {'bench': bench}), \
                 patch.dict(smoke.os.environ, {}, clear=True), \
                 patch.object(smoke.sys, 'path', [source_bin, *smoke.sys.path]), \
                 patch.object(smoke.subprocess, 'run', side_effect=checkpoint), \
                 patch.object(smoke, 'output', return_value=json.dumps(next(iter(images.values())))):
                report = smoke.smoke(root, 89)
            self.assertEqual([row['checkpoint'] for row in report['checks']], expected)
            self.assertEqual([row['guard'] for row in report['checks']], ['none', 'reference', 'refuse-all'])
            self.assertTrue(all(row['expected_control'] for row in report['checks']))
            bench.setup.assert_called_once()
            docker.assert_called_once_with('down', '-v', '--remove-orphans')
            self.assertEqual(bench.FACTORY_SLOT, 89)

    def test_evidence_runtime_failure_has_clean_cli_error(self):
        with patch.object(smoke.sys, 'argv', ['public_fixture_smoke.py', '--run']), \
             patch.object(smoke, 'smoke', side_effect=RuntimeError('incomplete checkpoint records')), \
             patch.object(smoke.sys, 'stderr', io.StringIO()) as stderr:
            self.assertEqual(smoke.main(), 1)
        self.assertEqual(stderr.getvalue(), 'public fixture qualification failed: incomplete checkpoint records\n')

    def test_cached_default_or_other_slot_refused_before_work_or_cleanup(self):
        root = Path('/public-fixture')
        for cached_slot in (0, 88):
            with self.subTest(cached_slot=cached_slot):
                bench = types.SimpleNamespace(ROOT=root, FACTORY_SLOT=cached_slot,
                    load_scenario=Mock(), setup=Mock(), dc=Mock(), command=Mock())
                original_dc, original_command = bench.dc, bench.command
                with patch.object(smoke, 'preflight', return_value={}), \
                     patch.dict(smoke.sys.modules, {'bench': bench}), \
                     patch.dict(smoke.os.environ, {}, clear=True), \
                     patch.object(smoke.sys, 'path', list(smoke.sys.path)), \
                     patch.object(smoke.subprocess, 'run') as external:
                    with self.assertRaisesRegex(ValueError, 'isolated canary slot'):
                        smoke.smoke(root, 89)
                bench.load_scenario.assert_not_called()
                bench.setup.assert_not_called()
                bench.dc.assert_not_called()
                bench.command.assert_not_called()
                external.assert_not_called()
                self.assertIs(bench.dc, original_dc)
                self.assertIs(bench.command, original_command)


if __name__ == '__main__': unittest.main()
