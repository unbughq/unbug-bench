"""Complete a writer rejection from its retained observation, without scoring gates."""
import copy
from pathlib import Path
import tempfile

from budget import BudgetError
import extensions
import gate_state
import job_authority
from registry import atomic_json

STAGES = ('G1', 'G15', 'G3', 'G4', 'G5', 'saved-cheats')
FIELDS = {'schema_version', 'kind', 'extension_id', 'writer_operation_id', 'round',
          'entry_sha256', 'case_tree_sha256', 'stage', 'record_sha256', 'receipt'}


def refuse():
    raise BudgetError('extension_snapshot_changed')


def marker(row):
    return f"extension-terminal/{row['extension_id']}-writer-rejection.json"


def receipt_valid(c, r, row, receipt, feedback):
    if (not isinstance(receipt, dict) or receipt.get('actor') != 'writer' or
            receipt.get('repair_pending') is not False or
            type(receipt.get('repair_requested')) is not bool or
            receipt.get('operation_id') != row['writer_operation_id'] or
            any(type(receipt.get(key)) is not int or receipt[key] != row[target]
                for key, target in (('extension_id', 'extension_id'), ('round', 'round'), ('round_limit', 'round'))) or
            receipt.get('output_sha256') != r.case_hash(c) or receipt.get('awaiting_stress') is True):
        return False
    if receipt.get('phase') == 'completed':
        return (receipt.get('next_phase') == 'G1' and not receipt.get('validation_problems') and
                not receipt.get('exhausted') and 'stop_reason' not in receipt)
    if receipt.get('phase') == 'validated':
        return (receipt.get('next_phase') == 'writer' and receipt.get('validation_problems') == feedback and
                (('exhausted' not in receipt and 'stop_reason' not in receipt) or
                 (receipt.get('exhausted') is True and receipt.get('stop_reason') == 'rounds_exhausted')))
    return False


def observation(c, r, row, stage):
    from extension_package import Records, writer_feedback
    owner = copy.copy(c)
    owner.args, owner.card = copy.deepcopy(c.args), copy.deepcopy(c.card)
    records = Records(owner, r, row)
    data = records.load(stage, check_version=False)
    feedback = writer_feedback(stage, data)
    if stage == 'saved-cheats' and data['info'].get('sample') != 'retained_case_cheats': refuse()
    case = records.root / stage / 'support/case'
    observed = extensions.tree(case)
    prefix = case.relative_to(c.work).as_posix() + '/'
    bound = {name[len(prefix):]: value for name, value in data['support'].items() if name.startswith(prefix)}
    if observed != bound or observed != extensions.tree(c.case): refuse()
    name = (records.root / stage / 'record.json').relative_to(c.work).as_posix()
    return data, feedback, name


def snapshot(c, row, proof, evidence, generation):
    value = dict(source_generation=generation, case_sha256=proof['case_tree_sha256'],
        stages=[dict(stage=s['stage'], version=s['version'], status='unreached',
                     binding_sha256=None, evidence_sha256=None) for s in row['entry']['stages']],
        frontier=0, evidence=evidence)
    extensions.validate_snapshot(value)
    if row['entry']['frontier'] == len(row['entry']['stages']): refuse()
    return value


def complete(c, r, row):
    authority = job_authority.for_case(c)
    from extension_package import Records
    records = Records(c, r, row)
    found = [s for s in STAGES if (records.root / s / 'record.json').exists() or
             (records.root / s / 'record.json').is_symlink()]
    if not found: return False
    try:
        if len(found) != 1: refuse()
        stage = found[0]
        if any((records.root / s).exists() or (records.root / s).is_symlink()
               for s in extensions.stages() if s != stage): refuse()
        data, feedback, name = observation(c, r, row, stage)
        receipt = extensions._writer_json(c.work / 'attack-state.json', c.work)
        if (receipt.get('actor') != 'writer' or type(receipt.get('round')) is not int or
                receipt['round'] != row['round'] or receipt.get('phase') not in ('completed', 'validated') or
                receipt.get('repair_pending') is not False): refuse()
        receipt = extensions.writer_receipt(c)
        if not receipt_valid(c, r, row, receipt, feedback): refuse()
        extensions._verify_case(c, row['extension_id'], 'entry', row['entry'])
        case_hash = extensions.digest(extensions.tree(c.case))
        proof = dict(schema_version=1, kind='writer_rejection', extension_id=row['extension_id'],
            writer_operation_id=row['writer_operation_id'], round=row['round'],
            entry_sha256=extensions.digest(row['entry']), case_tree_sha256=case_hash,
            stage=stage, record_sha256=gate_state.digest(c.work / name), receipt=receipt)
        with tempfile.TemporaryDirectory(prefix='unbug-writer-rejection-') as directory:
            root = Path(directory)
            evidence = {name: proof['record_sha256'], **data['support']}
            extensions._save_evidence(c.work, root, {'evidence': evidence})
            path = root / marker(row)
            path.parent.mkdir(parents=True)
            atomic_json(path, proof)
            evidence[marker(row)] = gate_state.digest(path)
            if extensions.digest(extensions.tree(c.case)) != case_hash: refuse()
            outcome = snapshot(c, row, proof, evidence, authority.source_generation)
            extensions.complete(c, outcome, evidence_root=root)
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, BudgetError):
        refuse()


def retained(c, r, row):
    outcome = row['outcome']
    name = marker(row)
    if outcome is None or name not in outcome['evidence']: return None
    try:
        for phase in ('entry', 'outcome'):
            extensions._verify_case(c, row['extension_id'], phase, row[phase])
        base = c.work / 'extension-snapshots' / str(row['extension_id']) / 'outcome'
        owner = copy.copy(c)
        owner.work, owner.case = base / 'evidence', base / 'case'
        proof = extensions._writer_json(owner.work / name, owner.work)
        if (set(proof) != FIELDS or type(proof['schema_version']) is not int or proof['schema_version'] != 1 or
                proof['kind'] != 'writer_rejection' or proof['stage'] not in STAGES or
                type(proof['extension_id']) is not int or type(proof['round']) is not int or
                any(proof[k] != row[k] for k in ('extension_id', 'round', 'writer_operation_id')) or
                proof['entry_sha256'] != extensions.digest(row['entry']) or
                proof['case_tree_sha256'] != extensions.digest(extensions.tree(owner.case))): refuse()
        data, feedback, record = observation(owner, r, row, proof['stage'])
        if (proof['record_sha256'] != gate_state.digest(owner.work / record) or
                not receipt_valid(owner, r, row, proof['receipt'], feedback)): refuse()
        evidence = {record: proof['record_sha256'], **data['support'], name: gate_state.digest(owner.work / name)}
        if snapshot(owner, row, proof, evidence, outcome['source_generation']) != outcome: refuse()
        return proof['stage'], data['info']
    except (OSError, ValueError, KeyError, TypeError, AttributeError, BudgetError):
        refuse()


def verified(c, r, row):
    return retained(c, r, row) is not None


def stop(c, row):
    import run as r
    result = retained(c, r, row)
    if result is None: refuse()
    stage, info = result
    c.card.update(gates={}, gate_results={})
    for key in ('failed_gate', 'failed_detail', 'infrastructure_gate', 'early_gates'):
        c.card.pop(key, None)
    for key in ('early', 'early_hash'):
        c.__dict__.pop(key, None)
    c.card['stress_review'] = dict(status='not_run', reason='writer_rejection')
    c.card['failed_detail'] = copy.deepcopy(info)
    if stage != 'saved-cheats': c.card['failed_gate'] = stage
    raise BudgetError('extension_incomplete')
