"""Offline smoke/driver checks: only temporary files and a fake provider transport."""

# Keep direct execution independent of the working directory.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))

import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader('gate_smoke', str(ROOT / 'bin/gate-smoke'))
spec = importlib.util.spec_from_loader(loader.name, loader)
smoke = importlib.util.module_from_spec(spec); loader.exec_module(smoke)


class SmokeTests(unittest.TestCase):
    def test_fixture_exercises_approved_case_local_service_history(self):
        sys.path[:0] = [str(ROOT / 'bin'), str(ROOT / 'factory')]
        import bench
        strategy = smoke.load_strategy()
        calls = []
        def checkpoint(scenarios, guard, report, runs, seed, label, **kwargs):
            self.assertEqual(kwargs, {'factory_workers': 2})
            self.assertEqual(runs, 2)
            calls.append(scenarios)
            return {'pass_runs': 2, 'legit_completion': 1, 'error_runs': 0, 'invalid_runs': 0}
        def simulate(case, name, runs, seed, *, execute, factory_workers):
            self.assertEqual(name, 'honest-reference')
            self.assertEqual(factory_workers, 2)
            ordered = strategy.steps(case)
            self.assertEqual(len(ordered), 3)
            self.assertEqual([s['delivery'] for s in ordered], ['announced', 'pending', 'announced'])
            from runpy import run_path
            checkpoint_api = run_path(str(ROOT / 'bin/checkpoint'))
            checks, schemas = checkpoint_api['oracle_requirements']([
                bench.load_scenario(s['scenario']) for s in ordered])
            self.assertEqual(checks, {'service:marketplace:confirmed_orders_ok'})
            self.assertEqual(schemas, {})
            self.assertIn('quantity: 11', (case / 'base/hooks.mjs').read_text())
            self.assertIn('ctx.record.services', (case / 'base/hooks.mjs').read_text())
            history = []
            for index, step in enumerate(ordered):
                paths = history + [step['scenario']]
                services = bench.inventory_services([bench.load_scenario(p) for p in paths])
                self.assertEqual([s['project'] for s in services], [(case / 'projects/marketplace').resolve()])
                execute(paths, step['reference'], {}, runs, seed, str(index))
                if step['delivery'] == 'pending':
                    self.assertEqual(step['key']['pending_correct'], ['approve'])
                    history.append(strategy.announced_scenario(step['scenario'], case.parent / 'approved-history'))
                else:
                    history.append(step['scenario'])
            return {'totals': {'unsafe': 0, 'wrong': 0}}
        from types import SimpleNamespace
        fake = SimpleNamespace(checkpoint=checkpoint, simulate=simulate)
        with tempfile.TemporaryDirectory() as tmp, patch.object(smoke, 'load_strategy', return_value=fake), \
             patch.object(bench, 'factory_memory_fits', return_value=True), \
             patch.object(smoke, 'prove_parallel', return_value=[]):
            smoke.step('g15-early', Path(tmp))
        self.assertEqual(len(calls), 3)

    def test_two_real_slot_receipts_required(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(smoke, 'ROOT', Path(tmp)):
            p = Path(tmp) / 'results/bench-progress-1.json'; p.parent.mkdir()
            row = {'slot': 0, 'status': 'completed', 'completed_trials': 2, 'total_trials': 2}
            p.write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError, 'both slots'): smoke.prove_parallel({})
            for slot in (0, 1):
                p = Path(tmp) / f'results/bench-progress-{slot + 2}.json'
                p.write_text(json.dumps({**row, 'slot': slot, 'completed_trials': 1, 'total_trials': 1}))
            self.assertEqual(len(smoke.prove_parallel({})), 3)
            with self.assertRaisesRegex(ValueError, 'both slots'): smoke.prove_parallel(smoke.progress())

    def test_failure_output_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'failure.log'
            with self.assertRaisesRegex(RuntimeError, 'synthetic seed cause'):
                smoke.child([sys.executable, '-c', "raise RuntimeError('synthetic seed cause')"],
                            time.monotonic() + 10, log)

    def test_both_orders_and_json_summary(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(smoke, 'ROOT', Path(tmp) / 'repo'), \
             patch.object(smoke, 'owned'):
            out = Path(tmp) / 'output'
            def child(args, deadline, log): log.write_text('GATE_SMOKE_JSON={}')
            with patch.object(smoke, 'child', child): self.assertEqual(smoke.execute('bx_fixture', out), 0)
            report = json.loads((out / 'summary.json').read_text())
            self.assertEqual(report['status'], 'PASS')
            for state in ('fresh', 'restored'):
                self.assertEqual([r['step'] for r in report['steps'] if r['state'] == state],
                                 ['prepare-state', 'account-handoff', 'g15-early', 'g3', 'g4', 'g5', 'g15-late'])

    def test_ownership_refused_without_marker_before_any_commands(self):
        with patch.object(smoke, 'MARKER', Path('/nonexistent-gate-smoke-fixture')), \
             patch.object(smoke.subprocess, 'run') as command:
            with self.assertRaises(FileNotFoundError): smoke.owned('bx_fixture')
            command.assert_not_called()

    def test_preallocation_accepts_only_exact_model_runtime_source(self):
        # Execute only the driver's actual Python preflight; never reach allocation.
        driver = (ROOT / 'tools/run-gate-smoke.sh').read_text()
        preflight = driver.split("<<'PYCODE'\n", 1)[1].split('\nPYCODE', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            names = ('factory/account_handoff.py', 'factory/restart.py', 'factory/control_resume.py', 'bin/push-secrets', 'tests/factory/test_account_handoff.py', 'tests/factory/test_control_resume.py', 'tests/factory/test_admission_handoff.py', 'tests/factory/fixtures/opencode-failover/policy.restore.json', 'tests/factory/fixtures/opencode-failover/launch.json', 'tests/factory/fixtures/opencode-failover/input-scorecard.json', 'tests/factory/fixtures/opencode-failover/launch-state.json', 'bin/gate-smoke', 'bin/bench.py', 'bin/bench_judging.py', 'bin/factory_pool.py',
                     'factory/gate_pipeline.py', 'factory/case_contract.py', 'factory/fairness.py',
                     'factory/founder_ruling.py', 'factory/restore_ledger.py', 'factory/recovery.py',
                     'factory/late_recovery.py', 'factory/founder_decisions.py', 'factory/late_rehearsal.py', 'factory/restore_bundle.py', 'bin/fake-pass-check',
                     'factory/run_artifacts.py', 'factory/run.py', 'factory/case_permissions.py', 'factory/model_runtime.py')
            for name in names:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT / name).read_bytes())
            adapter = root / 'adapter.py'
            adapter.write_text("import json\ndef load(release): return None,None,json.loads((release/'files.json').read_text())\n"
                               "def prepare(release,output): output.write_bytes(b'verified')\n")
            original = (root / 'factory/model_runtime.py').read_text()
            files = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
            output = root / 'bundle.tgz'
            def check(changes, accepted):
                output.unlink(missing_ok=True)
                (root / 'files.json').write_text(json.dumps({**files, **changes}))
                result = subprocess.run([sys.executable, '-B', '-', str(root), str(root), str(adapter),
                    hashlib.sha256(adapter.read_bytes()).hexdigest(), str(output)],
                    input=preflight, text=True, capture_output=True)
                self.assertEqual(result.returncode == 0, accepted, result.stderr)
                self.assertEqual(output.exists(), accepted)
            sha = lambda code: hashlib.sha256(code.encode()).hexdigest()
            check({}, True)
            for invalid in (original + '\n# unrelated edit\n', original.replace(
                    'case_budget_boundary(c, requested)', 'case_budget_boundary(c, requested)  # changed')):
                self.assertNotEqual(invalid, original)
                check({'factory/model_runtime.py': sha(invalid)}, False)
            check({'factory/model_runtime.py': None}, False)
            check({'factory/run.py': sha((root / 'factory/run.py').read_text() + '\n')}, False)
            for name in names[:-1]:
                check({name: '0' * 64}, False)

    def test_driver_lifecycle_uses_only_its_new_worker_and_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'tools').mkdir(); (root / 'bin').mkdir()
            driver = root / 'tools/run-gate-smoke.sh'
            driver.write_bytes((ROOT / 'tools/run-gate-smoke.sh').read_bytes())
            for name in ('boat-launch-guards.sh', 'boat-spend', 'processes.py'):
                target = root / 'bin' / name; target.write_bytes((ROOT / 'bin' / name).read_bytes()); target.chmod(0o755)
            names = ('factory/account_handoff.py', 'factory/restart.py', 'factory/control_resume.py', 'bin/push-secrets', 'tests/factory/test_account_handoff.py', 'tests/factory/test_control_resume.py', 'tests/factory/test_admission_handoff.py', 'tests/factory/fixtures/opencode-failover/policy.restore.json', 'tests/factory/fixtures/opencode-failover/launch.json', 'tests/factory/fixtures/opencode-failover/input-scorecard.json', 'tests/factory/fixtures/opencode-failover/launch-state.json', 'bin/gate-smoke', 'bin/bench.py', 'bin/bench_judging.py', 'bin/factory_pool.py', 'factory/run.py',
                     'factory/gate_pipeline.py', 'factory/case_contract.py', 'factory/fairness.py',
                     'factory/founder_ruling.py', 'factory/restore_ledger.py', 'factory/recovery.py',
                     'factory/late_recovery.py', 'factory/founder_decisions.py', 'factory/late_rehearsal.py', 'factory/restore_bundle.py', 'bin/fake-pass-check',
                     'factory/run_artifacts.py', 'factory/case_permissions.py', 'factory/model_runtime.py')
            for name in names:
                p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('synthetic source')
            adapter = root / 'adapter.py'
            adapter.write_text("import pathlib,json\ndef load(release): return None,None,json.loads((release/'manifest.json').read_text())\ndef prepare(release,output): output.write_bytes(b'public synthetic bundle')\n")
            (root / 'manifest.json').write_text(json.dumps({n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in names}))
            (root / 'tools/boat_readiness.py').write_text("import pathlib,sys\npathlib.Path(sys.argv[-1]).write_text('{}')\n")
            transport = root / 'bin/boat-call'
            transport.write_text(r"""#!/usr/bin/env python3
import json,os,pathlib,sys
args=sys.argv[1:]
if args[:1]==['--stdin']: args.pop(0); sys.stdin.buffer.read()
p=pathlib.Path(os.environ['FIXTURE_EVENTS'])
with p.open('a') as f: f.write(json.dumps(args)+'\n')
if args[0]=='billing': print(json.dumps({'limits':{'creditBalanceSeconds':10000000}}))
elif args[0]=='new': print(json.dumps({'event':'created','id':'bx_fixture'}))
elif args[0] in ('delete','deletion'):
 print(json.dumps({'operation':{'id':'op_fixture','targetId':'bx_fixture','kind':'sandbox','status':'completed','stage':'completed','completedAt':'2026-10-24T12:00:00Z'}}))
elif args[0]=='list': print(json.dumps({'sandboxes':[]}))
elif args[0]=='ssh' and 'bin/gate-smoke --run' in args[2] and os.environ.get('FIXTURE_SMOKE_FAIL'):
 print('synthetic remote seed failure',file=sys.stderr); sys.exit(17)
elif args[0]=='ssh' and 'summary.json' in args[2]: print(json.dumps({'status':'FAIL' if os.environ.get('FIXTURE_SMOKE_FAIL') else 'PASS'}))
""")
            transport.chmod(0o755)
            namer = root / 'bin/boat-name'; namer.write_text('#!/bin/sh\nexit 0\n'); namer.chmod(0o755)
            events = root / 'events.jsonl'
            env = {k: v for k, v in os.environ.items() if k not in ('BOAT_CMD', 'UNBUG_LAUNCH_STATE')}
            env['FIXTURE_EVENTS'] = str(events)
            env['UNBUG_CONTROL_HOME'] = str(root / 'control-home')
            args = ['sh', str(driver), '--release', str(root), '--adapter', str(adapter),
                    '--adapter-sha256', hashlib.sha256(adapter.read_bytes()).hexdigest(),
                    '--approved-by-founder', '--output', str(root / 'evidence')]
            p = subprocess.run(args, text=True, capture_output=True, env=env, timeout=30)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            calls = [json.loads(x) for x in events.read_text().splitlines()]
            self.assertEqual(sum(c[0] == 'new' for c in calls), 1)
            self.assertEqual(sum(c[0] == 'delete' for c in calls), 1)
            self.assertTrue(all(c[1] == 'bx_fixture' for c in calls if c[0] in ('ssh', 'delete')))
            self.assertTrue(list(root.glob('results/spend/*.deletions/bx_fixture/deletion-completion.json')))
            upload = next(c[2] for c in calls if c[0] == 'ssh' and 'sha256sum -c' in c[2])
            self.assertNotIn(str(Path.home()), upload)
            self.assertIn('gate-smoke-release.tgz', upload)
            # Old release/source drift must refuse before the fake provider sees a new call.
            before = len(calls)
            for name in ('bin/bench.py', 'bin/bench_judging.py', 'factory/gate_pipeline.py',
                         'factory/case_contract.py', 'factory/run_artifacts.py', 'factory/case_permissions.py', 'factory/model_runtime.py'):
                (root / name).write_text('changed after qualification')
                p = subprocess.run(args, text=True, capture_output=True, env=env, timeout=10)
                self.assertNotEqual(p.returncode, 0)
                self.assertEqual(len(events.read_text().splitlines()), before)
                (root / name).write_text('synthetic source')
            # A real remote failure must still collect the FAIL and delete this worker.
            p = subprocess.run(args, text=True, capture_output=True,
                               env={**env, 'FIXTURE_SMOKE_FAIL': '1'}, timeout=30)
            self.assertNotEqual(p.returncode, 0)
            calls = [json.loads(x) for x in events.read_text().splitlines()]
            self.assertEqual(sum(c[0] == 'new' for c in calls), 2)
            self.assertEqual(sum(c[0] == 'delete' for c in calls), 2)


if __name__ == '__main__': unittest.main()
