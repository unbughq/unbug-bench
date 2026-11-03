"""Fresh-batch route integration, with saved practice/execution/usage artifacts.

CLI answers, OS privileges, Docker, initial ordinary stress and checkpoint
transport are authored. Installation, attempts, diagnosis, admission, package
proofs and progress are real. This is not worker/VM/live qualification.
"""
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
import diagnosis
import diagnosis_dispatch as dispatch
import diagnosis_task as task
import durable_checkpoint
import extension_compare as comparison
import extension_evaluator as evaluator
import extension_package as package
import extensions
import gate_state
import job_authority
import job_config
import model_router
import model_runtime
import registry
import run
import worker_release
import run_validity
from launch_manifest import WORKER_BENCH
from run_validity import InvalidInfra, InfrastructureExhausted
import test_stream_d_runtime as runtime
import test_stream_d_inputs as inputs
import test_stream_d_dispatch as dispatch_tests
import test_stream_d_entry as entry_tests
import test_scientific_receipts as artifacts
from test_extension_compare import cached_source_inputs
REAL_G1, REAL_FRESHNESS, REAL_CATEGORIES = run.g1, run.loop_freshness, run.stress_categories


class Lifecycle(unittest.TestCase):
    """One case, genuine config/restore transitions, no inherited test methods."""
    patch = runtime.RuntimeTests.patch
    install_receipt = inputs.InputTests.install_receipt
    result = inputs.InputTests.result
    helper = dispatch_tests.DispatchTests.helper
    writable_tasks = dispatch_tests.DispatchTests.writable_tasks
    stress = entry_tests.EntryTests.stress

    def setUp(self):
        runtime.RuntimeTests.setUp(self)
        self.home = self.work
        self.c.case_id = 'case-integration-a'
        self.work = self.home / 'work' / self.c.case_id
        self.work.mkdir(parents=True)
        self.case.rename(self.work / 'case')
        (self.home / 'transcripts').rename(self.work / 'transcripts')
        self.case = self.work / 'case'
        sealed = self.home / 'sealed'; sealed.mkdir()
        self.ledger = self.ledger.rename(sealed / (self.c.case_id + '.continuation-budget.json'))
        c = self.c
        c.work, c.case, c.ledger = self.work, self.case, self.ledger
        c.card.update(case=c.case_id, builder_rounds=8, gates={})
        c.stopped = c.exhaustion_occurred = False
        c.args.rounds = 8
        c.args.no_early_probe = True
        for flag, role in [('builder', 'writer'), ('attacker', 'stress_tester'),
                           ('reviewer1', 'reviewer'), ('strong_calibrator', 'strong_calibrator')]:
            setattr(c.args, flag, c.card['roles'][role]['model'])
        (self.work / 'logs').mkdir()
        self.patch(run, 'SEALED', sealed)
        self.patch(run, 'log', lambda *a: None)
        shell = run.sh
        def offline_shell(c, command, **kwargs):
            # The real G1 contract may check saved patches locally. No Docker,
            # worker, provider CLI or other unconfigured subprocess may escape.
            if list(map(str, command))[:2] != ['git', 'apply']:
                self.fail('unconfigured process boundary: ' + str(command[0]))
            return shell(c, command, **kwargs)
        self.patch(run, 'sh', offline_shell)
        self.patch(gate_state, 'source_inputs', cached_source_inputs)
        self.patch(model_router, 'metadata', side_effect=lambda _: (
            c.batch_id, c.job_id, model_router.epoch(c.batch_deadline)))
        self.factory = self.home / 'release/factory'
        self.factory.mkdir(parents=True)
        self.bench = self.home / 'bench'; self.bench.mkdir()
        (self.bench / 'guards/none').mkdir(parents=True)
        self.source_files = worker_release.source_files(ROOT)
        for name in self.source_files:
            p = Path(name)
            if p.match('factory/*.py') or p.match('factory/prompts/*.md') or name == 'factory/control-recipient.txt':
                destination = self.factory.joinpath(*p.parts[1:])
            elif name in WORKER_BENCH and name.startswith('bin/'):
                destination = self.bench / name
            else:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((ROOT / name).read_bytes())
        self.patch(job_config, 'FACTORY', self.factory)
        self.patch(gate_state, 'RUNNER', self.factory / 'run.py')
        # Real gates use the repository bench; diagnosis reads shipped factory
        # files and the bin files copied into this authored worker layout.
        self.patch(run, 'BENCH', self.bench)
        self.channel = dict(schema=1, batch='integration', job='a', case=c.case_id,
            reservation_id=str(uuid.uuid4()), revision=1, source_generation=None,
            committed_total_usd='500.000000000', batch_deadline='2099-01-01T00:00:00Z')
        self.manifest = dict(schema=1, id='integration', money_limit_usd='500.000000000',
            batch_deadline=self.channel['batch_deadline'], max_concurrency=1, target_slots=1,
            restore_recipient=(ROOT / 'factory/control-recipient.txt').read_text().strip(),
            diagnosis_policy=dict(schema=1, enabled=getattr(self, 'enabled', True)), jobs={'a': dict(mode='batch',
                case=c.case_id, requested_total_usd='500.000000000', max_calls=1000, args=['7'])})
        self.config_path = self.home / 'ram/factory-job.json'
        self.pin_release()
        self.deliver()
        job_config.install(c, c.args)
        self.assertEqual(job_config.diagnosis_enabled(c), getattr(self, 'enabled', True))
        c.card['batch_release_sha256'] = c.args.batch_release_sha256
        c.models = c.card['models'] = run.pick_models(c)
        c.manifest0 = run.bench_manifest()
        self.patch(task, 'ROOT', self.home / 'tasks')
        self.patch(task, 'ROOT_UID', os.getuid())
        self.patch(task.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()))
        self.patch(task, '_quiet', return_value=None)
        self.patch(task.os, 'chown', return_value=None)
        remove = task._remove
        def unprivileged_remove(path):
            if path.is_dir() and not path.is_symlink():
                for p in [path, *path.rglob('*')]:
                    if p.is_dir(): p.chmod(0o700)
            remove(path)
        self.patch(task, '_remove', side_effect=unprivileged_remove)
        self.addCleanup(self.writable_tasks)
        self.patch(run, 'make_pilots')
        self.patch(run, 'dispose_diagnosis_pilot')
        self.patch(worker_release, 'verify_selected_drivers', return_value={})
        self.calls, self.helper_calls, self.model_calls, self.executed = [], [], [], []
        self.rotate_first_route = False
        self.answer = 'close_to_passing'
        self.patch(dispatch, 'helper', side_effect=self.helper)
        opencode = run.opencode
        def external_call(*a, **kw):
            if str(a[4]).startswith('diagnosis-'):
                self.parent = self.work / 'diagnosis' / c.card['diagnosis_state']['exhaustion_id']
                return dispatch_tests.DispatchTests.call(self, *a, **kw)
            return opencode(*a, **kw)
        self.patch(run, 'opencode', side_effect=external_call)
        self.patch(durable_checkpoint, 'checkpoint_progress', return_value=False)
        self.writer_kind = 'change'
        self.reject = None
        self.stress_kind = 'pass'
        self.comparison_failures = 0
        self.runtime_revision = 'authored-integration-release-0'
        self.patch(run_validity, 'runtime_revision', lambda: self.runtime_revision)
        self.transport_calls = []
        self.revisions = {}
        self.comparison_transport()
        self.patch(run, 'checkpoint', side_effect=self.saved_checkpoint)
        self.patch(model_runtime.ModelRuntime, '_invoke', lambda rt, *a, **kw: self.invoke(*a, **kw))
        self.patch(run, 'loop_freshness', side_effect=lambda c, result, report: (result, report))
        self.patch(run, 'g1', return_value=(True, {'problems': [], 'authored_control': 'G1'}))
        self.pipeline = run._gate_pipeline()
        self.pipeline.evaluate = self.evaluate
        self.patch(run, '_gate_pipeline', return_value=self.pipeline)
        self.initial = True
        self.initial_failure = 'G5'
        self.frontier = 'G16'
        self.saved_science = True
        (self.case / 'case.json').write_text(json.dumps(artifacts.REAL['suffix-case']['files']['case.json']))
        self.stress()

    def comparison_transport(self):
        test = self
        class Channel:
            def __init__(self, owner): self.owner = owner
            def send(self, message):
                if message[0] != 'stage': return
                owner, stage = self.owner, message[1]
                test.transport_calls.append((owner.phase, stage))
                c = owner.context
                if stage == 'stress': ok, info = True, {'complete': True, 'blocking': []}
                else: ok, info = test.evaluate(c, stage)
                owner.records.save(stage, ok, info, {}, package.project(c.card))
                self.reply = ('result', evaluator.operations(c))
        def start(owner):
            if test.comparison_failures:
                test.comparison_failures -= 1
                raise InvalidInfra('authored comparison child-start failure')
            owner.pipe = Channel(owner)
        self.patch(evaluator.Evaluator, 'start_child', start)
        self.patch(evaluator.Evaluator, 'receive', lambda owner: owner.pipe.reply)
        self.patch(evaluator.Evaluator, 'close_child', lambda owner: None)

    def pin_release(self):
        relative = 'factory/batches/' + self.manifest['id'] + '.json'
        path = self.factory.parent / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        registry.atomic_json(path, self.manifest)
        self.manifest_sha = gate_state.digest(path)
        files = {**self.source_files, relative: self.manifest_sha}
        # Shipped source hashes are actual bytes, including a fixed-release edit.
        for p in self.factory.glob('*.py'):
            files['factory/' + p.name] = gate_state.digest(p)
        worker = self.factory.parent / 'worker-release-manifest.json'
        registry.atomic_json(worker, {'files': files})
        release = self.factory.parent / 'batch-release.json'
        registry.atomic_json(release, {'files': {worker.name: gate_state.digest(worker)}})
        self.c.args.batch_release_sha256 = gate_state.digest(release)

    def deliver(self):
        c = self.c
        value = dict(schema=1, batch_id=self.channel['batch'], job_id='a', case_id=c.case_id,
            batch_deadline=self.channel['batch_deadline'], source_generation=self.channel['source_generation'],
            batch_release_sha256=c.args.batch_release_sha256, manifest_sha256=self.manifest_sha,
            job_money=copy.deepcopy(self.channel))
        raw = json.dumps(value).encode(); sha = hashlib.sha256(raw).hexdigest()
        job_config.deliver(raw, sha, self.config_path)
        c.args.factory_job_config, c.args.factory_job_config_sha256 = str(self.config_path), sha

    def evaluate(self, c, stage):
        self.executed.append(stage)
        if self.initial and stage == self.initial_failure:
            if stage == 'G2':
                with (c.case / 'freshness.jsonl').open('a') as out: out.write('\n{"authored_interrupted_topup":true}\n')
                raise budget.BudgetError('money_wait')
            with patch.object(run, 'checkpoint', side_effect=InvalidInfra('authored G5 child-start failure')):
                return run.g5(c)
        if stage == 'G1': return run.g1(c)
        if stage == 'G3': c.card['bench_workers_effective'] = c.args.bench_workers
        if self.saved_science and stage in ('G4', 'G5'):
            return getattr(run, stage.lower())(c)
        frontier = self.frontier
        if c is not self.c:
            frontier = self.revisions.get((c.case / 'BUILD-NOTES.md').read_text(), 'G5')
        return stage != frontier, {'authored_stage_control': stage}

    def saved_checkpoint(self, c, overlays, guard, runs, seed, tag, **kwargs):
        plain = (tag == 'g4-none' or (tag.startswith('early-g6') and self.reject != 'saved-cheats') or
                 self.reject == 'G5' or (c is not self.c and (c.case / 'BUILD-NOTES.md').read_text() not in self.revisions))
        saved = artifacts.execution('plain' if plain else 'reference')
        p = c.work / 'gate-details' / (tag + '-saved.json')
        p.parent.mkdir(exist_ok=True)
        registry.atomic_json(p, saved)
        return saved['summary'], saved['records']

    def invoke(self, c, models, text, cwd, name, **kw):
        c.model_process_state['started'] = True
        self.model_calls.append(name)
        if name.startswith('builder-'):
            if self.writer_kind != 'unchanged':
                (c.case / 'BUILD-NOTES.md').write_text('authored writer revision ' + name)
                self.revisions[(c.case / 'BUILD-NOTES.md').read_text()] = self.frontier
            if self.reject == 'G1':
                # Real practice contract with a deliberate run-source mismatch.
                (c.case / 'case.json').write_text(artifacts.fixture('invalid-runs-practice.json.gz')['files']['case.json'])
                c.manifest0 = run.bench_manifest()
                self.patch(run, 'g1', REAL_G1)
            if self.reject == 'saved-cheats':
                (c.case / 'guards/cheats/saved-reference-control').mkdir(parents=True, exist_ok=True)
            if self.stress_kind == 'public': self.public_freshness()
            if self.stress_kind == 'request-only':
                rows = run.freshness_lines(c)
                for row in rows: row.update(hit=False, ambiguous=False)
                (c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        elif name.startswith('attacker-'):
            number = name.split('-')[1]
            if self.stress_kind in ('blocking', 'request-only'):
                config = json.loads(text.split('CATEGORY MODE (overrides whole-review completion instructions):\n')[1].split('\n')[0])
                value = dict(category=config['category'], category_complete=False,
                    completed_subchecks=[config['required_subchecks'][0]],
                    blocking=['Authored scored case defect'], unfinished_validation=['Authored unfinished check'],
                    freshness_review=[], cheats_tried=[], non_blocking=[])
                if self.stress_kind == 'request-only':
                    value.update(blocking=['[freshness-review] independent verdict required'], unfinished_validation=[],
                        category_complete=True, completed_subchecks=config['required_subchecks'])
                    if config['category'] == 'wrong_fixes': value['blocking'] = []
                registry.atomic_json(Path(config['category_output']), value)
            else:
                registry.atomic_json(c.work / 'attacks' / ('round-' + number + '.json'),
                                     {'complete': True, 'blocking': []})
        else:
            self.fail('unexpected CLI transport ' + name)
        return 0

    def finish(self, action):
        c = self.c
        try:
            return action()
        except (budget.BudgetError, run.PauseRequested) as error:
            c.stopped = True
            if isinstance(error, diagnosis.FactoryBugHeldWait):
                c.card.update(status='stopped', terminal_stop='factory_bug_held', factory_bug_wait_reason=error.reason)
            elif str(error) == 'provider_wait' or (str(error) == 'cancelled' and getattr(c, 'router_waits', [])):
                run.write_provider_wait(c, error)
            else:
                c.card['terminal_stop'] = 'paused' if isinstance(error, run.PauseRequested) else str(error)
                c.exhaustion_occurred |= isinstance(error, budget.BudgetError)
            if isinstance(error, run.PauseRequested): c.card.update(run.pause_terminal(error, c.case_id))
            if str(error) == 'budget_exhausted' and (c.work / 'attack-state.json').exists() and c.card.get('stress_review', {}).get('status') != 'completed':
                c.card['stress_review'] = {'status': 'unresolved', 'reason': 'budget_exhausted'}
        except Exception as error:
            c.card['error'] = type(error).__name__
            c.stopped = True
            c.card['terminal_stop'] = 'infrastructure_exhausted' if isinstance(error, InfrastructureExhausted) else 'runner_error:' + type(error).__name__
            c.exhaustion_occurred |= isinstance(error, InfrastructureExhausted)
            self.failure_traceback = traceback.format_exc()
        finally:
            run.finalize_accounting(c)

    def start(self):
        result = self.finish(lambda: run.run_gates(self.c))
        self.assertIsNone(result)
        self.assertTrue(self.c.stopped)
        self.assertEqual(self.c.card['terminal_stop'], 'infrastructure_exhausted')
        self.assertEqual(self.c.card['gates'][self.initial_failure], 'invalid-infra')
        self.assertEqual(self.executed.count(self.initial_failure), 2)
        self.assertEqual(self.c.card['diagnosis_state']['status'], 'pending')
        if job_config.diagnosis_enabled(self.c):
            pointer = json.loads((self.work / 'entry-records/current.json').read_text())
            root = self.work / 'entry-records' / pointer['observation_id']
            self.assertFalse((root / 'closed.json').exists())
            self.assertFalse((root / self.initial_failure / 'record.json').exists())
        self.initial = False

    def restore(self, new_batch=None):
        c = self.c
        # Checkpoint transport carries RunArtifacts.seal's authority projection.
        c.card['job_money'] = copy.deepcopy(c.job_money)
        previous = json.loads(json.dumps(c.card))
        generation = hashlib.sha256(json.dumps(previous, sort_keys=True).encode()).hexdigest()
        c.checkpoint_card = previous
        c.source_generation = generation
        if new_batch:
            old = copy.deepcopy(self.manifest)
            raw = json.dumps(old)
            prior = c.args.batch_release_sha256
            policy = dict(jobs=old['jobs'], batch=dict(id=old['id'], release='/authored-fixed-release',
                sha256=prior, manifest_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                manifest_path='factory/batches/' + old['id'] + '.json', max_concurrency=1))
            self.manifest = {**old, 'id': new_batch, 'carry_from': dict(schema=1, manifest_json=raw,
                policy=policy, snapshot_sha256='f' * 64, jobs={'a': dict(generation=generation,
                    case=c.case_id, committed_total_usd=self.channel['committed_total_usd'])})}
            self.channel.update(batch=new_batch, source_generation=generation,
                                reservation_id=str(uuid.uuid4()), revision=1)
            self.pin_release()
        else:
            self.channel.update(source_generation=generation, revision=self.channel['revision'] + 1)
        c.card = {'case': c.case_id, 'batch_release_sha256': c.args.batch_release_sha256}
        c.args.resume = c.case_id
        c.stopped = c.exhaustion_occurred = False
        c.provider_resume_done = False
        c.model_resume_state = {'done': False}
        for key in ('early', 'early_hash'):
            c.__dict__.pop(key, None)
        self.deliver()
        self.install_receipt(release_sha256=c.args.batch_release_sha256,
            job_config_path=self.config_path, job_config_sha256=c.args.factory_job_config_sha256)
        job_config.install(c, c.args)
        run.inherit_recovery_history(c, previous)
        return previous

    def resume(self, new_batch=None, *, admit=True):
        previous = self.restore(new_batch)
        def routed():
            value = dispatch.dispatch(self.c, run, comparison_route=True)
            self.c.models = self.c.card['models'] = run.pick_models(self.c)
            if type(value) is not int:
                self.assertIs(value, False)
                return 'ordinary'
            if not admit: return value
            if value == 0: value = dispatch.admit_extension(self.c, run, previous)
            return package.run(self.c, run, previous, value)
        return self.finish(routed)

    def label(self, expected):
        self.assertEqual(self.c.card.get('terminal_stop'), expected, getattr(self, 'failure_traceback', ''))
        self.assertNotIn('error', self.c.card)
        self.assertFalse(self.c.card.get('cleanup_errors'))
        reservations = json.loads(self.ledger.read_text()).get('invocation_reservations', {})
        self.assertTrue(all(v['state'] == 'settled' for v in reservations.values()))

    def completed(self, stage='G16'):
        self.label('extension_incomplete')
        row = extensions.read(self.c)[-1]
        self.assertEqual(row['outcome']['frontier'], extensions.stages().index(stage))
        self.assertEqual(self.c.card['diagnosis_state']['status'], 'pending')
        return row

    def replay_package(self):
        row = extensions.read(self.c)[-1]
        tree = extensions.tree(self.work / 'extension-snapshots')
        calls = list(self.model_calls)
        state = copy.deepcopy(self.c.card['diagnosis_state'])
        self.restore()
        dispatch.carry_context(self.c)
        self.c.models = self.c.card['models'] = run.pick_models(self.c)
        with patch.object(run, 'write_and_attack', side_effect=AssertionError('replay writer/stress')), \
             patch.object(run, 'checkpoint', side_effect=AssertionError('replay checkpoint')), \
             patch.object(evaluator.Evaluator, 'start_child', side_effect=AssertionError('replay evaluator')):
            self.finish(lambda: package.run(self.c, run, self.c.checkpoint_card, row['extension_id']))
        self.label('extension_incomplete')
        self.assertEqual(self.c.card['diagnosis_state'], state)
        self.assertEqual(self.model_calls, calls)
        self.assertEqual(extensions.tree(self.work / 'extension-snapshots'), tree)

    def retire(self, expected='retired_no_progress'):
        with patch.object(run, 'writer_request', side_effect=AssertionError('retired writer admission')), \
             patch.object(evaluator, 'Evaluator', side_effect=AssertionError('retired evaluation')):
            self.resume()
        self.label(expected)
        self.replay_retirement(expected)

    def replay_retirement(self, expected):
        before = extensions.tree(self.work / 'diagnosis')
        state = copy.deepcopy(self.c.card.get('diagnosis_state'))
        count = self.c.card.get('factory_bug_resume_count')
        calls = list(self.calls), list(self.model_calls)
        reservations = json.loads(self.ledger.read_text()).get('invocation_reservations', {})
        with patch.object(dispatch, 'invoke', side_effect=AssertionError('terminal diagnosis replay')), \
             patch.object(run, 'pending_call', side_effect=AssertionError('terminal writer replay')):
            self.resume()
        self.label(expected)
        self.assertEqual(self.c.card.get('diagnosis_state'), state)
        self.assertEqual(self.c.card.get('factory_bug_resume_count'), count)
        self.assertEqual((self.calls, self.model_calls), calls)
        self.assertEqual(extensions.tree(self.work / 'diagnosis'), before)
        self.assertEqual(json.loads(self.ledger.read_text()).get('invocation_reservations', {}), reservations)

    def public_freshness(self):
        import freshness_retrieval
        http = artifacts.fixture('invalid-runs-http.json.gz')
        self.assertEqual(hashlib.sha256(http['body'].encode()).hexdigest(), http['sha256'])
        rows = run.freshness_lines(self.c)
        for row in rows: row.update(at=datetime.now(timezone.utc).isoformat(), hit=False, ambiguous=False)
        rows[0].update(url=http['url'], hit=True)
        (self.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        self.patch(freshness_retrieval, 'fetch', lambda url, **kw: (
            {'url': url, 'final_url': url, 'status': 200}, http['body'].encode()))
        def review(c, chain, text, directory, name, out, *a, **kw):
            registry.atomic_json(out, {'hits': [dict(url=row['url'], app_version=row['app_version'],
                resolved=True, retrieved=True, same_bug=True, version_scope='Authored pinned applicability',
                why='Authored same-bug judgment') for row in rows if row['hit']]})
        self.patch(run, 'retained_answer', review)
        self.patch(run, 'loop_freshness', REAL_FRESHNESS)

    def stress_control(self, kind):
        self.stress_kind = kind
        self.patch(run, 'stress_categories', REAL_CATEGORIES)
        self.c.stress_checkpoint = lambda: True  # External checkpoint transport ACK.
        if kind == 'request-only':
            self.patch(run, 'loop_freshness', REAL_FRESHNESS)
            self.patch(run, 'confirm_hits', side_effect=AssertionError('no requested retrieval'))


class AllOutcomesTests(unittest.TestCase):
    def branch(self, name):
        retired = set()
        branch_started = time.monotonic()
        f = Lifecycle()
        try:
            f.enabled = name != 'disabled'
            f.setUp()
            if name == 'rejected-G1':
                shutil.copytree(ROOT / 'projects/medusa', f.bench / 'projects/medusa',
                    ignore=shutil.ignore_patterns('node_modules', '.medusa', '.git', '__pycache__'))
                f.c.manifest0 = run.bench_manifest()
            if name in ('public', 'blocking', 'request-only', 'ordinary-factory-bug',
                        'not-converging', 'malformed', 'deadline', 'rejected-G1'):
                f.saved_science = False
                # These practice branches do not claim a real saved-cheat
                # score; real sample verdicts belong to the suffix-case
                # rejection branches above.
                f.pipeline.saved_cheat_check = lambda c: None
                (f.case / 'case.json').write_text(artifacts.fixture('invalid-runs-practice.json.gz')['files']['case.json'])
                f.stress()
            if name == 'disabled':
                f.c.card['diagnosis_policy'] = {'schema': 1, 'enabled': True}
            if name == 'interrupted-freshness': f.initial_failure = 'G2'
            if name == 'capture-recovery':
                sync = extensions._sync_directory
                failed = []
                def one_shot(path):
                    if (path / 'G1/record.json').exists() and not failed:
                        failed.append(True)
                        raise OSError('authored lost post-rename ACK')
                    return sync(path)
                with patch.object(extensions, '_sync_directory', side_effect=one_shot): f.start()
                self.assertEqual(failed, [True])
                self.assertEqual(f.executed.count('G1'), 1)
            elif name == 'interrupted-freshness':
                f.finish(lambda: run.run_gates(f.c))
                f.label('money_wait')
                self.assertNotIn('diagnosis_state', f.c.card)
                self.assertEqual(f.executed.count('G2'), 1)
                f.initial = False
            else: f.start()
            if name == 'disabled':
                with patch.dict(os.environ, DIAGNOSIS_ENABLED='true'):
                    f.resume(); f.label('diagnosis_pending')
                self.assertEqual(f.calls, []); self.assertEqual(f.model_calls, [])
            elif name in ('missing-proof', 'corrupt-proof', 'interrupted-freshness'):
                pointer = json.loads((f.work / 'entry-records/current.json').read_text())
                root = f.work / 'entry-records' / pointer['observation_id']
                if name == 'missing-proof': (root / 'G4/record.json').unlink()
                elif name == 'corrupt-proof':
                    target = next((root / 'G4/support/case').rglob('case.json'))
                    target.write_text('{}')
                with patch.object(run, 'pending_call', side_effect=AssertionError('missing-proof writer')), \
                     patch.object(evaluator.Evaluator, 'start_child', side_effect=AssertionError('missing-proof evaluator')):
                    if name == 'interrupted-freshness':
                        f.restore()
                        f.c.models = f.c.card['models'] = run.pick_models(f.c)
                        f.finish(lambda: package.entry(f.c, run))
                    else: f.resume()
                    f.label('extension_comparison_pending')
                self.assertFalse((f.work / 'extension-history.json').exists())
            elif name == 'deadline':
                self.assertEqual(f.resume(admit=False), 0)
                import datetime as dates
                class Expired(dates.datetime):
                    @classmethod
                    def now(cls, tz=None): return cls(2100, 1, 1, tzinfo=dates.timezone.utc)
                f.restore()
                with patch.object(job_authority, 'datetime', Expired), \
                     patch.object(dispatch, 'dispatch', side_effect=AssertionError('deadline dispatch')), \
                     patch.object(run, 'pending_call', side_effect=AssertionError('deadline writer')):
                    for _ in range(2):
                        with self.assertRaisesRegex(budget.BudgetError, '^retired_batch_bound$'):
                            job_config.install(f.c, f.c.args)
                retired.add('retired_batch_bound')
            elif name in ('public', 'blocking', 'request-only'):
                if name == 'public': f.stress_kind = 'public'
                else: f.stress_control(name)
                with patch.object(run, 'run_gates', side_effect=AssertionError('gates after terminal stress')):
                    f.resume()
                if name == 'request-only':
                    f.label('retired_stress_request_only')
                    f.replay_retirement('retired_stress_request_only')
                else:
                    row = f.completed('stress')
                    self.assertEqual(row['outcome']['stages'][0]['status'], 'fail')
                    if name == 'public':
                        self.assertEqual(f.c.card['loop_freshness']['outcome'], 'public_match')
                        self.assertEqual(f.c.card['gates'], {'G2': 'fail'})
                    else:
                        self.assertIn('Authored scored case defect',
                            package.Records(f.c, run, row).load('stress')['info']['blocking'])
                    f.replay_package(); f.retire()
            elif name == 'not-converging':
                f.answer = 'not_converging'
                f.retire('retired_not_converging')
            elif name == 'malformed':
                def malformed(c, cwd, before_attempt): (cwd / 'result.json').write_text('{')
                f.answer = malformed
                f.retire('retired_diagnosis_malformed')
                self.assertGreater(len(f.calls), 1)
            elif name in ('factory-bug-return', 'factory-bug-cap'):
                f.resume(); f.completed()
                original = {phase: extensions.tree(f.work / 'extension-snapshots/1' / phase)
                            for phase in ('entry', 'outcome')}
                count = 1 if name == 'factory-bug-return' else 4
                for index in range(count):
                    dependency = f.bench / 'projects/authored-scientific-input.txt'
                    dependency.parent.mkdir(exist_ok=True)
                    dependency.write_text('authored scientific revision ' + str(index))
                    f.c.manifest0 = run.bench_manifest()
                    f.comparison_failures = 2
                    f.answer = 'close_to_passing'
                    f.resume(); f.label('stress_validation_exhausted')
                    self.assertEqual(f.comparison_failures, 0)
                    self.assertEqual(f.c.card['diagnosis_state']['status'], 'pending')
                    f.answer = 'factory_bug'
                    f.resume(); f.label('factory_bug_held')
                    f.replay_retirement('factory_bug_held')
                    f.runtime_revision = 'authored-fixed-release-' + str(index + 1)
                    f.frontier = ('G8', 'G9', 'G6', 'G13')[index]
                    with patch.object(run, 'build', side_effect=AssertionError('lost comparison target')), \
                         patch.object(run, 'validate_and_repair', side_effect=AssertionError('ordinary repair')):
                        f.resume(new_batch='fixed-' + str(index + 1))
                    if index == 3:
                        f.label('retired_factory_bug_limit')
                        f.replay_retirement('retired_factory_bug_limit')
                    else:
                        f.completed(f.frontier)
                        self.assertEqual(f.c.card['factory_bug_resume_count'], index + 1)
                    print('all-outcomes factory-bug finding:', index + 1,
                          'resume count:', f.c.card['factory_bug_resume_count'], flush=True)
                    self.assertEqual({phase: extensions.tree(f.work / 'extension-snapshots/1' / phase)
                                      for phase in ('entry', 'outcome')}, original)
            elif name == 'ordinary-factory-bug':
                f.answer = 'factory_bug'
                f.resume(); f.label('factory_bug_held')
                f.replay_retirement('factory_bug_held')
                with patch.object(dispatch, 'admit_extension', side_effect=AssertionError('ordinary admission')), \
                     patch.object(package, 'run', side_effect=AssertionError('ordinary package')), \
                     patch.object(run, 'pending_call', side_effect=AssertionError('ordinary writer')):
                    self.assertEqual(f.resume(new_batch='fixed-one'), 'ordinary')
                self.assertEqual(f.c.card['factory_bug_resume_count'], 1)
                self.assertNotIn('diagnosis_state', f.c.card)
            elif name.startswith('rejected-'):
                f.reject = name.removeprefix('rejected-')
                with patch.object(run, 'run_gates', side_effect=AssertionError('gates after rejected writer')):
                    f.resume()
                f.label('extension_incomplete')
                self.assertEqual(f.model_calls, ['builder-9'])
                row = extensions.read(f.c)[-1]
                self.assertTrue(all(s['status'] == 'unreached' for s in row['outcome']['stages']))
                self.assertEqual(f.c.card.get('failed_gate'), None if f.reject == 'saved-cheats' else f.reject)
                if f.reject == 'G1':
                    self.assertEqual(f.c.card['failed_detail']['problems'], ['case.json source differs from the run argument'])
                f.replay_package(); f.retire()
            elif name == 'extension-cap':
                for number, frontier in enumerate(('G16', 'G8', 'G9', 'G6', 'G13'), 1):
                    f.frontier = frontier
                    f.resume(); row = f.completed(frontier)
                    self.assertEqual(row['extension_id'], number)
                    self.assertEqual(extensions.progress(row['entry'], row['outcome']), 'progress')
                f.retire('retired_extension_limit')
            else:
                f.resume(); row = f.completed()
                self.assertEqual(row['entry']['frontier'], extensions.stages().index('G5'))
                self.assertEqual(row['entry']['stages'][extensions.stages().index('G5')]['status'], 'unreached')
                f.replay_package()
                if name == 'unchanged': f.writer_kind = 'unchanged'
                f.resume()
                f.label('extension_incomplete')
                self.assertEqual(len(extensions.read(f.c)), 2)
                f.replay_package(); f.retire()
            label = f.c.card.get('terminal_stop', '')
            if label.startswith('retired_'): retired.add(label)
        finally:
            f.doCleanups()
            print('all-outcomes branch:', name, 'seconds:',
                  round(time.monotonic() - branch_started, 2), flush=True)
        return retired

    def test_fresh_batch_all_outcomes(self):
        started = time.monotonic()
        retired = set()
        branches = ('partial', 'capture-recovery', 'unchanged', 'irrelevant-edit', 'rejected-G1',
                    'rejected-G5', 'rejected-saved-cheats', 'not-converging', 'malformed',
                    'ordinary-factory-bug', 'extension-cap', 'public', 'blocking', 'request-only',
                    'disabled', 'deadline', 'missing-proof', 'corrupt-proof', 'interrupted-freshness',
                    'factory-bug-return', 'factory-bug-cap')
        for name in branches:
            with self.subTest(branch=name):
                retired.update(self.branch(name))
        self.assertEqual(retired, {'retired_not_converging', 'retired_no_progress', 'retired_extension_limit',
            'retired_factory_bug_limit', 'retired_diagnosis_malformed', 'retired_stress_request_only',
            'retired_batch_bound'})
        print('all-outcomes integration seconds:', round(time.monotonic() - started, 2))


if __name__ == '__main__': unittest.main()
