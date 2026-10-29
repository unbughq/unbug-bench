"""Bounded late-defect grants and already-applied restore authority.

The launcher's expected hash is the authority, not a claim inside the receipt.
New grants add one round without resetting any other allowance.
It never certifies a freshness or stress verdict under a new judging binding.
"""
import copy
import hashlib
from pathlib import Path
import re

from carry_over import digest, require
from registry import atomic_json


def authenticate(path, expected_sha256, case, generation, public_card):
    """New grants cover one late defect; historical grants can only carry forward."""
    from restore_ledger import read_object
    path = Path(path)
    record = read_object(path)
    require(hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256,
            'founder ruling hash mismatch')
    require(record.get('version') == 3, 'old founder ruling generations are retired')
    return authenticate_late(record, expected_sha256, case, generation, public_card)


def authenticate_late(record, pin, case, generation, card):
    """A fresh holder pin grants exactly one write+stress round for one late defect."""
    prior = card.get('founder_ruling') or {}
    authorization = prior.get('authorization') or {}
    old = card.get('recovery_config') or {}
    late = card.get('late_defect') or {}
    require(record.get('case') == case and record.get('generation') == generation and
            record.get('public_card_sha256') == digest(card) and
            record.get('ledger_sha256') == digest(card.get('continuation_budget')) and
            isinstance(record.get('authority'), str) and
            re.fullmatch(r'founder-[0-9]{4}-[0-9]{2}-[0-9]{2}', record['authority']) and
            card.get('terminal_stop') == 'late_defect_needs_ruling:' + str(late.get('gate')) and
            not card.get('failed_gate') and not card.get('checkpoint_error'), 'invalid late-defect ruling binding')
    require(record.get('prior_receipt_sha256') == digest(prior) and
            record.get('prior_ruling_sha256') == authorization.get('sha256') and
            record.get('sequence') == (authorization.get('record') or {}).get('sequence', 1) + 1,
            'invalid founder ruling succession')
    require(record.get('allowances') == dict(case_budget_usd=old.get('case_budget'), round_limit=old.get('rounds', 0) + 1)
            and record.get('late_defect') == late and isinstance(record.get('reason'), str) and record['reason'].strip(),
            'late ruling must grant exactly one round and preserve money cap')
    return dict(sha256=pin, record_sha256=digest(record), record=record)


def apply_late(work, accepted, prior):
    from restore_ledger import read_object
    from run import case_hash
    from types import SimpleNamespace
    record = accepted['record']
    late = read_object(work / 'late-defect.json')
    require(digest(prior) == record['prior_receipt_sha256'] and
            digest(late) == record['late_defect']['record_sha256'] and
            late.get('gate') == record['late_defect']['gate'] and
            late.get('case_sha256') == case_hash(SimpleNamespace(case=work / 'case')),
            'retained late defect differs from ruling')
    path = work / 'attack-state.json'
    journal = work / ('founder-ruling-sequence-' + str(record['sequence']) + '.json')
    if journal.exists():
        intent = read_object(journal)
        require(intent['authorization'] == accepted and intent['prior_ruling'] == prior,
                'conflicting founder ruling journal')
    else:
        require(hashlib.sha256(path.read_bytes()).hexdigest() == late['stress_receipt_sha256'],
                'retained stress receipt differs from late defect')
        intent = dict(authorization=accepted, prior_ruling=prior, original_attack_state=read_object(path))
        atomic_json(journal, intent)
    before = intent['original_attack_state']
    after = {**before, 'round_limit': record['allowances']['round_limit']}
    require(before.get('round_limit') == late['round_limit'] and
            before.get('round') == late['round_limit'] and read_object(path) in (before, after),
            'late ruling does not bind exhausted stress round')
    atomic_json(path, after)
    receipt = dict(authorization=accepted, prior_ruling=prior, reset_once=True,
                   changed_allowances=['round_limit'], preserved_other_allowances=True,
                   freshness_verdict_granted=False, stress_verdict_granted=False)
    atomic_json(work / 'founder-ruling-applied.json', receipt)
    return receipt


def apply(work, accepted):
    """Retry an applied grant or journal one bounded late-defect grant."""
    from restore_ledger import read_object
    work = Path(work)
    require(accepted['record'].get('version') == 3, 'old founder ruling generations are retired')
    done = work / 'founder-ruling-applied.json'
    prior = read_object(done) if done.exists() else {}
    if prior.get('authorization') == accepted:
        return prior  # retry only: never apply the allowance again
    return apply_late(work, accepted, prior)


def context(c):
    from restore_ledger import read_object
    path = c.work / 'founder-ruling-applied.json'
    if not path.exists(): return None
    receipt = read_object(path)
    accepted = receipt['authorization']; record = accepted['record']
    require(digest(record) == accepted['record_sha256'] and record['case'] == c.case_id,
            'invalid applied founder ruling')
    # An archived marker is history, never authority to grant fresh allowances.
    # Only the current worker's post-extraction importer can publish this external
    # receipt after checking the holder-pinned raw hash. It is outside work/.
    imported_path = c.ledger.parent / (c.case_id + '.restore-accounting.json')
    if not imported_path.exists(): return None
    imported = read_object(imported_path)
    if (imported.get('attempt_allowances_authenticated') is not True or
            imported.get('founder_ruling') != receipt): return None
    require(c.args.case_budget == record['allowances']['case_budget_usd'] and
            c.args.rounds == record['allowances']['round_limit'], 'worker limits differ from founder ruling')
    c.card['founder_ruling'] = copy.deepcopy(receipt)
    return receipt


def feedback_allowed(c, attack, report, findings):
    receipt = context(c)
    if receipt is None: return False
    feedback = receipt['authorization']['record'].get('feedback')
    if feedback is None: return False
    return (attack['round'] == feedback['round'] and bool(findings) and report is not None and
            hashlib.sha256(report.read_bytes()).hexdigest() == receipt['feedback_report_sha256'])
