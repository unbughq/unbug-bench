"""Protected behavioral qualification. App observations never authorize credit.

The private case defines observable business predicates. No submitted guard,
request or trial requires a model, approval, review callback or cache.
"""
import hashlib
import json
import os
import pathlib
import tempfile
import uuid
import socketserver
import threading

VERSION = 2


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def policy_files(directory):
    frozen = directory / 'refusal-policy.json'
    if frozen.is_file():
        return json.loads(frozen.read_text())
    case = directory.parents[1]
    files = {name: (case / name).read_text() for name in
             ('promise.md', 'fact-sheet.md', 'contestant.md', 'case.json', 'answer-key.json')
             if (case / name).is_file()}
    if not files:
        raise ValueError('missing immutable owner policy')
    return files


def private_directory(path):
    path = pathlib.Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError('refusal evidence directory is not private')
    return path


def write_private(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as f:
        json.dump(value, f, allow_nan=False)
    os.replace(f.name, path)


def schema_sql():
    # Definitions/privileges as well as source bytes: injected constraints, triggers,
    # role changes and live DDL invalidate a trial even if guard files did not move.
    return """SELECT json_build_object(
      'relations',(SELECT json_agg(x ORDER BY x::text) FROM (
        SELECT c.oid::regclass::text AS name,c.relowner,c.relacl,c.relrowsecurity
        FROM pg_class c WHERE c.relnamespace='public'::regnamespace) x),
      'constraints',(SELECT json_agg(x ORDER BY x::text) FROM (
        SELECT conrelid::regclass::text AS relation,pg_get_constraintdef(oid) AS definition
        FROM pg_constraint WHERE connamespace='public'::regnamespace) x),
      'triggers',(SELECT json_agg(x ORDER BY x::text) FROM (
        SELECT pg_get_triggerdef(oid) AS definition,tgenabled FROM pg_trigger WHERE NOT tgisinternal) x),
      'functions',(SELECT json_agg(x ORDER BY x::text) FROM (
        SELECT p.oid::regprocedure::text AS name,pg_get_functiondef(p.oid) AS definition,p.proowner,p.proacl
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND p.prokind='f') x),
      'roles',(SELECT json_agg(x ORDER BY x::text) FROM (
        SELECT rolname,rolsuper,rolcreaterole,rolbypassrls FROM pg_roles
        WHERE rolname IN ('medusa_app','bench_guard')) x),
      'administrator_password_disabled',(SELECT rolpassword IS NULL FROM pg_authid WHERE rolname='medusa'),
      'administrator_membership',pg_has_role('medusa_app','medusa','MEMBER') OR
                                  pg_has_role('bench_guard','medusa','MEMBER'))"""


def schema_stamp_sql():
    return "SELECT encode(sha256(convert_to((" + schema_sql() + ")::text,'UTF8')),'hex')"


class BehavioralRefusal:
    def __init__(self, bench, installation, scenarios):
        self.bench, self.installation, self.scenarios = bench, installation, scenarios
        oracle = next(s['dir'] / 'refusal_oracle.py' for s in scenarios if (s['dir'] / 'refusal_oracle.py').is_file())
        self.oracle_path = oracle
        self.oracle = {}
        exec(compile(oracle.read_text(), str(oracle), 'exec'), self.oracle)
        self.policy = policy_files(oracle.parent)
        self.root = private_directory(bench.RESULTS / 'refusal-evidence')
        self.directory = pathlib.Path(tempfile.mkdtemp(prefix='trial-', dir=self.root))
        self.nonce = uuid.uuid4().hex
        self.identity = None
        self.rows = []
        self.failure = 'not_finalized'
        self.observations = {}
        self.socket_directory = tempfile.TemporaryDirectory(prefix='ubr-', dir='/tmp')
        self.socket_path = pathlib.Path(self.socket_directory.name) / 'capture.sock'
        self.server = None

    def __getattr__(self, name):
        return getattr(self.bench, name)

    def install(self):
        # Created AFTER guard/scenario installation, BEFORE either app starts.
        # Restored tables already belong to the administrator. Neither guard nor
        # app can disable this trigger, replace its function or write this schema.
        # Docker's default administrator password is public fixture material.
        # Judge SQL uses the local Unix socket; remove remote password access
        # before crediting any administrator-owned witness. A host trust/ident
        # rule would defeat that boundary and is an invalid runtime configuration.
        unsafe = self.bench.sql("""SELECT (SELECT count(*) FROM pg_hba_file_rules
          WHERE error IS NOT NULL OR type LIKE 'host%' AND auth_method NOT IN
            ('scram-sha-256','md5','password','reject') AND NOT
            (auth_method='trust' AND address IN ('127.0.0.1','::1') AND netmask IN
              ('255.255.255.255','ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff')))
          + (SELECT count(*) FROM pg_roles WHERE rolname IN ('medusa_app','bench_guard')
             AND (rolsuper OR rolcreaterole OR rolreplication OR rolbypassrls))
          + (pg_has_role('medusa_app','medusa','MEMBER') OR
             pg_has_role('bench_guard','medusa','MEMBER'))::int""")
        if unsafe.strip() != '0':
            raise ValueError('administrator network authentication is not isolated')
        self.bench.sql("""ALTER ROLE medusa PASSWORD NULL;
          CREATE SCHEMA bench_refusal AUTHORIZATION medusa;
          REVOKE TRIGGER ON public.return,public.order_change FROM bench_guard,medusa_app;
          REVOKE ALL ON SCHEMA bench_refusal FROM PUBLIC,bench_guard,medusa_app;
          CREATE TABLE bench_refusal.meta(nonce text NOT NULL);
          INSERT INTO bench_refusal.meta VALUES ('""" + self.nonce + """');
          REVOKE ALL ON bench_refusal.meta FROM PUBLIC,bench_guard,medusa_app;
          CREATE TABLE bench_refusal.history(seq bigserial PRIMARY KEY, nonce text NOT NULL, row_data jsonb NOT NULL, items jsonb,
            kind text NOT NULL DEFAULT 'return');
          REVOKE ALL ON bench_refusal.history FROM PUBLIC,bench_guard,medusa_app;
          CREATE FUNCTION bench_refusal.capture() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
          SET search_path=pg_catalog AS $$ BEGIN
            IF NEW.requested_at IS NOT NULL THEN
              INSERT INTO bench_refusal.history(nonce,row_data,items) SELECT '""" + self.nonce + """',to_jsonb(NEW),
                (SELECT jsonb_agg(to_jsonb(i)) FROM public.return_item i WHERE i.return_id=NEW.id);
            END IF;
            RETURN NEW;
          END $$;
          REVOKE ALL ON FUNCTION bench_refusal.capture() FROM PUBLIC,bench_guard,medusa_app;
          CREATE TRIGGER bench_refusal_history AFTER INSERT OR UPDATE ON public.return
            FOR EACH ROW EXECUTE FUNCTION bench_refusal.capture();
          ALTER TABLE public.return ENABLE ALWAYS TRIGGER bench_refusal_history;
          CREATE FUNCTION bench_refusal.capture_change() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
          SET search_path=pg_catalog AS $$ BEGIN
            IF NEW.change_type IN ('return_request','exchange') AND
               (NEW.requested_at IS NOT NULL OR NEW.confirmed_at IS NOT NULL) THEN
              INSERT INTO bench_refusal.history(nonce,row_data,kind) VALUES ('""" + self.nonce + """',
                jsonb_build_object('id',COALESCE(NEW.return_id,'change:' || NEW.id),
                  'order_id',NEW.order_id,'exchange_id',NEW.exchange_id,'change_id',NEW.id), 'change');
            END IF;
            RETURN NEW;
          END $$;
          REVOKE ALL ON FUNCTION bench_refusal.capture_change() FROM PUBLIC,bench_guard,medusa_app;
          CREATE TRIGGER bench_refusal_change_history AFTER INSERT OR UPDATE ON public.order_change
            FOR EACH ROW EXECUTE FUNCTION bench_refusal.capture_change();
          ALTER TABLE public.order_change ENABLE ALWAYS TRIGGER bench_refusal_change_history;""")

    def runtime(self):
        ids = self.bench.dc('ps', '-q', *self.bench.APP_SERVICES).splitlines()
        if len(ids) != 2:
            raise ValueError('both runtime instances are required')
        rows = json.loads(self.bench.command(['docker', 'inspect', *ids]))
        for row in rows:
            host = row['HostConfig']
            if (host.get('Privileged') or host.get('PidMode') == 'host' or
                    host.get('NetworkMode', '').startswith(('host', 'container:'))):
                raise ValueError('app shares privileged runtime or database network namespace')
            protected = (self.root.resolve(), pathlib.Path(self.socket_directory.name).resolve())
            if any(any(p.is_relative_to(pathlib.Path(m['Source']).resolve()) for p in protected) or
                   m.get('Destination', '').startswith('/var/lib/postgresql') for m in row['Mounts']):
                raise ValueError('app can reach protected evidence or database storage')
        return [{'image': r['Image'], 'host': r['HostConfig'], 'config': {k: r['Config'].get(k) for k in
                ('Image', 'Env', 'Cmd', 'Entrypoint', 'User', 'WorkingDir')},
                'mounts': r['Mounts']} for r in rows]

    def start(self):
        self.schema = json.loads(self.bench.sql(schema_sql()))
        self.schema_stamp = self.bench.sql(schema_stamp_sql())
        self.runtime0 = self.runtime()
        self.source_paths = {name: pathlib.Path(__file__).parent / name for name in ('refusal.py', 'bench.py', 'bench_judging.py')}
        self.source_paths.update({'traffic': self.bench.ROOT / 'cases/medusa-oversell/traffic/run.mjs'})
        sources = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in self.source_paths.items()}
        self.identity = {'version': VERSION, 'scope_tags': list(self.oracle['TAGS']), 'policy': digest(self.policy),
                         'installation': self.installation, 'sources': sources,
                         'schema': digest(self.schema), 'runtime': digest(self.runtime0)}
        self.open_capture()

    def history_snapshot(self):
        value = json.loads(self.bench.sql("""SET statement_timeout='5s'; SELECT json_build_object(
          'nonce',(SELECT nonce FROM bench_refusal.meta),
          'rows',(SELECT COALESCE(json_agg(h ORDER BY h.seq),'[]') FROM bench_refusal.history h))"""))
        if value.get('nonce') != self.nonce or not isinstance(value.get('rows'), list):
            raise ValueError('missing_or_swapped_history_source')
        if any(h.get('nonce') != self.nonce or type(h.get('seq')) is not int for h in value['rows']):
            raise ValueError('mixed_history_source')
        return value['rows']

    def snapshot(self):
        # Runs in the independent host process, using administrator SQL. Neither
        # mutable app instance can write the socket or supply these facts.
        value = json.loads(self.bench.sql("""SET statement_timeout='5s'; SELECT json_build_object(
          'nonce',(SELECT nonce FROM bench_refusal.meta),
          'history',(SELECT COALESCE(json_agg(h ORDER BY h.seq),'[]') FROM bench_refusal.history h),
          'schema_stamp',(""" + schema_stamp_sql() + """),
          'facts',(""" + self.oracle['CAPTURE_SQL'] + "))"))
        if (value.get('nonce') != self.nonce or not isinstance(value.get('history'), list) or
                value.get('schema_stamp') != self.schema_stamp or
                not isinstance(value.get('facts'), dict) or
                any(h.get('nonce') != self.nonce or type(h.get('seq')) is not int for h in value['history'])):
            raise ValueError('missing_or_swapped_prestate')
        return value

    def open_capture(self):
        session = self
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    self.request.settimeout(30)
                    data = json.loads(self.rfile.readline(1_000_000))
                    if data['event'] == 'before':
                        ident = uuid.uuid4().hex
                        session.observations[ident] = {'wire': data, 'before': session.snapshot()}
                        response = {'id': ident}
                    elif data['event'] == 'after':
                        entry = session.observations[data['id']]
                        if 'after' in entry:
                            raise ValueError('duplicate_completion')
                        entry['after'] = session.snapshot()
                        entry['wire'].update(data)
                        response = {'id': data['id']}
                    else:
                        raise ValueError('unknown_capture_event')
                except Exception as error:
                    session.failure = 'protected_capture_failed: ' + str(error)
                    response = {'error': 'protected_capture_failed'}
                self.wfile.write(json.dumps(response).encode() + b'\n')
        self.server = socketserver.UnixStreamServer(str(self.socket_path), Handler)
        self.socket_path.chmod(0o600)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.05), daemon=True)
        self.thread.start()

    def close(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=2)
            self.server = None
        self.socket_directory.cleanup()

    def finalize(self, result):
        try:
            if self.failure != 'not_finalized':
                raise ValueError(self.failure)
            if any('after' not in e for e in self.observations.values()):
                raise ValueError('incomplete_protected_request')
            self.rows = [e['wire'] for e in self.observations.values()]
            if (not self.rows or len({r['id'] for r in self.rows}) != len(self.rows) or
                    any(type(r.get('instance')) is not int or r['instance'] not in (0, 1) for r in self.rows)):
                raise ValueError('missing_or_mixed_http_source')
            if (self.policy != policy_files(self.oracle_path.parent) or
                    self.identity['sources'] != {name: hashlib.sha256(path.read_bytes()).hexdigest()
                                                 for name, path in self.source_paths.items()} or
                    self.installation != self.bench.installation_identity(self.guard_path, self.scenarios) or
                    self.schema != json.loads(self.bench.sql(schema_sql())) or self.runtime0 != self.runtime()):
                raise ValueError('runtime_or_schema_changed')
            self.history = self.history_snapshot()
            # Source and trigger ACL/ownership are re-read; no app stream supplies history.
            intact = self.bench.sql("""SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
              JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace n ON n.oid=p.pronamespace
              WHERE t.tgname IN ('bench_refusal_history','bench_refusal_change_history') AND t.tgenabled='A'
              AND c.relowner='medusa'::regrole AND p.proowner='medusa'::regrole
              AND n.nspname='bench_refusal' AND n.nspowner='medusa'::regrole
              AND NOT has_schema_privilege('medusa_app',n.oid,'USAGE')
              AND NOT has_schema_privilege('bench_guard',n.oid,'USAGE')""")
            if intact.strip() != '2':
                raise ValueError('unprotected_history_source')
            base = next(s for s in self.scenarios if s['id'] == 'BASE')
            namespace = {}
            exec(compile((base['dir'] / 'judge.py').read_text(), str(base['dir'] / 'judge.py'), 'exec'), namespace)
            self.behavior = namespace['judge'](result, self.bench)
            self.final_state = self.snapshot()
            self.controls = self.oracle['complete'](result, self.behavior, self.final_state)
            self.evidence = {'identity': self.identity, 'nonce': self.nonce, 'history': self.history,
                'policy': self.policy, 'schema': self.schema, 'runtime': self.runtime0,
                'behavior': self.behavior, 'final_state': self.final_state, 'controls': self.controls,
                'observations': self.observations}
            write_private(self.directory / 'evidence.json', self.evidence)
            result['refusal_evidence'] = self.evidence
            self.failure = None
        except Exception as error:
            self.failure = str(error)

    def qualify_refusal(self, run, operation, stage):
        def answer(status, reason):
            return {'status': status, 'reason': reason, 'oracle_identity': digest(self.identity),
                    'fresh_evidence_sha256': digest(getattr(self, 'evidence', None))}
        if self.failure:
            return answer('invalid', 'protected_oracle_unavailable')
        if run.get('errors') or (run.get('traffic') or {}).get('timeouts'):
            return answer('invalid', 'runtime_or_transport_failure')
        record = ((run.get('traffic') or {}).get('scenario_records') or {}).get('BASE') or {}
        returns = record.get('returns') or []
        if any(len([r for r in returns if r.get('tag') == tag and r.get('received') is True]) != 1 for tag in self.oracle['FITTING']):
            return answer('invalid', 'fitting_operations_incomplete')
        if any(self.behavior.get('checks', {}).get(k) is not True for k in self.oracle['CHECKS']):
            return answer('invalid', 'behavioral_obligations_failed')
        if self.controls.get('status') != 'qualified':
            return answer(self.controls.get('status', 'unqualified'), self.controls.get('reason', 'incomplete_controls'))
        steps = operation.get('steps') or {}
        receipt = steps.get(stage) or {}
        matches = [r for r in self.rows if r.get('id') == receipt.get('judge_request_id')]
        if len(matches) != 1:
            return answer('invalid', 'missing_or_duplicate_protected_request')
        wire = matches[0]
        if (wire.get('status') != receipt.get('status') or wire.get('transport_error') or
                type(wire.get('instance')) is not int or wire['instance'] not in (0, 1) or
                wire.get('retried') or wire.get('method') != 'POST'):
            return answer('invalid', 'transport_retry_or_binding_failure')
        order, line = operation.get('order_id'), operation.get('line_id')
        if not isinstance(order, str) or not order or not isinstance(line, str) or not line:
            return answer('unqualified', 'missing_operation_identity')
        exchange = operation.get('exchange') is True
        identifier = operation.get('exchange_id' if exchange else 'return_id')
        prefix = '/admin/exchanges' if exchange else '/admin/returns'
        suffix = {'request_items': '/request-items', 'request_items_2': '/request-items',
                  'inbound': '/inbound/items', 'request': '/request'}
        expected_path = prefix if stage == 'begin' else prefix + '/' + str(identifier) + suffix.get(stage, '')
        if wire.get('path') != expected_path:
            return answer('invalid', 'request_path_mismatch')
        if stage != 'begin' and (not isinstance(identifier, str) or not identifier):
            return answer('unqualified', 'missing_operation_identity')
        body = wire.get('body')
        if (stage == 'begin' and (not isinstance(body, dict) or body.get('order_id') != order) or
                stage in ('request_items', 'request_items_2', 'inbound') and
                (not isinstance(body, dict) or not isinstance(body.get('items'), list) or
                 len(body['items']) != 1 or body['items'][0].get('id') != line or
                 type(body['items'][0].get('quantity')) is not int or
                 not 0 < body['items'][0]['quantity'] <= operation.get('quantity', 0)) or
                stage == 'request' and body != {}):
            return answer('invalid', 'request_body_mismatch')
        fitting_path = self.oracle.get('fitting_path_usable')
        if (not callable(fitting_path) or
                fitting_path(returns, self.observations, exchange, wire['instance'], self.nonce) is not True):
            return answer('unqualified', 'same_instance_fitting_path_unavailable')
        related = [h for h in self.history if h['row_data'].get('order_id') == order and
                   (stage == 'begin' or h['row_data'].get('exchange_id' if exchange else 'id') == identifier)]
        if stage == 'begin':
            known = {r.get('return_id') for r in returns if r is not operation and r.get('received') is True
                     and isinstance(r.get('return_id'), str) and r['return_id']}
            exchanges = {r.get('exchange_id') for r in returns if r.get('received') is True
                         and isinstance(r.get('exchange_id'), str) and r['exchange_id']}
            related = [h for h in related if h['row_data'].get('id') not in known
                       and h['row_data'].get('exchange_id') not in exchanges]
        if related:
            return answer('invalid', 'accepted_history_even_if_cleaned_up')
        observation = self.observations.get(receipt.get('judge_request_id'))
        if not observation or observation.get('before', {}).get('nonce') != self.nonce or observation.get('after', {}).get('nonce') != self.nonce:
            return answer('unqualified', 'protected_prestate_or_outcome_missing')
        earlier = {h['seq'] for h in observation['before']['history']}
        if any(h['seq'] not in earlier and h['row_data'].get('order_id') == order
               for h in observation['after']['history']):
            return answer('invalid', 'accepted_during_failed_request')
        try:
            verdict = self.oracle['qualify'](operation, stage, observation['wire'],
                observation['before'], observation['after'])
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return answer('unqualified', 'protected_business_facts_incomplete')
        if not isinstance(verdict, dict) or verdict.get('status') not in ('qualified', 'unqualified', 'invalid'):
            return answer('unqualified', 'malformed_case_oracle_result')
        return answer(verdict['status'], verdict['reason'])


def invalidate_unqualified(result):
    if any(e.get('stage') == 'refusal-evidence' for e in result.get('errors', [])):
        result['checker'].update(valid=False, **{'pass': False})
        result['judge'].update(invalid='protected refusal evidence unavailable', **{'pass': False})
    for scenario, facts in result.get('judge', {}).get('facts', {}).items():
        if isinstance(facts, dict) and facts.get('qualification', {}).get('status') in ('blocked', 'invalid'):
            result['errors'].append({'stage': 'refusal-qualification', 'scenario': scenario,
                                     'message': 'protected refusal qualification incomplete'})
            result['checker'].update(valid=False, **{'pass': False})
            result['judge'].update(invalid='refusal qualification incomplete', **{'pass': False})
