"""Verified local collections and a gated queue. No money ACK or launch authority."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time

import batch_money
from batch_accounting import card_total
import collection
from launch_manifest import collection_files
from registry import atomic_json
from transfer import digest

# Enable only in a reviewed D + collection/holder integration increment.
DIAGNOSIS_ENABLED = False


def resolve_job(manifest, job_id):
    """Resolve the frozen root template; this pure function grants no admission."""
    batch_money.check_manifest(manifest)
    if not isinstance(job_id, str): raise ValueError('invalid job')
    root, ordinal = job_id, 0
    match = re.fullmatch(r'(.+)-r([1-9][0-9]*)', job_id)
    if match:
        root, ordinal = match[1], int(match[2])
        if not manifest.get('replacement_policy', {}).get('enabled'):
            raise ValueError('replacement disabled')
    if root not in manifest['jobs']: raise ValueError('unknown job')
    return dict(job=job_id, root_job=root, ordinal=ordinal,
                case='case-' + manifest['id'] + '-' + job_id,
                template=deepcopy(manifest['jobs'][root]))


def _regular(path):
    """Open the checked inode, including for copy; never follow a final symlink."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError('nonregular collection member')
    return os.fdopen(fd, 'rb')


def _json(path):
    with _regular(path) as stream: return json.load(stream)


def _fsync(directory):
    fd = os.open(directory, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def _facts(value):
    if (not isinstance(value, dict) or set(value) != {
            'exhaustion', 'actual_model_work', 'pending_projection'} or
            type(value['exhaustion']) is not bool or type(value['actual_model_work']) is not bool):
        raise ValueError('invalid diagnosis facts')
    pending = value['pending_projection']
    if pending is not None:
        if (not isinstance(pending, dict) or set(pending) != {
                'schema_version', 'status', 'replacement_eligible'} or
                type(pending['schema_version']) is not int or pending['schema_version'] != 1 or
                pending['status'] != 'pending' or type(pending['replacement_eligible']) is not bool):
            raise ValueError('invalid diagnosis projection')
        if pending['replacement_eligible'] and not (value['exhaustion'] and value['actual_model_work']):
            raise ValueError('contradictory diagnosis projection')
    return value


def _project(card, api):
    """Consume only D predicates, never recreate model-work eligibility here."""
    source = json.dumps(card, sort_keys=True)
    result = {}
    try:
        for name in ('exhaustion', 'actual_model_work', 'pending_projection'):
            result[name] = deepcopy(getattr(api, name)(card))
            if json.dumps(card, sort_keys=True) != source:
                raise ValueError('mutated diagnosis input')
        return _facts(result)
    except Exception:
        raise ValueError('diagnosis projection refused') from None


def _load(directory, record, manifest_sha):
    path = directory / 'journal.json'
    if not path.exists() and not path.is_symlink():
        return dict(schema=1, batch=record['id'], manifest_sha256=manifest_sha,
                    entries={}, derivations={}, queue={}, next_sequence=0)
    state = _json(path)
    try:
        if (set(state) - {'operations'} != {'schema', 'batch', 'manifest_sha256', 'entries', 'derivations', 'queue', 'next_sequence'} or
                type(state['schema']) is not int or state['schema'] != 1 or state['batch'] != record['id'] or
                state['manifest_sha256'] != manifest_sha or type(state['next_sequence']) is not int or
                state['next_sequence'] < 0): raise ValueError()
        if 'operations' in state:
            from batch_holder import validate_operations
            validate_operations(state['operations'], record)
        for name in ('entries', 'derivations', 'queue'):
            if not isinstance(state[name], dict): raise ValueError()
        for key, entry in state['entries'].items():
            job = resolve_job(record, entry['job'])
            if (set(entry) != {'job', 'case', 'generation', 'manifest_sha256', 'state', 'facts'} or
                    entry['case'] != job['case'] or key != entry['case'] + '/' + entry['generation'] or
                    not re.fullmatch('[0-9a-f]{64}', entry['generation']) or
                    not re.fullmatch('[0-9a-f]{64}', entry['manifest_sha256']) or
                    entry['state'] != 'pending'): raise ValueError()
            if entry['facts'] is not None: _facts(entry['facts'])
        children = set()
        for parent, row in state['derivations'].items():
            job = resolve_job(record, row['parent_job'])
            child = resolve_job(record, row['child_job'])
            entry = state['entries'][parent + '/' + row['eligible_generation']]
            facts = _facts(entry['facts'])
            if (set(row) != {'parent_case', 'parent_job', 'root_job', 'ordinal', 'child_job', 'child_case', 'eligible_generation'} or
                    parent != row['parent_case'] or parent != job['case'] or
                    entry['job'] != job['job'] or row['root_job'] != job['root_job'] or
                    child['root_job'] != job['root_job'] or type(row['ordinal']) is not int or
                    row['ordinal'] != job['ordinal'] + 1 or child['ordinal'] != row['ordinal'] or
                    row['child_case'] != child['case'] or child['job'] in children or
                    not _replacement(facts)): raise ValueError()
            children.add(child['job'])
        for entry in state['entries'].values(): _lineage(state, record, entry['job'])
        sequences = set()
        for key, row in state['queue'].items():
            job = resolve_job(record, row['job'])
            if (set(row) != {'kind', 'job', 'case', 'source_generation', 'owner_job', 'parent_case', 'sequence', 'reason'} or
                    row['case'] != job['case'] or row['owner_job'] != job['job'] or
                    type(row['sequence']) is not int or row['sequence'] < 0 or
                    row['sequence'] >= state['next_sequence'] or row['sequence'] in sequences): raise ValueError()
            sequences.add(row['sequence'])
            if row['kind'] == 'replacement':
                derivation = state['derivations'][row['parent_case']]
                if (key != 'replacement/' + row['parent_case'] or derivation['child_job'] != row['job'] or
                        row['source_generation'] is not None or row['reason'] not in ('unknown_total', 'exhaustion')):
                    raise ValueError()
            elif row['kind'] == 'resume':
                entry = state['entries'][row['case'] + '/' + row['source_generation']]
                if (key != 'resume/' + row['case'] + '/' + row['source_generation'] or
                        row['parent_case'] is not None or entry['facts'] is None or
                        row['reason'] not in ('settlement', 'exhaustion')): raise ValueError()
            else: raise ValueError()
        if sequences != set(range(state['next_sequence'])): raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError('invalid batch journal') from None
    return state


def _lineage(state, record, name):
    job = resolve_job(record, name)
    if job['ordinal']:
        parents = [r for r in state['derivations'].values() if r['child_job'] == name]
        if len(parents) != 1 or parents[0]['child_case'] != job['case']:
            raise ValueError('unrecorded derived job')
    return job


def _card(directory, names, case, release):
    card = _json(directory / (case + '.scorecard.json'))
    if (not isinstance(card, dict) or card.get('case') != case or
            card.get('batch_release_sha256') != release or card.get('checkpoint_error')):
        raise ValueError('collection binding refused')
    if case + '.casekey.age' not in names: raise ValueError('missing wrapped key')
    if collection.verify(directory, names) != {case}: raise ValueError('unverified case')
    archives = {case + '.tar.gz.age', case + '.checkpoint.tar.gz.age'}
    bound = [name for name in names & archives if digest(directory / name) == card['sha256'] and
             (card.get('archive') is None or Path(card['archive']).name == name)]
    if len(bound) != 1: raise ValueError('ambiguous archive')
    for name, value in ((case + '.statement.age', card.get('statement_cipher_sha256')),
                        (case + '.search.age', card.get('public_search', {}).get('cipher_sha256'))):
        if value is not None and (name not in names or digest(directory / name) != value):
            raise ValueError('referenced ciphertext missing or mismatched')
    return card, bound[0]


def _snapshot(directory, entry, record, release):
    case, generation = entry['case'], entry['generation']
    path = directory / 'generations' / case / generation
    if path.is_symlink() or not path.is_dir(): raise ValueError('missing generation')
    manifest_path = path / 'manifest.json'
    value = _json(manifest_path)
    if digest(manifest_path) != entry['manifest_sha256']: raise ValueError('changed generation manifest')
    if (set(value) != {'schema', 'batch', 'job', 'case', 'generation', 'batch_release_sha256', 'files'} or
            type(value['schema']) is not int or value['schema'] != 1 or
            (value['batch'], value['job'], value['case'], value['generation'], value['batch_release_sha256']) !=
            (record['id'], entry['job'], case, generation, release)):
        raise ValueError('generation binding mismatch')
    names = set(value['files'])
    if not names <= collection_files(case) or {p.name for p in path.iterdir()} != names | {'manifest.json'}:
        raise ValueError('generation member mismatch')
    for name, info in value['files'].items():
        with _regular(path / name) as stream:
            h = hashlib.file_digest(stream, 'sha256').hexdigest()
            if info != dict(sha256=h, size=os.fstat(stream.fileno()).st_size):
                raise ValueError('generation bytes mismatch')
    card, bound = _card(path, names, case, release)
    if card['sha256'] != generation or names & {case + '.tar.gz.age', case + '.checkpoint.tar.gz.age'} != {bound}:
        raise ValueError('generation archive mismatch')
    return card


def collect(policy, root, home, job, directory):
    """Publish a complete immutable local snapshot; never a durability/money ACK."""
    record = batch_money.manifest(policy, root)
    with batch_money.locked(home, record['id']) as state_dir:
        state = _load(state_dir, record, policy['batch']['manifest_sha256'])
        case = _lineage(state, record, job)['case']
        parent = state_dir / 'generations' / case
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if parent.is_symlink(): raise ValueError('linked generation directory')
        with tempfile.TemporaryDirectory(prefix='.stage-', dir=parent) as temporary:
            stage = Path(temporary)
            for name in sorted(collection_files(case)):
                source = Path(directory) / name
                if not source.exists() and not source.is_symlink(): continue
                with _regular(source) as reader, (stage / name).open('xb') as writer:
                    shutil.copyfileobj(reader, writer, 1024 * 1024)
                    writer.flush(); os.fsync(writer.fileno())
            names = {p.name for p in stage.iterdir()}
            card, bound = _card(stage, names, case, policy['batch']['sha256'])
            for name in (names & {case + '.tar.gz.age', case + '.checkpoint.tar.gz.age'}) - {bound}:
                (stage / name).unlink()
            names = {p.name for p in stage.iterdir()}
            generation = card['sha256']
            value = dict(schema=1, batch=record['id'], job=job, case=case,
                         generation=generation, batch_release_sha256=policy['batch']['sha256'],
                         files={n: dict(sha256=digest(stage / n), size=(stage / n).stat().st_size) for n in sorted(names)})
            atomic_json(stage / 'manifest.json', value)
            entry = dict(job=job, case=case, generation=generation,
                         manifest_sha256=digest(stage / 'manifest.json'), state='pending', facts=None)
            destination = parent / generation
            if destination.exists() or destination.is_symlink():
                _snapshot(state_dir, entry, record, policy['batch']['sha256'])
            else:
                _fsync(stage); os.rename(stage, destination); _fsync(parent); _fsync(parent.parent)
            key = case + '/' + generation
            if key in state['entries']:
                if {**state['entries'][key], 'facts': None} != entry:
                    raise ValueError('conflicting journal entry')
            else: state['entries'][key] = entry
            atomic_json(state_dir / 'journal.json', state)
            return deepcopy(state['entries'][key])


def _replacement(facts):
    pending = facts['pending_projection']
    return facts['exhaustion'] and facts['actual_model_work'] and (
        pending is not None and pending['replacement_eligible'])


def _enqueue(state, record, entry, card):
    facts = entry['facts']
    job = _lineage(state, record, entry['job'])
    unknown = card_total(card) is None
    def request(key, kind, owner, source, parent, reason):
        if key in state['queue']: return
        state['queue'][key] = dict(kind=kind, job=owner['job'], case=owner['case'],
                                  source_generation=source, owner_job=owner['job'], parent_case=parent,
                                  sequence=state['next_sequence'], reason=reason)
        state['next_sequence'] += 1
    if _replacement(facts) and record.get('replacement_policy', {}).get('enabled'):
        child = resolve_job(record, job['root_job'] + '-r' + str(job['ordinal'] + 1))
        row = dict(parent_case=job['case'], parent_job=job['job'], root_job=job['root_job'],
                   ordinal=child['ordinal'], child_job=child['job'], child_case=child['case'],
                   eligible_generation=entry['generation'])
        old = state['derivations'].get(job['case'])
        if old:
            if {**old, 'eligible_generation': entry['generation']} != row:
                raise ValueError('changed replacement lineage')
        else:
            if any(r['child_job'] == child['job'] for r in state['derivations'].values()):
                raise ValueError('claimed replacement')
            state['derivations'][job['case']] = row
        request('replacement/' + job['case'], 'replacement', child, None, job['case'],
                'unknown_total' if unknown else 'exhaustion')
    if facts['pending_projection'] is not None or (facts['exhaustion'] and unknown):
        request('resume/' + job['case'] + '/' + entry['generation'], 'resume', job,
                entry['generation'], None, 'settlement' if unknown else 'exhaustion')


def ordered_queue(state):
    """Ordering metadata only: no request here is a ready/granted launch."""
    return sorted(deepcopy(list(state['queue'].values())), key=lambda r: (
        0 if r['reason'] == 'settlement' else 1 if r['kind'] == 'replacement' else 2, r['sequence']))


def retire_legacy(directory, entry, card):
    """Retire unbound exhaustion planning, never ordinary checkpoint resumes."""
    if isinstance(card.get('diagnosis_state'), dict): return False
    import diagnosis
    if not diagnosis.exhaustion(card): return False
    value = dict(schema=1, status='retired', reason='legacy_retire', decision_date='2026-10-30',
                 case=entry['case'], generation=entry['generation'], manifest_sha256=entry['manifest_sha256'])
    parent = directory
    for name in ('retirements', entry['case']):
        child = parent / name
        if child.is_symlink() or (child.exists() and not child.is_dir()):
            raise ValueError('retirement conflict')
        if not child.exists():
            child.mkdir(mode=0o700)
            _fsync(parent)
        parent = child
    path = parent / (entry['generation'] + '.json')
    if path.exists() or path.is_symlink():
        try:
            if _json(path) != value: raise ValueError()
        except (OSError, ValueError, TypeError):
            raise ValueError('retirement conflict') from None
    else:
        atomic_json(path, value)
    return True


def plan(policy, root, home, case, generation, now=None):
    record = batch_money.manifest(policy, root)
    with batch_money.locked(home, record['id']) as directory:
        state = _load(directory, record, policy['batch']['manifest_sha256'])
        entry = state['entries'].get(case + '/' + generation)
        if entry is None: raise ValueError('uncollected generation')
        card = _snapshot(directory, entry, record, policy['batch']['sha256'])
        if retire_legacy(directory, entry, card):
            return dict(status='retired', reason='legacy_retire', facts=None, queue=[])
        if not DIAGNOSIS_ENABLED: return dict(status='diagnosis_unavailable', facts=None, queue=[])
        if entry['facts'] is None:
            if batch_money.deadline(record['batch_deadline']) <= (time.time() if now is None else now):
                raise ValueError('retired_batch_bound')
            import diagnosis
            entry['facts'] = _project(card, diagnosis)
            _enqueue(state, record, entry, card)
            atomic_json(directory / 'journal.json', state)
        return dict(status='planned', facts=deepcopy(entry['facts']), queue=ordered_queue(state))
