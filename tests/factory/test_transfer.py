"""Offline Boat tests: never use a provider or decrypt an archive."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import importlib.util
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('transfer', (Path(__file__).resolve().parents[2] / "factory" / 'transfer.py'))
transfer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transfer)


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vm = self.root / 'vm'
        (self.vm / 'sealed').mkdir(parents=True)
        self.dest = self.root / 'dest'
        self.dest.mkdir()
        self.name = 'case-synthetic.tar.gz.age'
        self.data = b'encrypted synthetic bytes only' * 4
        (self.vm / 'sealed' / self.name).write_bytes(self.data)
        self.fake = self.root / 'fake-transport'
        self.fake.write_text('''#!/usr/bin/env python3
import os,pathlib,signal,subprocess,sys
assert sys.argv[1:3]==['ssh','synthetic']
command=sys.argv[3]; home=pathlib.Path(os.environ['MOCK_HOME'])
if 'f.seek(' in command:
 with (home/'offsets').open('a') as f: f.write(command+'\\n')
 flag=home/'fail'
 if flag.exists():
  mode=flag.read_text()
  if mode=='once': flag.unlink()
  if mode in ('once','always'):
   sys.stdout.buffer.write(b'partial');sys.stdout.flush()
   # Only this event moves boat-call's deadline clock; the real owner must kill us.
   clock=pathlib.Path(os.environ['FAKE_COMMAND_CLOCK']);pending=clock.with_suffix('.tmp')
   pending.write_text(str(float(os.environ['BOAT_COMMAND_TIMEOUT_SECONDS'])+1));pending.replace(clock)
   signal.pause()
  if mode=='corrupt': sys.stdout.buffer.write(b'X'*8);sys.exit(0)
  if mode=='mutate':
   flag.unlink();p=home/'sealed'/'case-synthetic.tar.gz.age';p.write_bytes(b'Z'*p.stat().st_size)
env={**os.environ,'HOME':str(home)}
sys.exit(subprocess.run(['/bin/sh','-c',command],env=env).returncode)
''')
        self.fake.chmod(0o755)
        # Freeze the copied boat-call's deadline clock (as in test-launch-guards), so a
        # loaded host's slow interpreter start-up never times out a call; real owner otherwise.
        repo = Path(__file__).resolve().parents[2]
        (self.root / 'bin').mkdir()
        for source in (repo / 'bin/boat-call', repo / 'bin/processes.py', repo / 'tests/bench/launch_guard_clock.py'):
            shutil.copy2(source, self.root / 'bin' / source.name)
        call = self.root / 'bin/boat-call'
        text = call.read_text()
        self.assertEqual(text.count('import processes\n'), 1, 'boat-call clock seam moved')
        call.write_text(text.replace('import processes\n',
            'import processes\nimport launch_guard_clock\nlaunch_guard_clock.install(processes)\n'))
        call_patch = patch.object(transfer, 'CALL', call)
        call_patch.start()
        self.addCleanup(call_patch.stop)
        self.env = patch.dict(os.environ, {'BOAT_CMD': str(self.fake), 'MOCK_HOME': str(self.vm),
                                           'BOAT_COMMAND_TIMEOUT_SECONDS': '2', 'FAKE_STATE': str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def collect(self, retries=2):
        transfer.collect('synthetic', self.name, self.dest, chunk_bytes=8, retries=retries)

    def test_timeout_partial_retries_without_promoting_short_bytes(self):
        (self.vm / 'fail').write_text('once')
        self.collect()
        self.assertEqual((self.dest / self.name).read_bytes(), self.data)
        self.assertIn('f.seek(0)', (self.vm / 'offsets').read_text())

    def test_retry_resumes_verified_chunks_and_preserves_previous_archive(self):
        original_remote = transfer.remote
        calls = 0
        def interrupt(worker, code):
            nonlocal calls
            if 'f.seek(' in code:
                calls += 1
                if calls >= 3:
                    raise subprocess.CalledProcessError(124, 'synthetic timeout')
            return original_remote(worker, code)
        (self.dest / self.name).write_bytes(b'previous good ciphertext')
        with patch.object(transfer, 'remote', interrupt):
            with self.assertRaises(subprocess.CalledProcessError): self.collect()
        self.assertEqual((self.dest / self.name).read_bytes(), b'previous good ciphertext')
        self.assertEqual(next(self.dest.glob('*.part')).stat().st_size, 16)
        (self.vm / 'offsets').write_text('')
        self.collect()
        offsets = (self.vm / 'offsets').read_text()
        self.assertIn('f.seek(16)', offsets)
        self.assertNotIn('f.seek(0)', offsets)
        self.assertEqual((self.dest / self.name).read_bytes(), self.data)

    def test_corruption_or_mutation_never_replaces_good_archive(self):
        for mode in ('corrupt', 'mutate'):
            with self.subTest(mode=mode):
                (self.vm / 'sealed' / self.name).write_bytes(self.data)
                (self.dest / self.name).write_bytes(b'previous good ciphertext')
                (self.vm / 'fail').write_text(mode)
                with self.assertRaises(ValueError): self.collect()
                self.assertEqual((self.dest / self.name).read_bytes(), b'previous good ciphertext')
                self.assertEqual(list(self.dest.glob('*.part')), [])

    def test_uncertain_pause_retains_worker_even_when_archive_arrives(self):
        progress = self.vm / 'sealed/case-synthetic.progress.json'
        progress.write_text('{"schema":1,"stages":{}}')
        host = self.root / 'host'
        (host / 'factory').mkdir(parents=True)
        (host / 'bin').mkdir()
        for name in ('collect.sh', 'collection.py', 'transfer.py'):
            shutil.copy((Path(__file__).resolve().parents[2] / "factory" / name), host / 'factory' / name)
        boat = host / 'bin/boat-call'
        boat.write_text("#!/usr/bin/env python3\nimport os,subprocess,sys\n"
                        "command=sys.argv[3]\n"
                        "if command.startswith('python3 -c '): assert os.environ['BOAT_COMMAND_TIMEOUT_SECONDS']=='2', 'pause timeout leaked into transfer'\n"
                        "if command.startswith('if [ ! -f ~/sealed/DONE ]'): sys.exit(int(os.environ.get('MOCK_PAUSE_STATUS','124')))\n"
                        "sys.exit(subprocess.run(['/bin/sh','-c',command],env={**os.environ,'HOME':os.environ['MOCK_HOME']}).returncode)\n")
        boat.chmod(0o755)
        result = subprocess.run(['/bin/sh', str(host / 'factory/collect.sh'), 'synthetic'],
                                capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual((host / 'sealed' / self.name).read_bytes(), self.data)
        self.assertEqual((host / 'sealed' / progress.name).read_bytes(), progress.read_bytes())
        # A runner that already died may leave an older valid archive plus newer work.
        case = self.vm / 'work/case-synthetic/case'
        case.mkdir(parents=True)
        (case / 'new-work').write_text('synthetic state after the old checkpoint')
        result = subprocess.run(['/bin/sh', str(host / 'factory/collect.sh'), 'synthetic'],
                                capture_output=True, timeout=60,
                                env={**os.environ, 'MOCK_PAUSE_STATUS': '0'})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(b'without a completed seal', result.stderr)

    def test_already_verified_result_needs_no_chunks(self):
        (self.dest / self.name).write_bytes(self.data)
        self.collect()
        self.assertFalse((self.vm / 'offsets').exists())


if __name__ == '__main__': unittest.main()
