"""Exercise scheduled backup transitions with local systemctl/runuser transports."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TRANSPORT = '''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name
op=sys.argv[1] if name=='systemctl' else ('backup' if '--resume-after' in sys.argv else sys.argv[-1])
with open(os.environ['BACKUP_TEST_LOG'],'a') as f:f.write(json.dumps(op)+'\\n')
fence=pathlib.Path(os.environ['BACKUP_TEST_FENCE'])
if op=='is-active':sys.exit(0 if os.environ['BACKUP_TEST_ACTIVE']=='1' else 3)
if op=='stop' and os.environ.get('BACKUP_TEST_RACE')=='1':fence.write_text('operator handover')
if op=='backup':
 if fence.exists():sys.exit(1)
 # The real backup command removes only its own fence under the runtime lock.
 sys.exit(int(os.environ['BACKUP_TEST_FAIL']))
if op=='resume':fence.unlink()
'''


class ScheduledBackup(unittest.TestCase):
    def test_pause_snapshot_resume_and_failures(self):
        for active, fail, preexisting, race in ((True, False, False, False), (True, True, False, False),
                (False, False, False, False), (True, False, True, False), (True, False, False, True)):
            with self.subTest(active=active, fail=fail, preexisting=preexisting), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state = root / 'state'; state.mkdir()
                commands = root / 'commands'; commands.mkdir()
                for name in ('systemctl', 'runuser'):
                    path = commands / name
                    path.write_text(TRANSPORT); path.chmod(0o755)
                script = root / 'backup.sh'
                script.write_text((ROOT / 'control/durable-backup.sh').read_text()
                    .replace('PATH=/usr/sbin:/usr/bin:/bin', 'PATH='+str(commands)+':/usr/bin:/bin')
                    .replace('state=/home/user/.unbug-durable', 'state='+str(state)))
                fence = state / 'cold-backup.json'
                if preexisting:fence.write_text('operator handover')
                log = root / 'log'
                done = subprocess.run(['sh', str(script)], env={**os.environ,
                    'BACKUP_TEST_LOG': str(log), 'BACKUP_TEST_FENCE': str(fence),
                    'BACKUP_TEST_RACE': str(int(race)), 'BACKUP_TEST_ACTIVE': str(int(active)), 'BACKUP_TEST_FAIL': str(int(fail))},
                    capture_output=True)
                calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
                if preexisting:
                    self.assertEqual(calls, [])
                    self.assertEqual(fence.read_text(), 'operator handover')
                    self.assertNotEqual(done.returncode, 0)
                elif race:
                    self.assertEqual(calls, ['is-active', 'stop', 'backup'])
                    self.assertEqual(fence.read_text(), 'operator handover')
                    self.assertNotEqual(done.returncode, 0)
                else:
                    self.assertEqual(calls, ['is-active'] + (['stop'] if active else []) +
                        ['backup'] + (['start'] if active else []))
                    self.assertEqual(done.returncode, int(fail), done.stderr)
                    self.assertFalse(fence.exists())


if __name__ == '__main__':
    unittest.main()
