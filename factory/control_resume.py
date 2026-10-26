#!/usr/bin/env python3
"""Own a persistent launch lock, then exec the existing shell controller."""
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

# Public routing/account labels only. Credentials and identity stay on stdin/in memory.
ENVIRONMENT = ('UNBUG_CLOUD', 'BOAT_CMD', 'BOAT_TYPE', 'HCLOUD_PLACES',
               'UNBUG_SECRETS_FILE', 'FACTORY_SECRETS', 'OPENCODE_SECRET_NAME',
               'CLAUDE_SECRET_NAME', 'FACTORY_TTL_CONTINUATION', 'FACTORY_ACCOUNT_POLICY', 'FACTORY_ACCOUNT_STATE')


def main():
    os.umask(0o077)
    launches = Path(os.environ.get('UNBUG_CONTROL_HOME', str(Path.home() / '.unbug-control'))).expanduser().resolve() / 'launches'
    launches.mkdir(parents=True, exist_ok=True, mode=0o700)
    argv = sys.argv[1:]
    launcher = Path(__file__).with_name('launch.sh')
    if argv == ['--resume-launches']:
        # Read the same stdin identity once, share it only through child stdin pipes.
        identity = sys.stdin.buffer.read()
        children = []
        for state in sorted(launches.iterdir()):
            if not (state / 'monitor.sh').is_file() or (state / 'complete').exists(): continue
            with (state / 'controller.lock').open('a+') as lock:
                try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError: continue
                fcntl.flock(lock, fcntl.LOCK_UN)
            child = subprocess.Popen(['sh', str(launcher), '--resume-launch', state.name], stdin=subprocess.PIPE)
            try:
                child.stdin.write(identity); child.stdin.close()
            except BrokenPipeError: pass  # Another owner may have claimed it since the scan.
            children.append(child)
        return max((child.wait() for child in children), default=0)
    resume = argv[:1] == ['--resume-launch']
    if resume:
        if len(argv) != 2 or not re.fullmatch(r'[A-Za-z0-9_-]+', argv[1]):
            sys.exit('usage: launch.sh --resume-launch <launch-id>')
        state = launches / argv[1]
        if not (state / 'launch.json').is_file(): sys.exit('unknown launch')
    else:
        launch_id = os.environ.pop('UNBUG_LAUNCH_ID', None) or uuid.uuid4().hex
        if not re.fullmatch(r'[0-9a-f]{32}', launch_id): sys.exit('invalid reserved launch id')
        state = launches / launch_id
        state.mkdir(mode=0o700)
    lock = (state / 'controller.lock').open('a+')
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: sys.exit('launch already owned by a live controller')
    started = subprocess.check_output(['ps', '-p', str(os.getpid()), '-o', 'lstart='], text=True).strip()
    lock.seek(0); lock.truncate()
    json.dump(dict(pid=os.getpid(), started=started), lock); lock.flush(); os.fsync(lock.fileno())
    if (state / 'complete').exists(): return 0
    if resume:
        job = json.loads((state / 'launch.json').read_text())
        argv = job['argv']
        for name in ENVIRONMENT:
            os.environ.pop(name, None)
        os.environ.update(job['environment'])
        os.environ['UNBUG_RESUME_LAUNCH'] = '1'
        if not (state / 'monitor.sh').is_file(): sys.exit('launch initialization incomplete; reconcile manually')
    else:
        with (state / 'launch.json').open('w') as file:
            json.dump(dict(argv=argv, environment={k:os.environ[k] for k in ENVIRONMENT if k in os.environ}), file)
            file.flush(); os.fsync(file.fileno())
        os.environ.pop('UNBUG_RESUME_LAUNCH', None)
    os.set_inheritable(lock.fileno(), True)
    os.environ.update(UNBUG_CONTROL_PID=str(os.getpid()), UNBUG_LAUNCH_STATE=str(state))
    print('launch ' + state.name + ': ' + str(state), file=sys.stderr)
    os.execv('/bin/sh', ['sh', str(launcher), *argv])


if __name__ == '__main__': sys.exit(main())
