"""Pinned, whole-batch export/import. No launcher and no new money allocation."""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import tarfile
import uuid

from carry_over import digest
from registry import atomic_json
import batch_money as money


def require(value):
    if not value: raise ValueError('batch transfer refused')


def predecessor(record):
    """Read public predecessor manifests already pinned by the current manifest."""
    carry = record['carry_from']
    require(isinstance(carry, dict) and set(carry) == {'schema', 'manifest_json', 'policy', 'snapshot_sha256', 'jobs'})
    require(type(carry['schema']) is int and carry['schema'] == 1 and money._sha(carry['snapshot_sha256']))
    policy = carry['policy']; require(set(policy) == {'batch', 'jobs'})
    batch = policy['batch']; raw = carry['manifest_json'].encode('utf-8')
    require(hashlib.sha256(raw).hexdigest() == batch['manifest_sha256'])
    old = json.loads(raw)
    require(old['id'] == batch['id'] != record['id'] and old['jobs'] == policy['jobs'] and
            old['max_concurrency'] == batch['max_concurrency'] and
            old['restore_recipient'] == record['restore_recipient'] and
            batch['manifest_path'] == 'factory/batches/' + old['id'] + '.json')
    require(isinstance(carry['jobs'], dict) and bool(carry['jobs']))
    for name, item in carry['jobs'].items():
        require(isinstance(name, str) and re.fullmatch('[a-z0-9-]+', name) and
                set(item) == {'generation', 'case', 'committed_total_usd'} and
                (item['generation'] is None or money._sha(item['generation'])) and
                isinstance(item['case'], str) and re.fullmatch('case-[A-Za-z0-9-]+', item['case']))
        money.amount(item['committed_total_usd'])
        if re.search(r'-r[1-9][0-9]*$', name):
            require(record.get('replacement_policy', {}).get('enabled') is True)
    return policy, old


def check(record):
    """Bound recursion and authenticate each exact predecessor manifest byte string."""
    seen = {record['id']}
    current = record
    while 'carry_from' in current:
        _, old = predecessor(current)
        require(old['id'] not in seen and len(seen) < 64)
        seen.add(old['id']); current = old
    # Validate ancestors oldest first so ordinary validators do not recurse forever.
    current = record
    while 'carry_from' in current:
        _, old = predecessor(current)
        money.check_manifest(old, _ancestors=False)
        current = old


def frozen_manifest(record):
    from batch import verify
    policy, old = predecessor(record)
    directory = Path(policy['batch']['release'])
    verify(directory, policy['batch']['sha256'])
    source = json.loads((directory / 'source-manifest.json').read_text())
    relative = policy['batch']['manifest_path']
    require(source['files'][relative] == policy['batch']['manifest_sha256'])
    with tarfile.open(directory / 'public-source.tar.gz') as archive:
        member = archive.getmember('unbug-bench/' + relative)
        require(member.isfile())
        require(archive.extractfile(member).read() == record['carry_from']['manifest_json'].encode())
    return policy, old


def latches(receipt):
    snapshot = receipt['snapshot']
    result = deepcopy(snapshot['imported_derivations'])
    for parent, row in snapshot['derivations'].items():
        wrapped = dict(source_batch=snapshot['batch'], derivation=row)
        require(parent not in result or result[parent] == wrapped)
        result[parent] = wrapped
    children = [row['derivation']['child_job'] for row in result.values()]
    require(len(set(children)) == len(children))
    return result


def snapshot(directory, record, policy):
    """Caller holds the source lock; no mutations, network or launch."""
    import batch_holder as holder
    import batch_service as service
    state = money.load_locked(directory, record, policy['batch']['manifest_sha256'])
    require(not state['incidents'] and all(not row['overrun'] and row['previous']['total_usd'] is not None
                                         for row in state['jobs'].values()))
    operations = holder._operations(directory, record, policy)
    for op in operations.values():
        require(op['incident'] is None and (op['state'] == 'failed' or
                op['state'] == 'launched' and op['retirement'] is not None and op['output_generation'] is not None))
    journal = service._load(directory, record, policy['batch']['manifest_sha256'])
    entries = {row['parent_case'] + '/' + row['eligible_generation']: journal['entries'][
        row['parent_case'] + '/' + row['eligible_generation']] for row in journal['derivations'].values()}
    return dict(schema=1, batch=record['id'], manifest_sha256=policy['batch']['manifest_sha256'],
                release_sha256=policy['batch']['sha256'], money=state, operations=operations,
                derivations=journal['derivations'], entries=entries,
                imported_derivations=journal.get('imported_derivations', {}),
                prior_import=service._json(directory / 'import.json') if (directory / 'import.json').exists() else None)


def read_import(directory, record):
    """Frozen proof, no nested locks. Source export is never changed or removed."""
    import batch_service as service
    policy, old = predecessor(record)
    source_dir = directory.parent / old['id']
    with service._regular(directory / 'import.json') as stream: raw = stream.read()
    with service._regular(source_dir / 'export.json') as stream: require(stream.read() == raw)
    receipt = json.loads(raw)
    require(set(receipt) == {'schema', 'source_batch', 'target_batch', 'target_manifest_sha256',
            'target_release_sha256', 'snapshot', 'jobs', 'carried_debit_usd'} and
            type(receipt['schema']) is int and receipt['schema'] == 1 and
            receipt['source_batch'] == old['id'] and receipt['target_batch'] == record['id'] and
            digest(receipt['snapshot']) == record['carry_from']['snapshot_sha256'] and
            set(receipt['jobs']) == set(record['carry_from']['jobs']))
    snap = receipt['snapshot']
    require(snap['batch'] == old['id'] and snap['manifest_sha256'] == policy['batch']['manifest_sha256'] and
            snap['release_sha256'] == policy['batch']['sha256'])
    total = money.aggregate(snap['money'])
    selected = 0
    for name, binding in receipt['jobs'].items():
        require(set(binding) == {'generation', 'authority'})
        spec = record['carry_from']['jobs'][name]; old_row = snap['money']['jobs'][name]
        auth = money.channel(binding['authority'], record, name)
        require(binding['generation'] == spec['generation'] == auth['source_generation'] and
                auth['revision'] == 1 and auth['reservation_id'] != old_row['authority']['reservation_id'] and
                auth['case'] == spec['case'] == old_row['authority']['case'] and
                auth['committed_total_usd'] == spec['committed_total_usd'] == old_row['held_usd'])
        selected += max(money.amount(old_row['held_usd']), money.amount(old_row['known_floor_usd']))
    require(money.amount(receipt['carried_debit_usd']) == total - selected and
            total <= money.amount(record['money_limit_usd']) <= money.amount(old['money_limit_usd']))
    return receipt


def imported_row(directory, record, name, row):
    receipt = read_import(directory, record)
    old = receipt['snapshot']['money']['jobs'][name]
    expected = dict(generation=receipt['jobs'][name]['generation'], authority=receipt['jobs'][name]['authority'],
                    previous=old['previous'], known_floor_usd=old['known_floor_usd'])
    require(row['imported'] == expected)
    return expected


def _local_source(directory, record, policy, snapshot_value, name, generation):
    import batch_holder as holder
    return holder._source(directory, record, policy, snapshot_value['operations'], snapshot_value['money'], name, generation)


def source(home, record, name, generation):
    """Resolve only the imported base against unchanged source ACK/artifacts."""
    directory = home / 'batches' / record['id']
    receipt = read_import(directory, record)
    require(receipt['jobs'][name]['generation'] == generation and generation is not None)
    policy, old = frozen_manifest(record)
    source_dir = home / 'batches' / old['id']
    require(snapshot(source_dir, old, policy) == receipt['snapshot'])
    ack, entry, card = _local_source(source_dir, old, policy, receipt['snapshot'], name, generation)
    return ack, entry, card, source_dir / 'generations' / card['case'] / generation


def _usd(n):
    return f'{n // 10**9}.{n % 10**9:09d}'


def prepare(policy, root, home):
    """Export-first commit; replay repairs projections, never advanced money."""
    import batch_holder as holder
    import batch_service as service
    record = money.manifest(policy, root)
    if 'carry_from' not in record: return
    old_policy, old = frozen_manifest(record)
    require(old_policy['batch']['sha256'] != policy['batch']['sha256'])
    with ExitStack() as stack:
        directories = {key: stack.enter_context(money.locked(home, key, read_export=True))
                       for key in sorted((old['id'], record['id']))}
        src, dst = directories[old['id']], directories[record['id']]
        require(not (dst / 'export.json').exists())
        require(money.deadline(record['batch_deadline']) > __import__('time').time())
        snap = snapshot(src, old, old_policy)
        require(digest(snap) == record['carry_from']['snapshot_sha256'])
        require(money.aggregate(snap['money']) <= money.amount(record['money_limit_usd']) <= money.amount(old['money_limit_usd']))
        existing = service._json(src / 'export.json') if (src / 'export.json').exists() else None
        if existing is None:
            require(not any((dst / n).exists() for n in ('money.json', 'import.json', 'journal.json', 'reservations.json')))
        else:
            require(existing['target_batch'] == record['id'] and
                    existing['target_manifest_sha256'] == policy['batch']['manifest_sha256'] and
                    existing['target_release_sha256'] == policy['batch']['sha256'] and existing['snapshot'] == snap)
        jobs, imported, selected = {}, {}, 0
        journal = service._load(src, old, old_policy['batch']['manifest_sha256'])
        for name, spec in record['carry_from']['jobs'].items():
            previous = service._lineage(journal, old, name)
            target = service.resolve_job(record, name)
            row = snap['money']['jobs'][name]
            require(previous['case'] == target['case'] == spec['case'])
            ignore = {'case', 'requested_total_usd'}
            require({k:v for k,v in previous['template'].items() if k not in ignore} ==
                    {k:v for k,v in target['template'].items() if k not in ignore})
            require(target['template']['requested_total_usd'] == row['held_usd'] == spec['committed_total_usd'])
            generation = spec['generation']
            if generation is None:
                require(previous['ordinal'] > 0 and not any(op['job'] == name for op in snap['operations'].values()) and
                        row['authority']['source_generation'] is None and row['known_floor_usd'] == '0.000000000')
            else:
                # Only a local successor can be exported, not an unlaunched imported checkpoint.
                require(generation in row['acks'])
                ack, _, card = _local_source(src, old, old_policy, snap, name, generation)
                require(ack['authority'] == row['authority'] and card.get('status') == 'stopped' and
                        card.get('terminal_stop') not in ('retired_not_converging', 'retired_factory_bug_limit',
                                                         'factory_bug_history_invalid', 'diagnosis_input_invalid'))
            authority = (existing['jobs'][name]['authority'] if existing else dict(schema=1,
                batch=record['id'], job=name, case=spec['case'], reservation_id=str(uuid.uuid4()), revision=1,
                source_generation=generation, committed_total_usd=row['held_usd'], batch_deadline=record['batch_deadline']))
            money.channel(authority, record, name)
            jobs[name] = dict(generation=generation, authority=authority)
            base = dict(generation=generation, authority=authority, previous=row['previous'], known_floor_usd=row['known_floor_usd'])
            imported[name] = dict(authority=authority, held_usd=row['held_usd'], known_floor_usd=row['known_floor_usd'],
                                  previous=row['previous'], sources=[generation], acks={}, overrun=False, imported=base)
            selected += max(money.amount(row['held_usd']), money.amount(row['known_floor_usd']))
        receipt = dict(schema=1, source_batch=old['id'], target_batch=record['id'],
                       target_manifest_sha256=policy['batch']['manifest_sha256'], target_release_sha256=policy['batch']['sha256'],
                       snapshot=snap, jobs=jobs, carried_debit_usd=_usd(money.aggregate(snap['money']) - selected))
        if existing: require(existing == receipt)
        else: atomic_json(src / 'export.json', receipt)
        if (dst / 'import.json').exists(): require(service._json(dst / 'import.json') == receipt)
        else: atomic_json(dst / 'import.json', receipt)
        if not (dst / 'money.json').exists():
            state = money.load_locked(dst, record, policy['batch']['manifest_sha256'])
            state.update(jobs=imported, carried_debit_usd=receipt['carried_debit_usd'])
            atomic_json(dst / 'money.json', state)
        state = money.load_locked(dst, record, policy['batch']['manifest_sha256'])
        require(set(jobs) <= set(state['jobs']))
        target_journal = service._load(dst, record, policy['batch']['manifest_sha256'])
        inherited = latches(receipt)
        if 'imported_derivations' in target_journal: require(target_journal['imported_derivations'] == inherited)
        target_journal['imported_derivations'] = inherited
        for name, item in jobs.items():
            if item['generation'] is not None: continue
            parent, = [parent for parent, value in inherited.items() if value['derivation']['child_job'] == name]
            key = 'replacement/' + parent
            if key not in target_journal['queue']:
                target_journal['queue'][key] = dict(kind='replacement', job=name, case=item['authority']['case'],
                    source_generation=None, owner_job=name, parent_case=parent,
                    sequence=target_journal['next_sequence'], reason='exhaustion')
                target_journal['next_sequence'] += 1
        atomic_json(dst / 'journal.json', target_journal)
        money.project(home, record, state)
