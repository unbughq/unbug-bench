"""Offline worker qualification: source drift and selected tool pins fail closed."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('worker_release', (Path(__file__).resolve().parents[2] / "factory" / 'worker_release.py'))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class WorkerReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in release.BENCH_FILES + ('factory/runtime.py', 'factory/prompts/builder.md',
                'factory/rotation.json', 'factory/rotation-3writers.json', 'factory/worker-release.json',
                'factory/statements-recipient.txt'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('public synthetic source')
        self.manifest = self.root / 'manifest.json'
        release.stamp(self.root, self.manifest)
        self.policy = json.loads(self.manifest.read_text())
        self.calls = []

    def output(self, command):
        self.calls.append(command)
        if command[0] == 'node': return 'v22.22.2'
        if command[0] == '/usr/local/bin/opencode': return '1.19.0'
        if command[0] == 'harbor': return 'harbor 0.24.0'
        if command[:3] == ['docker', 'image', 'inspect']: return 'sha256:' + 'a' * 64
        return 'synthetic installed version'

    def verify(self, drivers=('opencode',)):
        with patch.object(release, 'output', self.output), patch.object(release.subprocess, 'run'):
            return release.verify(self.policy, self.root, self.root / 'factory', drivers)

    def test_verifies_selected_tools_and_no_credentials_in_manifest(self):
        secret = self.root / 'factory' / 'credential.age'
        secret.write_text('never read this key')
        result = self.verify()
        self.assertEqual(result['verified_drivers'], ['opencode'])
        self.assertFalse(any('codex' in c[0] for c in self.calls))
        self.assertNotIn(secret.name, self.manifest.read_text())
        self.assertNotIn('never read this key', self.manifest.read_text())

    def test_runtime_or_prompt_drift_rejected_before_tool_execution(self):
        (self.root / 'factory/prompts/builder.md').write_text('changed public prompt')
        with self.assertRaisesRegex(ValueError, 'release file mismatch'):
            self.verify()
        self.assertEqual(self.calls, [])

    def test_judging_drift_rejected_before_tool_execution(self):
        (self.root / 'bin/bench_judging.py').write_text('changed verdict arithmetic')
        with self.assertRaisesRegex(ValueError, 'release file mismatch: bin/bench_judging.py'):
            self.verify()
        self.assertEqual(self.calls, [])

    def test_selected_wrong_version_rejected(self):
        with self.assertRaisesRegex(ValueError, 'version mismatch: codex'):
            self.verify(('codex',))

    def test_selected_claude_hook_checks_actual_installed_path(self):
        with patch.object(release, 'output', return_value='2.1.299 (Claude Code)') as command:
            self.assertEqual(release.verify_driver('claude', '/synthetic/claude'), '2.1.299 (Claude Code)')
            command.assert_called_once_with(['/synthetic/claude', '--version'])
        with patch.object(release, 'output', return_value='2.1.2999 (Claude Code)'):
            with self.assertRaisesRegex(ValueError, 'version mismatch: claude'):
                release.verify_driver('claude', '/synthetic/claude')

    def test_selected_role_chains_qualify_each_actual_driver_once(self):
        paths = {'claude': '/installed/claude', 'codex': '/installed/codex', 'opencode': '/installed/opencode'}
        models = {'builder': ['openrouter/meta/public-model'],
                  'attacker': ['opencode-go/public-model'],
                  'reviewers': [['claude/public-model'], ['codex/public-model']],
                  'strong_calibrator': ['claude/public-model']}
        with patch.object(release, 'verify_driver', side_effect=lambda driver, executable, policy: driver + '-version') as verify:
            resolver = unittest.mock.Mock(side_effect=paths.__getitem__)
            result = release.verify_selected_drivers(models, resolver)
        self.assertEqual(result['verified_drivers'], ['claude', 'codex', 'opencode'])
        self.assertEqual(verify.call_count, 3)
        self.assertEqual(resolver.call_args_list, [unittest.mock.call(d) for d in ('claude', 'codex', 'opencode')])

    def test_unselected_driver_never_installed_or_probed(self):
        with patch.object(release, 'verify_driver', return_value='verified') as verify:
            resolver = unittest.mock.Mock(return_value='/installed/opencode')
            result = release.verify_selected_drivers({'builder': ['opencode/public-model']}, resolver)
        self.assertEqual(result['verified_drivers'], ['opencode'])
        resolver.assert_called_once_with('opencode')
        verify.assert_called_once_with('opencode', '/installed/opencode', None)

    def test_full_qualification_never_defers_requested_claude(self):
        original = self.output
        def output(command):
            if command[0] == '/tmp/factory-claude-cli/bin/claude': return '2.1.299 (Claude Code)'
            return original(command)
        with patch.object(release, 'output', output), patch.object(release.subprocess, 'run'):
            result = release.verify(self.policy, self.root, self.root / 'factory', ['claude'])
        self.assertEqual(result['verified_drivers'], ['claude'])
        self.assertEqual(result['deferred_drivers'], [])

    def test_empty_manifest_rejected(self):
        self.policy['files'] = {}
        with self.assertRaisesRegex(ValueError, 'source release hashes'):
            self.verify()


if __name__ == '__main__': unittest.main()
