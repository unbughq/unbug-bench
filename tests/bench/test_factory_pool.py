"""Parallel runner regressions with real child processes and synthetic runtime I/O."""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import contextlib
import io
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str((_BENCH_ROOT / "bin")))
import bench
import factory_pool


def runtime(root, slot):
    """Only Docker/traffic/oracle I/O is fake; freezing, receipts and fingerprints are real."""
    results = root / 'results' if not slot else root / 'results/factory-slots' / str(slot)
    results.mkdir(parents=True, exist_ok=True)
    ids = root / 'projects/medusa/seed-ids.json' if not slot else results / 'seed-ids.json'
    stack = contextlib.ExitStack()
    stack.enter_context(mock.patch.multiple(bench, ROOT=root, RESULTS=results, IDS=ids, FACTORY_SLOT=slot))
    def command(args, **kwargs):
        if args[:2] == ['docker', 'cp']:
            ids.write_text('{"admin":{"email":"synthetic","password":"synthetic"}}')
            (results / 'seeded').write_text('yes')
        return '{}'
    def reset(*args, scenarios=(), **kwargs):
        if not ids.is_file(): raise RuntimeError('synthetic unseeded database')
        mutation = os.environ.get('G15_MUTATION')
        if mutation and kwargs.get('app_prepared'):
            guard = pathlib.Path(args[0])
            target = {'guard': guard / 'db.sql', 'scenario': scenarios[-1]['dir'] / 'judge.py',
                      'policy': scenarios[-1]['dir'] / 'refusal-policy.json',
                      'service': bench.inventory_services(scenarios)[0]['project'] / 'adapter.py'}[mutation]
            target.write_text(target.read_text() + '\n ')
        return {'reset_seconds': 0}
    for name, fake in (
        ('command', command), ('dc', lambda *a, **k: ''), ('sql', lambda *a, **k: ''),
        ('reset', reset), ('stop_inventory_services', lambda: None),
        ('prepare_app_guard', lambda *a: None), ('checker', lambda: {'valid': True, 'pass': True}),
        ('score', lambda r: None), ('check_inventory_services', lambda *a: {}),
        ('judge_checkpoint', lambda *a, **k: {'pass': True, 'facts': {}}),
    ):
        stack.enter_context(mock.patch.object(bench, name, fake))
    import refusal
    stack.enter_context(mock.patch.object(refusal.BehavioralRefusal, 'start', lambda self: None))
    def finalize(self, result):
        self.failure = ''; self.identity = {'synthetic': True}
    stack.enter_context(mock.patch.object(refusal.BehavioralRefusal, 'finalize', finalize))
    return stack


class ParallelTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name).resolve()
        self.guard = self.root / 'guard'; self.guard.mkdir()
        (self.guard / 'db.sql').write_text('-- synthetic guard\n')
        for name in ('cases/medusa-oversell/checker/check.sql', 'cases/medusa-oversell/traffic/run.mjs',
                     'factory/case_permissions.py', 'bin/bench.py', 'bin/bench_judging.py', 'bin/refusal.py', 'projects/medusa/seed-ids.json'):
            p = self.root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('{}')
        (self.root / 'case').mkdir()
        (self.root / 'case/case.json').write_text('{"policy":"synthetic"}')
        service = self.root / 'service'; service.mkdir()
        (service / 'compose.yaml').write_text('services: {}\n')
        (service / 'adapter.py').write_text('# synthetic adapter\n')
        self.scenarios = []
        for name in ('establish', 'portal-launch', 'runbook-docs', 'portal-cache'):
            p = self.root / 'case/scenarios' / name; p.mkdir(parents=True)
            (p / 'scenario.json').write_text(json.dumps({'id': name, 'inventory_services': [
                {'name': 'channel', 'project': str(service), 'host_ports': [9010]}]}))
            (p / 'judge.py').write_text('def judge(*a): return {}\n')
            self.scenarios.append(bench.load_scenario(p))
        (p / 'refusal_oracle.py').write_text('# synthetic oracle\n')
        self.child_records = []
        self.differences = []
        real_run = subprocess.run
        def child(args, *, env, check=False, **kwargs):
            if args[1:3] == ['-c', 'import bench; bench.prepare_factory_slot()']:
                bootstrap = ('import os,sys,pathlib; slot=int(os.environ.pop("UNBUG_FACTORY_SLOT")); '
                             'sys.path.insert(0, ' + repr(str(pathlib.Path(__file__).resolve().parent)) + '); '
                             'import test_factory_pool as fixture; os.environ["UNBUG_FACTORY_SLOT"]=str(slot); '
                             'ctx=fixture.runtime(pathlib.Path(os.environ["G15_ROOT"]),slot); '
                             'fixture.bench.prepare_factory_slot()')
                return real_run([sys.executable, '-c', bootstrap],
                                env={**env, 'G15_ROOT': str(self.root)}, check=check,
                                capture_output=True, text=True)
            if len(args) < 4 or args[1] != factory_pool.__file__:
                return subprocess.CompletedProcess(args, 0)
            job = json.loads(pathlib.Path(args[2]).read_text())
            # Import without the production slot's module-level filesystem side effects.
            bootstrap = ('import os,sys,runpy,pathlib; slot=int(os.environ.pop("UNBUG_FACTORY_SLOT")); '
                         'sys.path.insert(0, ' + repr(str(pathlib.Path(__file__).resolve().parent)) + '); '
                         'import test_factory_pool as fixture; os.environ["UNBUG_FACTORY_SLOT"]=str(slot); '
                         'sys.argv=sys.argv[1:]; '
                         'ctx=fixture.runtime(pathlib.Path(os.environ["G15_ROOT"]),slot); '
                         'runpy.run_path(sys.argv[0],run_name="__main__")')
            try:
                result = real_run([sys.executable, '-c', bootstrap, *args[1:]],
                                  env={**env, 'G15_ROOT': str(self.root)}, check=check,
                                  capture_output=True, text=True)
            except subprocess.CalledProcessError as error:
                error.add_note(error.stderr)
                raise
            records = json.loads(pathlib.Path(args[3]).read_text())
            self.child_records.extend(records)
            # Record the exact identity field and byte differences before parent scoring.
            expected = bench.installation_identity(pathlib.Path(job['guard']),
                                                  [bench.load_scenario(s) for s in job['scenarios']])
            for r in records:
                for n, (want, got) in enumerate(zip(expected['scenarios'], r.get('installation', {}).get('scenarios', []))):
                    if want != got:
                        copied = self.root / r['scenarios'][n]['dir']
                        original = bench.scenario_files({'dir': pathlib.Path(job['scenarios'][n])})
                        actual = bench.scenario_files({'dir': copied})
                        self.differences.append({'field': f'scenarios[{n}].sha256',
                                                 'expected': want['sha256'], 'actual': got['sha256'],
                                                 'files': [f for f in original.keys() | actual.keys()
                                                           if original.get(f) != actual.get(f)],
                                                 'parent': json.loads(original['scenario.json']),
                                                 'child': json.loads(actual['scenario.json'])})
            return result
        self.stack = contextlib.ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(runtime(self.root, 0))
        self.stack.enter_context(mock.patch.object(bench, 'factory_memory_fits', return_value=True))
        self.stack.enter_context(mock.patch.object(factory_pool.subprocess, 'run', child))

    def run_case(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            summary = bench.run_case(self.guard, 3, scenarios=self.scenarios, factory_workers=2, **kwargs)
        directory = self.root / summary['results_directory']
        return summary, [json.loads((directory / f'{n:02}.json').read_text()) for n in (1, 2, 3)]

    def seed_slot(self):
        p = self.root / 'results/factory-slots/1/seed-ids.json'
        p.parent.mkdir(parents=True, exist_ok=True); p.write_text('{}')
        (p.parent / '.prepared.json').write_text(json.dumps({'version': 1, 'slot': 1,
            'seed_ids_sha256': hashlib.sha256(p.read_bytes()).hexdigest()}))

    def test_fresh_slot_is_seeded_before_trials(self):
        # No scenarios: isolate missing seed IDs from the independent re-freeze bug.
        self.scenarios = []
        summary, records = self.run_case()
        self.assertTrue((self.root / 'results/factory-slots/1/seeded').exists())
        self.assertEqual(summary['errors'], 0, records)
        self.assertEqual([r['run'] for r in records], [1, 2, 3])
        self.assertFalse((self.root / 'results/seeded').exists(), 'existing slot zero must not be reseeded')

    def test_parallel_uses_the_same_frozen_installation(self):
        self.seed_slot()
        summary, records = self.run_case()
        self.assertTrue(all(not r['errors'] for r in self.child_records), self.child_records)
        self.assertEqual(summary['errors'], 0, json.dumps(self.differences, indent=2))
        self.assertTrue(all(r.get('installation') for r in records))
        self.assertFalse((self.root / 'results/factory-slots/1/seeded').exists())

    def test_parent_preserves_each_workers_seed_fingerprint(self):
        self.seed_slot()
        ids = self.root / 'results/factory-slots/1/seed-ids.json'
        ids.write_text('{"seed":"different worker manifest"}')
        (ids.parent / '.prepared.json').write_text(json.dumps({'version': 1, 'slot': 1,
            'seed_ids_sha256': hashlib.sha256(ids.read_bytes()).hexdigest()}))
        _, records = self.run_case()
        field = 'projects/medusa/seed-ids.json'
        expected = {r['run']: r['bench_sha256'][field] for r in self.child_records}
        self.assertEqual(len(set(expected.values())), 2)
        self.assertEqual({r['run']: r['bench_sha256'][field] for r in records}, expected)

    def test_real_input_changes_still_fail(self):
        self.seed_slot()
        for mutation in ('guard', 'scenario', 'policy', 'service'):
            with self.subTest(mutation=mutation), mock.patch.dict(os.environ, G15_MUTATION=mutation):
                summary, records = self.run_case()
                self.assertEqual(summary['errors'], 3, records)
                self.assertTrue(all('installation' not in r for r in records))

    def test_serial_fallback_avoids_the_pool(self):
        for isolated, fits in ((False, True), (True, False)):
            with self.subTest(isolated=isolated, fits=fits), \
                 mock.patch.object(bench, 'isolated_inventory_services', return_value=isolated), \
                 mock.patch.object(bench, 'factory_memory_fits', return_value=fits), \
                 mock.patch.object(factory_pool, 'run_records') as pool:
                summary, records = self.run_case()
                pool.assert_not_called()
                self.assertEqual(summary['errors'], 0, records)

    def test_parent_snapshot_changes_after_trials_still_fail(self):
        self.seed_slot()
        run_records = factory_pool.run_records
        for mutation in ('guard', 'scenario'):
            def mutate(guard, numbers, options, scenarios, workers, per_run_options):
                records = run_records(guard, numbers, options, scenarios, workers, per_run_options)
                target = guard / 'db.sql' if mutation == 'guard' else scenarios[-1]['dir'] / 'judge.py'
                target.write_text(target.read_text() + '\n# changed after trials\n')
                return records
            with self.subTest(mutation=mutation), mock.patch.object(factory_pool, 'run_records', mutate):
                self.child_records.clear()
                summary, records = self.run_case()
                self.assertTrue(all(not r['errors'] for r in self.child_records))
                self.assertEqual(summary['errors'], 3, records)
                self.assertTrue(all('installation' not in r for r in records))


if __name__ == '__main__':
    unittest.main()
