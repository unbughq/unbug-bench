"""Synthetic strategy checkpoints only; no Docker, models or sealed data."""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import importlib.machinery, importlib.util, json, pathlib, tempfile, unittest
from unittest.mock import patch, Mock
import subprocess, contextlib, io

loader = importlib.machinery.SourceFileLoader('strategy', str((_BENCH_ROOT / "bin" / 'strategy')))
spec = importlib.util.spec_from_loader(loader.name, loader)
strategy = importlib.util.module_from_spec(spec); loader.exec_module(strategy)


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def checkpoint_files(path, summary):
    """Materialize the run evidence the subprocess adapter is expected to return."""
    runs = summary['runs']
    summary.setdefault('paths', {})
    summary.setdefault('checks', {})
    passed = all(p['violated_runs'] == 0 for p in summary.get('paths', {}).values()) and all(
        c['ok_runs'] == runs for c in summary.get('checks', {}).values())
    summary.setdefault('pass_runs', runs if passed else 0)
    for number in range(1, runs + 1):
        write(path.parent / f'{number:02}.json', {'run': number, 'errors': [],
              'checker': {'valid': True}, 'judge': {'pass': passed,
              'paths': {name: value['violated_runs'] > 0 for name, value in summary.get('paths', {}).items()},
              'checks': {name: value['ok_runs'] == runs for name, value in summary.get('checks', {}).items()}}})
    write(path, summary)


def fixture(case):
    ingredients = {'unstated_rules': [{'id': 'rule', 'scenario': 'blind', 'intent_check': 'intent', 'fact_sheet_anchor': 'decision'}],
                   'second_writer': {'service': 'fixture-writer', 'path': 'second'},
                   'pending': {'harmful': ['harmful'], 'harmless': ['harmless']}, 'blind': ['blind'], 'unannounced': []}
    write(case / 'case.json', {'ingredients': ingredients, 'steps': ['blind', 'harmful', 'harmless']})
    write(case / 'answer-key.json', {'blind': {'reference_guard': 'guards/updated'}})
    (case / 'fact-sheet.md').write_text('# Decision\nOwner answer.\n')
    for name in ('reference', 'updated', 'one-place', 'wrong-guess/rule'):
        p = case / 'guards' / name; p.mkdir(parents=True); (p / 'db.sql').write_text('-- fixture\n')
    for sid in ('establish', 'blind', 'harmful', 'harmless'):
        directory = case / ('base' if sid == 'establish' else 'scenarios/' + sid)
        write(directory / 'scenario.json', {'id': sid, 'delivery': 'pending' if sid in ('harmful', 'harmless') else 'announced'})
        key = {'correct_responses': ['keep'], 'claims': {'*': ['protected']}}
        if sid == 'blind': key['intent_checks'] = ['intent']
        if sid in ('harmful', 'harmless'):
            key.update(pending_correct=['block'] if sid == 'harmful' else ['approve'], pending_harmful=sid == 'harmful', owner_decision='block' if sid == 'harmful' else 'approve')
        write(directory / 'key.json', key)
    return ingredients


def execute(scenarios, guard, report, runs, seed, label):
    sid = json.loads((scenarios[-1] / 'scenario.json').read_text())['id']
    key = json.loads((scenarios[-1] / 'key.json').read_text())
    decision = report.get('pending_decision', 'approve')
    landed = decision == 'approve' or decision == 'escalate' and key['owner_decision'] == 'approve'
    bad = sid == 'blind' and guard.name in ('reference', 'rule') or sid == 'harmful' and landed
    summary = {'runs': runs, 'error_runs': 0, 'invalid_runs': 0, 'legit_completion': 1,
            'paths': {'shop': {'runs': runs, 'violated_runs': runs if bad else 0},
                      'second': {'runs': runs, 'violated_runs': runs if guard.name == 'one-place' else 0}},
            'checks': {'intent': {'runs': runs, 'ok_runs': 0 if guard.name == 'rule' else runs},
                       'monitor_blind': {'runs': runs, 'ok_runs': runs},
                       'monitor_blind.fixture-writer': {'runs': runs, 'ok_runs': runs}}, 'key': key,
            **({'pending': {'decision': decision, 'missing': False, 'landed': landed}} if 'pending_correct' in key else {})}
    # Synthetic judge-proof schema for strategy-only fixtures. Production provenance
    # and fail-closed verification are exercised by test_pending_proof.py.
    if 'pending_correct' in key:
        summary.update(scenarios=[sid], guard=guard.name, pass_runs=0 if bad else runs,
                       errors=[], legit={'attempted': runs * 10, 'placed': runs * 10},
                       landed_scenarios=[sid] if landed else [])
        summary['pending_verification'] = {
            'version': strategy.claims.SCORING_VERSION, **strategy.claims.scoring_identity(), 'verified': not bad,
            'guard_sha256': 'a' * 64, 'record_sha256': ['b' * 64] * runs,
            'installed_scenarios': [{'id': sid, 'sha256': 'c' * 64}],
            'requested_runs': runs, 'binding': strategy.claims.pending_binding(summary)}
    return summary


class StrategyTests(unittest.TestCase):
    def test_approved_history_preserves_case_local_inventory(self):
        import bench
        with tempfile.TemporaryDirectory() as tmp:
            case = pathlib.Path(tmp) / 'case'; case.mkdir(); fixture(case)
            project = case / 'projects/trade-portal'; project.mkdir(parents=True)
            (project / 'compose.yaml').write_text('services: {}')
            (project / 'adapter.py').write_text('# public path fixture')
            for path in [case / 'base', *sorted((case / 'scenarios').iterdir())]:
                meta = json.loads((path / 'scenario.json').read_text())
                meta['inventory_services'] = [{'name': 'trade-portal', 'project':
                    '../projects/trade-portal' if path.name == 'base' else '../../projects/trade-portal',
                    'host_ports': [9010]}]
                write(path / 'scenario.json', meta)
            meta = json.loads((case / 'case.json').read_text())
            meta['steps'] = ['harmless', 'blind', 'harmful']; write(case / 'case.json', meta)
            original = (case / 'scenarios/harmless/scenario.json').read_bytes()
            seen = []
            def driver(*args):
                services = bench.inventory_services([bench.load_scenario(p) for p in args[0]])
                self.assertEqual([s['project'] for s in services], [project.resolve()])
                seen.append(args[0])
                return execute(*args)
            for name in strategy.STRATEGIES:
                strategy.simulate(case, name, execute=driver)
            # G14 used to make its own broken history copy outside simulate().
            sys.path.insert(0, str(_BENCH_ROOT / 'factory'))
            import run
            from types import SimpleNamespace
            def checkpoint(scenarios, guard, report, runs, seed, label, **kwargs):
                self.assertEqual(kwargs, {'factory_workers': 2})
                return driver(scenarios, guard, report, runs, seed, label)
            with patch.object(run, 'strategy_module', return_value=strategy), \
                 patch.object(run, 'case_ingredients', return_value=[]), \
                 patch.object(strategy, 'checkpoint', checkpoint):
                ok, detail = run.g14(SimpleNamespace(case=case, seed=1, work=pathlib.Path(tmp) / 'work',
                    args=SimpleNamespace(dry_run=False, scenario_runs=3, bench_workers=2)))
            self.assertTrue(ok, detail)
            self.assertEqual((case / 'scenarios/harmless/scenario.json').read_bytes(), original)
            self.assertTrue(any(any(not p.is_relative_to(case) for p in paths) for paths in seen))

    def test_silent_steps_carry_watcher_claims_without_a_new_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = pathlib.Path(tmp); fixture(case)
            meta = json.loads((case / 'case.json').read_text())
            meta['steps'] += ['quiet-one', 'quiet-two']
            meta['ingredients']['unannounced'] = ['quiet-one', 'quiet-two']
            write(case / 'case.json', meta)
            for sid in meta['ingredients']['unannounced']:
                write(case / 'scenarios' / sid / 'scenario.json', {'id': sid, 'delivery': 'unannounced'})
                write(case / 'scenarios' / sid / 'key.json', {'correct_responses': ['keep']})
            reports = []
            replacement = {'response': 'withdraw', 'claims': [{'path': 'shop', 'status': 'unknown'}]}
            def window(case, step, prior, guard, report, watching):
                self.assertTrue(watching)
                reports.append(report)
                return {'_evidence_path': str(case / (step['id'] + '-checkpoint.json')), 'latest_claims': replacement, 'claims_score': {'unsafe_checkpoint': False,
                    'response_correct': True, 'human_minutes': {'total': 0}, 'exposure': {'paths': {}}}}
            with patch.object(strategy, 'silent_checkpoint', window):
                result = strategy.simulate(case, 'ask-everything', execute=execute)
            self.assertEqual(reports[1], replacement)
            self.assertEqual(result['_evidence_paths'], [str(case / (sid + '-checkpoint.json')) for sid in ('quiet-one', 'quiet-two')])
            self.assertEqual([s['questions'] for s in result['unannounced']], [0, 0])
            self.assertEqual(result['totals']['human_minutes'], 535)

    def test_checkpoint_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); summary = root / 'checkpoint.json'
            checkpoint_files(summary, {'runs': 1, 'error_runs': 0, 'invalid_runs': 0})
            def command(argv, **kwargs):
                self.assertEqual(json.loads(pathlib.Path(argv[argv.index('--claims') + 1]).read_text()), {'pending_decision': 'block'})
                self.assertEqual(argv[1:5], ['--scenario', str(root / 'base'), '--scenario', str(root / 'pending')])
                state = pathlib.Path(argv[argv.index('--pending-state') + 1])
                self.assertEqual(state.parent, pathlib.Path(argv[argv.index('--claims') + 1]).parent)
                self.assertFalse(state.exists(), 'independent strategy checkpoints must not inherit decisions')
                return subprocess.CompletedProcess(argv, 0, 'Checkpoint: ' + str(summary) + '\n')
            with patch.object(strategy.processes, 'run', command):
                result = strategy.checkpoint([root / 'base', root / 'pending'], root / 'guard', {'pending_decision': 'block'}, 1, 7, 'fixture')
                self.assertEqual(result['runs'], 1)
                self.assertEqual(result['_evidence_path'], str(summary.resolve()))
            summary.write_text('{"error_runs": 1}')
            with patch.object(strategy.processes, 'run', command), self.assertRaises(RuntimeError):
                strategy.checkpoint([root / 'base', root / 'pending'], root / 'guard', {'pending_decision': 'block'}, 1, 7, 'fixture')

    def test_cli_workers_reach_checkpoints_without_changing_history_or_trials(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = pathlib.Path(tmp); fixture(case)
            for flags, workers in (([], 1), (['--factory-workers', '3'], 3)):
                seen = []
                def command(argv, **kwargs):
                    self.assertEqual(int(argv[argv.index('--factory-workers') + 1]), workers)
                    self.assertEqual(argv[argv.index('--runs') + 1], '5')
                    self.assertEqual(argv[argv.index('--seed') + 1], '41')
                    self.assertEqual(pathlib.Path(argv[0]), strategy.BENCH / 'bin/checkpoint')
                    scenarios = [pathlib.Path(argv[i + 1]) for i, value in enumerate(argv) if value == '--scenario']
                    guard = pathlib.Path(argv[argv.index('--guard') + 1])
                    report = json.loads(pathlib.Path(argv[argv.index('--claims') + 1]).read_text())
                    label = argv[argv.index('--label') + 1]
                    seen.append([json.loads((path / 'scenario.json').read_text())['id'] for path in scenarios])
                    summary = case / 'checkpoint.json'
                    checkpoint_files(summary, execute(scenarios, guard, report, 5, 41, label))
                    return subprocess.CompletedProcess(argv, 0, 'Checkpoint: ' + str(summary) + '\n')
                argv = ['strategy', '--case', str(case), '--strategy', 'honest-reference', '--runs', '5', '--seed', '41', *flags]
                with patch.object(strategy.sys, 'argv', argv), patch.object(strategy.processes, 'run', command), contextlib.redirect_stdout(io.StringIO()) as output:
                    strategy.main()
                self.assertEqual(json.loads(output.getvalue())['_evidence_paths'], [str((case / 'checkpoint.json').resolve())] * 4)
                self.assertEqual(seen, [['establish'], ['establish', 'blind'],
                                        ['establish', 'blind', 'harmful'], ['establish', 'blind', 'harmless']])
                self.assertEqual(json.loads(output.getvalue())['totals'],
                                 {'steps': 4, 'unsafe': 0, 'wrong': 0, 'human_minutes': 5})

    def test_cli_rejects_nonpositive_workers_before_execution(self):
        for workers in ('0', '-1'):
            with patch.object(strategy.sys, 'argv', ['strategy', '--case', '.', '--strategy', 'honest-reference', '--factory-workers', workers]), patch.object(strategy.processes, 'run') as command, contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
                strategy.main()
            self.assertEqual(stopped.exception.code, 2)
            command.assert_not_called()

    def test_diagnostic_limits_one_attempt_and_removes_mode_from_child(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            args = SimpleNamespace(case=root, strategy='honest-reference', seed=17)
            process = Mock(pid=99999999, returncode=0)
            process.communicate.return_value = ('{"_evidence_paths": [], "totals": {}}', '')
            with patch.object(strategy.subprocess, 'Popen', return_value=process) as start, patch('os.killpg') as kill, patch.dict(strategy.os.environ, {'FACTORY_STRATEGY_DIAGNOSTIC': str(root), 'FACTORY_STRATEGY_SECONDS': '2'}):
                result = strategy.diagnostic(args, root, seconds=2, workers=3)
                command = start.call_args.args[0]
                self.assertEqual(command[command.index('--runs') + 1], '1')
                self.assertEqual(command[command.index('--factory-workers') + 1], '3')
                self.assertFalse(any(k.startswith('FACTORY_STRATEGY_') for k in start.call_args.kwargs['env']))
                self.assertTrue(start.call_args.kwargs['start_new_session'])
                self.assertEqual(result['diagnostic'], {'gate_evidence': False, 'runs': 1})
                self.assertEqual(json.loads((root / 'status.json').read_text())['status'], 'completed')
                with self.assertRaisesRegex(RuntimeError, 'allowance exhausted'):
                    strategy.diagnostic(args, root, seconds=2)
                self.assertEqual(start.call_count, 1)
                kill.assert_called_once()

    def test_diagnostic_timeout_is_unfinished_and_kills_process_group(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            args = SimpleNamespace(case=root, strategy='honest-reference', seed=17)
            process = Mock(pid=99999999)
            process.communicate.side_effect = [subprocess.TimeoutExpired('fixture', 1), ('', '')]
            with patch.object(strategy.subprocess, 'Popen', return_value=process), patch('os.killpg') as kill:
                with self.assertRaisesRegex(RuntimeError, 'unfinished, not passed'):
                    strategy.diagnostic(args, root, seconds=1)
                kill.assert_called_once()
            status = json.loads((root / 'status.json').read_text())
            self.assertEqual(status['status'], 'timeout')
            self.assertFalse(status['gate_evidence'])

    def test_real_diagnostic_timeout_stops_term_ignoring_silent_watcher(self):
        import os, sys, time
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'harbor/task/steps/quiet').mkdir(parents=True)
            (root / 'harbor/task/task.toml').write_text('')
            write(root / 'harbor/task/steps/quiet/window.json', {'synthetic': True})
            guard = root / 'guard'; guard.mkdir()
            heartbeat = root / 'heartbeat'
            pidfile = root / 'watcher.pid'
            watcher = root / 'watcher.py'
            watcher.write_text("import os,signal,time,pathlib\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                               + "pathlib.Path(" + repr(str(pidfile)) + ").write_text(str(os.getpid()))\n"
                               + "while True:\n pathlib.Path(" + repr(str(heartbeat)) + ").write_text(str(time.time_ns()))\n time.sleep(.02)\n")
            import shlex
            (guard / 'watch.sh').write_text('exec ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(watcher)) + '\n')
            runner = root / 'runner.py'
            runner.write_text("import sys,pathlib,types,asyncio,importlib.machinery,importlib.util\n"
                + "sys.path.insert(0," + repr(str(pathlib.Path(strategy.__file__).parent)) + ")\n"
                + "loader=importlib.machinery.SourceFileLoader('under_test'," + repr(str(pathlib.Path(strategy.__file__).resolve())) + ")\n"
                + "spec=importlib.util.spec_from_loader(loader.name,loader);mod=importlib.util.module_from_spec(spec);loader.exec_module(mod)\n"
                + "sys.modules['bench']=types.SimpleNamespace(reset=lambda *a,**k:None,RESULTS=pathlib.Path(" + repr(str(root / 'results')) + "))\n"
                + "async def window(*a):\n await asyncio.sleep(60)\n"
                + "sys.modules['silent_window']=types.SimpleNamespace(run_window=window)\n"
                + "mod.silent_checkpoint(pathlib.Path(" + repr(str(root)) + "),{'name':'quiet','id':'quiet'},[],pathlib.Path(" + repr(str(guard)) + "),{},True)\n")
            args = SimpleNamespace(case=root, strategy='honest-reference', seed=1)
            try:
                with patch.object(strategy, '__file__', str(runner)):
                    with self.assertRaisesRegex(RuntimeError, 'unfinished, not passed'):
                        strategy.diagnostic(args, root / 'budget', seconds=2)
                self.assertTrue(pidfile.exists(), 'synthetic watcher must actually start')
                before = heartbeat.read_bytes()
                time.sleep(.15)
                self.assertEqual(heartbeat.read_bytes(), before)
                pid = int(pidfile.read_text())
                state = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True).stdout.strip()
                self.assertTrue(not state or state.startswith('Z'), state)
            finally:
                if pidfile.exists():
                    try: os.kill(int(pidfile.read_text()), 9)
                    except ProcessLookupError: pass

    def test_partial_checkpoint_resume_reuses_only_completed_intact_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); case = root / 'case'; case.mkdir(); fixture(case)
            cache = root / 'cache'
            seen = []
            interrupt = True
            def driver(scenarios, guard, report, runs, seed, label):
                if interrupt and len(seen) == 2: raise RuntimeError('synthetic interruption')
                seen.append(label)
                summary = execute(scenarios, guard, report, runs, seed, label)
                path = root / 'results/runs' / str(len(seen)) / 'checkpoint.json'
                write(path, summary)
                summary['_evidence_path'] = str(path)
                return summary
            kwargs = dict(execute=driver, checkpoint_cache_dir=cache, checkpoint_binding=lambda: 'implementation-v1')
            with patch.object(strategy, 'BENCH', root):
                with self.assertRaisesRegex(RuntimeError, 'synthetic interruption'):
                    strategy.simulate(case, 'honest-reference', **kwargs)
                interrupt = False
                resumed = strategy.simulate(case, 'honest-reference', **kwargs)
                self.assertEqual(len(seen), 4, 'completed prefix must not execute twice')
                expected = strategy.simulate(case, 'honest-reference', execute=execute)
                self.assertEqual(resumed['steps'], expected['steps'])
                self.assertEqual(resumed['totals'], expected['totals'])
                strategy.simulate(case, 'honest-reference', **kwargs)
                self.assertEqual(len(seen), 4)
                checkpoint = pathlib.Path(resumed['_evidence_paths'][0])
                checkpoint.write_text('{}')
                strategy.simulate(case, 'honest-reference', **kwargs)
                self.assertEqual(len(seen), 5, 'tampered checkpoint must rerun')
                # Inputs and implementation identity independently invalidate completed receipts.
                (case / 'guards/reference/db.sql').write_text('-- changed fixture')
                strategy.simulate(case, 'honest-reference', **kwargs)
                self.assertEqual(len(seen), 6)
                strategy.simulate(case, 'honest-reference', **{**kwargs, 'checkpoint_binding': lambda: 'implementation-v2'})
                self.assertEqual(len(seen), 10)
                strategy.simulate(case, 'honest-reference', seed=99, **kwargs)
                self.assertEqual(len(seen), 14)
                with patch.object(strategy.claims, 'SCORING_VERSION', 'changed-scoring-semantics'):
                    strategy.simulate(case, 'honest-reference', seed=99, **kwargs)
                self.assertEqual(len(seen), 18, 'changed scorer invalidates old scoring receipts')

    def test_incomplete_checkpoint_never_creates_partial_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); case = root / 'case'; case.mkdir(); fixture(case)
            seen = []
            def driver(*args):
                seen.append(args[-1])
                summary = execute(*args)
                summary['runs'] = 2  # requested 3: interruption cannot become reusable evidence
                path = root / 'results/runs' / str(len(seen)) / 'checkpoint.json'
                write(path, summary)
                summary['_evidence_path'] = str(path)
                return summary
            with patch.object(strategy, 'BENCH', root):
                for _ in range(2):
                    strategy.simulate(case, 'honest-reference', runs=3, execute=driver,
                                      checkpoint_cache_dir=root / 'cache', checkpoint_binding=lambda: 'same')
            self.assertEqual(len(seen), 8)
            self.assertFalse((root / 'cache').exists())

    def test_live_windows_disable_partial_strategy_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = pathlib.Path(tmp); fixture(case)
            meta = json.loads((case / 'case.json').read_text()); meta['steps'].append('quiet')
            write(case / 'case.json', meta)
            write(case / 'scenarios/quiet/scenario.json', {'id': 'quiet', 'delivery': 'unannounced'})
            write(case / 'scenarios/quiet/key.json', {'correct_responses': ['keep']})
            window = {'runs': 1, 'latest_claims': {}, 'claims_score': {'unsafe_checkpoint': False,
                      'response_correct': True, 'human_minutes': {'total': 0}, 'exposure': {}}}
            driver = Mock(side_effect=execute)
            with patch.object(strategy, 'silent_checkpoint', return_value=window):
                for _ in range(2):
                    strategy.simulate(case, 'honest-reference', execute=driver,
                                      checkpoint_cache_dir=case / 'cache', checkpoint_binding=lambda: 'same')
            self.assertEqual(driver.call_count, 8)
            self.assertFalse((case / 'cache').exists())

    def test_all_strategies_and_pending_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = pathlib.Path(tmp); fixture(case)
            seen = []
            def driver(*args):
                seen.append(([json.loads((p / 'scenario.json').read_text()) for p in args[0]], args[2]))
                return execute(*args)
            results = {s: strategy.simulate(case, s, execute=driver) for s in strategy.STRATEGIES}
            self.assertEqual(results['honest-reference']['totals'], {'steps': 4, 'unsafe': 0, 'wrong': 0, 'human_minutes': 5})
            self.assertEqual(results['honest-reference']['steps'][2]['pending_outcome'], 'prevented')
            self.assertEqual(results['block-all-pending']['steps'][3]['pending_outcome'], 'false-block')
            self.assertGreater(results['frozen-first-fix']['totals']['unsafe'], 0)
            self.assertGreater(results['claim-without-evidence']['totals']['unsafe'], 0)
            self.assertEqual(results['ask-everything']['steps'][1]['questions'], 11)
            self.assertEqual(results['ask-everything']['totals']['human_minutes'], 535)
            # Each current pending change is delivered only to checkpoint; accepted history is announced.
            self.assertTrue(all(all(s['delivery'] == 'announced' for s in history[:-1]) for history, _ in seen))
            self.assertNotIn('pending', results['honest-reference']['skipped'])

    def test_identical_executions_run_once_across_strategies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); case = root / 'case'; case.mkdir(); fixture(case)
            seen = []
            def driver(scenarios, guard, report, runs, seed, label):
                seen.append(label)
                summary = execute(scenarios, guard, report, runs, seed, label)
                path = root / 'results/runs' / str(len(seen)) / 'checkpoint.json'
                write(path, summary)
                summary['_evidence_path'] = str(path)
                return summary
            alone = {s: strategy.simulate(case, s, execute=execute) for s in strategy.STRATEGIES}
            shared = {}
            order = ('honest-reference', 'claim-without-evidence', 'ask-everything', 'block-all-pending', 'frozen-first-fix')
            counts, results = {}, {}
            for name in order:
                before = len(seen)
                results[name] = strategy.simulate(case, name, execute=driver, shared=shared)
                counts[name] = len(seen) - before
            # ask-everything is honest-reference plus questions; frozen-first-fix is claim-without-evidence;
            # every strategy shares the establish step; block-all-pending shares the steps before its first block.
            self.assertEqual(counts, {'honest-reference': 4, 'claim-without-evidence': 3, 'ask-everything': 0,
                                      'block-all-pending': 1, 'frozen-first-fix': 0})
            for name in order:
                self.assertEqual(results[name]['steps'], alone[name]['steps'], name)
                self.assertEqual(results[name]['totals'], alone[name]['totals'], name)
                paths = results[name]['_evidence_paths']
                self.assertEqual(len(paths), 4); self.assertEqual(len(set(paths)), 4, 'one checkpoint per step')
            self.assertEqual(results['ask-everything']['_evidence_paths'], results['honest-reference']['_evidence_paths'])
            # Different runs, seed, workers or guard bytes are different executions.
            strategy.simulate(case, 'ask-everything', execute=driver, shared=shared, seed=2)
            self.assertEqual(len(seen), 12)
            strategy.simulate(case, 'ask-everything', execute=driver, shared=shared, factory_workers=2)
            self.assertEqual(len(seen), 16)
            (case / 'guards/reference/db.sql').write_text('-- changed fixture')
            strategy.simulate(case, 'ask-everything', execute=driver, shared=shared)
            self.assertEqual(len(seen), 17, 'only the step run under the changed guard executes again')
            # Missing evidence is never reused.
            pathlib.Path(results['honest-reference']['_evidence_paths'][1]).unlink()
            strategy.simulate(case, 'honest-reference', execute=driver, shared=shared)
            self.assertEqual(len(seen), 18, 'only the step whose evidence is gone executes again')

    def test_incomplete_or_live_window_executions_are_never_shared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); case = root / 'case'; case.mkdir(); fixture(case)
            seen = []
            def driver(*args):
                seen.append(args[-1])
                summary = execute(*args)
                summary['runs'] = 2
                path = root / 'results/runs' / str(len(seen)) / 'checkpoint.json'
                write(path, summary); summary['_evidence_path'] = str(path)
                return summary
            shared = {}
            for _ in range(2): strategy.simulate(case, 'honest-reference', runs=3, execute=driver, shared=shared)
            self.assertEqual(len(seen), 8); self.assertEqual(shared, {})
            meta = json.loads((case / 'case.json').read_text()); meta['steps'].append('quiet')
            write(case / 'case.json', meta)
            write(case / 'scenarios/quiet/scenario.json', {'id': 'quiet', 'delivery': 'unannounced'})
            write(case / 'scenarios/quiet/key.json', {'correct_responses': ['keep']})
            window = {'runs': 1, 'latest_claims': {}, 'claims_score': {'unsafe_checkpoint': False,
                      'response_correct': True, 'human_minutes': {'total': 0}, 'exposure': {}}}
            live = Mock(side_effect=execute)
            with patch.object(strategy, 'silent_checkpoint', return_value=window):
                for _ in range(2): strategy.simulate(case, 'honest-reference', execute=live, shared=shared)
            self.assertEqual(live.call_count, 8); self.assertEqual(shared, {})

    def test_public_practice_shape_and_skips(self):
        case = _BENCH_ROOT
        for name in strategy.STRATEGIES:
            result = strategy.simulate(case, name, execute=lambda *a: {
                'paths': {'shop': {'runs': 1, 'violated_runs': 0}}, 'checks': {}, 'legit_completion': 1})
            self.assertGreater(len(result['steps']), 1)
            self.assertIn('pending', result['skipped'])
            self.assertNotIn('blind', result['skipped'], 'the public monitor-blind scenario still runs')
            self.assertTrue(all(s['pending_outcome'] is None for s in result['steps']))

    def test_factory_practice_fixture_order(self):
        import shutil
        bench = _BENCH_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            case = pathlib.Path(tmp)
            shutil.copytree(bench / 'scenarios/dev/S0-null', case / 'base')
            shutil.copytree(bench / 'guards/reference', case / 'guards/reference')
            for directory in ('S2-express-checkout', 'S11-monitor-blind'):
                shutil.copytree(bench / 'scenarios/dev' / directory, case / 'scenarios' / directory)
            shutil.copytree(bench / 'harbor/medusa-oversell', case / 'harbor/practice')
            self.assertEqual([s['id'] for s in strategy.steps(case)], ['establish', 'S0', 'S2', 'S11'])


if __name__ == '__main__': unittest.main()
