"""Offline worker control replays over real practice bytes and the 5813be ledger.

Job/release envelopes and model answers are authored. Unix accounts, transport,
and root commands are substituted; this is not VM isolation qualification.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import test_stream_d_inputs as inputs
from router_test_support import synthetic_maximum
import batch_service
import budget
from carry_over import digest
import diagnosis
import diagnosis_dispatch as dispatch
import diagnosis_task as task
import job_authority
import model_router
import model_runtime
import run
import worker_release
from registry import atomic_json


class Crash(BaseException): pass


class DispatchTests(unittest.TestCase):
    patch = inputs.InputTests.patch
    install_receipt = inputs.InputTests.install_receipt
    freeze = inputs.InputTests.freeze
    result = inputs.InputTests.result

    def setUp(self):
        inputs.InputTests.setUp(self)
        roles = {name: {'model': value} for name, value in (
            ('writer', 'claude/claude-opus-5-5'), ('stress_tester', 'opencode/minimax-m3.1-flash-free'),
            ('strong_calibrator', 'codex/gpt-6.1-sol'), ('reviewer', 'openrouter/deepseek/deepseek-v4.1-flash'))}
        self.c.card['roles'] = roles
        self.c.card['case_budget'] = {'total_spent_usd': self.baseline}
        self.c.checkpoint_card = copy.deepcopy(self.c.card)
        self.install_receipt()
        self.patch(run, 'BENCH', self.bench)
        self.patch(task, 'ROOT', self.work.parent.parent / 'tasks')
        self.patch(task, 'ROOT_UID', os.getuid())
        self.patch(task.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()))
        self.patch(task, '_quiet', return_value=None)
        self.patch(task.os, 'chown', return_value=None)
        remove = task._remove
        def unprivileged_remove(path):
            # Root can unlink inside 0550; the offline test UID cannot.
            if path.is_dir() and not path.is_symlink():
                for entry in [path, *path.rglob('*')]:
                    if entry.is_dir(): entry.chmod(0o700)
            remove(path)
        self.patch(task, '_remove', side_effect=unprivileged_remove)
        self.patch(batch_service, 'DIAGNOSIS_ENABLED', False)
        self.pilots = self.patch(run, 'make_pilots')
        self.dispose = self.patch(run, 'dispose_diagnosis_pilot')
        self.qualify = self.patch(worker_release, 'verify_selected_drivers', return_value={})
        self.calls = []
        self.helper_calls = []
        self.patch(dispatch, 'helper', side_effect=self.helper)
        self.patch(run, 'opencode', side_effect=self.call)
        self.answer = 'factory_bug'
        self.addCleanup(self.writable_tasks)

    def writable_tasks(self):
        if task.ROOT.exists():
            for path in [task.ROOT, *task.ROOT.rglob('*')]:
                if path.is_dir(): path.chmod(0o700)

    def helper(self, c, operation, identity):
        self.helper_calls.append((operation, identity))
        response = task.operate(operation, c.case_id, identity,
                                runner_home=self.work.parent.parent, root=task.ROOT)
        import base64
        return response, base64.b64decode(response['raw_base64'])

    def call(self, c, models, text, cwd, name, *, user, before_attempt):
        # Real admission and settlement; no process or inference was invoked.
        routes = model_router.routes(models[0])
        route = next(row for row in routes if row['pool'] + '/' + row['route'] not in c.router_excluded)
        lease = model_router.Lease(lease_id=uuid.uuid4().hex, expires_at=time.time() + 300,
                                  **route, **synthetic_maximum(route['route']))
        reservation = budget.reserve_invocation(c.ledger, lease, 1, job_authority.for_case(c),
            operation_id=c.model_operation_id, call_name=name)
        c.invocation_reservation = reservation
        try:
            before_attempt()
            self.calls.append((name, route['route'], c.model_operation_id, text))
            if callable(self.answer): return self.answer(c, cwd, before_attempt)
            manifest = json.loads((self.parent / 'input.json').read_text())
            result = self.result(manifest)
            if self.answer != 'factory_bug': result.update(outcome=self.answer, factory_bug=None)
            (cwd / 'result.json').write_text(json.dumps(result))
        finally:
            budget.release_uninvoked(c.ledger, lease.lease_id)

    def stopped(self, label):
        with self.assertRaisesRegex(budget.BudgetError, '^' + label + '$'):
            dispatch.dispatch(self.c, run)
        self.assertEqual(self.c.card['terminal_stop'], label)

    def resume(self):
        self.c.checkpoint_card = copy.deepcopy(self.c.card)
        self.c.card = {'case': self.c.case_id}
        self.c.provider_resume_done = False
        self.c.model_resume_state = {'done': False}

    def test_disabled_gate_freezes_after_settlement_without_any_role_side_effect(self):
        self.stopped('diagnosis_pending')
        self.assertTrue((self.parent / 'input.json').exists())
        self.assertEqual(self.helper_calls, [])
        self.pilots.assert_not_called(); self.qualify.assert_not_called()
        self.assertEqual(self.calls, [])
        state = copy.deepcopy(self.c.card['diagnosis_state'])
        for label in ('money_wait', 'extension_comparison_pending', 'runner_error:KeyError', 'diagnosis_pending'):
            self.c.card['diagnosis_state'].update(status='completed', outcome='close_to_passing')
            self.c.card['terminal_stop'] = label
            self.c.exhaustion_occurred = True
            for _ in range(2): run.finalize_accounting(self.c)
            self.assertEqual(self.c.card['diagnosis_state']['exhaustion_id'], state['exhaustion_id'])
        self.c.card['terminal_stop'] = 'infrastructure_exhausted'
        run.finalize_accounting(self.c)
        self.assertNotEqual(self.c.card['diagnosis_state']['exhaustion_id'], state['exhaustion_id'])

    def test_unknown_pending_does_not_create_inputs_before_settlement_ack(self):
        self.c.checkpoint_card['case_budget']['total_spent_usd'] = None
        self.stopped('diagnosis_pending')
        self.assertFalse((self.parent / 'input.json').exists())
        self.assertEqual(self.helper_calls, [])

    def test_archived_roles_survive_cleanup_and_active_history_never_falls_to_writer(self):
        roles = copy.deepcopy(self.c.checkpoint_card['roles'])
        self.c.card = {'case': self.c.case_id}
        self.assertTrue(dispatch.carry_context(self.c))
        self.assertEqual(self.c.card['roles'], roles)
        self.c.checkpoint_card.pop('diagnosis_state')
        (self.work / 'extension-history.json').write_text('[]')
        self.stopped('diagnosis_input_invalid')
        self.assertEqual(self.calls, [])

    def test_main_resume_enters_diagnosis_before_compose_models_or_writer(self):
        import job_config
        (self.work / 'logs').mkdir(exist_ok=True)
        (self.work.parent.parent / 'batch-release.json').write_bytes((job_config.FACTORY.parent / 'batch-release.json').read_bytes())
        card = copy.deepcopy(self.c.checkpoint_card)
        card['batch_release_sha256'] = self.c.args.batch_release_sha256
        atomic_json(self.work / 'scorecard.json', card)
        control = self.work / 'authored-control.json'
        atomic_json(control, {key: getattr(self.c, key) for key in ('job_money', 'authenticated_job_config',
            'batch_id', 'job_id', 'batch_deadline', 'source_generation')})
        code = r'''
import json, pathlib, sys
from unittest.mock import patch
sys.path[:0]=[sys.argv[1], sys.argv[2]]
import run, job_config, founder_ruling, free_models, diagnosis_task, model_router
home, case, release, source, bench = sys.argv[3:]
run.HOME=pathlib.Path(home); run.SEALED=run.HOME/'sealed'; run.BENCH=pathlib.Path(bench)
job_config.FACTORY=pathlib.Path(source); diagnosis_task.ROOT=run.HOME/'tasks'
run.bench_manifest=lambda: 'authored-clean-bench'
def install(c,a):
 for k,v in json.loads((c.work/'authored-control.json').read_text()).items(): setattr(c,k,v)
def forbidden(*a,**k): raise AssertionError('unexpected role/Compose work')
run.sh=run.pick_models=run.build=run.validate_and_repair=run.make_pilots=forbidden
run.stop_pilot=lambda *a: False
run.seal=lambda *a,**k: None
run.pilot_homes=lambda: []
founder_ruling.context=lambda c: None
free_models.first_resume=lambda *a: False
job_config.install=install
with patch.object(sys,'argv',['run.py','--source','hunt','--resume',case,'--resume-bench-sha','authored-clean-bench',
                              '--batch-release-sha256',release]): run.main()
'''
        process = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT / 'factory'), str(ROOT / 'bin'),
            str(self.work.parent.parent), self.c.case_id, self.c.args.batch_release_sha256,
            str(job_config.FACTORY), str(self.bench)], capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        published = json.loads((self.ledger.parent / (self.c.case_id + '.scorecard.json')).read_text())
        self.assertEqual(published['terminal_stop'], 'diagnosis_pending')
        self.assertEqual(published['diagnosis_state']['exhaustion_id'], self.parent.name)
        self.assertNotIn('invocation_reservations', published['continuation_budget'])

    def test_all_outcomes_replay_after_unknown_total_and_preserve_id(self):
        # Separate contexts because each outcome is immutable.
        for outcome in ('factory_bug', 'close_to_passing', 'not_converging'):
            with self.subTest(outcome=outcome):
                self.answer = outcome
                with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True):
                    self.stopped(dispatch.STOPS[outcome])
                saved = copy.deepcopy(self.c.card['diagnosis_state'])
                calls = len(self.calls)
                for _ in range(2):
                    self.c.card['case_budget'] = {'total_spent_usd': None}
                    self.resume()
                    self.stopped(dispatch.STOPS[outcome])
                    self.c.exhaustion_occurred = True
                    run.finalize_accounting(self.c)
                    self.assertEqual(self.c.card['diagnosis_state'], saved)
                self.assertEqual(len(self.calls), calls)
                if outcome != 'not_converging':
                    # Authored distinct exhaustion, preserving the real source ledger.
                    self.c.card.pop('factory_bug', None)
                    self.c.card['terminal_stop'] = 'infrastructure_exhausted'
                    diagnosis.record_exhaustion(self.c.card, new_exhaustion=True)
                    self.c.card['case_budget'] = {'total_spent_usd': self.baseline}
                    self.c.checkpoint_card = copy.deepcopy(self.c.card)
                    self.install_receipt()
                    self.parent = self.work / 'diagnosis' / self.c.card['diagnosis_state']['exhaustion_id']

    def test_valid_journal_without_decision_finishes_before_gate(self):
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True), patch.object(dispatch, 'decision', side_effect=Crash):
            with self.assertRaises(Crash): dispatch.dispatch(self.c, run)
        self.assertFalse((self.parent / 'decision.json').exists())
        self.assertEqual(json.loads((self.parent / 'attempts.json').read_text())['attempts'][-1]['status'], 'valid')
        self.pilots.reset_mock(); self.qualify.reset_mock(); self.helper_calls.clear()
        self.resume(); self.stopped('factory_bug_held')
        self.assertEqual(len(self.calls), 1)
        self.pilots.assert_not_called(); self.qualify.assert_not_called()
        self.assertEqual(self.helper_calls, [])

    def test_missing_valid_raw_is_input_invalid_before_gate(self):
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True), patch.object(dispatch, 'decision', side_effect=Crash):
            with self.assertRaises(Crash): dispatch.dispatch(self.c, run)
        next(self.parent.glob('raw-bytes-*')).unlink()
        self.resume(); self.stopped('diagnosis_input_invalid')
        self.assertEqual(len(self.calls), 1)

    def test_schema_only_repair_gets_no_inputs_and_keeps_route(self):
        def answer(c, cwd, callback):
            if len(self.calls) == 1: (cwd / 'result.json').write_text('authored malformed response')
            else:
                self.assertFalse((cwd.parent / 'inputs').exists())
                manifest = json.loads((self.parent / 'input.json').read_text())
                (cwd / 'result.json').write_text(json.dumps(self.result(manifest)))
        self.answer = answer
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True): self.stopped('factory_bug_held')
        first, repair = self.calls
        self.assertEqual(first[1], repair[1]); self.assertNotEqual(first[2], repair[2])
        self.assertTrue(repair[0].endswith('-repair-1'))
        self.assertNotIn('"inputs":', repair[3])
        self.assertFalse((task.ROOT / self.c.case_id / self.parent.name).exists())

    def test_partial_prepare_cleanup_is_audit_only_and_keeps_pending_operation(self):
        def interrupt(c, cwd, callback):
            (cwd / 'result.json').write_text('partial output')
            raise Crash()
        self.answer = interrupt
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True):
            with self.assertRaises(Crash): dispatch.dispatch(self.c, run)
        operation = self.calls[0][2]
        identity = self.parent.name
        partial = task.ROOT / self.c.case_id / identity / 'inputs'
        partial.mkdir(parents=True); (partial / 'partial').write_text('interrupted prepare')
        dispatch.cleanup_tasks(self.c)
        self.assertFalse(partial.parent.exists())
        audits = [json.loads(p.read_text()) for p in self.parent.glob('audit-*.json')]
        self.assertTrue(any(row['status'] == 'input_invalid' for row in audits))
        self.resume(); self.stopped('diagnosis_pending')
        self.assertEqual(self.parent.name, self.c.card['diagnosis_state']['exhaustion_id'])
        self.answer = 'factory_bug'
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True): self.stopped('factory_bug_held')
        self.assertEqual(self.calls[-1][2], operation)
        self.assertEqual({p.name for p in (task.ROOT / self.c.case_id).iterdir()}, {'.lock'})

    def test_all_malformed_routes_retire_without_new_model_on_false_gate(self):
        self.answer = lambda c, cwd, callback: (cwd / 'result.json').write_text('malformed')
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True): self.stopped('retired_diagnosis_malformed')
        count = len(self.calls)
        self.assertEqual(count, 2 * len({r['route'] for r in model_router.routes(self.c.card['roles']['reviewer']['model'])}))
        self.assertEqual(self.c.card['diagnosis_state']['status'], 'pending')
        self.resume(); self.stopped('retired_diagnosis_malformed')
        self.assertEqual(len(self.calls), count)

    def test_schema_contract_roll_waits_without_relabelling_input_corruption(self):
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True), patch.object(dispatch, 'decision', side_effect=Crash):
            with self.assertRaises(Crash): dispatch.dispatch(self.c, run)
        state = copy.deepcopy(self.c.card['diagnosis_state'])
        with patch.object(diagnosis, 'RESULT_SCHEMA', {'new': 'unsupported schema'}):
            self.stopped('diagnosis_schema_wait')
        self.assertEqual(self.c.card['diagnosis_state'], state)

    def test_orphan_binding_includes_every_new_artifact(self):
        self.freeze(); (self.parent / 'input.json').unlink()
        for name in ('attempts.json', 'decision.json', 'raw-bytes-' + 'a' * 64,
                     'audit-bytes-' + 'b' * 64, 'audit-' + 'c' * 64 + '.json'):
            path = self.parent / name; path.write_text('authored orphan')
            self.c.card['terminal_stop'] = 'infrastructure_exhausted'
            with self.assertRaisesRegex(budget.BudgetError, 'diagnosis_input_invalid'): self.freeze()
            self.assertTrue(path.exists()); path.unlink()


    def test_helper_output_bounds_symlink_fifo_and_input_damage(self):
        def answer(c, cwd, callback):
            result = cwd / 'result.json'
            for mode in ('missing', 'symlink', 'fifo', 'oversized'):
                if mode == 'symlink': result.symlink_to(self.ledger)
                if mode == 'fifo': os.mkfifo(result)
                if mode == 'oversized': result.write_bytes(b'x' * (task.MAX_RESULT + 1))
                value, raw = self.helper(c, 'collect', self.parent.name)
                self.assertEqual(value['status'], 'unsafe' if mode in ('symlink', 'fifo') else mode)
                self.assertLessEqual(len(raw), task.MAX_RESULT)
                result.unlink(missing_ok=True)
            exposed = cwd.parent / 'inputs/ledger.json'
            self.assertEqual(exposed.stat().st_mode & 0o777, 0o440)
            self.assertEqual(exposed.parent.stat().st_mode & 0o777, 0o550)
            # Authored root-side corruption; a pilot lacks this permission.
            exposed.chmod(0o640); exposed.write_bytes(b'changed copy')
        self.answer = answer
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True): self.stopped('diagnosis_input_invalid')
        self.assertTrue((self.parent / 'inputs/ledger.json').exists())

    def test_cleanup_visits_prior_ids_and_replays_held_after_infrastructure_failure(self):
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True): self.stopped('factory_bug_held')
        identity = self.parent.name
        state = copy.deepcopy(self.c.card['diagnosis_state'])
        old = str(uuid.uuid4())
        for key in (identity, old):
            path = task.ROOT / self.c.case_id / key / 'output'
            path.mkdir(parents=True); (path / 'result.json').write_text('orphan')
        with patch.object(dispatch, 'remove_task', side_effect=dispatch.DiagnosisTaskCleanupError()):
            with self.assertRaises(dispatch.DiagnosisTaskCleanupError): dispatch.cleanup_tasks(self.c)
        self.c.card['terminal_stop'] = 'runner_error:DiagnosisTaskCleanupError'
        dispatch.cleanup_tasks(self.c)
        self.assertTrue(list((self.work / 'diagnosis' / old).glob('audit-*.json')))
        self.resume(); self.stopped('factory_bug_held')
        self.assertEqual(self.c.card['diagnosis_state'], state)
        self.assertEqual(len(self.calls), 1)

    def test_reset_prevents_an_interrupted_attempt_answer_becoming_the_next_answer(self):
        def answer(c, cwd, callback):
            manifest = json.loads((self.parent / 'input.json').read_text())
            (cwd / 'result.json').write_text(json.dumps(self.result(manifest)))
            callback()  # Another before_attempt clears the predecessor.
            self.assertFalse((cwd / 'result.json').exists())
            self.assertTrue(list(self.parent.glob('audit-bytes-*')))
            raise Crash()
        self.answer = answer
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True):
            with self.assertRaises(Crash): dispatch.dispatch(self.c, run)
        self.resume(); self.stopped('diagnosis_pending')
        self.assertFalse((self.parent / 'decision.json').exists())


class IsolationPolicyTests(unittest.TestCase):
    def test_runtime_driver_commands_do_not_reintroduce_ambient_keys(self):
        import contextlib
        import shutil
        import tempfile
        from router_test_support import offline_router
        router, _ = offline_router(); self.addCleanup(router.close)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'transcripts').mkdir()
            home = root / 'pilot'; (home / '.cache').mkdir(parents=True)
            c = SimpleNamespace(work=root, case_id='case-control', card={}, ledger=root / 'ledger.json',
                args=run.argument_parser().parse_args(['--source', 'hunt']), model_cap_used={})
            events, seen = [], []
            def command(c, argv, **kwargs):
                events.append(list(map(str, argv)))
                if argv[:2] == ['sudo', 'mv']: shutil.move(str(argv[2]), str(argv[3]))
                return 0
            runtime = model_runtime.ModelRuntime(root, command, Mock(),
                lambda path, sudo=False: shutil.rmtree(path), lambda user: home)
            @contextlib.contextmanager
            def gate(*args):
                yield SimpleNamespace(server=SimpleNamespace(server_port=12345))
            def budgeted(cmd, cwd, env, *args, **kwargs):
                seen.append((cmd, dict(env)))
                return subprocess.CompletedProcess(cmd, 0)
            ambient = {key: 'authored-only' for key in ('UNBUG_JUDGE', 'RESTORE_KEY', 'AWS_SECRET_ACCESS_KEY',
                'FACTORY_JOB_CONFIG', 'OPENCODE_ENABLE_EXA', 'OPENCODE_API_KEY', 'OPENROUTER_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN')}
            with patch.dict(os.environ, ambient), patch.object(model_runtime, 'pinned_cli', side_effect=lambda name: name), \
                 patch.object(model_runtime, '_opencode_flags', return_value=()), \
                 patch.object(model_runtime, 'run_budgeted', side_effect=budgeted), \
                 patch.object(model_runtime.model_call_gate, 'enforce', gate), \
                 patch.object(model_runtime, 'case_budget_boundary'), patch.object(model_runtime, 'update_case_budget'), \
                 patch.object(task, '_quiet'), patch.object(model_runtime.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=123)):
                for model in ('codex/gpt-6.1-sol', 'claude/claude-opus-5-5', 'openrouter/deepseek/deepseek-v4.1-flash'):
                    route = model_router.routes(model)[0]
                    lease = model_router.Lease(lease_id=uuid.uuid4().hex, expires_at=time.time() + 300,
                                              **route, **synthetic_maximum(model))
                    c.model_lease = lease; c._model_launch_permit = lease.lease_id
                    runtime._invoke(c, [model], 'authored prompt', root, 'diagnosis-' + str(uuid.uuid4()), user='pilot')
            for cmd, env in seen:
                self.assertFalse(set(env) & {'UNBUG_JUDGE', 'RESTORE_KEY', 'AWS_SECRET_ACCESS_KEY', 'FACTORY_JOB_CONFIG', 'OPENCODE_ENABLE_EXA'})
            codex, claude, opencode = seen
            self.assertEqual(codex[0][1], '--preserve-env=CODEX_HOME,PATH')
            self.assertNotIn('WebSearch', claude[0][-1])
            self.assertEqual(set(opencode[1]) & set(ambient), {'OPENROUTER_API_KEY'})

    def test_environment_for_each_driver_has_only_one_selected_provider(self):
        env = {key: 'authored-control' for key in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR',
            'AWS_SECRET_ACCESS_KEY', 'UNBUG_JUDGE', 'FACTORY_JOB_CONFIG', 'RESTORE_KEY', 'CLAUDE_CODE_OAUTH_TOKEN',
            'OPENROUTER_API_KEY', 'OPENCODE_API_KEY', 'OPENCODE_ENABLE_EXA', 'OPENCODE_API_KEY_BASE_URL')}
        home = Path('/authored/pilot')
        for driver, account, key in (('claude', 'claude-token', 'CLAUDE_CODE_OAUTH_TOKEN'),
                ('opencode', 'openrouter-key', 'OPENROUTER_API_KEY'),
                ('opencode', 'opencode-key', 'OPENCODE_API_KEY'), ('opencode', None, None), ('codex', 'codex-auth.json', None)):
            with self.subTest(driver=driver, account=account):
                clean = model_runtime.diagnosis_environment(env, driver, SimpleNamespace(account=account), home)
                self.assertEqual(set(clean), {'PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR'} | ({key} if key else set()))
                self.assertEqual(clean['HOME'], str(home))
        with patch.dict(os.environ, {'OPENCODE_API_KEY_BASE_URL': 'https://authored-invalid'}):
            config = json.loads(model_runtime.opencode_config('opencode-go/muse-spark-1.3-contributor', diagnosis=True).read_text())
        self.assertNotIn('baseURL', config['provider']['opencode-go']['options'])
        self.assertEqual(config['permission']['webfetch'], 'deny')
        self.assertEqual(config['permission']['websearch'], 'deny')
        self.assertEqual(config['small_model'], 'opencode-go/muse-spark-1.3-contributor')

    def test_loopback_rules_precede_reject_and_are_removed_on_every_exit(self):
        for error in (None, RuntimeError, Crash):
            events = []
            command = lambda c, argv, **kw: events.append(argv)
            try:
                with model_runtime.diagnosis_loopback(None, command, SimpleNamespace(server=SimpleNamespace(server_port=12345)), True):
                    self.assertEqual(len(events), 2)
                    if error: raise error()
            except (RuntimeError, Crash): pass
            self.assertEqual(len(events), 4)
            self.assertTrue(all(row[4:7] == ['-I', 'factory-pilot', '1'] for row in events[:2]))
            self.assertEqual([row[6:] for row in events[2:]], [row[7:] for row in reversed(events[:2])])

    def test_diagnosis_pilot_has_no_config_copy_or_bench_port(self):
        c = SimpleNamespace(card={})
        events = []
        with patch.object(run, 'sh', side_effect=lambda c, args, **kw: events.append(list(map(str, args)))), \
             patch.object(run, 'shred_tree'), patch.object(run, 'pilot_wall') as wall:
            run.make_pilots(c, [('pilot', None)], True, diagnosis=True)
        self.assertFalse(any(row[:2] == ['sudo', 'cp'] for row in events))
        self.assertIn(['sudo', 'chmod', '700', str(run.pilot_home('pilot'))], events)
        wall.assert_any_call(c, 'pilot', None)
        events.clear()
        with patch.object(run, 'sh', side_effect=lambda c, args, **kw: events.append(args)):
            run.pilot_wall(c, 'pilot', None)
        self.assertFalse(any('ACCEPT' in row for row in events))

    def test_helper_flock_serializes_a_surviving_process(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory, patch.object(task, 'ROOT_UID', os.getuid()):
            root = Path(directory) / 'tasks'
            code = """import sys, pathlib, os
sys.path.insert(0, sys.argv[1])
import diagnosis_task as t
t.ROOT_UID=os.getuid()
with t.locked(pathlib.Path(sys.argv[2]), 'case-control'):
 print('locked', flush=True)
 sys.stdin.readline()
"""
            with subprocess.Popen([sys.executable, '-B', '-c', code, str(ROOT / 'factory'), str(root)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as child:
                self.assertEqual(child.stdout.readline().strip(), 'locked')
                import fcntl
                with open(root / 'case-control/.lock', 'rb') as lock:
                    with self.assertRaises(BlockingIOError): fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                child.communicate('\n', timeout=5)
            with task.locked(root, 'case-control'): pass


if __name__ == '__main__': unittest.main()
