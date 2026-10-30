"""Queued-input control replays: saved 5813be ledger and verified practice bytes.

Release/transport envelopes and lifecycle stops are authored. No live qualification.
"""
import copy
import hashlib
import gzip
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
import restore_ledger
import run
import worker_release
from launch_manifest import WORKER_BENCH
import test_stream_d_runtime as runtime
import test_stream_d_extensions as extension_tests


class Interrupted(BaseException): pass


class InputTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch

    def setUp(self):
        runtime.RuntimeTests.setUp(self)
        # Use the worker's real layout so install() produces the actual external
        # receipt. The practice bytes and saved ledger remain unchanged.
        home = self.work
        self.work = home / 'work' / self.c.case_id
        self.work.mkdir(parents=True)
        self.case.rename(self.work / 'case')
        (home / 'transcripts').rename(self.work / 'transcripts')
        self.case = self.work / 'case'
        sealed = home / 'sealed'; sealed.mkdir()
        self.ledger = self.ledger.rename(sealed / (self.c.case_id + '.continuation-budget.json'))
        self.c.work, self.c.case, self.c.ledger = self.work, self.case, self.ledger
        self.c.card = copy.deepcopy(self.source)
        self.c.card.pop('sha256', None)  # The archived first seal cannot name itself.
        self.c.card.update(status='stopped', terminal_stop='infrastructure_exhausted', gates={},
                           infrastructure_gate={'gate': 'G10', 'exhausted': True})
        diagnosis.record_exhaustion(self.c.card)
        self.c.checkpoint_card = copy.deepcopy(self.c.card)
        self.install_receipt()
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

    def install_receipt(self, public=None, **kwargs):
        card = self.c.checkpoint_card
        (self.work / 'scorecard.json').write_text(json.dumps(card))
        (self.work / 'continuation-budget.json').write_text(json.dumps(card['continuation_budget']))
        public = public or {**copy.deepcopy(card), 'sha256': self.c.source_generation}
        return restore_ledger.install(self.work, self.ledger.parent, self.c.case_id,
                                      self.c.source_generation, public, **kwargs)

    @property
    def restore_receipt(self):
        return self.ledger.parent / (self.c.case_id + '.restore-accounting.json')

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
        # An ordinary later restore replaces this external receipt; the original
        # generation remains inside the frozen evidence and finding.
        live_receipt = json.loads(self.restore_receipt.read_text())
        live_receipt['generation'] = later
        self.restore_receipt.write_text(json.dumps(live_receipt))
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
            self.assertFalse((self.parent / 'input.json').exists())

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

    def test_archive_sha_is_not_generation_and_live_settlement_is_separate(self):
        for old_sha in (None, 'd' * 64):
            if self.parent.exists(): shutil.rmtree(self.parent)
            if old_sha is None: self.c.checkpoint_card.pop('sha256', None)
            else: self.c.checkpoint_card['sha256'] = old_sha
            receipt = self.install_receipt()
            manifest = self.freeze()
            self.assertEqual(manifest['generation'], receipt['generation'])
            frozen = json.loads((self.parent / 'inputs/card.json').read_text())
            self.assertEqual(frozen.get('sha256'), old_sha)
        shutil.rmtree(self.parent)
        ledger = json.loads(self.ledger.read_text())
        ledger['events'].append({'id': 'authored-post-restore-event', 'cost': 0, 'calls': 1})
        ledger['calls'] += 1
        self.ledger.write_text(json.dumps(ledger))
        self.freeze()
        self.assertEqual(json.loads((self.parent / 'inputs/ledger.json').read_text()), ledger)
        self.assertNotEqual(restore_ledger.digest(ledger), receipt['ledger_sha256'])

    def test_restore_receipt_and_embedded_ledger_fail_closed(self):
        original = self.restore_receipt.read_bytes()
        mutations = [('version', True), ('version', 2), ('case', 'case-other'),
                     ('accounting_authenticated', False), ('accounting_authenticated', 1),
                     ('generation', None), ('generation', 'f' * 64),
                     ('ledger_sha256', 'f' * 64), ('public_card_sha256', None)]
        for key, bad in mutations:
            with self.subTest(field=key, value=bad):
                self.reset_stop()
                receipt = json.loads(original); receipt[key] = bad
                self.restore_receipt.write_text(json.dumps(receipt))
                self.assert_invalid()
                self.assertFalse((self.parent / 'input.json').exists())
        self.reset_stop(); self.restore_receipt.unlink(); self.assert_invalid()
        self.restore_receipt.write_bytes(original)
        for absent in (True, False):
            self.reset_stop()
            if absent: self.c.checkpoint_card.pop('continuation_budget')
            else: self.c.checkpoint_card['continuation_budget'] = None
            self.assert_invalid()
        self.reset_stop(); self.freeze()
        frozen = self.parent / 'inputs/restore-accounting.json'
        frozen.write_bytes(original + b'\n')
        self.assert_invalid()

    def test_corrected_and_carried_forward_real_restore_receipts(self):
        # Authored, hash-pinned ruling envelope; real install/authenticate/apply
        # code and the saved 5813be ledger, without launching or decrypting.
        from late_recovery import digest
        self.c.card.pop('founder_ruling', None)
        self.c.card.update(builder_rounds=8, recovery_config={'rounds': 8, 'case_budget': 50})
        attack = self.work / 'attack-state.json'
        attack.write_text(json.dumps({'round': 8, 'round_limit': 8}))
        late = dict(gate='G4', round_limit=8, case_sha256=run.case_hash(self.c),
                    stress_receipt_sha256=hashlib.sha256(attack.read_bytes()).hexdigest())
        (self.work / 'late-defect.json').write_text(json.dumps(late))
        self.c.card['late_defect'] = {'gate': 'G4', 'record_sha256': digest(late)}
        self.reset_stop('late_defect_needs_ruling:G4')
        public = {**copy.deepcopy(self.c.checkpoint_card), 'sha256': self.c.source_generation}
        corrected = public['continuation_budget']
        corrected['events'].append({'id': 'authored-explicit-correction', 'cost': .25, 'calls': 1})
        corrected['cost'] += .25; corrected['calls'] += 1
        record = dict(version=3, authority='founder-2026-10-30', case=self.c.case_id,
            generation=self.c.source_generation, sequence=2, public_card_sha256=digest(public),
            ledger_sha256=digest(corrected), prior_receipt_sha256=digest({}), prior_ruling_sha256=None,
            allowances={'case_budget_usd': 50, 'round_limit': 9}, late_defect=public['late_defect'],
            reason='Authored accounting-correction test control')
        ruling = self.work / 'authored-ruling.json'; ruling.write_text(json.dumps(record))
        self.ledger.unlink()  # A fresh restore target, not overwriting a newer worker ledger.
        receipt = self.install_receipt(public, ruling_path=ruling,
            ruling_sha256=hashlib.sha256(ruling.read_bytes()).hexdigest())
        self.assertNotEqual(receipt['ledger_sha256'], receipt['retained_ledger_sha256'])
        self.freeze()
        shutil.rmtree(self.parent)
        for missing in (True, False):
            self.reset_stop('late_defect_needs_ruling:G4')
            bad = copy.deepcopy(receipt)
            if missing: bad.pop('retained_ledger_sha256')
            else: bad['retained_ledger_sha256'] = 'f' * 64
            self.restore_receipt.write_text(json.dumps(bad))
            self.assert_invalid()
        self.c.card['continuation_budget'] = copy.deepcopy(corrected)
        self.c.card['founder_ruling'] = receipt['founder_ruling']
        self.reset_stop('late_defect_needs_ruling:G4')
        carried = self.install_receipt()
        self.assertIs(carried['ruling_carried_forward'], True)
        self.assertNotIn('retained_ledger_sha256', carried)
        self.freeze()

    def test_pass_then_fail_cache_is_omitted_and_live_evidence_preserved(self):
        import gate_state
        detail = self.work / 'gate-details/G4.json'; detail.parent.mkdir()
        detail.write_text(json.dumps({'ok': True, 'case': self.c.case_id}))
        gate_state.save(self.c, 'G4', {'ok': True},
                        gate_state.fingerprint(self.c, 'G4', self.bench), {}, self.bench)
        cache = self.work / 'gate-cache/G4.json'; original = cache.read_bytes()
        detail.write_text(json.dumps({'ok': False, 'case': self.c.case_id}))
        self.reset_stop('budget_exhausted')
        manifest = self.freeze()
        self.assertNotIn('work/gate-cache/G4.json', manifest['files'])
        self.assertEqual((self.parent / 'inputs/work/gate-details/G4.json').read_bytes(), detail.read_bytes())
        self.assertEqual(cache.read_bytes(), original)

    def test_cache_path_controls_and_published_cache_damage(self):
        cache = self.work / 'gate-cache'; cache.mkdir()
        detail = self.work / 'gate-details/G4.json'; detail.parent.mkdir(); detail.write_text('{}')
        evidence = {'kind': 'work', 'path': 'gate-details/G4.json', 'sha256': hashlib.sha256(b'{}').hexdigest()}
        good = cache / 'G4.json'; good.write_text(json.dumps({'evidence': [evidence]}))
        for number, bad in enumerate(('/outside', '../outside', 'gate-cache/G4.json', 'missing.json')):
            (cache / f'bad-{number}.json').write_text(json.dumps({'evidence': [{**evidence, 'path': bad}]}))
        (cache / 'malformed.json').write_text('{')
        manifest = self.freeze()
        self.assertEqual([n for n in manifest['files'] if n.startswith('work/gate-cache/')], ['work/gate-cache/G4.json'])
        (self.parent / 'inputs/work/gate-cache/G4.json').write_text('{}')
        self.assert_invalid()
        shutil.rmtree(self.parent); self.reset_stop()
        (cache / 'linked.json').symlink_to(detail)
        self.assert_invalid()

    def test_saved_bench_bytes_current_wins_and_replay_never_reselects(self):
        real = json.loads(gzip.decompress((ROOT / 'tests/factory/fixtures/invalid-runs-real.json.gz').read_bytes()))
        old = json.dumps(real['plain']['files']['checkpoint.json']).encode()
        new = json.dumps(real['reference']['files']['checkpoint.json']).encode()
        self.assertNotEqual(old, new)
        restored = self.work / 'bench-results/runs/baseline.json'; restored.parent.mkdir(parents=True)
        current = self.bench / 'results/runs/baseline.json'; current.parent.mkdir(parents=True)
        restored.write_bytes(old); current.write_bytes(new)
        only = restored.with_name('restored-only.json'); only.write_bytes(old)
        cache = self.work / 'gate-cache/G4.json'; cache.parent.mkdir()
        cache.write_text(json.dumps({'evidence': [{'kind': 'bench', 'path': 'runs/baseline.json',
                                                'sha256': hashlib.sha256(old).hexdigest()}]}))
        manifest = self.freeze()
        frozen = self.parent / 'inputs/work/bench-results/runs/baseline.json'
        self.assertEqual(frozen.read_bytes(), new)
        self.assertIn('work/bench-results/runs/restored-only.json', manifest['files'])
        self.assertNotIn('work/gate-cache/G4.json', manifest['files'])
        self.assertEqual(restored.read_bytes(), old); self.assertEqual(current.read_bytes(), new)
        current.write_bytes(old)
        self.assertEqual(self.freeze(), manifest); self.assertEqual(frozen.read_bytes(), new)

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

    def test_gate_cache_references_and_current_bench_precedence(self):
        current = self.bench / 'results/test.json'; current.parent.mkdir(); current.write_text('{}')
        restored = self.work / 'bench-results/test.json'; restored.parent.mkdir(); restored.write_text('{}')
        cache = self.work / 'gate-cache/G4.json'; cache.parent.mkdir()
        cache.write_text(json.dumps({'evidence': [{'kind': 'bench', 'path': 'test.json',
                                                'sha256': hashlib.sha256(b'{}').hexdigest()}]}))
        self.assertIn('work/bench-results/test.json', self.freeze()['files'])
        shutil.rmtree(self.parent); restored.write_text('{"different":true}')
        manifest = self.freeze()
        self.assertEqual((self.parent / 'inputs/work/bench-results/test.json').read_bytes(), b'{}')
        self.assertIn('work/gate-cache/G4.json', manifest['files'])
        shutil.rmtree(self.parent); restored.unlink(); current.unlink()
        self.assertNotIn('work/gate-cache/G4.json', self.freeze()['files'])

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
