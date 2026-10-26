"""Host-owned clients in the shop network and the HOST's PID namespace.

The client is outside the contestant's PID namespace (no contestant ptrace/kill).
The image has no case files, mounts,
Docker host socket, or private inputs. The contestant cannot replace its client
binaries. PostgreSQL is read over its real database connection; SQLite through
the live service process root, with a read transaction including WAL.
"""
import asyncio
import json
import re
from pathlib import Path
import os
import base64

IMAGE = os.environ.get('UNBUG_PHASE2_READER_IMAGE', 'unbug-phase2-reader:dev')


async def command(*args, data=None):
    process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE if data is not None else None,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(process.communicate(data.encode() if data is not None else None), 30)
    except BaseException:
        process.kill()
        await process.wait()
        raise
    if process.returncode: raise RuntimeError(err.decode())
    return out.decode().strip()


class DockerLiveReader:
    def __init__(self, container, main_pid):
        self.container, self.main_pid = container, main_pid

    @classmethod
    async def create(cls, main):
        main_pid = int(await command('docker', 'inspect', '--format', '{{.State.Pid}}', main))
        if main_pid <= 0: raise ValueError('main is not running')
        container = await command('docker', 'run', '-d', '--rm', '--network', 'container:' + main,
            '--pid', 'host', '--cap-add', 'SYS_PTRACE', '--read-only',
            '--security-opt', 'apparmor=unconfined',
            '--tmpfs', '/var/lib/postgresql/data:rw,noexec,nosuid,size=1m',
            '--tmpfs', '/traffic:rw,noexec,nosuid,size=64m',
            '--entrypoint', 'bash', IMAGE, '-c', 'exec -a unbug-phase2-judge-client sleep infinity')
        return cls(container, main_pid)

    async def python(self, source, data=None):
        return await command('docker', 'exec', *(['-i'] if data is not None else []), self.container,
                             'python3', '-I', '-c', source, data=data)

    async def service(self, name):
        if not re.fullmatch('[a-z][a-z0-9-]*', name): raise ValueError('invalid service')
        # Discovery alone uses the nested engine; clients and verdicts do not.
        source = '''import http.client,json,socket,urllib.parse
def request(path):
 s=socket.socket(socket.AF_UNIX); s.connect('/proc/MAIN_PID/root/run/docker.sock')
 s.sendall(('GET '+path+' HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n').encode())
 response=http.client.HTTPResponse(s); response.begin()
 assert response.status==200
 return json.loads(response.read())
filters={'label':['com.docker.compose.project=unbug-bench','com.docker.compose.service=NAME']}
rows=request('/containers/json?filters='+urllib.parse.quote(json.dumps(filters)))
assert len(rows)==1, rows
print(json.dumps(request('/containers/'+rows[0]['Id']+'/json')))
'''.replace('NAME', name).replace('MAIN_PID', str(self.main_pid))
        return json.loads(await self.python(source))

    async def sql(self, query, *, service='postgres', database='medusa', user='medusa', password='medusa'):
        container = await self.service(service)
        addresses = [n['IPAddress'] for n in container['NetworkSettings']['Networks'].values() if n['IPAddress']]
        if len(addresses) != 1: raise ValueError('ambiguous database network')
        return await command('docker', 'exec', '-e', 'PGPASSWORD=' + password, '-e', 'PGCONNECT_TIMEOUT=3',
            self.container, 'psql', '-XqAt', '-h', addresses[0], '-U', user, '-d', database,
            '-v', 'ON_ERROR_STOP=1', '-c', query)

    async def read_sql(self, query, **connection):
        return json.loads(await self.sql('BEGIN READ ONLY; SET LOCAL search_path=pg_catalog; ' + query + '; COMMIT;', **connection))

    async def orders(self, name):
        rows = await self.sqlite(name, '/data/marketplace.sqlite', 'SELECT id,kit,quantity FROM orders', table='orders')
        if not all(type(i) is int and i > 0 and k == 's' and type(q) is int and q > 0 for i, k, q in rows):
            raise ValueError('invalid marketplace ledger')
        return {'orders': {'marketplace-' + str(i): {'units': {k: q}, 'canceled': False} for i, k, q in rows}}

    async def sqlite(self, name, path, query, table=None):
        if not path.startswith('/') or '\x00' in path: raise ValueError('invalid database path')
        service = await self.service(name)
        pid = service['State']['Pid']
        if type(pid) is not int or pid <= 0: raise ValueError('invalid service PID')
        source = f'''import json,os,sqlite3
# Load trusted client modules before changing this one process's filesystem root.
# SQLite's VFS must resolve database, journal and WAL in the service namespace.
os.chroot('/proc/{self.main_pid}/root/proc/{pid}/root'); os.chdir('/')
path={path!r}
assert not os.path.islink(path)
with sqlite3.connect('file:'+path+'?mode=ro',uri=True) as db:
 db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
 if {table!r} is not None:
  assert db.execute("SELECT type FROM sqlite_master WHERE name=?",({table!r},)).fetchone()==('table',)
 print(json.dumps(db.execute({query!r}).fetchall()))
'''
        return json.loads(await self.python(source))

    async def claims(self, path='/app/claims.json'):
        return json.loads(await self.python('import json; from pathlib import Path; p=Path(' +
            repr(f'/proc/{self.main_pid}/root' + path) + '); print(p.read_text() if p.is_file() else "{}")'))

    async def prepare_traffic(self, spec):
        root = Path(__file__).resolve().parents[2]
        files = {name: base64.b64encode((root / name).read_bytes()).decode()
                 for name in ('bin/live_traffic.py', 'bin/shoppers', 'projects/medusa/seed-ids.json')}
        for path in (root / 'cases/medusa-oversell/traffic').rglob('*'):
            if path.is_file(): files[str(path.relative_to(root))] = base64.b64encode(path.read_bytes()).decode()
        options = dict(spec['traffic'])
        options['inventory_service_ports'] = {s['name']: s['host_ports'] for s in spec.get('inventory_services', []) if 'host_ports' in s}
        scenarios = []
        for sid, source in spec.get('traffic_hooks', {}).items():
            if not re.fullmatch('[A-Za-z0-9_-]+', sid): raise ValueError('invalid traffic hook id')
            directory = '/traffic/scenarios/' + sid
            files['scenarios/' + sid + '/hooks.mjs'] = base64.b64encode(source.encode()).decode()
            scenarios.append({'id': sid, 'dir': directory})
        if scenarios: options['scenarios'] = scenarios
        await self.python('''import base64,json,sys
from pathlib import Path
for name,data in json.load(sys.stdin).items():
 p=Path('/traffic')/name
 p.parent.mkdir(parents=True,exist_ok=True)
 p.write_bytes(base64.b64decode(data))
''', data=json.dumps(files))
        return options

    async def traffic(self, spec, options, deadline):
        # Long-lived traffic is bounded by its own deadline; query calls keep the
        # shorter timeout. No traffic process runs inside the contestant PID ns.
        process = await asyncio.create_subprocess_exec('docker', 'exec', self.container,
            'python3', '/traffic/bin/live_traffic.py', str(deadline), json.dumps(options),
            '--deadline',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(process.communicate(), spec['duration_sec'] + 10)
        except BaseException:
            process.kill(); await process.wait(); raise
        if process.returncode: raise RuntimeError(err.decode())
        return out.decode()

    async def stop(self):
        if self.container:
            container, self.container = self.container, None
            await command('docker', 'rm', '-f', container)
