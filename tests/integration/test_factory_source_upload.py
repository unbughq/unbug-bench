"""Exercise the launcher's public upload block with local SSH and broken SCP."""
import os
import datetime
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class SourceUploadTests(unittest.TestCase):
    def run_upload(self, mode):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            payload = home / 'public.txt'
            payload.write_text('synthetic public source\n')
            bundle = home / 'bundle.tgz'
            with tarfile.open(bundle, 'w:gz') as archive:
                archive.add(payload, arcname=payload.name)
            payload.unlink()
            fake = home / 'fake-boat'
            fake.write_text('''#!/usr/bin/env python3
import os, subprocess, sys
if sys.argv[1] == 'scp':
    sys.exit('scp: Connection closed')
assert sys.argv[1:3] == ['ssh', 'synthetic-worker']
data = sys.stdin.buffer.read()
if os.environ['UPLOAD_MODE'] == 'truncated': data = data[:len(data)//2]
sys.exit(subprocess.run(['/bin/sh', '-c', sys.argv[3]], input=data).returncode)
''')
            fake.chmod(0o755)
            launch = (ROOT / 'factory/launch.sh').read_text()
            start = launch.index('  if [ -n "$qualified_release" ]; then qualified_readiness; fi\n')
            start = launch.index('\n', start) + 1
            end = launch.index('  if [ -n "$qualified_release" ]; then\n', start)
            script = 'set -eu\nboat() { "$CALL" "$@"; }\n' + launch[start:end]
            proc = subprocess.run(['/bin/sh', '-c', script], capture_output=True, text=True,
                timeout=5, env={**os.environ, 'HOME':str(home), 'bundle':str(bundle),
                    'id':'synthetic-worker', 'CALL':str(ROOT / 'bin/boat-call'),
                    'BOAT_CMD':str(fake), 'UPLOAD_MODE':mode,
                    'BOAT_COMMAND_TIMEOUT_SECONDS':'2'})
            return proc, payload.exists()

    def test_public_upload_works_when_scp_is_closed(self):
        proc, unpacked = self.run_upload('complete')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(unpacked)

    def test_truncated_upload_cannot_be_unpacked(self):
        proc, unpacked = self.run_upload('truncated')
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(unpacked)
        self.assertIn('checksum', proc.stderr)

    def test_existing_readiness_fixture_streams_real_bundle(self):
        spec = importlib.util.spec_from_file_location('deployment_fixture',
            ROOT / 'tests/integration/test_qualified_deployment.py')
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            payload = home / 'public.txt'
            payload.write_text('synthetic public source\n')
            with tarfile.open(home / 'factory.tgz', 'w:gz') as archive:
                archive.add(payload, arcname=payload.name)
            payload.unlink()
            release = home / 'qualified-release'
            release.mkdir()
            (release / 'deploy.py').write_text(
                'from pathlib import Path\n'
                'assert Path.home().joinpath("public.txt").read_text() == "synthetic public source\\n"\n'
                'print(\'{"source_files_verified":1}\')\n')
            # The archived release pin mismatch is independent of this fixture;
            # this synthetic install checks upload/order without changing its pins.
            case = fixture.DeploymentTests()
            case.home = home
            value = dict(id='fixture', type='default', ttlSeconds=1800,
                archiveAfter=(datetime.datetime.now(datetime.timezone.utc) +
                    datetime.timedelta(seconds=1800)).isoformat(),
                holdsCreatorLogins=False, monitoring=False, snapshots=False,
                state='idle', health='ok', error=None, setupError=None,
                setupStatus=None, degradedSince=None, hydrated=True, hydration=None)
            pending = {**value, 'hydrated':False, 'hydration':{
                'phase':'folding', 'entriesDone':4, 'entriesTotal':None, 'percent':None}}
            proc = case.readiness_boundary(value, sequence=[pending, value])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(payload.read_text(), 'synthetic public source\n')
            self.assertEqual(json.loads((home / 'fixture.source-install.json').read_text()),
                             {'source_files_verified':1})
            self.assertTrue((home / 'credentials-delivered').exists())
            self.assertEqual(json.loads((home / 'public-spend-fixture.readiness.json').read_text())['attempts'], 2)


if __name__ == '__main__': unittest.main()
