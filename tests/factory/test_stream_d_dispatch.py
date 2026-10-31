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
import extensions
import test_stream_d_extensions as extension_tests
import test_stream_d_runtime as runtime
import registry
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
        self.rotate_first_route = False
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
        if self.rotate_first_route and not self.calls: routes = list(reversed(routes))
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
        self.main_resume()

    def test_main_driver_failure_retries_with_the_same_exhaustion(self):
        published = self.main_resume('qualification')
        self.c.checkpoint_card = published
        self.main_resume()

    def main_resume(self, fault='none'):
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
import run, job_config, founder_ruling, free_models, diagnosis_task, model_router, batch_service, worker_release
home, case, release, source, bench, fault = sys.argv[3:]
run.HOME=pathlib.Path(home); run.SEALED=run.HOME/'sealed'; run.BENCH=pathlib.Path(bench)
job_config.FACTORY=pathlib.Path(source); diagnosis_task.ROOT=run.HOME/'tasks'
run.bench_manifest=lambda: 'authored-clean-bench'
def install(c,a):
 for k,v in json.loads((c.work/'authored-control.json').read_text()).items(): setattr(c,k,v)
 if fault.startswith('mode:'):
  name=fault.split(':')[1]
  if name == 'audit_source': c.audit_source='authored audit'
  elif name == 'salvaged_from': c.card['salvaged_from']='authored salvage'
  else: setattr(a,name,True)
def forbidden(*a,**k): raise AssertionError('unexpected role/Compose work')
run.sh=run.pick_models=run.build=run.validate_and_repair=run.make_pilots=forbidden
run.stop_pilot=lambda *a: False
run.seal=lambda *a,**k: None
run.pilot_homes=lambda: []
founder_ruling.context=lambda c: None
job_config.install=install
if fault == 'execute' or fault.startswith('mode:'): batch_service.DIAGNOSIS_ENABLED=True
if fault == 'execute':
 run.sh=lambda *a,**k: None
 run.pick_models=lambda c: {'builder':['claude/claude-opus-5-5']}
 worker_release.verify_selected_drivers=lambda *a,**k: {}
 def execute(c,r,prev,extension_id):
  assert extension_id == 1
  assert prev['diagnosis_state']['outcome'] == 'close_to_passing'
  c.card['execution_test_entered']=True
  raise run.BudgetError('extension_comparison_pending')
 import extension_package
 extension_package.run=execute
 import restart
 restart.raised_limits=run.restore_gate_crash=forbidden
if fault == 'qualification':
 batch_service.DIAGNOSIS_ENABLED=True
 def unavailable(*a,**k): raise ValueError('authored CLI version mismatch')
 worker_release.verify_selected_drivers=unavailable
with patch.object(sys,'argv',['run.py','--source','hunt','--resume',case,'--resume-bench-sha','authored-clean-bench',
                              '--batch-release-sha256',release]): run.main()
'''
        process = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT / 'factory'), str(ROOT / 'bin'),
            str(self.work.parent.parent), self.c.case_id, self.c.args.batch_release_sha256,
            str(job_config.FACTORY), str(self.bench), fault], capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        published = json.loads((self.ledger.parent / (self.c.case_id + '.scorecard.json')).read_text())
        expected = {'qualification': 'runner_error:ValueError', 'active': 'extension_comparison_pending',
                    'execute': 'extension_comparison_pending'}
        if fault.startswith('mode:'): expected[fault] = 'extension_execution_mode_invalid'
        self.assertEqual(published['terminal_stop'], expected.get(fault, 'diagnosis_pending'))
        self.assertEqual(published['diagnosis_state']['exhaustion_id'], self.parent.name)
        if fault in ('active', 'execute') or fault.startswith('mode:'):
            self.assertEqual(published['builder_rounds'], self.admitted_receipt['round'])
            self.assertEqual(published['continuation_budget']['invocation_reservations'],
                             json.loads(self.ledger.read_text())['invocation_reservations'])
        else:
            self.assertNotIn('invocation_reservations', published['continuation_budget'])
        if fault == 'execute': self.assertTrue(published['execution_test_entered'])
        return published

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

    def admit_active_control(self, frontier):
        entry = extension_tests.ExtensionTests.snapshot(self, frontier)
        proposal = extensions.propose(self.c, entry)
        receipt = runtime.RuntimeTests.receipt(self)
        receipt.update(round=proposal['round'], round_limit=proposal['round'], report=f"round-{proposal['round']}.json")
        atomic = registry.atomic_json
        def interrupt(path, value):
            if path == self.work / 'attack-state.json': raise Crash()
            return atomic(path, value)
        with patch.object(registry, 'atomic_json', side_effect=interrupt), \
                patch.object(run, 'opencode', side_effect=AssertionError('writer before publication')):
            with self.assertRaises(Crash):
                run.pending_call(self.c, self.c.models['builder'], 'authored extension request',
                    self.case, 'builder-' + str(proposal['round']), receipt, role='writer',
                    on_complete=lambda: None, extension_proposal=proposal)
        row = extensions.active(self.c)
        self.admitted_receipt = json.loads((self.work / 'extension-writers' /
            (row['writer_operation_id'] + '.json')).read_text())['receipt']
        self.c.card['builder_rounds'] = row['round']
        return row

    def prepare_active_launch(self):
        self.answer = 'close_to_passing'
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True):
            self.stopped('extension_comparison_pending')
        row = self.admit_active_control(1)
        # Emulate the public count lagging the durable admission.
        self.c.card['builder_rounds'] = row['round'] - 1
        self.c.checkpoint_card = copy.deepcopy(self.c.card)
        self.pilots.reset_mock(); self.qualify.reset_mock(); self.helper_calls.clear()
        return row

    def test_freshness_context_is_deep_copied(self):
        self.prepare_active_launch()
        previous = {'verdict_path': 'g2-confirm-123/verdict.json', 'detail': {'rows': [1]}}
        self.c.checkpoint_card['loop_freshness'] = previous
        self.assertTrue(dispatch.carry_context(self.c))
        self.assertEqual(self.c.card['loop_freshness'], previous)
        self.c.card['loop_freshness']['detail']['rows'].append(2)
        self.assertEqual(previous['detail']['rows'], [1])

    def test_enabled_replay_returns_verified_extension_identity(self):
        row = self.prepare_active_launch()
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True):
            self.assertEqual(dispatch.dispatch(self.c, run), row['extension_id'])
        self.assertEqual(json.loads((self.work / 'attack-state.json').read_text()), self.admitted_receipt)
        self.pilots.assert_not_called()

    def test_replay_rejects_active_row_from_other_decision(self):
        row = self.prepare_active_launch()
        with patch.object(extensions, 'active', return_value={**row, 'exhaustion_id': str(uuid.uuid4())}), \
                patch.object(extensions, 'writer_receipt', side_effect=AssertionError('unverified intent')):
            self.stopped('diagnosis_input_invalid')

    def test_main_routes_execution_and_stops_before_gates(self):
        self.prepare_active_launch()
        self.main_resume('execute')

    def test_main_refuses_nonordinary_modes_before_setup(self):
        self.prepare_active_launch()
        for name in ('dry_run', 'rehearse_only', 'audit_fairness', 'late_gate_rehearsal',
                     'statement_only', 'skip_build', 'audit_source', 'salvaged_from'):
            with self.subTest(mode=name): self.main_resume('mode:' + name)

    def test_main_recovers_admitted_writer_before_ordinary_launch_twice(self):
        self.prepare_active_launch()
        path = self.work / 'attack-state.json'
        self.assertFalse(path.exists())
        freshness = {'outcome': 'unresolved', 'verdict_path': 'g2-confirm-123/verdict.json',
                     'diagnostic': {'reason': 'review_interrupted'}}
        self.c.checkpoint_card['loop_freshness'] = copy.deepcopy(freshness)
        retained = {name: extensions.tree(self.work / name) for name in
                    ('extension-writers', 'extension-snapshots', 'diagnosis')}
        history = (self.work / 'extension-history.json').read_bytes()
        reservations = json.loads(self.ledger.read_text())['invocation_reservations']
        for _ in range(2):
            published = self.main_resume('active')
            self.assertEqual(published['loop_freshness'], freshness)
            self.assertEqual(json.loads((self.work / 'scorecard.json').read_text())['loop_freshness'], freshness)
            self.assertEqual(json.loads(path.read_text()), self.admitted_receipt)
            self.assertEqual((self.work / 'extension-history.json').read_bytes(), history)
            self.assertEqual({name: extensions.tree(self.work / name) for name in retained}, retained)
            self.assertEqual(json.loads(self.ledger.read_text())['invocation_reservations'], reservations)
            self.c.checkpoint_card = published

    def test_launcher_preserves_finished_writer_and_stress_receipts(self):
        self.prepare_active_launch()
        receipt = copy.deepcopy(self.admitted_receipt)
        path = self.work / 'attack-state.json'
        run.complete_writer(self.c, receipt, path)
        for phase in ('completed', 'validated'):
            receipt['phase'] = phase
            atomic_json(path, receipt)
            before = path.read_bytes()
            self.resume()
            self.stopped('extension_comparison_pending')
            self.assertEqual(path.read_bytes(), before)
        for phase in ('pending', 'completed', 'validated'):
            atomic_json(path, dict(actor='stress_tester', round=receipt['round'], phase=phase))
            before = path.read_bytes()
            self.resume()
            self.stopped('extension_comparison_pending')
            self.assertEqual(path.read_bytes(), before)
        self.pilots.assert_not_called(); self.qualify.assert_not_called()
        self.assertEqual(self.helper_calls, [])

    def test_launcher_missing_old_intent_refuses_without_reconstruction(self):
        row = self.prepare_active_launch()
        (self.work / 'extension-writers' / (row['writer_operation_id'] + '.json')).unlink()
        with self.assertRaisesRegex(budget.BudgetError, '^extension_reservation_mismatch$'):
            dispatch.dispatch(self.c, run)
        self.assertFalse((self.work / 'attack-state.json').exists())

    def test_launcher_corrupt_diagnosis_refuses_before_writer_recovery(self):
        self.prepare_active_launch()
        decision = json.loads((self.parent / 'decision.json').read_text())
        decision['input_sha256'] = '0' * 64
        atomic_json(self.parent / 'decision.json', decision)
        with patch.object(extensions, 'writer_receipt', side_effect=AssertionError('repair before verification')):
            self.stopped('diagnosis_input_invalid')
        self.assertFalse((self.work / 'attack-state.json').exists())

    def test_launcher_selector_permission_failure_stays_infrastructure(self):
        self.prepare_active_launch()
        reader = extensions._writer_json
        def denied(path, *args, **kwargs):
            if path.parent.name == 'extension-writers': raise PermissionError('authored read denial')
            return reader(path, *args, **kwargs)
        with patch.object(extensions, '_writer_json', side_effect=denied):
            with self.assertRaises(PermissionError): dispatch.dispatch(self.c, run)
        self.assertNotEqual(self.c.card.get('terminal_stop'), 'diagnosis_input_invalid')
        self.assertFalse((self.work / 'attack-state.json').exists())

    def check_active_dispatch(self, origin):
        self.answer = 'close_to_passing'
        self.c.card.update(builder_rounds=8, recovery_config={'rounds': 8})
        if origin.startswith('late_defect'):
            gate = origin.split(':')[1]
            record = dict(version=1, gate=gate, detail='authored defect')
            (self.work / 'late-defect.json').write_text(json.dumps(record))
            self.c.card['late_defect'] = dict(gate=gate, record_sha256=digest(record))
            self.c.card['terminal_stop'] = origin
            self.c.card['diagnosis_state']['stop'] = origin
        self.c.checkpoint_card = copy.deepcopy(self.c.card)
        self.install_receipt()
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True):
            self.stopped('extension_comparison_pending')
        if origin == 'extension_incomplete':
            self.admit_active_control(1)
            extensions.complete(self.c, extension_tests.ExtensionTests.snapshot(self, 2))
            self.c.card['terminal_stop'] = origin
            self.c.exhaustion_occurred = True
            run.finalize_accounting(self.c)
            self.parent = self.work / 'diagnosis' / self.c.card['diagnosis_state']['exhaustion_id']
            self.c.checkpoint_card = copy.deepcopy(self.c.card)
            self.install_receipt()
            with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True):
                self.stopped('extension_comparison_pending')
        self.admit_active_control(2 if origin == 'extension_incomplete' else 1)
        saved = copy.deepcopy(self.c.card)
        private = {name: extensions.tree(self.work / name) for name in ('extension-snapshots', 'diagnosis')}
        history = (self.work / 'extension-history.json').read_bytes()
        calls = list(self.calls)
        self.pilots.reset_mock(); self.qualify.reset_mock(); self.helper_calls.clear()
        for _ in range(2):
            self.resume()
            run.inherit_recovery_history(self.c, self.c.checkpoint_card)
            self.stopped('extension_comparison_pending')
            self.assertEqual(self.c.card['diagnosis_state'], saved['diagnosis_state'])
            self.assertEqual(self.c.card['extension_history'], saved['extension_history'])
            self.assertEqual(self.calls, calls)
            self.assertEqual({name: extensions.tree(self.work / name) for name in private}, private)
            self.assertEqual((self.work / 'extension-history.json').read_bytes(), history)
        self.pilots.assert_not_called(); self.qualify.assert_not_called()
        self.assertEqual(self.helper_calls, [])
        self.c.card['diagnosis_state']['exhaustion_id'] = str(uuid.uuid4())
        wrong = copy.deepcopy(self.c.card['diagnosis_state'])
        self.resume()
        with self.assertRaisesRegex(budget.BudgetError, '^extension_history_invalid$'):
            dispatch.dispatch(self.c, run)
        self.assertEqual(self.c.card['diagnosis_state'], wrong)
        self.assertEqual(self.c.card['extension_history'], saved['extension_history'])
        self.assertNotIn('terminal_stop', self.c.card)
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), history)
        self.assertEqual({name: extensions.tree(self.work / name) for name in private}, private)
        self.assertEqual(self.calls, calls)

    def test_late_origin_active_dispatch_replays_retained_decision(self):
        self.check_active_dispatch('late_defect_needs_ruling:G4')

    def test_second_extension_active_dispatch_verifies_frozen_completed_history(self):
        self.check_active_dispatch('extension_incomplete')

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
        self.rotate_first_route = True
        self.assertGreater(len({r['route'] for r in model_router.routes(self.c.card['roles']['reviewer']['model'])}), 1)
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

    def test_changed_decision_cannot_disagree_with_its_valid_raw_answer(self):
        self.answer = 'close_to_passing'
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True): self.stopped('extension_comparison_pending')
        path = self.parent / 'decision.json'; value = json.loads(path.read_text())
        value['diagnosis']['reason'] = 'different but schema-valid authored reason'
        atomic_json(path, value)
        self.resume(); self.stopped('diagnosis_input_invalid')
        self.assertEqual(len(self.calls), 1)

    def test_reviewer_must_differ_from_each_archived_author_family(self):
        roles = copy.deepcopy(self.c.checkpoint_card['roles'])
        for peer in ('writer', 'stress_tester', 'strong_calibrator'):
            with self.subTest(peer=peer):
                self.c.checkpoint_card['roles'] = copy.deepcopy(roles)
                self.c.checkpoint_card['roles']['reviewer'] = copy.deepcopy(roles[peer])
                self.c.card['terminal_stop'] = 'infrastructure_exhausted'
                self.stopped('diagnosis_input_invalid')
        self.pilots.assert_not_called(); self.qualify.assert_not_called()

    def test_successful_role_with_changed_exposed_digest_refuses_immediately(self):
        def helper(c, operation, identity):
            response, raw = self.helper(c, operation, identity)
            if operation == 'collect' and raw:
                self.assertEqual(response['status'], 'ok')
                response['inputs_sha256'] = 'f' * 64
            return response, raw
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True), patch.object(dispatch, 'helper', side_effect=helper):
            self.stopped('diagnosis_input_invalid')
        self.assertEqual(len(self.calls), 1)
        self.assertFalse((self.parent / 'decision.json').exists())

    def test_unknown_task_names_refuse_cleanup(self):
        root = task.ROOT / self.c.case_id; root.mkdir(parents=True)
        (root / 'temporary-unknown').mkdir()
        with self.assertRaisesRegex(dispatch.DiagnosisTaskCleanupError, 'unknown task name'):
            dispatch.cleanup_tasks(self.c)
        self.assertTrue((root / 'temporary-unknown').exists())

    def test_failed_orphan_audit_preserves_bytes_for_the_next_resume(self):
        self.freeze()
        path = task.ROOT / self.c.case_id / self.parent.name / 'output'
        path.mkdir(parents=True); (path / 'result.json').write_text('retained orphan')
        with patch.object(dispatch, 'audit', side_effect=OSError('authored unavailable audit disk')):
            with self.assertRaises(dispatch.DiagnosisTaskCleanupError): dispatch.cleanup_tasks(self.c)
        self.assertEqual((path / 'result.json').read_text(), 'retained orphan')
        dispatch.cleanup_tasks(self.c)
        self.assertFalse(path.exists())
        self.assertTrue(list(self.parent.glob('audit-bytes-*')))

    def test_failed_interruption_audit_preserves_task_until_a_later_cleanup(self):
        def answer(c, cwd, callback):
            (cwd / 'result.json').write_text('interrupted bytes')
            raise Crash()
        audit = dispatch.audit
        def failed_audit(c, identity, response, raw):
            if raw: raise OSError('authored disk failure')
            return audit(c, identity, response, raw)
        self.answer = answer
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True), patch.object(dispatch, 'audit', side_effect=failed_audit):
            with self.assertRaises(dispatch.DiagnosisTaskCleanupError): dispatch.dispatch(self.c, run)
        output = task.ROOT / self.c.case_id / self.parent.name / 'output/result.json'
        self.assertEqual(output.read_text(), 'interrupted bytes')
        dispatch.cleanup_tasks(self.c)
        self.assertFalse(output.exists())

    def retry_after(self, fault, expected=OSError):
        import recovery
        identity = self.parent.name
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True), fault:
            with self.assertRaises(expected) as raised: dispatch.dispatch(self.c, run)
        # The unchanged runner handler publishes this exact infrastructure label.
        label = 'runner_error:' + type(raised.exception).__name__
        self.assertTrue(recovery.RETRY.fullmatch(label))
        self.assertNotIn(self.c.card.get('terminal_stop'), dispatch.INVALID)
        self.c.card.update(status='stopped', terminal_stop=label)
        self.c.stopped = True
        run.finalize_accounting(self.c)
        self.assertEqual(self.c.card['diagnosis_state']['exhaustion_id'], identity)
        self.resume()
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True): self.stopped('factory_bug_held')
        self.assertEqual(self.c.card['diagnosis_state']['exhaustion_id'], identity)

    def test_driver_qualification_failure_is_retryable(self):
        self.retry_after(patch.object(worker_release, 'verify_selected_drivers',
            side_effect=ValueError('authored wrong installed CLI')), ValueError)
        self.assertNotIn('diagnosis_driver_qualification', self.c.card)

    def test_prepare_transport_failure_is_retryable(self):
        def helper(c, operation, identity):
            if operation == 'prepare': raise ValueError('authored nonzero helper exit')
            return self.helper(c, operation, identity)
        self.retry_after(patch.object(dispatch, 'helper', side_effect=helper), ValueError)

    def test_non_ok_prepare_response_is_retryable(self):
        def helper(c, operation, identity):
            response, raw = self.helper(c, operation, identity)
            if operation == 'prepare': response['status'] = 'input_invalid'
            return response, raw
        self.retry_after(patch.object(dispatch, 'helper', side_effect=helper), RuntimeError)

    def test_wrong_prepare_copy_digest_is_retryable(self):
        def helper(c, operation, identity):
            response, raw = self.helper(c, operation, identity)
            if operation == 'prepare': response['inputs_sha256'] = 'f' * 64
            return response, raw
        self.retry_after(patch.object(dispatch, 'helper', side_effect=helper), RuntimeError)

    def test_raw_answer_permission_failure_is_retryable(self):
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True): self.stopped('factory_bug_held')
        self.resume()
        read = diagnosis._input_bytes
        def unreadable(path, base):
            if path.name.startswith('raw-bytes-'): raise PermissionError('authored unreadable retained answer')
            return read(path, base)
        self.retry_after(patch.object(diagnosis, '_input_bytes', side_effect=unreadable), PermissionError)
        self.assertEqual(len(self.calls), 1)

    def test_decision_permission_failure_is_retryable(self):
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True): self.stopped('factory_bug_held')
        self.resume()
        read = diagnosis._input_bytes
        def unreadable(path, base):
            if path.name == 'decision.json': raise PermissionError('authored unreadable decision')
            return read(path, base)
        self.retry_after(patch.object(diagnosis, '_input_bytes', side_effect=unreadable), PermissionError)
        self.assertEqual(len(self.calls), 1)

    def test_history_permission_failure_is_retryable(self):
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True): self.stopped('factory_bug_held')
        self.resume()
        read = Path.read_text
        def unreadable(path, *args, **kwargs):
            if path.name == 'factory-bug-resumes.json': raise PermissionError('authored unreadable history')
            return read(path, *args, **kwargs)
        self.retry_after(patch.object(Path, 'read_text', unreadable), PermissionError)
        self.assertEqual(len(self.calls), 1)

    def test_predecessor_audit_mismatch_is_infrastructure_even_if_retrying_audit_succeeds(self):
        self.freeze()
        raw = b'authored predecessor'
        audit_path = self.parent / ('audit-bytes-' + hashlib.sha256(raw).hexdigest())
        audit_path.write_bytes(b'corrupt audit bytes')
        def helper(c, operation, identity):
            result = self.helper(c, operation, identity)
            if operation == 'prepare':
                (task.ROOT / c.case_id / identity / 'output/result.json').write_bytes(raw)
            return result
        audit = dispatch.audit
        def repaired_after_first_error(c, identity, response, raw):
            try: return audit(c, identity, response, raw)
            except dispatch.InputVerificationError:
                audit_path.write_bytes(raw)  # Isolate the first callback's classification.
                raise
        with patch.object(dispatch, 'helper', side_effect=helper):
            self.retry_after(patch.object(dispatch, 'audit', side_effect=repaired_after_first_error),
                             dispatch.DiagnosisTaskCleanupError)

    def test_reset_transport_failure_is_retryable(self):
        def helper(c, operation, identity):
            if operation == 'reset': raise ValueError('authored reset helper failure')
            return self.helper(c, operation, identity)
        self.retry_after(patch.object(dispatch, 'helper', side_effect=helper), ValueError)

    def test_raw_answer_disk_failure_is_retryable(self):
        import errno
        retain = dispatch.retain
        def failed(path, raw):
            if path.name.startswith('raw-bytes-'): raise OSError(errno.ENOSPC, 'authored full disk')
            return retain(path, raw)
        self.retry_after(patch.object(dispatch, 'retain', side_effect=failed))

    def test_decision_publication_disk_failure_is_retryable(self):
        import errno
        def failed(path, value):
            if path.name == 'decision.json': raise OSError(errno.ENOSPC, 'authored full disk')
            return atomic_json(path, value)
        self.retry_after(patch.object(dispatch, 'atomic_json', side_effect=failed))
        self.assertEqual(len(self.calls), 1)

    def test_history_creation_disk_failure_is_retryable(self):
        import errno
        def failed(path, value):
            if path.name == 'factory-bug-resumes.json': raise OSError(errno.ENOSPC, 'authored full disk')
            return atomic_json(path, value)
        self.retry_after(patch.object(diagnosis, 'atomic_json', side_effect=failed))
        self.assertEqual(len(self.calls), 1)

    def test_input_manifest_disk_failure_is_retryable(self):
        import errno
        def failed(path, value):
            if path.name == 'input.json': raise OSError(errno.ENOSPC, 'authored full disk')
            return atomic_json(path, value)
        self.retry_after(patch.object(diagnosis, 'atomic_json', side_effect=failed))
        self.assertEqual(len(self.calls), 1)

    def test_model_free_publication_failure_is_retryable_before_the_gate(self):
        import errno
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True), patch.object(dispatch, 'decision', side_effect=Crash):
            with self.assertRaises(Crash): dispatch.dispatch(self.c, run)
        state = copy.deepcopy(self.c.card['diagnosis_state'])
        for file, module in (('decision.json', dispatch), ('scorecard.json', diagnosis)):
            def failed(path, value):
                if path.name == file: raise OSError(errno.ENOSPC, 'authored full disk')
                return atomic_json(path, value)
            with patch.object(module, 'atomic_json', side_effect=failed):
                with self.assertRaises(OSError): dispatch.dispatch(self.c, run)
            self.c.card.update(status='stopped', terminal_stop='runner_error:OSError')
            self.c.stopped = True; run.finalize_accounting(self.c)
            self.assertEqual(self.c.card['diagnosis_state'], state)
            self.resume()
        self.stopped('factory_bug_held')
        self.assertEqual(len(self.calls), 1)

    def test_declared_result_contract_matches_validated_fields_and_outcomes(self):
        manifest = self.freeze(); value = self.result(manifest)
        schema = diagnosis.RESULT_SCHEMA
        def fields(node, sample):
            self.assertEqual(node['type'], 'object')
            self.assertIs(node['additionalProperties'], False)
            self.assertEqual(set(node['required']), set(sample))
            self.assertEqual(set(node['properties']), set(sample))
        fields(schema, value)
        fields(schema['properties']['evidence']['items'], value['evidence'][0])
        fields(schema['properties']['factory_bug']['anyOf'][1], value['factory_bug'])
        def validate(answer):
            return diagnosis.validate_result(answer, case=self.c.case_id,
                generation=manifest['generation'], evidence_root=self.parent / 'inputs')
        for key in schema['required']:
            bad = copy.deepcopy(value); del bad[key]
            with self.assertRaises(budget.BudgetError): validate(bad)
        self.assertEqual(schema['properties']['schema_version'], {'type': 'integer', 'const': 1})
        with self.assertRaises(budget.BudgetError): validate({**value, 'schema_version': True})
        with self.assertRaises(budget.BudgetError): validate({**value, 'extra': 'forbidden'})
        outcomes = schema['properties']['outcome']['enum']
        self.assertEqual(set(outcomes), set(dispatch.STOPS))
        conditional, = schema['allOf']
        self.assertEqual(conditional['if']['properties']['outcome']['const'], 'factory_bug')
        self.assertEqual(conditional['then']['properties']['factory_bug']['type'], 'object')
        self.assertEqual(conditional['else']['properties']['factory_bug']['type'], 'null')
        for outcome in outcomes:
            correct = {**value, 'outcome': outcome, 'factory_bug': value['factory_bug'] if outcome == 'factory_bug' else None}
            self.assertEqual(validate(correct), correct)
            wrong = {**correct, 'factory_bug': None if outcome == 'factory_bug' else value['factory_bug']}
            with self.assertRaises(budget.BudgetError): validate(wrong)

    def test_long_model_evidence_path_is_malformed_then_repaired(self):
        def answer(c, cwd, callback):
            manifest = json.loads((self.parent / 'input.json').read_text())
            result = self.result(manifest)
            if len(self.calls) == 1: result['evidence'][0]['path'] = 'x' * 300
            (cwd / 'result.json').write_text(json.dumps(result))
        self.answer = answer
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True): self.stopped('factory_bug_held')
        rows = json.loads((self.parent / 'attempts.json').read_text())['attempts']
        self.assertEqual([(r['kind'], r['status'], r['error']) for r in rows],
                         [('judgment', 'malformed', 'schema'), ('repair', 'valid', None)])
        self.assertEqual(len(self.calls), 2)

    def test_invalid_evidence_names_are_rejected_before_any_filesystem_probe(self):
        manifest = self.freeze()
        for name in ('x' * 300, 'é' * 200, '/'.join(['x' * 200] * 6), 'bad\x00name'):
            with self.subTest(name_bytes=len(name.encode())):
                result = self.result(manifest); result['evidence'][0]['path'] = name
                with patch.object(Path, 'is_symlink', side_effect=AssertionError('model path reached filesystem')), \
                     patch.object(Path, 'is_file', side_effect=AssertionError('model path reached filesystem')):
                    with self.assertRaisesRegex(budget.BudgetError, '^diagnosis_result_invalid$'):
                        diagnosis.validate_result(result, case=self.c.case_id, generation=manifest['generation'],
                                                  evidence_root=self.parent / 'inputs')

    def test_valid_frozen_evidence_read_io_failure_is_infrastructure(self):
        import errno
        manifest = self.freeze(); result = self.result(manifest)
        read = Path.read_bytes
        def failed(path):
            if path == self.parent / 'inputs/ledger.json': raise OSError(errno.EIO, 'authored storage I/O failure')
            return read(path)
        with patch.object(Path, 'read_bytes', failed):
            with self.assertRaises(OSError):
                diagnosis.validate_result(result, case=self.c.case_id, generation=manifest['generation'],
                                          evidence_root=self.parent / 'inputs')

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
            def gate(lease, env, *args, user=None):
                self.assertEqual(user, 'pilot')
                listener = SimpleNamespace(server=SimpleNamespace(server_port=12345), token='authored-gate-token')
                if lease.route in model_runtime.GATED_OPENROUTER:
                    self.assertNotIn('OPENCODE_CONFIG', env)
                    clean = model_runtime.model_call_gate.openrouter_environment(lease, env, listener)
                    env.clear(); env.update(clean)
                yield listener
            def budgeted(cmd, cwd, env, *args, **kwargs):
                inserted = sum(row[4:7] == ['-I', 'factory-pilot', '1'] for row in events)
                removed = sum(row[4:6] == ['-D', 'factory-pilot'] for row in events)
                self.assertEqual(inserted - removed, 2, 'runtime must install its listener permits before transport')
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
            self.assertFalse(set(opencode[1]) & set(ambient))
            config = json.loads(opencode[1]['OPENCODE_CONFIG_CONTENT'])
            self.assertEqual(config['permission'], dict(task='deny', webfetch='deny', websearch='deny'))
            self.assertEqual(config['provider']['openrouter']['options']['apiKey'], 'authored-gate-token')
            self.assertEqual(config['provider']['openrouter']['options']['baseURL'], 'http://127.0.0.1:12345/api/v1')
            self.assertEqual(config['enabled_providers'], ['openrouter'])
            self.assertEqual(opencode[1]['OPENCODE_PURE'], '1')
            for key in ('OPENCODE_DISABLE_PROJECT_CONFIG', 'OPENCODE_DISABLE_MODELS_FETCH', 'OPENCODE_DISABLE_AUTOUPDATE'):
                self.assertEqual(opencode[1][key], '1')
            roots = [Path(opencode[1][key]) for key in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME')]
            self.assertEqual({path.name for path in roots}, {'config', 'data', 'cache'})
            self.assertEqual(len({path.parent for path in roots}), 1)
            self.assertEqual(set(opencode[0][1].removeprefix('--preserve-env=').split(',')), set(opencode[1]))

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
