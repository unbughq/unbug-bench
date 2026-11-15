"""Authenticated in-step publication and process-loss replay without providers."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'factory')]

import contextlib
import dataclasses
import json
import os
import select
import shutil
import signal
import tempfile
import types
import unittest
from unittest.mock import patch

import model_runtime
from durable import checkpoints as cp
from durable.artifacts import AgeSealer
from durable.contract import ArtifactKind, Ref, Step, StepInput, StepKind, PollState, WORKER_ROOT
from durable.worker_step import Worker, blob_name, ledger_totals, restore


class Runner:
    @staticmethod
    def retained_paths(c):
        return sorted(p.relative_to(c.work) for p in c.work.iterdir())


def context(work, si):
    return types.SimpleNamespace(work=work, ledger=work / 'continuation-budget.json',
        engine=types.SimpleNamespace(key=si.idempotency_key),
        card=json.loads((work / 'scorecard.json').read_text()))


class ReleaseScope(unittest.TestCase):
    def test_a_plumbing_only_release_keeps_saved_gate_results(self):
        """18681d (12 November): a plumbing release that changed no gate made the GATES retry redo
        ~8 hours of passed gates. Saved results now survive plumbing releases; each still needs its
        exact binding, and a new bench, feedback or ruling starts afresh."""
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        work = Path(tmp.name)
        base = {'plumbing': 'p1', 'bench': 'b1', 'feedback': None, 'ruling': None}
        def ctx(**change):
            return types.SimpleNamespace(work=work, card={}, engine=types.SimpleNamespace(
                key='b-test/case-test/3/gates:1/1', source_binding={**base, **change}))
        ran = []
        def gate():
            ran.append(1); return True, {'ok': True}
        self.assertEqual(cp.gate_call(ctx(), 'G4', gate, 'binding'), (True, {'ok': True}))
        self.assertEqual(cp.gate_call(ctx(plumbing='p2'), 'G4', gate, 'binding'), (True, {'ok': True}))
        self.assertEqual(len(ran), 1)                     # reused across the plumbing release
        cp.gate_call(ctx(plumbing='p2'), 'G4', gate, 'changed-binding')
        self.assertEqual(len(ran), 2)                     # its own binding still decides
        for change in ({'bench': 'b2'}, {'feedback': 'f'}, {'ruling': 'r'}):
            cp.gate_call(ctx(**change), 'G4', gate, 'binding')
        self.assertEqual(len(ran), 5)                     # bench, feedback and ruling still scope it
        # A saved failure replays only under the release that recorded it (the next may be its fix).
        def failing():
            ran.append(1); return False, {'problems': ['x']}
        cp.gate_call(ctx(plumbing='p3'), 'G5', failing, 'binding')
        cp.gate_call(ctx(plumbing='p3'), 'G5', failing, 'binding')
        self.assertEqual(len(ran), 6)
        cp.gate_call(ctx(plumbing='p4'), 'G5', failing, 'binding')
        self.assertEqual(len(ran), 7)
        # A change to the verdict-path code starts afresh even for passes.
        with patch.object(cp, 'verdict_code', return_value='other'):
            cp.gate_call(ctx(plumbing='p5'), 'G4', gate, 'binding')
        self.assertEqual(len(ran), 8)

    def test_a_cached_bench_pass_has_one_home(self):
        """A G4-G7/G13-G15 pass that gate-cache holds (GatePipeline.check marks c.gate_cached) is not
        also a step record. A pass it does not hold, a model stage's pass and a failure still are."""
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        c = types.SimpleNamespace(work=Path(tmp.name), card={}, gate_cached={'G4', 'G16'}, engine=types.SimpleNamespace(
            key='b-test/case-test/3/gates:1/1', source_binding={'plumbing': 'p1', 'bench': 'b1', 'feedback': None, 'ruling': None}))
        passing = lambda: (True, {'ok': True})
        for gate, model in (('G4', False), ('G5', False), ('G16', True), ('G11', True)):
            cp.gate_call(c, gate, passing, 'binding')
        cp.gate_call(c, 'G6', lambda: (False, {'problems': ['x']}), 'binding')
        c.gate_cached.add('G6')
        records = lambda model: sorted(p.name for p in cp.directory(c, model=model).glob('gate-*.json'))
        self.assertEqual(records(False), ['gate-G5.json', 'gate-G6.json'])
        self.assertEqual(records(True), ['gate-G11.json', 'gate-G16.json'])

    def test_a_pinned_release_keeps_the_previous_receipt_folder(self):
        """The folder name hashes the verdict-path files, so a release editing them moves every live case
        to a fresh folder. A reviewed pin (invalid-runs-compat.json verdict_code_pins) maps this release's
        digest to its predecessor's; a stale pin changes nothing."""
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        work = Path(tmp.name)
        c = types.SimpleNamespace(work=work / 'w', card={}, engine=types.SimpleNamespace(
            key='b-test/case-test/3/gates:1/2', source_binding={'plumbing': 'p2', 'bench': 'b1', 'feedback': None, 'ruling': None}))
        compat = work / 'compat.json'
        def folder(pins):
            compat.write_text(json.dumps({'verdict_code_pins': pins}))
            cp._VERDICT_DIGEST.clear()
            with patch.object(cp, 'COMPAT', compat):
                return cp.directory(c, model=False), cp.verdict_code(False)
        self.addCleanup(cp._VERDICT_DIGEST.clear)
        fresh, digest = folder({})
        old, _ = folder({'bench': {'from': 'previous-release', 'to': 'other'}})
        self.assertEqual(old, fresh, 'a stale pin changes nothing')
        with patch.object(cp, 'verdict_code', return_value='previous-release'):
            previous = cp.directory(c, model=False)
        previous.mkdir(parents=True)   # a pass and a failure the previous release recorded (attempt 1)
        (previous / 'gate-G1.json').write_text(json.dumps({'binding': 'b', 'ok': True, 'info': {'kept': 1}, 'plumbing': 'p1'}))
        (previous / 'gate-G5.json').write_text(json.dumps({'binding': 'b', 'ok': False, 'info': {}, 'plumbing': 'p1'}))
        pinned, _ = folder({'bench': {'from': 'previous-release', 'to': digest}})
        self.assertEqual(pinned, previous)
        ran = []
        with patch.object(cp, 'COMPAT', compat):
            self.assertEqual(cp.gate_call(c, 'G1', lambda: self.fail('kept pass repeated'), 'b'), (True, {'kept': 1}))
            cp.gate_call(c, 'G5', lambda: (ran.append(1), (True, {}))[1], 'b')
        self.assertEqual(ran, [1], 'a failure still replays only under the release that recorded it')


@unittest.skipUnless(shutil.which('age'), 'requires local age CLI')
class Checkpoints(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.si = StepInput('b-test', 'case-test', 1, Step(StepKind.WRITER, 1), 1,
            'a' * 64, 'b' * 64, Ref('c' * 64, ArtifactKind.INPUTS),
            Ref('d' * 64, ArtifactKind.CASE_SNAPSHOT), 600, 5_000_000)
        self.key = os.urandom(32)
        self.worker = Worker(self.home)
        self.work = self.home / 'work'
        self.work.mkdir()
        (self.work / 'scorecard.json').write_text('{}')
        (self.work / 'continuation-budget.json').write_text('{"calls":0,"events":[],"cost":0}')
        self.c = context(self.work, self.si)
        self.c.engine_checkpoint = lambda: self.worker.publish_checkpoint(
            self.si, self.c, AgeSealer(), self.key, Runner)

    def completed_work(self, c):
        def invoke():
            (c.work / 'answer').write_text('completed model artifact')
            (c.work / 'answer').chmod(0o750)
            (c.work / 'usage-receipts').mkdir(exist_ok=True)
            (c.work / 'usage-receipts/call.json').write_text('{"final_usage_known":true}')
            c.card['route_receipts'] = [{'invocation': 'builder-1', 'outcome': 'done',
                                         'call_id': 'usage-receipts/call.json'}]
            c.ledger.write_text(json.dumps({'calls': 1, 'cost': 0.25, 'events': [
                {'id': 'paid', 'cost': 0.25, 'configured_model': 'local/test'}],
                'invocation_reservations': {'uncertain': {'lease_id': 'uncertain', 'call_name': 'builder-uncertain', 'state': 'pending', 'maximum_usd': 1, 'event_ids': []}}}))
            return 0
        runtime = model_runtime.ModelRuntime(None, None, None, None, None)
        with patch.object(model_runtime.ModelRuntime, '_call', side_effect=lambda *a, **kw: invoke()):
            runtime.call(c, ['local/test'], 'deterministic prompt', c.work, 'builder-1')
        def gate():
            (c.work / 'gate-evidence').write_text('verified')
            return True, {'verified': True}
        cp.gate_call(c, 'G4', gate, 'unchanged-case')
        cp.checkpoint(c)

    def recover(self):
        ref = self.worker.read_checkpoint(self.si.idempotency_key)
        ciphertext = (self.worker.paths(self.si.idempotency_key)['attempt'] / 'out' / blob_name(ref)).read_bytes()
        fresh = self.home / 'fresh-worker'
        fresh.mkdir()
        blob = fresh / WORKER_ROOT / 'blobs' / blob_name(ref)
        blob.parent.mkdir(parents=True)
        blob.write_bytes(ciphertext)
        worker = Worker(fresh)
        recovered = fresh / 'work'
        restore(worker.open_blob(AgeSealer(), self.key, ref), recovered)
        c = context(recovered, dataclasses.replace(self.si, attempt=2))
        # Simulate caller preparing the same workspace before model dispatch.
        (recovered / 'answer').unlink()  # caller restores the pre-call workspace
        never = lambda: self.fail('completed work repeated')
        self.assertEqual(cp.model_call(c, ['local/test'], recovered, 'builder-1', never, text='deterministic prompt'), 0)
        self.assertEqual(cp.gate_call(c, 'G4', never, 'unchanged-case'), (True, {'verified': True}))
        self.assertEqual((recovered / 'answer').read_text(), 'completed model artifact')
        self.assertEqual((recovered / 'answer').stat().st_mode & 0o777, 0o750)
        ledger = json.loads(c.ledger.read_text())
        self.assertEqual(ledger['calls'], 1)
        self.assertEqual(ledger['events'][0]['cost'], 0.25)
        self.assertIn('uncertain', ledger['invocation_reservations'])
        self.assertEqual(float(ledger_totals(c.ledger)['total']), 1.25)
        self.assertEqual((recovered / 'gate-evidence').read_text(), 'verified')
        with self.assertRaises(Exception):
            AgeSealer().open(self.key, ref, ciphertext[:-1] + bytes([ciphertext[-1] ^ 1]))

    def test_committed_snapshot_replays_outputs_and_keeps_accounting(self):
        self.completed_work(self.c)
        with patch.object(self.worker, 'processes', return_value={123}):
            poll = self.worker.poll({'key': self.si.idempotency_key})
        self.assertEqual(poll.state, PollState.RUNNING)
        self.assertIsNotNone(poll.checkpoint)
        self.recover()

    def test_failed_blob_publication_cannot_advance_pointer(self):
        self.completed_work(self.c)
        previous = self.worker.read_checkpoint(self.si.idempotency_key)
        (self.work / 'answer').write_text('new state')
        with patch.object(self.worker, '_sync_directory', side_effect=OSError('fault')):
            with self.assertRaises(OSError): self.c.engine_checkpoint()
        self.assertEqual(self.worker.read_checkpoint(self.si.idempotency_key), previous)

    def test_isolated_role_defers_nested_checkpoints_until_joined(self):
        seen = []
        self.c.engine_checkpoint = lambda: seen.append(True)
        external = self.home / 'pilot-home'
        external.mkdir()
        cp.model_call(self.c, ['local/test'], external, 'pilot', lambda: cp.checkpoint(self.c))
        self.assertEqual(seen, [])
        cp.checkpoint(self.c)
        self.assertEqual(seen, [True])

    def test_real_reviewer_replays_on_new_worker_but_obeys_changed_ruling(self):
        import run
        from test_durable_worker_step import practice_tree
        si = dataclasses.replace(self.si, step=Step(StepKind.GATES, 1))
        work = practice_tree(self.home / 'initial', si.case_id)
        c = run.context_for_step(si, work)
        self.worker.bind_checkpoint(si, c, AgeSealer(), self.key, run)
        seen = []
        def model(c, models, text, cwd, name, **kwargs):
            seen.append(text)
            c.model_lease = types.SimpleNamespace(route=models[0])
            # Retained answers live outside the review cwd, like the real provider.
            target = Path(text.split('verdict_path": "')[1].split('"')[0])
            target.write_text(json.dumps({
                'fairness': {'approve': True}, 'realism': {'approve': True}}))
            receipt = c.work / 'usage-receipts' / f'{len(seen)}.json'
            receipt.parent.mkdir(exist_ok=True)
            receipt.write_text('{"final_usage_known":true}')
            c.card.setdefault('route_receipts', []).append({'invocation': name,
                'outcome': 'done', 'call_id': str(receipt.relative_to(c.work))})
            return 0
        with patch.object(model_runtime.ModelRuntime, '_call', side_effect=model):
            first = run.review(c)
            ref = self.worker.read_checkpoint(si.idempotency_key)
            raw = (self.worker.paths(si.idempotency_key)['out'] / blob_name(ref)).read_bytes()
            fresh = self.home / 'replacement' / si.case_id
            restore(AgeSealer().open(self.key, ref, raw), fresh)
            states = list((fresh / 'ordinary-retries').glob('*/state.json'))
            self.assertTrue(states, 'runner snapshot omitted retained answers')
            self.assertTrue(all(json.loads(p.read_text())['attempts'][-1]['phase'] == 'completed' for p in states))
            retry = dataclasses.replace(si, attempt=2, snapshot=ref)
            c = run.context_for_step(retry, fresh)
            c.engine_checkpoint = lambda: True
            self.assertEqual(run.review(c), first)
            self.assertEqual(len(seen), len(c.models['reviewers']))
            c = run.context_for_step(dataclasses.replace(retry, attempt=3), fresh)
            c.engine_checkpoint = lambda: True
            c.engine_ruling = 'Judge the newly clarified owner requirement.'
            run.review(c)
            self.assertEqual(len(seen), 2 * len(c.models['reviewers']))
            self.assertIn('newly clarified owner requirement', seen[-1])

    def test_changed_read_only_model_evidence_is_not_replayed(self):
        evidence = self.work / 'retrieved-page'
        evidence.write_text('original evidence')
        self.completed_work(self.c)
        evidence.write_text('new evidence at the same URL')
        c = context(self.work, dataclasses.replace(self.si, attempt=2))
        invoked = []
        cp.model_call(c, ['local/test'], self.work, 'builder-1',
                      lambda: invoked.append(True) or 1, text='deterministic prompt')
        self.assertEqual(invoked, [True])

    def edit(self, c, name, edits, known=True):
        """Run one model call that edits files and settles (or not) like a real route."""
        runs = c.__dict__.setdefault('runs', [])
        def invoke():
            runs.append(name)
            for p, text in edits.items(): (c.work / p).write_text(text)
            receipt = c.work / 'usage-receipts' / f'{name}.json'
            receipt.parent.mkdir(exist_ok=True)
            receipt.write_text(json.dumps({'final_usage_known': known}))
            c.card.setdefault('route_receipts', []).append({'invocation': name, 'outcome': 'done',
                'call_id': f'usage-receipts/{name}.json'})
            return 0
        return cp.model_call(c, ['local/test'], c.work, name, invoke, text=name)

    def attempt(self, n):
        c = context(self.work, dataclasses.replace(self.si, attempt=n))
        c.runs = []
        return c

    def test_receipt_is_not_reused_over_newer_work_in_a_file_it_edited(self):
        (self.work / 'x').write_text('x0')
        first = self.attempt(1)
        self.edit(first, 'a', {'x': 'A1'}, known=False)  # unknown usage: no receipt
        self.edit(first, 'b', {'x': 'B-after-A1'})
        (self.work / 'x').write_text('x0')
        retry = self.attempt(2)
        self.edit(retry, 'a', {'x': 'A2'}, known=False)
        self.edit(retry, 'b', {'x': 'B-after-A2'})
        self.assertEqual(retry.runs, ['a', 'b'])
        self.assertEqual((self.work / 'x').read_text(), 'B-after-A2')

    def test_receipt_is_not_reused_when_a_file_absent_at_its_start_exists_now(self):
        first = self.attempt(1)
        self.edit(first, 'b', {'x': 'B1'})  # x did not exist when b started
        (self.work / 'x').write_text('created by newer work')
        retry = self.attempt(2)
        self.edit(retry, 'b', {'x': 'B2'})
        self.assertEqual((retry.runs, (self.work / 'x').read_text()), (['b'], 'B2'))

    def test_receipt_replays_from_the_state_before_or_after_the_call(self):
        (self.work / 'x').write_text('x0')
        self.edit(self.attempt(1), 'b', {'x': 'B1', 'new': 'created'})
        (self.work / 'x').write_text('x0')  # checkpoint restored the pre-call state
        (self.work / 'new').unlink()
        retry = self.attempt(2)
        self.edit(retry, 'b', {'x': 'never'})
        self.assertEqual((retry.runs, (self.work / 'x').read_text(), (self.work / 'new').read_text()), ([], 'B1', 'created'))
        retry = self.attempt(3)  # restored state already holds the call's output
        self.edit(retry, 'b', {'x': 'never'})
        self.assertEqual((retry.runs, (self.work / 'x').read_text()), ([], 'B1'))

    CHAIN = (('c1', {'x': '1', 'y': 'y1'}), ('c2', {'x': '2', 'z': 'z2'}), ('c3', {'x': '3'}))

    def chain(self, attempt, known=(True, True, True)):
        c = self.attempt(attempt)
        for (name, edits), ok in zip(self.CHAIN, known): self.edit(c, name, edits, ok)
        return c

    def state(self):
        return {n: (self.work / n).read_text() for n in 'xyz' if (self.work / n).exists()}

    def put(self, state):
        for n in 'xyz': (self.work / n).unlink(missing_ok=True)
        for n, text in state.items(): (self.work / n).write_text(text)

    def test_chained_receipts_replay_from_every_restore_point(self):
        states = [{}]
        c = self.attempt(1)
        for name, edits in self.CHAIN:
            self.edit(c, name, edits)
            states.append(self.state())
        for n, state in enumerate(states):
            self.put(state)
            retry = self.attempt(2 + n)
            for name, _ in self.CHAIN: self.edit(retry, name, {'x': 'never'})
            self.assertEqual((n, retry.runs, self.state()), (n, [], states[-1]))

    def test_chain_with_a_missing_last_receipt_overwrites_nothing(self):
        self.chain(1, known=(True, True, False))
        final = self.state()
        retry = self.attempt(2)
        for name, _ in self.CHAIN: self.edit(retry, name, {'x': 'rerun-' + name})
        self.assertEqual((retry.runs, (self.work / 'x').read_text()), (['c1', 'c2', 'c3'], 'rerun-c3'))
        self.assertNotEqual(self.state(), final)

    def test_chain_is_not_replayed_over_a_middle_call_that_reran_differently(self):
        self.chain(1, known=(True, False, True))
        self.put({})
        retry = self.attempt(2)
        self.edit(retry, 'c1', {'x': 'never'})
        self.edit(retry, 'c2', {'x': '2-new', 'z': 'z2'}, known=False)
        self.edit(retry, 'c3', {'x': '3-new'})
        self.assertEqual((retry.runs, (self.work / 'x').read_text()), (['c2', 'c3'], '3-new'))

    def test_partial_chain_is_never_replayed_over_newer_work(self):
        (self.work / 'x').write_text('x0')
        first = self.attempt(1)
        self.edit(first, 'a', {'x': 'A'})
        self.edit(first, 'b', {'x': 'B', 'z': 'zb'})
        (self.work / 'z').write_text('newer z')  # b would no longer replay
        retry = self.attempt(2)
        def fails():
            retry.runs.append('a')
            raise RuntimeError('rerun failed')
        with self.assertRaises(RuntimeError):
            cp.model_call(retry, ['local/test'], self.work, 'a', fails, text='a')
        self.assertEqual((retry.runs, self.state()), (['a'], {'x': 'B', 'z': 'newer z'}))

    def test_freshness_gate_is_rechecked_after_restore(self):
        calls = []
        invoke = lambda: (calls.append(True) or (True, {}))
        cp.gate_call(self.c, 'G2', invoke, 'same-case')
        cp.gate_call(self.c, 'G2', invoke, 'same-case')
        self.assertEqual(len(calls), 2)

    def test_real_scientific_gate_binding_replays_after_encrypted_restore(self):
        import run
        from gate_state import inputs
        from test_durable_worker_step import practice_tree
        si = dataclasses.replace(self.si, step=Step(StepKind.GATES, 1))
        work = practice_tree(self.home / 'initial-gate', si.case_id)
        c = run.context_for_step(si, work)
        self.worker.bind_checkpoint(si, c, AgeSealer(), self.key, run)
        binding = {'science': inputs(c, 'G1', run.BENCH), 'ruling': None}
        expected = cp.gate_call(c, 'G1', lambda: (True, {'verified': True}), binding)
        cp.checkpoint(c)
        ref = self.worker.read_checkpoint(si.idempotency_key)
        ciphertext = (self.worker.paths(si.idempotency_key)['out'] / blob_name(ref)).read_bytes()
        fresh = self.home / 'replacement-gate' / si.case_id
        restore(AgeSealer().open(self.key, ref, ciphertext), fresh)
        retry = run.context_for_step(dataclasses.replace(si, attempt=2, snapshot=ref), fresh)
        actual = cp.gate_call(retry, 'G1', lambda: self.fail('completed scientific gate repeated'),
                              {'science': inputs(retry, 'G1', run.BENCH), 'ruling': None})
        self.assertEqual(actual, expected)
        changed = {'science': inputs(retry, 'G1', run.BENCH), 'ruling': 'changed owner requirement'}
        invoked = []
        cp.gate_call(retry, 'G1', lambda: (invoked.append(True) or (False, {})), changed)
        self.assertEqual(invoked, [True])

    @unittest.skipUnless(hasattr(os, 'fork'), 'requires POSIX process control; also runs on Linux')
    def test_sigkill_then_restore_on_fresh_worker(self):
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(read_fd)
            try:
                self.completed_work(self.c)
                os.write(write_fd, b'1')
                while True: signal.pause()
            finally:
                os._exit(1)
        os.close(write_fd)
        try:
            self.assertTrue(select.select([read_fd], [], [], 30)[0], 'checkpoint did not commit')
            self.assertEqual(os.read(read_fd, 1), b'1')
            with patch.object(self.worker, 'processes', return_value={pid}):
                self.assertIsNotNone(self.worker.poll({'key': self.si.idempotency_key}).checkpoint)
        finally:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
            os.close(read_fd)
        self.recover()


if __name__ == "__main__":
    unittest.main()
