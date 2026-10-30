"""Queued-input control replays: saved 5813be ledger and verified practice bytes.

Release/transport envelopes and lifecycle stops are authored. No live qualification.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
import diagnosis
import job_config
import worker_release
from launch_manifest import WORKER_BENCH
import test_stream_d_runtime as runtime
import test_stream_d_extensions as extension_tests


class Interrupted(BaseException): pass


class InputTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch

    def setUp(self):
        runtime.RuntimeTests.setUp(self)
        self.c.card = copy.deepcopy(self.source)
        self.c.card.update(status='stopped', terminal_stop='infrastructure_exhausted', gates={},
                           infrastructure_gate={'gate': 'G10', 'exhausted': True})
        diagnosis.record_exhaustion(self.c.card)
        self.c.checkpoint_card = copy.deepcopy(self.c.card)
        self.parent = self.work / 'diagnosis' / self.c.card['diagnosis_state']['exhaustion_id']
        self.bench = self.work / 'authored-bench'
        factory = self.work / 'authored-release/factory'
        factory.mkdir(parents=True)
        files = worker_release.source_files(ROOT)
        for name in files:
            relative = Path(name)
            if (relative.match('factory/*.py') or relative.match('factory/prompts/*.md') or
                    (name in WORKER_BENCH and name.startswith('bin/'))):
                destination = factory.joinpath(*relative.parts[1:]) if relative.parts[0] == 'factory' else self.bench / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((ROOT / name).read_bytes())
        worker = factory.parent / 'worker-release-manifest.json'
        worker.write_text(json.dumps({'files': files}))
        release = factory.parent / 'batch-release.json'
        release.write_text(json.dumps({'files': {worker.name: hashlib.sha256(worker.read_bytes()).hexdigest()}}))
        release_sha = hashlib.sha256(release.read_bytes()).hexdigest()
        self.c.args.batch_release_sha256 = release_sha
        self.c.authenticated_job_config['batch_release_sha256'] = release_sha
        self.patch(job_config, 'FACTORY', factory)

    def freeze(self):
        return diagnosis.queued_inputs(self.c, self.bench, quiescent=True)

    def reset_stop(self, stop='infrastructure_exhausted'):
        self.c.card['terminal_stop'] = stop
        self.c.card['diagnosis_state']['stop'] = stop
        self.c.checkpoint_card = copy.deepcopy(self.c.card)

    def assert_invalid(self, action=None):
        state = copy.deepcopy(self.c.card['diagnosis_state'])
        with self.assertRaisesRegex(budget.BudgetError, '^diagnosis_input_invalid$'):
            (action or self.freeze)()
        self.assertEqual(self.c.card['terminal_stop'], 'diagnosis_input_invalid')
        self.assertEqual(self.c.card['status'], 'stopped')
        self.assertFalse(diagnosis.exhaustion(self.c.card))
        self.assertIsNone(diagnosis.pending_projection(self.c.card))
        diagnosis.record_exhaustion(self.c.card, new_exhaustion=True)
        self.assertEqual(self.c.card['diagnosis_state'], state)

    def result(self, manifest):
        return dict(schema_version=1, case_id=self.c.case_id, checkpoint_sha256=manifest['generation'],
            outcome='factory_bug', reason='authored finding',
            evidence=[dict(path='ledger.json', sha256=manifest['files']['ledger.json'], finding='authored evidence')],
            factory_bug=dict(component='private component', reproducer='private reproducer',
                             affected_operations=[], fix_required='private fix'))

    def persist(self, manifest):
        diagnosis.persist_factory_bug(self.c, self.result(manifest), generation=manifest['generation'],
                                       evidence_root=self.parent / 'inputs')

    def test_frozen_evidence_survives_live_usage_and_later_generation(self):
        manifest = self.freeze()
        atomic = diagnosis.atomic_json
        def interrupted(path, value):
            if Path(path).name == 'scorecard.json': raise Interrupted()
            atomic(path, value)
        with patch.object(diagnosis, 'atomic_json', side_effect=interrupted):
            with self.assertRaises(Interrupted): self.persist(manifest)
        finding = (self.parent / 'finding.json').read_bytes()
        frozen = diagnosis._input_inventory(self.parent / 'inputs')
        self.ledger.write_text(self.ledger.read_text() + '\n')
        later = 'c' * 64
        self.c.source_generation = self.c.job_money['source_generation'] = later
        self.c.authenticated_job_config['job_money']['source_generation'] = later
        self.c.checkpoint_card['sha256'] = later
        self.assertEqual(self.freeze(), manifest)
        self.assertTrue(diagnosis.restore_factory_bug(self.c, generation=manifest['generation'],
                                                      evidence_root=self.parent / 'inputs'))
        self.assertEqual((self.parent / 'finding.json').read_bytes(), finding)
        self.assertEqual(diagnosis._input_inventory(self.parent / 'inputs'), frozen)
        self.assertEqual(self.c.card['terminal_stop'], 'factory_bug_held')

    def test_missing_manifest_after_finding_or_completion_preserves_bound_bytes(self):
        manifest = self.freeze()
        self.persist(manifest)
        finding = (self.parent / 'finding.json').read_bytes()
        files = diagnosis._input_inventory(self.parent / 'inputs')
        (self.parent / 'input.json').unlink()
        self.ledger.write_text(self.ledger.read_text() + '\n')
        self.assert_invalid()
        self.assertEqual((self.parent / 'finding.json').read_bytes(), finding)
        self.assertEqual(diagnosis._input_inventory(self.parent / 'inputs'), files)
        self.c.card['diagnosis_state'].update(status='pending', outcome=None)
        self.c.card['terminal_stop'] = 'infrastructure_exhausted'
        self.assert_invalid()
        self.assertEqual(diagnosis._input_inventory(self.parent / 'inputs'), files)

    def test_raw_or_reserved_invocation_prevents_orphan_replacement(self):
        manifest = self.freeze()
        (self.parent / 'input.json').unlink()
        frozen = diagnosis._input_inventory(self.parent / 'inputs')
        raw = self.parent / 'raw-result-test.json'; raw.write_text('{}')
        self.assert_invalid()
        raw.unlink()
        for suffix in ('', '-repair-1'):
            self.reset_stop()
            ledger = json.loads(self.ledger.read_text())
            ledger['invocation_reservations'] = {'authored': {
                'call_name': 'diagnosis-' + manifest['exhaustion_id'] + suffix}}
            self.ledger.write_text(json.dumps(ledger))
            self.assert_invalid()
            self.assertEqual(diagnosis._input_inventory(self.parent / 'inputs'), frozen)

    def test_unbound_orphan_restages_after_settlement_and_manifest_is_last(self):
        atomic = diagnosis.atomic_json
        def interrupted(path, value):
            if Path(path).name == 'input.json': raise Interrupted()
            atomic(path, value)
        with patch.object(diagnosis, 'atomic_json', side_effect=interrupted):
            with self.assertRaises(Interrupted): self.freeze()
        self.assertTrue((self.parent / 'inputs/ledger.json').exists())
        self.assertFalse((self.parent / 'input.json').exists())
        old = (self.parent / 'inputs/ledger.json').read_bytes()
        self.ledger.write_bytes(old + b'\n')
        manifest = self.freeze()
        self.assertEqual((self.parent / 'inputs/ledger.json').read_bytes(), old + b'\n')
        self.assertEqual(manifest['files'], diagnosis._input_inventory(self.parent / 'inputs'))
        self.assertEqual(json.loads(self.ledger.read_text()).get('invocation_reservations', {}), {})

    def test_corrupt_manifest_inventory_or_binding_is_terminal(self):
        original = self.freeze()
        path = self.parent / 'input.json'
        for key, bad in [('schema_version', True), ('case_id', 'case-other'),
                         ('exhaustion_id', str(uuid.uuid4())), ('generation', None), ('files', {})]:
            self.reset_stop()
            value = copy.deepcopy(original); value[key] = bad
            path.write_text(json.dumps(value))
            self.assert_invalid()
        path.write_text(json.dumps(original))
        ledger = self.parent / 'inputs/ledger.json'; data = ledger.read_bytes()
        self.reset_stop(); ledger.write_bytes(data + b'\n'); self.assert_invalid()
        self.reset_stop(); ledger.unlink(); self.assert_invalid()
        ledger.write_bytes(data)
        self.reset_stop(); (self.parent / 'inputs/extra.json').write_text('{}'); self.assert_invalid()

    def test_initial_generation_missing_or_mismatched_refuses(self):
        for generation in (None, 'b' * 64):
            self.reset_stop()
            self.c.source_generation = self.c.job_money['source_generation'] = generation
            self.c.authenticated_job_config['job_money']['source_generation'] = generation
            self.assert_invalid()
            self.assertFalse((self.parent / 'inputs').exists())

    def test_budget_and_stress_minimum_inputs_and_quiescence(self):
        for stop in ('budget_exhausted', 'stress_review_unresolved:rounds_exhausted'):
            if self.parent.exists(): shutil.rmtree(self.parent)
            self.reset_stop(stop)
            self.c.card.pop('infrastructure_gate', None)
            self.c.checkpoint_card = copy.deepcopy(self.c.card)
            self.assertIn('ledger.json', self.freeze()['files'])
        self.assert_invalid(lambda: diagnosis.queued_inputs(self.c, self.bench, quiescent=False))

    def test_self_consistent_manifest_cannot_drop_required_input_records(self):
        manifest = self.freeze()
        path = self.parent / 'inputs/card.json'
        path.unlink(); manifest['files'].pop('card.json')
        (self.parent / 'input.json').write_text(json.dumps(manifest))
        self.assert_invalid()

    def test_g4_g6_late_defect_receipts_need_no_gate_detail_file(self):
        from late_recovery import digest
        for gate in ('G4', 'G6'):
            if self.parent.exists(): shutil.rmtree(self.parent)
            # The saved legacy card predates this control envelope.
            self.c.card['recovery_config'] = {'rounds': 8}
            self.c.card['builder_rounds'] = 8
            self.reset_stop('late_defect_needs_ruling:' + gate)
            record = dict(version=1, gate=gate, detail='authored defect')
            (self.work / 'late-defect.json').write_text(json.dumps(record))
            self.c.card['late_defect'] = dict(gate=gate, record_sha256=digest(record))
            self.c.checkpoint_card = copy.deepcopy(self.c.card)
            self.assertIn('work/late-defect.json', self.freeze()['files'])
            shutil.rmtree(self.parent)
            for wrong in ('missing', 'gate', 'digest'):
                self.reset_stop('late_defect_needs_ruling:' + gate)
                (self.work / 'late-defect.json').write_text(json.dumps(record))
                self.c.checkpoint_card['late_defect'] = dict(gate=gate, record_sha256=digest(record))
                if wrong == 'missing': (self.work / 'late-defect.json').unlink()
                elif wrong == 'gate': self.c.checkpoint_card['late_defect']['gate'] = 'G3'
                else: self.c.checkpoint_card['late_defect']['record_sha256'] = 'f' * 64
                self.assert_invalid()

    def test_gate_cache_references_and_restored_bench_results_agree(self):
        current = self.bench / 'results/test.json'; current.parent.mkdir(); current.write_text('{}')
        restored = self.work / 'bench-results/test.json'; restored.parent.mkdir(); restored.write_text('{}')
        cache = self.work / 'gate-cache/G4.json'; cache.parent.mkdir()
        cache.write_text(json.dumps({'evidence': [{'kind': 'bench', 'path': 'test.json',
                                                'sha256': hashlib.sha256(b'{}').hexdigest()}]}))
        self.assertIn('work/bench-results/test.json', self.freeze()['files'])
        shutil.rmtree(self.parent); restored.write_text('{"different":true}')
        self.assert_invalid()
        self.reset_stop(); restored.unlink(); current.unlink()
        self.assert_invalid()

    def test_release_digest_and_selected_symlinks_refuse_exclusions_stay_out(self):
        for name in ('job-money.json', 'private-key.txt', 'logs/stdio.log', 'statements/statement.md'):
            path = self.work / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('authored exclusion')
        manifest = self.freeze()
        self.assertTrue(all(not name.startswith(('work/logs/', 'work/statements/')) for name in manifest['files']))
        self.assertNotIn('work/job-money.json', manifest['files'])
        self.assertNotIn('work/private-key.txt', manifest['files'])
        shutil.rmtree(self.parent)
        source = job_config.FACTORY / 'run.py'; original = source.read_bytes(); source.write_bytes(original + b'\n')
        self.assert_invalid(); source.write_bytes(original)
        self.reset_stop(); link = self.case / 'authored-link'; link.symlink_to(self.ledger)
        self.assert_invalid(); link.unlink()
        self.reset_stop()
        if self.parent.exists(): shutil.rmtree(self.parent)
        self.parent.symlink_to(self.work)
        self.assert_invalid()
        self.assertTrue(self.ledger.exists())

    def test_completed_extension_inputs_verify_snapshots_and_public_outcome(self):
        import extensions
        harness = extension_tests.ExtensionTests()
        # Use this test's actual retained practice tree and ledger; only stage proofs are authored.
        harness.c, harness.work, harness.case, harness.ledger = self.c, self.work, self.case, self.ledger
        harness.begin(harness.snapshot(1))
        extensions.complete(self.c, harness.snapshot(2))
        self.c.card['diagnosis_state'] = dict(schema_version=1, exhaustion_id=str(uuid.uuid4()),
            stop='extension_incomplete', status='pending', outcome=None)
        self.reset_stop('extension_incomplete')
        self.parent = self.work / 'diagnosis' / self.c.card['diagnosis_state']['exhaustion_id']
        self.assertIn('work/extension-history.json', self.freeze()['files'])
        shutil.rmtree(self.parent)
        self.c.checkpoint_card['extension_history'][-1]['outcome_sha256'] = 'f' * 64
        self.assert_invalid()
        self.reset_stop('extension_incomplete')
        (self.work / 'extension-snapshots/1/entry/case/case.json').write_text('{}')
        self.assert_invalid()


if __name__ == '__main__': unittest.main()
