"""Owning-job comparison execution; no launcher and no independent money authority."""
import contextlib
import copy
import ctypes
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from types import SimpleNamespace

from budget import BudgetError, reconcile_reservations
from case_contract import CaseProblem
import extension_compare as comparison
from extension_package import Records, project, safe_directory
import extensions
import factory_waste
import gate_attempt
import gate_state
import job_authority
import model_runtime
from registry import atomic_json
from run_validity import InvalidInfra

EXECUTION = {'bench_workers': 1, 'concurrent_roles': False}
OP_LISTS = ('route_receipts', 'cleanup_errors', 'router_waits', 'router_interrupted_calls')
OP_FLAGS = ('budget_resumed', 'force_budget_resume')
_MISSING = object()


def read(path, base):
    return extensions._writer_json(path, base)


def source_files(root, runner):
    """Materialize safe included file links; never export a link into the copy."""
    root = Path(root).resolve()
    def included(name):
        return runner.bench_manifest_includes(name) or (
            name.startswith('factory/') and '__pycache__' not in Path(name).parts)
    files = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        parent = Path(directory)
        for name in list(dirs):
            path = parent / name
            rel = path.relative_to(root).as_posix()
            if not included(rel + '/') or name == '__pycache__':
                dirs.remove(name)
            elif path.is_symlink():
                raise InvalidInfra('linked source directory')
        for name in names:
            path = parent / name
            relative = path.relative_to(root).as_posix()
            if not included(relative): continue
            if path.is_symlink():
                if Path(os.readlink(path)).is_absolute(): raise InvalidInfra('absolute source link')
                try: target = path.resolve(strict=True)
                except (OSError, RuntimeError): raise InvalidInfra('invalid source link') from None
                if (not target.is_relative_to(root) or not target.is_file() or
                        not included(target.relative_to(root).as_posix())):
                    raise InvalidInfra('escaping source link')
                path = target
            if not path.is_file(): raise InvalidInfra('non-file source')
            files[relative] = path
    return files


def install_bench(c, runner, target):
    files = source_files(runner.BENCH, runner)
    inventory = {name: gate_state.digest(path) for name, path in sorted(files.items())}
    if runner.bench_manifest() != c.manifest0:
        raise InvalidInfra('source bench manifest changed')
    manifest = {'schema_version': 1, 'files': inventory}
    if target.exists():
        if read(target.parent / 'source.json', c.work) != manifest:
            raise InvalidInfra('copied source changed')
        if any((target / name).is_symlink() or not (target / name).is_file() or
               gate_state.digest(target / name) != sha for name, sha in inventory.items()):
            raise InvalidInfra('incomplete private source')
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix='.bench-', dir=target.parent))
        try:
            for name, source in files.items():
                destination = temporary / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                destination.chmod(source.stat().st_mode & 0o777)
            if any(gate_state.digest(temporary / name) != sha for name, sha in inventory.items()):
                raise InvalidInfra('source changed during copy')
            if runner.bench_manifest(temporary) != c.manifest0:
                raise InvalidInfra('private bench manifest mismatch')
            extensions._sync_tree(temporary)
            atomic_json(target.parent / 'source.json', manifest)
            temporary.rename(target)
            extensions._sync_directory(target.parent)
        finally:
            if temporary.exists(): shutil.rmtree(temporary)
    if runner.bench_manifest(target) != c.manifest0 or runner.bench_manifest() != c.manifest0:
        raise InvalidInfra('private bench manifest changed')


def subreaper(value=None):
    if sys.platform != 'linux': raise InvalidInfra('comparison process requires Linux')
    libc = ctypes.CDLL(None, use_errno=True)
    current = ctypes.c_int()
    ctypes.set_errno(0)
    result = libc.prctl(37, ctypes.byref(current), 0, 0, 0)
    if result != 0 or ctypes.get_errno(): raise InvalidInfra('subreaper query failed')
    if value is not None:
        ctypes.set_errno(0)
        result = libc.prctl(36, int(value), 0, 0, 0)
        if result != 0 or ctypes.get_errno(): raise InvalidInfra('subreaper update failed')
    return current.value


def descendants():
    try:
        result = subprocess.run(['ps', '-axo', 'pid=,ppid=,pgid='], capture_output=True,
                                text=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError):
        raise InvalidInfra('process verification unavailable') from None
    rows = [tuple(map(int, line.split())) for line in result.stdout.splitlines()
            if len(line.split()) == 3]
    owned, found = {os.getpid()}, set()
    while True:
        more = {pid for pid, parent, _ in rows if parent in owned} - owned
        if not more: break
        found.update(more); owned.update(more)
    # The completed ps probe may appear in its own listing; it is already reaped.
    return {pid for pid in found if Path('/proc', str(pid)).exists()}


def operations(c):
    return {'card': {key: copy.deepcopy(c.card.get(key, [])) for key in OP_LISTS} |
                    {'models_used': copy.deepcopy(c.card.get('models_used', {}))},
            'attrs': {key: copy.deepcopy(getattr(c, key)) for key in (*OP_LISTS[2:], *OP_FLAGS)
                      if hasattr(c, key)}}


def merge_operations(c, value):
    for key in OP_LISTS:
        target = c.card.setdefault(key, [])
        for row in value.get('card', {}).get(key, []):
            if row not in target: target.append(copy.deepcopy(row))
    c.card.setdefault('models_used', {}).update(value.get('card', {}).get('models_used', {}))
    for key in OP_FLAGS:
        if key in value.get('attrs', {}): setattr(c, key, bool(value['attrs'][key]))
    for key in OP_LISTS[2:]:
        target = getattr(c, key, [])
        for row in value.get('attrs', {}).get(key, []):
            if row not in target: target.append(copy.deepcopy(row))
        setattr(c, key, target)


def phase_context(c, root, number):
    context = copy.copy(c)
    context.args, context.models, context.card = copy.deepcopy((c.args, c.models, c.card))
    context.case, context.work = root / 'case', root / 'work'
    context.accounting_work = c.work
    for key in ('recipient', 'early', 'early_hash', 'votes', 'votes_hash', 'pilot_passes',
                'role_cancel', 'calibrator_slot_offset', 'audit_source', 'audit_gates',
                'model_dispatch_lock', 'active_model_calls', 'model_resume_state'):
        context.__dict__.pop(key, None)
    context.args.bench_workers, context.args.concurrent_roles = 1, False
    context.args.no_early_probe = True
    context.card = {key: value for key, value in context.card.items()
                    if key in ('roles', 'case', 'diagnosis_state', 'factory_bug',
                               'factory_bug_resume_count', 'batch_release_sha256',
                               'case_budget', 'recovery_config', *OP_LISTS, 'models_used')}
    context.card['builder_rounds'] = number
    context.card['gates'] = {}
    context.stopped = False
    return context


def stress(c, r, number):
    path = c.work / 'attack-state.json'
    report = c.work / 'attacks' / f'round-{number}.json'
    report.parent.mkdir(parents=True, exist_ok=True)
    binding = r.attack_binding(c)
    if path.exists():
        receipt = read(path, c.work)
        if receipt.get('binding') != binding: raise BudgetError('extension_snapshot_changed')
    else:
        receipt = dict(round=number, round_limit=number, binding=binding, report=report.name,
                       actor='stress_tester', review_pending=True, review_attempt=uuid.uuid4().hex,
                       next_phase='gates', output_sha256=None)
        atomic_json(path, receipt)
    def completed():
        receipt.update(phase='completed', review_pending=False,
                       output_sha256=gate_state.digest(report))
        receipt['review_completed'] = dict(attempt=receipt['review_attempt'],
            binding=hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest(),
            report_sha256=receipt['output_sha256'])
        atomic_json(path, receipt)
    r.stress_categories(c, number, report, receipt, completed)
    result = r.attack_report(report)
    if result is None: raise InvalidInfra('missing stress report')
    try:
        result, _ = r.loop_freshness(c, result, report)
    except BudgetError as error:
        if str(error) == 'freshness_public_match':
            return False, {'confirmed_public_match': True,
                           'freshness': copy.deepcopy(c.card.get('loop_freshness', {}))}
        if str(error) == 'freshness_unresolved':
            raise BudgetError('freshness_evidence_unavailable') from None
        raise
    findings = [item for item in result['blocking'] if item.strip().lower() != 'review incomplete']
    if not findings and (not result['complete'] or result['unfinished_validation'] or
                         r.attack_diagnostic_unfinished(c, number)):
        raise InvalidInfra('incomplete stress review')
    return not findings, result


def child(pipe, c, r, private_bench, phase_manifest, versions):
    """Private process. Only durable records and operational IPC leave this scope."""
    import processes
    processes._deadline.set((float('inf'), False))  # forked inside a gate window: each stage message carries its own end
    os.setpgid(0, 0)
    def child_seal(*args, **kwargs): raise RuntimeError('child seal')
    runners = [r]
    other = sys.modules.get('run')
    if other is not None and other is not r: runners.append(other)
    original_bin = (r.BENCH / 'bin').resolve()
    for runner in runners:
        runner.seal = child_seal
        runner.BENCH = private_bench
        runner.COMPOSE = ['docker', 'compose', '-f', str(private_bench / 'projects/medusa/compose.yaml')]
        runner.parallel_calibrators = lambda c: False
        runner.g10_overlap_reason = lambda c: 'comparison serial'
    os.environ['BENCH'] = str(private_bench)
    sys.path.insert(0, str(private_bench / 'bin'))
    for name in ('bench', 'factory_pool', 'claims'): sys.modules.pop(name, None)
    for name, module in tuple(sys.modules.items()):
        location = getattr(module, '__file__', None)
        if (location and Path(location).resolve().is_relative_to(original_bin) and
                name not in ('run_validity', 'processes')):
            pipe.send(('stop', 'InvalidInfra', 'unexpected path-bound bin module'))
            return
    import run_validity
    assert run_validity.InvalidInfra is comparison.InvalidInfra
    pipe.send(('ready', os.getpid()))
    lock = threading.RLock()
    def request(kind, value):
        with lock:
            pipe.send((kind, value))
            reply = pipe.recv()
            if reply[0] == 'budget': raise BudgetError(reply[1])
            if reply[0] != 'ack': raise InvalidInfra('invalid parent reply')
            return reply[1]
    def checkpoint(force=False):
        effects = operations(c)
        atomic_json(c.work / 'operational-effects.json', effects)
        return request('checkpoint', {'effects': effects, 'force': force})
    c.stress_checkpoint = lambda: checkpoint(True)
    def progress(context, stage, status, elapsed_seconds=None, reused=False):
        request('progress', [stage, status, elapsed_seconds, reused])
    for runner in runners: runner.public_progress = progress
    original = r._opencode
    def opencode(context, *args, **kwargs):
        result = original(context, *args, **kwargs)
        atomic_json(c.work / 'operational-effects.json', operations(c))
        if (not kwargs.get('user') and not getattr(context, 'stress_category_call', False)
                and not getattr(context, 'active_model_calls', set())):
            checkpoint()
        return result
    for runner in runners: runner._opencode = opencode
    records = Records(c, r, observation_id=phase_manifest['observation_id'],
                      round_number=phase_manifest['round_number'], expected_versions=versions)
    prepared = False
    with factory_waste.forward_attempt(None):
        while True:
            message = pipe.recv()
            if message[0] == 'close': break
            _, stage, attempt_id, *rest = message
            end = rest[0] if rest else None  # absolute monotonic end of this stage's gate window
            def mark(reason):
                path = c.work / 'attempt-effects' / (attempt_id + '.json')
                value = read(path, c.work) if path.exists() else dict(
                    schema_version=1, attempt_id=attempt_id, unpublishable=[])
                if reason not in value['unpublishable']: value['unpublishable'].append(reason)
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_json(path, value)
                request('unpublishable', value)
            try:
                with factory_waste.forward_attempt(mark if attempt_id else None):
                    for prior in extensions.stages():
                        if prior == stage: break
                        data = records.load(prior)
                        if data is not None: records.restore(prior, data)
                    old = records.load(stage)
                    if old is not None:
                        records.restore(stage, old)
                    else:
                        if stage not in ('G1', 'G2') and not prepared:
                            ok, setup = r.g3(c)
                            if not ok: raise InvalidInfra('private setup failed')
                            prepared = records.prepared = True
                        before = {key: gate_state.digest(path)
                                  for key, path in gate_state.inventory(c, private_bench).items()}
                        old_card = project(c.card)
                        immutable = {k: v for k, v in extensions.tree(c.case).items()
                                     if k != 'freshness.jsonl'}
                        try:
                            if stage == 'stress': result = stress(c, r, phase_manifest['round_number'])
                            elif stage == 'G3' and prepared: result = True, setup
                            else:
                                with (processes.deadline(max(end - time.monotonic(), 1e-3))
                                      if end is not None else contextlib.nullcontext()):
                                    result = getattr(r, stage.lower())(c)
                        except CaseProblem as error:
                            result = False, {'problems': [str(error)]}
                        if immutable != {k: v for k, v in extensions.tree(c.case).items()
                                         if k != 'freshness.jsonl'}:
                            raise InvalidInfra('comparison changed case inputs')
                        if comparison._pending(*result): raise InvalidInfra('incomplete stage result')
                        records.save(stage, *result, before, old_card)
                effects = operations(c)
                atomic_json(c.work / 'operational-effects.json', effects)
                pipe.send(('result', effects))
            except BaseException as error:
                effects = operations(c)
                atomic_json(c.work / 'operational-effects.json', effects)
                kind = ('BudgetError' if isinstance(error, BudgetError) else
                        'InvalidInfra' if isinstance(error, InvalidInfra) else
                        'CaseProblem' if isinstance(error, CaseProblem) else 'RuntimeError')
                pipe.send(('stop', kind, str(error), effects))
    pipe.close()


class Evaluator:
    def __init__(self, c, r, number, versions):
        self.c, self.r, self.number, self.versions = c, r, number, dict(versions)
        self.row = extensions.read(c)[number - 1]
        self.identity = extensions.digest(dict(schema_version=1, extension_id=number,
            cases={phase: self.row[phase]['case_sha256'] for phase in ('entry', 'outcome')},
            versions=self.versions))
        self.root = c.work / 'comparison-runs' / str(number) / self.identity
        safe_directory(c, self.root)
        self.phase = self.context = self.records = self.pipe = self.process = None
        self.reaper = None
        self.scope = None
        self.cleanup_pending = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            self.close_child()
        finally:
            if self.reaper is not None:
                subreaper(self.reaper)
                self.reaper = None

    def phase_for(self, w):
        phase = w.work.parent.name
        if phase not in ('entry', 'outcome') or comparison._case(w) != self.row[phase]['case_sha256']:
            raise BudgetError('extension_snapshot_changed')
        if self.phase != phase:
            self.close_child()
            self.phase = phase
            root = self.root / phase
            safe_directory(self.c, root)
            root.mkdir(parents=True, exist_ok=True)
            manifest_path = root / 'manifest.json'
            expected = dict(schema_version=1, identity=self.identity, phase=phase,
                            case_sha256=self.row[phase]['case_sha256'], round_number=self.row['round'])
            if manifest_path.exists():
                manifest = read(manifest_path, self.c.work)
                from diagnosis import _uuid4
                if (set(manifest) != set(expected) | {'observation_id'} or
                        any(manifest[k] != v for k, v in expected.items()) or
                        not _uuid4(manifest['observation_id'])):
                    raise BudgetError('extension_snapshot_changed')
            else:
                manifest = {**expected, 'observation_id': str(uuid.uuid4())}
                if (root / 'case').exists(): shutil.rmtree(root / 'case')
                shutil.copytree(w.case, root / 'case')
                atomic_json(manifest_path, manifest)
            self.context = phase_context(self.c, root, self.row['round'])
            for name in ('logs', 'transcripts'):
                (self.context.work / name).mkdir(parents=True, exist_ok=True)
            # Freshness is derived evidence; every semantic byte remains the input.
            if ({k: v for k, v in extensions.tree(self.context.case).items() if k != 'freshness.jsonl'} !=
                    {k: v for k, v in extensions.tree(w.case).items() if k != 'freshness.jsonl'}):
                raise BudgetError('extension_snapshot_changed')
            self.manifest = manifest
            self.records = Records(self.context, self.r, observation_id=manifest['observation_id'],
                round_number=self.row['round'], expected_versions=self.versions)
            effects = self.context.work / 'operational-effects.json'
            if effects.exists(): merge_operations(self.c, read(effects, self.c.work))

    def start_child(self):
        if self.cleanup_pending: self.close_child()
        if self.process is not None: return
        deadline = time.monotonic() + 30
        while threading.active_count() != 1 or getattr(self.c, 'active_model_calls', set()):
            job_authority.for_case(self.c)
            if time.monotonic() >= deadline: raise InvalidInfra('comparison fork is not quiescent')
            if getattr(self.c, 'role_cancel', None) is not None and self.c.role_cancel.is_set():
                raise BudgetError('cancelled')
            time.sleep(.1)
        install_bench(self.c, self.r, self.root / 'bench')
        if self.reaper is None: self.reaper = subreaper(1)
        context = multiprocessing.get_context('fork')
        self.pipe, peer = context.Pipe()
        self.process = context.Process(target=child, args=(peer, self.context, self.r,
                            self.root / 'bench', self.manifest, self.versions))
        self.process.start()
        peer.close()
        reply = self.receive()
        if reply != ('ready', self.process.pid): raise InvalidInfra('comparison child setup failed')

    def receive(self):
        while not self.pipe.poll(.2):
            if not self.process.is_alive(): raise InvalidInfra('comparison child died')
            job_authority.for_case(self.c)
            if getattr(self.c, 'role_cancel', None) is not None and self.c.role_cancel.is_set():
                raise BudgetError('cancelled')
        try: return self.pipe.recv()
        except (EOFError, OSError): raise InvalidInfra('comparison IPC lost') from None

    def checkpoint(self, force=False):
        from durable_checkpoint import checkpoint_progress
        advanced = checkpoint_progress(self.c, self.r.seal, quiescent=True, **({'interval': 0} if force else {}))
        return advanced and self.c.card.get('durable_checkpoint', {}).get('remote_durable') is True

    def close_child(self):
        if self.process is None and not self.cleanup_pending: return
        import processes
        self.cleanup_pending = True
        if self.process is not None:
            process, pipe = self.process, self.pipe
            try:
                if process.is_alive():
                    try: pipe.send(('close',))
                    except (OSError, BrokenPipeError): pass
                    process.join(1)
                processes.kill_tree(process.pid, alive=process.is_alive())
                if process.is_alive():
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                process.join(5)
            finally:
                pipe.close()
                self.process = self.pipe = None
        # Pilot UIDs can own detached groups the unprivileged owner cannot kill.
        for user, _ in self.r.pilot_homes(): self.r.stop_pilot(self.c, user)
        for pid in descendants():
            try: processes.kill_tree(pid)
            except ProcessLookupError: pass
        deadline = time.monotonic() + 30
        while True:
            while True:
                try:
                    pid, _ = os.waitpid(-1, os.WNOHANG)
                    if not pid: break
                except ChildProcessError: break
            alive = descendants()
            if not alive: break
            for pid in alive:
                try: os.kill(pid, signal.SIGKILL)
                except ProcessLookupError: pass
            if time.monotonic() >= deadline: raise InvalidInfra('comparison descendants remain')
            time.sleep(.05)
        self.r.archive_pilot_state(self.context)
        self.cleanup_pending = False

    def crash(self, stage, error):
        root = self.context.work if self.context is not None else self.root / self.phase / 'work'
        directory = root / 'gate-details'
        directory.mkdir(parents=True, exist_ok=True)
        number = len(list(directory.glob(stage + '.crash-*.json'))) + 1
        atomic_json(directory / f'{stage}.crash-{number}.json',
                    dict(error_type=type(error).__name__, message=str(error), traceback=traceback.format_exc()))

    def retain_diagnostic(self, stage, *, pair=False):
        destination = self.c.work / 'comparison-diagnostics' / self.identity / ('pair' if pair else self.phase)
        safe_directory(self.c, destination)
        destination.mkdir(parents=True, exist_ok=True)
        source = self.root if pair else self.root / self.phase
        candidates = ([source / 'pair-attempts.json', source / 'pair-crash.json'] if pair else
                      [source / 'manifest.json', source / 'work/infra-attempts.json',
                       *(source / 'work/gate-details').glob('*.crash-*.json')])
        for path in candidates:
            if path.is_file():
                from diagnosis import _input_bytes
                target = destination / path.name
                target.write_bytes(_input_bytes(path, self.c.work))
        atomic_json(destination / 'index.json', dict(scope='pair' if pair else 'stage',
            extension_id=self.number, phase=None if pair else self.phase, stage=stage,
            versions=self.versions, cases={p: self.row[p]['case_sha256'] for p in ('entry', 'outcome')}))
        return (destination / 'index.json').relative_to(self.c.work).as_posix()

    def exhausted(self, stage, error_type='InvalidInfra', *, pair=False):
        diagnostic = self.retain_diagnostic(stage, pair=pair)
        if stage != 'stress' and not pair:
            self.c.card['infrastructure_gate'] = dict(gate=stage, error_type=error_type,
                classification='invalid-infra', exhausted=True, diagnostic=diagnostic)
            raise BudgetError('infrastructure_exhausted')
        self.c.card.pop('infrastructure_gate', None)
        raise BudgetError('stress_validation_exhausted')

    def check_versions(self):
        if comparison._versions(comparison.Workspace(self.c.case, self.c.work, self.r.BENCH,
                self.c.args, self.c.models, self.c.card, self.c.seed,
                getattr(self.c, 'factory_slot', 0), self.c.case_id)) != self.versions:
            raise InvalidInfra('comparison version changed')

    def invoke(self, stage):
        self.check_versions()
        committed = self.records.load(stage)
        if committed is not None: return committed['ok'], committed['info']
        self.r.case_budget_boundary(self.c)
        before = set(read(self.c.ledger, self.c.ledger.parent).get('invocation_reservations', {}))
        complete_reply, quiet = False, True
        with factory_waste.attempt(self.c, stage, self.r.case_hash(self.context), comparison=True) as scope:
            self.scope = scope
            attempt_id = scope.value['attempt_id'] if scope is not None else None
            try:
                self.start_child()
                self.check_versions()
                import processes
                end, _ = processes._deadline.get()
                self.pipe.send(('stage', stage, attempt_id, end if end != float('inf') else None))
                while True:
                    message = self.receive()
                    if message[0] == 'unpublishable':
                        self.apply_marks(message[1], scope)
                        self.pipe.send(('ack', True))
                    elif message[0] == 'progress':
                        self.r.public_progress(self.c, *message[1])
                        self.pipe.send(('ack', True))
                    elif message[0] == 'checkpoint':
                        merge_operations(self.c, message[1]['effects'])
                        try:
                            durable = self.checkpoint(message[1]['force'])
                            self.pipe.send(('ack', durable))
                        except BudgetError as error: self.pipe.send(('budget', str(error)))
                    elif message[0] in ('result', 'stop'):
                        complete_reply = True
                        merge_operations(self.c, message[-1])
                        if message[0] == 'result': break
                        kind, text = message[1:3]
                        if kind == 'BudgetError': raise BudgetError(text)
                        if kind == 'InvalidInfra': raise InvalidInfra(text)
                        if kind == 'CaseProblem': raise CaseProblem(text)
                        raise RuntimeError(text)
                    else: raise InvalidInfra('invalid comparison IPC')
                self.check_versions()
                data = self.records.load(stage)
                if data is None: raise InvalidInfra('child omitted stage record')
                self.checkpoint()
                return data['ok'], data['info']
            except BaseException:
                quiet = False
                self.close_child()
                reconcile_reservations(self.c.work, self.c.ledger)
                quiet = True
                raise
            finally:
                try:
                    path = self.context.work / 'attempt-effects' / (str(attempt_id) + '.json')
                    if attempt_id and path.exists(): self.apply_marks(read(path, self.c.work), scope)
                    if scope is not None:
                        if not complete_reply and not quiet: scope.mark_unpublishable('comparison_child_lost')
                        after = read(self.c.ledger, self.c.ledger.parent).get('invocation_reservations', {})
                        for key in set(after) - before: factory_waste.record_reservation(self.c, after[key])
                finally: self.scope = None

    @staticmethod
    def apply_marks(value, scope):
        if (scope is None or set(value) != {'schema_version', 'attempt_id', 'unpublishable'}
                or value['schema_version'] != 1 or value['attempt_id'] != scope.value['attempt_id']
                or not isinstance(value['unpublishable'], list)
                or any(not isinstance(s, str) or not s for s in value['unpublishable'])):
            raise BudgetError('invalid_waste_attribution')
        for reason in value['unpublishable']: scope.mark_unpublishable(reason)

    def __call__(self, w, stage):
        self.check_versions()
        self.phase_for(w)
        data = self.records.load(stage)
        if data is None:
            with self.r._gate_pipeline().window(self.c, stage):  # retries share it; invoke() sends its end to the child
                outcome = gate_attempt.execute(lambda: self.invoke(stage),
                    publish=lambda state, *args: self.r.public_progress(self.c, 'comparison:' + stage, state),
                    record_crash=lambda error: self.crash(stage, error), interruption=BudgetError,
                    attempts=2, journal=self.context.work / 'infra-attempts.json',
                    identity=dict(operation='comparison-stage', comparison=self.identity,
                                  phase=self.phase, gate=stage, versions=self.versions))
            if outcome.crashed: self.exhausted(stage)
            data = self.records.load(stage)
        if data is None: raise InvalidInfra('missing comparison result')
        paths = []
        for name, sha in data['support'].items():
            source = comparison._path(self.context.work, name)
            if gate_state.digest(source) != sha: raise BudgetError('extension_snapshot_changed')
            relative = 'evaluator-support/' + stage + '/' + name
            target = w.work / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            paths.append(relative)
        return data['ok'], data['info'], paths

