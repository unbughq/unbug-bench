"""Synthetic terminal failures preserve checkpoints and signal DONE to the deleting launcher."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

HARNESS = r'''
import json, pathlib, sys
from unittest.mock import patch
import run, worker_release
root = pathlib.Path(sys.argv[1])
mode = sys.argv[2]
case = root / 'work/case-test'
(case / 'case').mkdir(parents=True)
(case / 'logs').mkdir()
(case / 'case/preserved').write_text('synthetic fixture')
(case / 'case/preserved').chmod(0o600)
(case / 'case').chmod(0o700)
(case / 'scorecard.json').write_text(json.dumps({'factory_slots_prepared': 3}))
run.HOME, run.SEALED = root, root / 'sealed'
run.GATES = ['G1']
if mode == 'restore':
    (case / 'continuation-budget.json').write_text(json.dumps({'cost': 1.25, 'calls': 300, 'events': [], 'terminal_stop': 'total_call_limit'}))
if mode == 'defaults':
    (root / 'sealed').mkdir()
    (root / 'sealed/DONE').write_text('stale')
def gate(c):
    if mode == 'gate': raise OSError('synthetic operational failure')
    if mode == 'rejected': return False, {'verified': {'rules': 0}}
    return True, {}
def seal(c, checkpoint=False):
    if mode == 'seal': raise OSError('synthetic encryption failure')
    (root / 'checkpoint').touch()
def build(c):
    assert (c.case / "preserved").stat().st_mode & 0o044 == 0o044, "in-place resume must repair private source modes"
    assert (root / 'QUALIFIED').exists(), 'selected drivers must qualify before construction'
    assert c.card['driver_qualification'] == {'synthetic': 'qualified'}
    (root / 'BUILT').touch()
    assert not (root / 'sealed/DONE').exists(), 'resume must clear stale DONE'
    if mode == 'defaults':
        assert (c.args.rounds, c.args.pilot_tries, c.args.runs) == (8, 3, 10)
        assert c.args.case_budget == 50
        assert (c.args.max_cost, c.args.max_role_calls, c.args.max_total_calls) == (5, 400, 1000)
        assert c.card['recovery_config']['max_total_calls'] == 1000
        assert c.args.no_progress_minutes == 45 and c.args.max_zero_tokens == 3
        assert c.args.concurrent_roles  # on by default since 2026-10-17
    if mode in ('budget', 'defaults'): raise run.BudgetError('cost_limit')
    if mode == 'restore':
        from budget import run_budgeted
        import os
        run_budgeted([sys.executable, '-c', 'raise AssertionError("must not spawn")'], c.work, os.environ.copy(),
                     c.work / 'transcripts/test.jsonl', c.ledger, 1, containment=False, resume=True)
    if mode in ('limit', 'stall', 'zero'):
        from budget import run_budgeted
        import os
        event = {'type': 'step_finish', 'sessionID': 's', 'part': {'id': 'p', 'messageID': 'p', 'cost': 0,
                 'tokens': {'input': 0, 'output': 0, 'reasoning': 0, 'cache': {'read': 0, 'write': 0}}}}
        if mode == 'limit': code = "print('GoUsageLimitError weekly usage limit', flush=True)"
        elif mode == 'stall': code = ''
        else:
            code = '\n'.join('print(' + repr(__import__('json').dumps({**event, 'part': {**event['part'], 'id': str(i), 'messageID': str(i)}})) + ', flush=True)' for i in range(3))
        code += '\nimport time; time.sleep(60)'
        run_budgeted([sys.executable, '-c', code], c.work, os.environ.copy(), c.work / 'transcripts/test.jsonl',
                     c.ledger, 5, containment=False, progress_timeout=0.2, configured_model='opencode-go/test')
run.g1, run.seal, run.build = gate, seal, build
run.sh = lambda *args, **kwargs: 0
run.bench_manifest = lambda: 'trusted'
run.wipe = lambda c: (root / 'WIPED').touch()
def qualify(models, resolver):
    assert models, 'qualify resolved selected roles'
    assert not (root / 'BUILT').exists(), 'qualification cannot follow construction'
    if mode == 'qualification': raise ValueError('synthetic unsupported selected driver')
    (root / 'QUALIFIED').touch()
    return {'synthetic': 'qualified'}
worker_release.verify_selected_drivers = qualify
with patch.object(sys, 'argv', ['run.py', '--source', 'port', '--resume', 'case-test', '--resume-bench-sha', 'trusted']):
    run.main()
'''

DRY_RUN_HARNESS = r'''
import json, pathlib, subprocess, sys
from unittest.mock import patch
import run, worker_release
root = pathlib.Path(sys.argv[1]); mode = sys.argv[2]
run.HOME, run.SEALED = root, root / 'sealed'
run.SEALED.mkdir()
existing = b'synthetic existing throwaway fixture'
generated = b'synthetic new throwaway fixture'
if mode == 'resume':
    work = root / 'work/case-test'
    (work / 'case').mkdir(parents=True); (work / 'logs').mkdir()
    (work / 'case/case.json').write_text('{}')
    (run.SEALED / 'case-test.throwaway-key.txt').write_bytes(existing)
calls = []
def shell(c, args, **kwargs):
    if args[:2] == ['age-keygen', '-o']:
        assert kwargs.get('check') is True
        path = pathlib.Path(args[-1])
        assert not path.exists(), 'throwaway keys must never be overwritten'
        path.write_bytes(generated); calls.append('generate')
    if args[:2] == ['age-keygen', '-y']:
        assert kwargs.get('capture') is True and kwargs.get('check') is True
        assert pathlib.Path(args[-1]).read_bytes() == (existing if mode == 'resume' else generated)
        calls.append('public-recipient')
        return subprocess.CompletedProcess(args, 0, stdout='age1syntheticpublicfixture\n')
    return 0
def fixture(c):
    assert mode == 'fresh', 'resume must preserve its existing fixture'
    c.case.mkdir(); (c.case / 'case.json').write_text('{}')
def gates(c):
    assert c.recipient == 'age1syntheticpublicfixture'
    assert c.keyfile.read_bytes() == (existing if mode == 'resume' else generated)
    assert calls == (['public-recipient'] if mode == 'resume' else ['generate', 'public-recipient'])
    (root / 'verified').write_text(json.dumps(calls))
    raise run.BudgetError('synthetic-dry-run-stop')
run.sh = shell; run.bench_manifest = lambda: 'trusted'; run.pilot_homes = lambda: []
run.build_fixture = fixture; run.validate_and_repair = gates; run.seal = lambda *a, **kw: None
worker_release.verify_selected_drivers = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('dry runs have no selected model drivers'))
argv = ['run.py', '--dry-run']
if mode == 'resume': argv += ['--resume', 'case-test', '--resume-bench-sha', 'trusted']
with patch.object(sys, 'argv', argv): run.main()
'''


class ResumeTests(unittest.TestCase):
    def test_batch_key_failure_raises_and_dry_run_never_requests_case_key(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from run_artifacts import RunArtifacts
        import r2_upload
        bench = pathlib.Path(__file__).resolve().parents[2]
        saved = json.loads((bench / 'tests/factory/fixtures/c7d405-confirm-timeout-card.json').read_text())
        class BeforeEncryption(BaseException): pass
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run), tempfile.TemporaryDirectory() as tmp:
                home = pathlib.Path(tmp); work = home / saved['case']; work.mkdir()
                artifacts = RunArtifacts(home, bench, home / 'sealed', home / 'absent', (),
                    lambda: [], lambda *a: None, lambda c: 1, lambda c: None)
                c = SimpleNamespace(work=work, case_id=saved['case'], recipient='public-test-recipient',
                    args=SimpleNamespace(dry_run=dry_run), card={**saved, 'batch_release_sha256': 'a' * 64})
                with patch.object(artifacts, 'results_since', return_value=[]), \
                     patch.object(r2_upload, 'case_recipient', side_effect=OSError('unavailable')) as case_key, \
                     patch('run_artifacts.processes.run', side_effect=BeforeEncryption):
                    if dry_run:
                        with self.assertRaises(BeforeEncryption): artifacts.seal(c, checkpoint=True)
                        case_key.assert_not_called()
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'batch checkpoint requires a wrapped case key'):
                            artifacts.seal(c, checkpoint=True)
                        case_key.assert_called_once()
                self.assertFalse(list((home / 'sealed').glob('*.tar.gz.age')))

    def test_gate_results_and_failed_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, '-c', HARNESS, tmp, 'rejected'],
                                    cwd=_TEST_ROOT / "factory", env={**os.environ, 'BENCH': str(_TEST_ROOT)}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            card = json.loads((pathlib.Path(tmp) / 'sealed/case-test.scorecard.json').read_text())
            self.assertEqual(card['gate_results']['G1'], {'verified': {'rules': 0}})
            self.assertEqual(card['failed_detail'], card['gate_results']['G1'])
            self.assertEqual(card['failed_gate'], 'G1')

    def test_operational_and_budget_failures_preserve_work(self):
        for mode in ('gate', 'seal', 'budget', 'limit', 'stall', 'zero', 'restore', 'defaults', 'qualification'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                result = subprocess.run([sys.executable, '-c', HARNESS, tmp, mode],
                                        cwd=_TEST_ROOT / "factory", env={**os.environ, 'BENCH': str(_TEST_ROOT)}, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                root = pathlib.Path(tmp)
                card = json.loads((root / 'sealed/case-test.scorecard.json').read_text())
                self.assertEqual(card['status'], 'stopped')
                cause = {'gate': 'infrastructure_exhausted', 'seal': 'seal_error:OSError', 'budget': 'cost_limit',
                         'limit': 'provider_limit:opencode-go/test', 'stall': 'stalled', 'zero': 'zero_tokens',
                         'restore': 'Budget stopped: total_call_limit', 'defaults': 'cost_limit',
                         'qualification': 'runner_error:ValueError'}[mode]
                self.assertEqual(card['terminal_stop'], cause)
                self.assertEqual(card['resume']['bench_sha'], 'trusted')
                self.assertEqual(card['factory_slots_prepared'], 3, 'an early stop before G3 lost prior cleanup scope')
                if mode == 'restore':
                    self.assertEqual(card['continuation_budget']['cost'], 1.25)
                    self.assertEqual(card['continuation_budget']['calls'], 300)
                    self.assertEqual(card['continuation_budget']['previous_stops'], ['total_call_limit'])
                    self.assertEqual(json.loads((root / 'work/case-test/continuation-budget.json').read_text())['calls'], 300)
                self.assertIn('STOPPED: ' + cause, result.stdout)
                self.assertFalse((root / 'sealed/PAUSED.json').exists())
                self.assertTrue((root / 'work/case-test/case/preserved').exists())
                self.assertFalse((root / 'WIPED').exists())
                self.assertEqual((root / 'sealed/DONE').read_text(), 'case-test\n')
                self.assertEqual((root / 'checkpoint').exists(), mode != 'seal')
                self.assertEqual((root / 'BUILT').exists(), mode != 'qualification')
                self.assertEqual((root / 'QUALIFIED').exists(), mode != 'qualification')

    def test_dry_run_resume_reuses_throwaway_key_and_fresh_run_generates_one(self):
        for mode in ('resume', 'fresh'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                result = subprocess.run([sys.executable, '-c', DRY_RUN_HARNESS, tmp, mode],
                                        cwd=_TEST_ROOT / "factory", env={**os.environ, 'BENCH': str(_TEST_ROOT)}, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                root = pathlib.Path(tmp)
                self.assertTrue((root / 'verified').exists(), result.stdout)
                calls = json.loads((root / 'verified').read_text())
                self.assertEqual(calls, ['public-recipient'] if mode == 'resume' else ['generate', 'public-recipient'])

    def test_checkpoint_replacement_is_atomic(self):
        import argparse, shlex
        from unittest.mock import patch
        import run, r2_upload
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            c = run.Ctx(); c.work = root / 'work'; c.work.mkdir()
            c.case_id = 'case-test'; c.card = {}; c.args = argparse.Namespace(dry_run=False)
            c.recipient = 'synthetic-recipient'
            archive = root / 'case-test.checkpoint.tar.gz.age'
            archive.write_bytes(b'previous encrypted fixture')
            def encrypt(cmd, **kwargs):
                staged = pathlib.Path(shlex.split(cmd)[-1])
                self.assertFalse(staged.exists(), 'checkpoint must use a fresh staging path')
                staged.write_bytes(b'new encrypted fixture')
                return subprocess.CompletedProcess(cmd, 0)
            with patch.object(run, 'SEALED', root), patch.object(run, 'AGENT_STATE', []), \
                 patch.object(run, 'PILOT_HOME', root / 'no-pilot'), patch.object(run.RunArtifacts, 'results_since', return_value=[]), \
                 patch.object(r2_upload, 'case_recipient', return_value=None), \
                 patch.object(r2_upload, 'upload', return_value=None):
                with patch("run_artifacts.processes.run", encrypt): run.seal(c, checkpoint=True)
                self.assertEqual(archive.read_bytes(), b'new encrypted fixture')
                with patch("run_artifacts.processes.run", return_value=subprocess.CompletedProcess([], 1)):
                    with self.assertRaisesRegex(RuntimeError, 'encryption failed'): run.seal(c, checkpoint=True)
                self.assertEqual(archive.read_bytes(), b'new encrypted fixture')


if __name__ == '__main__':
    unittest.main()
