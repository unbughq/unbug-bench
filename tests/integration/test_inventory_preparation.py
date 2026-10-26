"""Synthetic services: image reuse must never reuse trial state or stale build inputs."""
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

BIN = pathlib.Path(__file__).resolve().parents[2] / 'bin'
sys.path.insert(0, str(BIN))
SPEC = importlib.util.spec_from_file_location('inventory_preparation_test', BIN / 'bench.py')
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


class InventoryPreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        self.project = self.root / 'service'; self.project.mkdir()
        self.guard = self.root / 'guard'; self.guard.mkdir()
        (self.project / 'Dockerfile').write_text('FROM scratch\nCOPY source /source\n')
        (self.project / 'source').write_text('original\n')
        (self.project / 'compose.yaml').write_text('services: {}\n')
        self.services = [{'name': 'channel', 'project': self.project, 'compose': self.project / 'compose.yaml'}]
        self.config = {'services': {'channel': {'build': {'context': str(self.project)}}}}
        self.events, self.images, self.ledger = [], [], {}
        self.fail_build = False
        def command(args, **kwargs):
            if args[0] == 'git':
                result = subprocess.run(args, cwd=kwargs.get('cwd'), capture_output=True, text=True)
                if result.returncode: raise RuntimeError(result.stderr)
                return result.stdout.strip()
            if 'config' in args: return json.dumps(self.config)
            if 'build' in args:
                context = pathlib.Path(json.loads((self.root / '.inventory-compose.json').read_text())['services']['channel']['build']['context'])
                self.images.append((context / 'source').read_text())
                if self.fail_build: raise RuntimeError('synthetic build failure')
            elif 'up' in args:
                self.events.append('create'); self.ledger = {'old': True}
            elif 'stop' in args: self.events.append('stop')
            elif 'rm' in args: self.events.append('remove')
            return ''
        def adapter(service, action, compose):
            self.events.append(action)
            if action == 'reset': self.ledger = {}
            return {'orders': dict(self.ledger)}
        for patcher in (
            mock.patch.multiple(bench, RESULTS=self.root, INVENTORY_STATE=self.root / 'state.json',
                                FACTORY_SLOT=0, _INVENTORY_PREPARATION={}),
            mock.patch.object(bench, 'command', side_effect=command),
            mock.patch.object(bench, 'service_adapter', side_effect=adapter),
        ):
            patcher.start(); self.addCleanup(patcher.stop)

    def trial(self):
        bench.stop_inventory_services()
        self.assertEqual(bench.start_inventory_services(self.services, self.guard), {'channel': {'orders': {}}})

    def test_reuse_preserves_fresh_container_and_ledger_checks(self):
        self.trial(); self.trial()
        self.assertEqual(self.images, ['original\n'])
        cached_events = list(self.events)
        bench.stop_inventory_services(); self.events.clear(); self.images.clear()
        with mock.patch.object(bench, '_INVENTORY_PREPARATION', None):
            self.trial(); self.trial()
        self.assertEqual(self.images, ['original\n', 'original\n'])
        self.assertEqual(self.events, cached_events)
        self.assertEqual(cached_events, ['create', 'reset', 'check', 'stop', 'remove', 'create', 'reset', 'check'])

    def test_source_patch_configuration_and_mode_invalidate(self):
        self.trial()
        (self.project / 'source').write_text('changed\n'); self.trial()
        (self.guard / 'services.patch').write_text('--- a/channel/source\n+++ b/channel/source\n@@ -1 +1 @@\n-changed\n+patched\n'); self.trial()
        self.config['services']['channel']['build']['args'] = {'VERSION': '2'}; self.trial()
        (self.project / 'source').chmod(0o755); self.trial()
        self.assertEqual(self.images, ['original\n', 'changed\n', 'patched\n', 'patched\n', 'patched\n'])
        self.assertEqual((self.project / 'source').read_text(), 'changed\n', 'build patches must not touch source')

    def test_no_cross_batch_reuse(self):
        def batch(*args, **kwargs):
            self.trial(); self.trial()
            return {}
        with mock.patch.object(bench, '_run_case', side_effect=batch):
            bench.run_case('none', 2)
            bench.run_case('none', 2)
        self.assertEqual(self.images, ['original\n', 'original\n'])

    def test_external_inputs_and_symlinks_never_reuse(self):
        self.config['services']['channel']['build']['additional_contexts'] = {'external': '/elsewhere'}
        self.trial(); self.trial()
        del self.config['services']['channel']['build']['additional_contexts']
        (self.project / 'link').symlink_to(self.project / 'source')
        self.trial(); self.trial()
        self.assertEqual(len(self.images), 4)

    def test_failed_rebuild_cannot_leave_old_cache_valid(self):
        self.trial()
        (self.project / 'source').write_text('changed\n'); self.fail_build = True
        with self.assertRaises(RuntimeError): self.trial()
        (self.project / 'source').write_text('original\n'); self.fail_build = False
        self.trial()
        self.assertEqual(self.images, ['original\n', 'changed\n', 'original\n'])

    def test_clamp_workers_before_memory_check_and_park_unused_slots(self):
        import factory_pool
        with mock.patch.object(bench, 'isolated_inventory_services', return_value=True), \
             mock.patch.object(bench, 'factory_memory_fits', return_value=True) as fits, \
             mock.patch.object(bench, 'resolve_guard', return_value=self.guard), \
             mock.patch.object(bench.subprocess, 'run') as parked, \
             mock.patch.object(factory_pool, 'run_records', side_effect=RuntimeError('stop before trials')) as pool:
            with self.assertRaisesRegex(RuntimeError, 'stop before trials'):
                bench._run_case('none', 2, factory_workers=8)
        fits.assert_called_once_with((), 2)
        self.assertEqual(pool.call_args.args[4], 2)
        self.assertEqual([int(call.kwargs['env']['UNBUG_FACTORY_SLOT']) for call in parked.call_args_list], list(range(2, 8)))


if __name__ == '__main__':
    unittest.main()
