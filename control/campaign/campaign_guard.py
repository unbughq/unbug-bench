"""One guard pass for a bounded campaign. All decisions live in durable/guard.py."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys

root = Path(os.environ.get('UNBUG_CAMPAIGN_ROOT', Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'factory'))
from durable.guard import CHECKPOINT_GRACE_S, CheckFailed, Guard, webhook
from durable.workers import BoatCli, BoatPool, ReleaseStore

SERVICE = 'unbug-durable-case-campaign.service'
request = json.loads((root / 'campaign-request.json').read_text())
config = json.loads((root / 'config.json').read_text())
state = Path(config['state_dir'])
cli = BoatCli(env={**os.environ, 'HOME': '/home/user', 'XDG_CONFIG_HOME': '/home/user/.config',
                   'BOAT_CMD': '/usr/local/bin/boat'})
pool = BoatPool(state / 'pool', ReleaseStore(state / 'releases'), config['pool_id'], boat=cli)


def rpc(op):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(15)
        client.connect(str(state / 'operator.sock'))
        client.sendall(json.dumps({'op': op, 'batch': request['batch_id']}).encode() + b'\n')
        with client.makefile('rb') as stream:
            reply = json.loads(stream.readline(1024 * 1024))
    if not reply.get('ok'):
        raise CheckFailed('rpc_refused', reply.get('error', ''))
    return reply['result']


class Service:
    def state(self):
        done = subprocess.run(['systemctl', 'show', SERVICE, '--timestamp=unix', '-p', 'ActiveState',
                               '-p', 'ActiveEnterTimestamp'], capture_output=True, text=True, timeout=10, check=True)
        values = dict(line.split('=', 1) for line in done.stdout.splitlines() if '=' in line)
        entered = values.get('ActiveEnterTimestamp', '').lstrip('@')
        try:
            ready = (state / 'operator.sock').stat().st_mtime
        except OSError:
            ready = None
        return values.get('ActiveState', 'unknown'), float(entered) if entered else None, ready

    def stop(self):
        subprocess.run(['systemctl', 'stop', SERVICE], capture_output=True, timeout=150, check=True)


def count():
    marker = state / 'campaign-create-count.json'
    return json.loads(marker.read_text()) if marker.exists() else 0


def router():
    """Real spend and the ceiling, in dollars. Read-only: the guard never writes the router's books."""
    db = sqlite3.connect(f"file:{os.environ.get('UNBUG_ROUTER_DB', '/home/user/.unbug-control/router/factory.sqlite3')}?mode=ro", uri=True)
    try:
        spent = db.execute('SELECT COALESCE(SUM(charge), 0) FROM paid_requests').fetchone()[0]
        ceiling = db.execute('SELECT ceiling FROM paid_account').fetchone()[0]
    finally:
        db.close()
    return spent / 1e9, ceiling / 1e9


url = os.environ.get('UNBUG_ALERT_WEBHOOK')
Guard(request, state / 'guard', boat=cli.probe, rpc=rpc, service=Service(),
      ours=lambda row: pool._live(row) and pool._ours(row) is not None, count=count, delete=pool._delete_raw, router=router,
      checkpoint_grace_s=float(os.environ.get('UNBUG_CHECKPOINT_GRACE_S', CHECKPOINT_GRACE_S)),
      notify=webhook(url) if url else None).run(cleanup='--cleanup' in sys.argv)
