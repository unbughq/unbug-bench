"""Offline transport tests; privileged and model execution are the only fakes."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
from budget import BudgetError
from carry_over import digest
import diagnosis
import diagnosis_task as task
from durable import diagnosis_invocation as invocation

REAL_RUN = subprocess.run


class InvocationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.c = SimpleNamespace(case_id='case-invocation', work=self.home / 'work/case-invocation')
        self.c.work.mkdir(parents=True)
        self.inputs = self.home / 'immutable inputs'
        (self.inputs / 'case').mkdir(parents=True)
        (self.inputs / 'case/answer.py').write_bytes(b'private evidence')
        self.output = self.home / 'private output'
        self.events = []
        self.raw = b'{"private": "report"}'
        self.error = None
        self.mutate = lambda operation, value: value
        self.runner = SimpleNamespace(__file__='/installed/release/factory/run.py',
            make_pilots=self.pilots, dispose_diagnosis_pilot=self.dispose, opencode=self.model)
        self.addCleanup(patch.stopall)
        patch.object(invocation.subprocess, 'run', side_effect=self.helper).start()

    def pilots(self, c, identities, concurrent, *, diagnosis):
        self.assertIs(c, self.c)
        self.assertEqual(identities, [('pilot', None)])
        self.assertIs(concurrent, True)
        self.assertIs(diagnosis, True)
        self.events.append('pilot')

    def dispose(self, c):
        self.events.append('dispose')

    def helper(self, command, **kwargs):
        self.assertEqual(command[:5], ['sudo', '--', 'python3', '-I', '-B'])
        self.assertEqual(command[5], '/installed/release/factory/diagnosis_task.py')
        operation, case, identity = command[6:]
        task.identities(case, identity)
        self.identity = identity
        self.assertEqual(kwargs, dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120))
        self.events.append(operation)
        source = self.c.work / 'diagnosis' / identity
        manifest = json.loads((source / 'input.json').read_text())
        self.assertEqual(manifest, dict(case_id=case, exhaustion_id=identity,
            files=diagnosis._input_inventory(self.inputs)))
        self.assertEqual(json.loads((source / 'attempts.json').read_text()),
            {'attempts': [{'kind': 'judgment', 'status': 'pending'}]})
        self.assertEqual(diagnosis._input_inventory(source / 'inputs'), manifest['files'])
        raw = self.raw if operation == 'collect' else b''
        value = task._response(data=raw, inputs=digest(manifest['files'])
            if operation in ('prepare', 'collect') else None)
        value = self.mutate(operation, value)
        wire = value if isinstance(value, (bytes, SimpleNamespace)) else json.dumps(value).encode()
        if isinstance(value, SimpleNamespace): return value
        return SimpleNamespace(returncode=0, stdout=wire, stderr=b'')

    def model(self, c, models, prompt, cwd, name, *, user, before_attempt):
        self.events.append('model')
        self.assertIs(c, self.c)
        self.assertEqual(models, ['openrouter/selected'])
        self.assertEqual(name, 'diagnosis-' + self.identity)
        self.assertEqual(user, 'pilot')
        exposed = task.ROOT / c.case_id / self.identity
        self.assertEqual(cwd, exposed / 'output')
        context = json.loads(prompt.split('Run context (data):\n')[1])
        self.assertEqual(context['inputs'], str(exposed / 'inputs'))
        self.assertEqual(context['output'], str(exposed / 'output/result.json'))
        before_attempt()
        # Represents already-accounted work; errors must not erase its ledger.
        (self.c.work / 'ledger.json').write_text('{"spent": 0.25}')
        if self.error: raise self.error

    def invoke(self):
        prompt = 'Inspect evidence.\nRun context (data):\n' + json.dumps(dict(
            inputs=str(self.inputs), output=str(self.output / 'result.json')))
        return invocation.invoke(self.runner, self.c, model='openrouter/selected',
            prompt=prompt, inputs=self.inputs, output=self.output)

    def assert_clean(self):
        self.assertEqual(list((self.c.work / 'diagnosis').iterdir()), [])
        self.assertEqual(self.events[-2:], ['dispose', 'remove'])

    def test_accounted_invocation_and_private_protocol(self):
        self.assertEqual(self.invoke(), self.raw)
        self.assertEqual(self.events, ['pilot', 'prepare', 'model', 'reset', 'collect', 'dispose', 'remove'])
        self.assert_clean()
        self.assertEqual((self.inputs / 'case/answer.py').read_bytes(), b'private evidence')

    def test_rejects_untrusted_helper_responses(self):
        corruptions = [
            lambda v: {**v, 'schema_version': True},
            lambda v: {**v, 'extra': 1},
            lambda v: {**v, 'status': 'input_invalid'},
            lambda v: {**v, 'status': 'oversized'},
            lambda v: {**v, 'status': 'missing'},
            lambda v: {**v, 'status': 'unsafe'},
            lambda v: {**v, 'inputs_sha256': 'a' * 64},
            lambda v: {**v, 'raw_sha256': 'b' * 64},
            lambda v: {**v, 'raw_base64': '!!'},
            lambda v: {**v, 'raw_base64': 123},
            lambda v: b'private invalid JSON',
            lambda v: b' ' * (task.MAX_RESPONSE + 1),
        ]
        for corrupt in corruptions:
            with self.subTest(corrupt=corrupt):
                self.events.clear()
                self.mutate = lambda op, value: corrupt(value) if op == 'collect' else value
                with self.assertRaises(BudgetError): self.invoke()
                self.assert_clean()

    def test_collect_status_is_its_own_stop_with_the_helper_said_as_cause(self):
        """f46dac-5 diagnosis attempt 5 (14 November): every non-ok collect read as
        diagnosis_result_invalid, and the helper's stderr went to /dev/null."""
        for status, reason in (('missing', 'diagnosis_result_missing'), ('oversized', 'diagnosis_result_oversized'),
                               ('unsafe', 'diagnosis_result_unsafe'), ('input_invalid', 'diagnosis_input_invalid')):
            with self.subTest(status=status):
                self.events.clear()
                self.mutate = lambda op, value: {**value, 'status': status} if op == 'collect' else value
                with self.assertRaisesRegex(BudgetError, '^' + reason + '$') as caught:
                    self.invoke()
                self.assertIn('status=' + status, str(caught.exception.__cause__))
                self.assert_clean()
        self.events.clear()
        failed = SimpleNamespace(returncode=1, stdout=b'', stderr=b'Traceback: /case/secret.py line 3\n'
                                 b'diagnosis task operation failed: PermissionError\n')
        self.mutate = lambda op, value: failed if op == 'collect' else value
        with self.assertRaisesRegex(BudgetError, '^diagnosis_result_invalid$') as caught:
            self.invoke()
        cause = str(caught.exception.__cause__)
        self.assertIn('returncode=1', cause)
        self.assertIn('diagnosis task operation failed: PermissionError', cause)
        self.assertNotIn('secret', cause)  # only the helper's fixed lines pass, never raw stderr
        self.assert_clean()

    def test_rejects_oversized_bytes_even_with_valid_digest(self):
        self.raw = b'x' * (task.MAX_RESULT + 1)
        with self.assertRaisesRegex(BudgetError, '^diagnosis_result_invalid$'): self.invoke()
        self.assert_clean()

    def test_maximum_result_is_accepted(self):
        self.raw = b'x' * task.MAX_RESULT
        self.assertEqual(self.invoke(), self.raw)
        self.assert_clean()

    def test_cleanup_after_paid_failure_preserves_error_and_ledger(self):
        self.error = BudgetError('provider_limit:openrouter/selected')
        with self.assertRaises(BudgetError) as caught: self.invoke()
        self.assertIs(caught.exception, self.error)
        self.assertEqual(json.loads((self.c.work / 'ledger.json').read_text()), {'spent': .25})
        self.assert_clean()

    def test_partial_preparation_is_removed(self):
        self.mutate = lambda op, value: b'invalid' if op == 'prepare' else value
        with self.assertRaises(BudgetError): self.invoke()
        self.assertEqual(self.events, ['pilot', 'prepare', 'dispose', 'remove'])
        self.assert_clean()

    def test_cleanup_failures_are_fixed_and_both_cleanups_run(self):
        for broken in ('dispose', 'remove'):
            with self.subTest(broken=broken):
                self.events.clear()
                self.error = RuntimeError('private paid failure')
                if broken == 'dispose':
                    def dispose(c):
                        self.events.append('dispose')
                        raise RuntimeError('private cleanup')
                    self.runner.dispose_diagnosis_pilot = dispose
                else:
                    self.runner.dispose_diagnosis_pilot = self.dispose
                    self.mutate = lambda op, value: b'private cleanup' if op == 'remove' else value
                # The first error stays the cause and is marked; the cleanup failure no longer replaces it.
                with self.assertRaises(RuntimeError) as caught: self.invoke()
                self.assertIs(caught.exception, self.error)
                self.assertIs(caught.exception.diagnosis_cleanup_failed, True)
                self.assert_clean()

    def test_cleanup_failure_without_an_earlier_error_is_its_own_stop(self):
        self.error = None
        self.mutate = lambda op, value: b'private cleanup' if op == 'remove' else value
        # The stop names the failed stage and its error's class (1bb2ad-2, f46dac-2r2).
        with self.assertRaisesRegex(BudgetError, '^diagnosis_cleanup_failed:task_remove:BudgetError$'): self.invoke()

    def test_a_failed_pilot_disposal_names_its_stage(self):
        self.error = None
        def dispose(c):
            self.events.append('dispose')
            failure = RuntimeError('pilot disposal failed')
            failure.cleanup_stage, failure.cleanup_error = 'pilot_userdel', 'RuntimeError'
            raise failure
        self.runner.dispose_diagnosis_pilot = dispose
        self.c.card = {}
        with self.assertRaisesRegex(BudgetError, '^diagnosis_cleanup_failed:pilot_userdel:RuntimeError$'): self.invoke()
        self.assertEqual(self.c.card['cleanup_errors'], [{'stage': 'diagnosis_pilot_userdel', 'error': 'RuntimeError'}])
        self.assert_clean()

    def test_a_read_only_copied_directory_is_still_removed(self):
        from durable.diagnosis_invocation import _remove_tree
        tree = self.home / 'read-only-copy'
        (tree / 'inputs/work/attacks').mkdir(parents=True)
        (tree / 'inputs/work/attacks/round-1.json').write_text('{}')
        for path in (tree / 'inputs/work/attacks', tree / 'inputs/work'): path.chmod(0o500)
        _remove_tree(tree)
        self.assertFalse(tree.exists())

    def test_partial_pilot_creation_still_disposes(self):
        def fail(*args, **kwargs):
            raise RuntimeError('pilot creation failed')
        self.runner.make_pilots = fail
        with self.assertRaises(RuntimeError): self.invoke()
        self.assertEqual(self.events, ['dispose'])
        self.assertEqual(list((self.c.work / 'diagnosis').iterdir()), [])

    def test_linked_inputs_rejected_before_model_work(self):
        (self.inputs / 'link').symlink_to(self.inputs / 'case/answer.py')
        with self.assertRaises(ValueError): self.invoke()
        self.assertEqual(self.events, ['dispose'])


def linux_pilot():
    if not sys.platform.startswith('linux') or os.geteuid() != 0: return False
    try: pwd.getpwnam('pilot')
    except KeyError: return False
    return True


@unittest.skipUnless(linux_pilot(), 'requires Linux root and a provisioned idle pilot UID')
class LinuxHelperQualification(unittest.TestCase):
    """Use real root ownership, inventory validation, and pilot filesystem access."""
    pilots = InvocationTests.pilots
    dispose = InvocationTests.dispose
    invoke = InvocationTests.invoke

    def setUp(self):
        InvocationTests.setUp(self)
        self.change_inputs = False
        self.home.chmod(0o755)
        self.c.work.chmod(0o700)
        self.protected = self.home / 'protected'
        patch.object(task, 'ROOT', self.protected).start()

    def helper(self, command, **kwargs):
        if command[0] != 'sudo': return REAL_RUN(command, **kwargs)
        operation, case, identity = command[6:]
        self.identity = identity
        self.events.append(operation)
        if operation == 'collect' and self.change_inputs:
            (self.protected / case / identity / 'inputs/case/answer.py').write_bytes(b'changed by root')
        value = task.operate(operation, case, identity, runner_home=self.home, root=self.protected)
        return SimpleNamespace(returncode=0, stdout=json.dumps(value).encode())

    def model(self, c, models, prompt, cwd, name, *, user, before_attempt):
        before_attempt()
        pilot = pwd.getpwnam('pilot')
        code = """
import pathlib, sys
source = pathlib.Path(sys.argv[1])
try: source.write_bytes(b'changed')
except PermissionError: pass
else: raise AssertionError('pilot changed protected inputs')
pathlib.Path(sys.argv[2]).write_bytes(sys.argv[3].encode())
"""
        REAL_RUN([sys.executable, '-c', code, str(cwd.parent / 'inputs/case/answer.py'),
                  str(cwd / 'result.json'), self.raw.decode()], check=True,
                 user=pilot.pw_uid, group=pilot.pw_gid, extra_groups=[])

    def test_real_helper(self):
        self.assertEqual(self.invoke(), self.raw)
        self.assertFalse((self.protected / self.c.case_id / self.identity).exists())

    def test_real_helper_rejects_changed_inventory(self):
        self.change_inputs = True
        with self.assertRaises(BudgetError): self.invoke()
        self.assertFalse((self.protected / self.c.case_id / self.identity).exists())

    def test_real_helper_rejects_oversized_result(self):
        self.raw = b'x' * (task.MAX_RESULT + 1)
        with self.assertRaises(BudgetError): self.invoke()
        self.assertFalse((self.protected / self.c.case_id / self.identity).exists())


if __name__ == '__main__': unittest.main()
