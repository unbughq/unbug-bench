"""Trusted host reader for Medusa live windows. Queries never use monitor logins.

Only raw facts cross from the contestant box. SQL and verdict computation stay
in the host checkout. SQLite reads use mode=ro and a read transaction, including
its WAL; copying an active SQLite file without its WAL is not a snapshot.
"""
import json
from pathlib import Path
import shlex
import bench


class LocalReader:
    """Native deterministic strategies have no contestant-controlled client binaries."""
    def __init__(self, shop): self.shop = shop

    async def read_sql(self, query, **connection):
        if connection:
            service = connection.get('service', 'postgres')
            argv = ['docker', 'exec', '-e', 'PGPASSWORD=' + connection.get('password', 'medusa')]
            suffix = ['psql', '-XqAt', '-v', 'ON_ERROR_STOP=1', '-U', connection.get('user', 'medusa'),
                      '-d', connection.get('database', 'medusa'), '-c', 'BEGIN READ ONLY; SET LOCAL search_path=pg_catalog; ' + query + '; COMMIT;']
            command = 'cid=$(docker ps -q --filter ' + shlex.quote('label=com.docker.compose.service=' + service) + '); '
            return json.loads(await self.shop.execute(command + shlex.join(argv) + ' "$cid" ' + shlex.join(suffix)))
        return json.loads(await self.shop.sql('BEGIN READ ONLY; SET LOCAL search_path=pg_catalog; ' + query + '; COMMIT;'))

    async def sqlite(self, name, path, query, table=None):
        if not path.startswith('/') or '\x00' in path: raise ValueError('invalid database path')
        program = f"""import json,sqlite3
with sqlite3.connect('file:'+{path!r}+'?mode=ro',uri=True) as db:
 db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
 if {table!r} is not None:
  assert db.execute("SELECT type FROM sqlite_master WHERE name=?",({table!r},)).fetchone()==('table',)
 print(json.dumps(db.execute({query!r}).fetchall()))
"""
        command = 'cid=$(docker ps -q --filter ' + shlex.quote('label=com.docker.compose.service=' + name) + '); '
        command += 'test -n "$cid" && docker exec -u 0 "$cid" /usr/local/bin/python -I -c ' + shlex.quote(program)
        return json.loads(await self.shop.execute(command))


class LiveShop:
    def __init__(self, execute, spec, trusted=None):
        self.execute, self.spec, self.trusted = execute, spec, trusted
        self.root = spec.get('root', '/app')
        self.compose = ['docker', 'compose', '-f', self.root + '/projects/medusa/compose.yaml']
        self.scenarios = [{'id': 'live-window', 'dir': Path(__file__).parent,
                           'rule': spec.get('rule', {}), 'key': {},
                           'inventory_services': spec.get('inventory_services', [])}]

    async def sql(self, query):
        if self.trusted: return await self.trusted.sql(query)
        return await self.execute(shlex.join(self.compose + ['exec', '-T', 'postgres', 'psql', '-XqAt',
            '-v', 'ON_ERROR_STOP=1', '-U', 'medusa', '-d', 'medusa', '-c', query]))

    async def inject(self):
        if self.spec.get('admin_sql'): await self.sql(self.spec['admin_sql'])

    async def snapshot(self):
        query = (bench.ROOT / 'cases/medusa-oversell/checker/check.sql').read_text()
        ids = json.loads((bench.ROOT / 'projects/medusa/seed-ids.json').read_text())
        for key in ('inventory_x', 'product_x', 'variant_single', 'variant_pack'):
            query = query.replace('{{' + key + '}}', "'" + ids[key].replace("'", "''") + "'")
        check = json.loads(await self.sql(query))
        if not check.get('valid'): raise ValueError('invalid live database snapshot')
        services = {}
        for service in self.spec.get('inventory_services', []):
            if service.get('reader_source'):
                # Same trust boundary as a case's judge.py: private factory-owned
                # source, evaluated on the host, never in the contestant box.
                namespace = {}
                exec(compile(service['reader_source'], '<case-live-reader>', 'exec'), namespace)
                services[service['name']] = await namespace['read'](self.trusted or LocalReader(self), service['name'])
                continue
            # Adapter protocol is frozen per service; currently marketplace SQLite.
            if service.get('reader') != 'marketplace-sqlite': raise ValueError('unknown live service reader')
            if self.trusted:
                services[service['name']] = await self.trusted.orders(service['name'])
                continue
            program = """import json,sqlite3
with sqlite3.connect('file:/data/marketplace.sqlite?mode=ro',uri=True) as db:
 db.execute('PRAGMA query_only=ON')
 db.execute('BEGIN')
 assert db.execute("SELECT type FROM sqlite_master WHERE name='orders'").fetchone()==('table',)
 rows=db.execute('SELECT id,kit,quantity FROM orders').fetchall()
 assert all(type(i) is int and i>0 and k=='s' and type(q) is int and q>0 for i,k,q in rows)
 print(json.dumps({'orders':{'marketplace-'+str(i):{'units':{k:q},'canceled':False} for i,k,q in rows}}))
"""
            # Obtain container by frozen Compose service label, without loading
            # contestant-controlled Compose overlays or adapter source.
            command = "cid=$(docker ps -q --filter " + shlex.quote('label=com.docker.compose.service=' + service['name']) + "); "
            command += 'test -n "$cid" && docker exec -u 0 "$cid" /usr/local/bin/python -I -c ' + shlex.quote(program)
            services[service['name']] = json.loads(await self.execute(command))
        return {'checker': check, 'inventory_services': services, 'traffic': {}, 'errors': []}

    def judge(self, snapshot, traffic=None):
        snapshot = dict(snapshot, checker=dict(snapshot['checker']), traffic=traffic or {})
        if traffic is not None:
            # Match normal checkpoints: enrich raw database facts with the
            # independent API receipt cross-check before evaluating BASE_CHECKS.
            bench.score(snapshot)
        return bench.judge_checkpoint(snapshot, self.scenarios, declared_services=self.spec.get('inventory_services', []))

    async def probe(self):
        snapshot = await self.snapshot()
        judged = self.judge(snapshot)
        if snapshot['errors'] or not snapshot['checker'].get('checker_ok'):
            raise ValueError('live judge could not validate the database facts')
        return judged['paths']
