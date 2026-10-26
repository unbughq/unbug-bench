"""Founder restores, authorized by a holder-pinned receipt hash.

The launcher's expected hash is the authority, not a claim inside the receipt.
This imports one exact collected ledger and resets only the named allowances.
It never certifies a freshness or stress verdict under a new judging binding.
"""
import copy
import hashlib
from pathlib import Path
import re

from carry_over import digest, require
from registry import atomic_json


ALLOWANCES = {
    'case-20261024T043353Z-e15450': (55, 9, 8, 1),
    'case-20261024T085209Z-873d7f': (50, 8, 4, None),
}


def authenticate(path, expected_sha256, case, generation, public_card):
    from restore_ledger import read_object
    path = Path(path)
    record = read_object(path)
    require(hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256,
            'founder ruling hash mismatch')
    if record.get('version') == 2:
        return authenticate_next(record, expected_sha256, case, generation, public_card)
    require(case in ALLOWANCES, 'case has no last legacy founder ruling')
    budget, rounds, feedback_round, findings = ALLOWANCES[case]
    require(record.get('version') == 1 and record.get('authority') == 'founder-2026-10-25' and
            record.get('case') == case and record.get('generation') == generation and
            record.get('public_card_sha256') == digest(public_card) and
            record.get('ledger_sha256') == digest(public_card.get('continuation_budget')),
            'founder ruling does not name this collected generation/accounting')
    require(record.get('allowances') == dict(case_budget_usd=budget, round_limit=rounds,
            freshness_repair_attempts=0, rereviews=0, release_rereviews=[], release_review_attempts=[]),
            'founder ruling allowances differ from decision')
    require(record.get('feedback') == dict(round=feedback_round, findings=findings,
            reask_unresolved_freshness=True), 'founder ruling feedback differs from decision')
    require(isinstance(record.get('ruling_verbatim'), str) and record['ruling_verbatim'].strip(),
            'founder ruling reason missing')
    from budget import case_spending
    spending = case_spending(public_card['continuation_budget'])
    require(spending['spent_usd'] is not None and record.get('case_spent_usd') == spending['spent_usd'] and
            record.get('infrastructure_waste_usd') == spending['infrastructure_waste_usd'],
            'founder ruling monetary facts differ from collected ledger')
    return dict(sha256=expected_sha256, record_sha256=digest(record), record=record)


def authenticate_next(record, pin, case, generation, card):
    """Only the two recorded $70 decisions; no other allowance resets."""
    canary = case == 'case-20261024T085209Z-873d7f'
    saved_round = 8 if canary else 9
    prior = card.get('founder_ruling') or {}
    authorization = prior.get('authorization') or {}
    previous = authorization.get('record') or {}
    require(digest(previous) == authorization.get('record_sha256') and previous.get('case') == case,
            'invalid prior founder ruling')
    require(record.get('authority') == 'founder-2026-10-26' and
            case in ALLOWANCES and record.get('case') == case and
            record.get('generation') == generation and record.get('public_card_sha256') == digest(card) and
            record.get('ledger_sha256') == digest(card.get('continuation_budget')),
            'founder ruling does not name this collected generation/accounting')
    require(record.get('sequence') == previous.get('sequence', 1) + 1 == 2 and
            record.get('prior_ruling_sha256') == authorization.get('sha256') and
            record.get('prior_receipt_sha256') == digest(prior) and pin != authorization.get('sha256') and
            previous.get('authority') == 'founder-2026-10-25', 'invalid founder ruling succession')
    require(record.get('allowances') == dict(case_budget_usd=70, round_limit=saved_round + 1),
            'founder ruling allowances differ from decision')
    resume = record.get('resume') or {}
    require(set(resume) == ({'round', 'attack_state_sha256', 'attack_state_record_sha256', 'case_sha256'} |
            ({'pending_writer'} if canary else set())) and resume['round'] == saved_round and
            (not canary or resume['pending_writer'] is True) and
            all(isinstance(resume[k], str) and re.fullmatch('[0-9a-f]{64}', resume[k])
                for k in ('attack_state_sha256', 'attack_state_record_sha256', 'case_sha256')), 'invalid founder resume identity')
    diagnosis = record.get('diagnosis') or {}
    require(isinstance(diagnosis.get('path'), str) and diagnosis['path'].startswith('/private/tmp/') and
            (re.fullmatch('[0-9a-f]{64}', diagnosis.get('sha256', '')) if canary else
             diagnosis.get('sha256') == '6ff5c019747548f12aa3bf0692ea7b9910fb52db8f867de5939bfc749a799366') and
            isinstance(record.get('reason'), str) and record['reason'].strip(), 'founder ruling reason missing')
    from budget import case_spending
    summary = case_spending(card['continuation_budget'])
    require(record.get('case_spent_usd') == summary['spent_usd'] == (35.168597415 if canary else 46.809458182) and
            record.get('infrastructure_waste_usd') == summary['infrastructure_waste_usd'] == (16.0 if canary else 0),
            'founder ruling monetary facts differ from collected ledger')
    if canary:
        feedback = record.get('feedback') or {}
        require(feedback == dict(round=8, findings=2, reask_unresolved_freshness=True) and
                re.fullmatch('[0-9a-f]{64}', record.get('feedback_report_sha256', '')),
                'invalid pending writer feedback')
    return dict(sha256=pin, record_sha256=digest(record), record=record)


def apply_next(work, accepted, prior):
    """Journal the chain before replacing its head. Retries never reset counters."""
    from restore_ledger import read_object
    from run import case_hash
    from types import SimpleNamespace
    record = accepted['record']; resume = record['resume']
    require(prior is not None and digest(prior) == record['prior_receipt_sha256'] and
            prior['authorization']['sha256'] == record['prior_ruling_sha256'],
            'different or older founder ruling already applied')
    journal = work / ('founder-ruling-sequence-' + str(record['sequence']) + '.json')
    if journal.exists():
        intent = read_object(journal)
        require(intent['authorization'] == accepted and intent['prior_ruling'] == prior,
                'conflicting founder ruling journal')
    else:
        attack = read_object(work / 'attack-state.json')
        require(hashlib.sha256((work / 'attack-state.json').read_bytes()).hexdigest() == resume['attack_state_sha256'],
                'retained final repair differs from founder ruling')
        intent = dict(authorization=accepted, prior_ruling=prior, original_attack_state=attack)
        atomic_json(journal, intent)
    attack = intent['original_attack_state']
    require(digest(attack) == resume['attack_state_record_sha256'] and
            attack.get('round') == resume['round'] and attack.get('round_limit') == resume['round'] and
            attack.get('final_repair') is True and
            attack.get('stop_reason') == ('budget_exhausted' if resume.get('pending_writer') else 'rounds_exhausted') and
            (attack.get('binding') or {}).get('case_id') == record['case'],
            'retained final repair differs from founder ruling')
    require(case_hash(SimpleNamespace(case=work / 'case')) == resume['case_sha256'],
            'retained final case differs from founder ruling')
    if resume.get('pending_writer'):
        from run import attack_report
        report = work / 'attacks' / attack['report']
        parsed = attack_report(report)
        require(attack.get('findings_report') == attack['report'] and not attack.get('repair_pending') and
                parsed is not None and not parsed['unfinished_validation'] and
                len(parsed['blocking']) == record['feedback']['findings'] and
                hashlib.sha256(report.read_bytes()).hexdigest() == record['feedback_report_sha256'],
                'retained pending writer feedback differs from founder ruling')
    after = copy.deepcopy(intent['original_attack_state'])
    after['round_limit'] = record['allowances']['round_limit']
    require(read_object(work / 'attack-state.json') in (intent['original_attack_state'], after),
            'conflicting founder ruling state')
    atomic_json(work / 'attack-state.json', after)
    receipt = dict(authorization=accepted, prior_ruling=prior, reset_once=True,
        changed_allowances=['case_budget_usd', 'round_limit'], preserved_other_allowances=True,
        freshness_verdict_granted=False, stress_verdict_granted=False)
    if resume.get('pending_writer'):
        receipt['feedback_report_sha256'] = record['feedback_report_sha256']
    atomic_json(work / 'founder-ruling-applied.json', receipt)
    return receipt


def apply(work, accepted):
    """Validate first; save originals before resets, so publication can be retried."""
    from restore_ledger import read_object
    work = Path(work)
    done = work / 'founder-ruling-applied.json'
    if done.exists():
        prior = read_object(done)
        if prior['authorization'] == accepted:
            return prior  # retry only: never apply the allowance again
        if accepted['record'].get('version') == 2:
            return apply_next(work, accepted, prior)
        require(False, 'different founder ruling already applied')
    require(accepted['record'].get('version') == 1, 'missing prior founder ruling')
    backup = work / 'founder-ruling-originals.json'
    originals = read_object(backup) if backup.exists() else {
        name: read_object(work / name) for name in ('attack-state.json', 'freshness-repair.json')
        if (work / name).exists()}
    require('attack-state.json' in originals, 'founder ruling requires retained stress receipt')
    attack = originals['attack-state.json']
    record = accepted['record']
    feedback = record['feedback']
    require(attack.get('round') == feedback['round'] and
            attack.get('report') == f"round-{feedback['round']}.json" and
            (attack.get('binding') or {}).get('case_id') == record['case'],
            'retained stress receipt differs from founder ruling')
    # Findings stay sealed. Record only their file digest; validate their shape on
    # the worker, never reconstruct them from the public counts.
    from run import attack_report
    report = work / 'attacks' / attack['report']
    parsed = attack_report(report)
    require(parsed is not None and not attack.get('review_pending'), 'retained stress report is uncommitted')
    findings = [v for v in parsed['blocking'] if v.strip().lower() != 'review incomplete']
    require(feedback['findings'] is None or len(findings) == feedback['findings'],
            'retained finding count differs from founder ruling')
    after = copy.deepcopy(originals)
    after['attack-state.json'].update({key: copy.deepcopy(record['allowances'][key]) for key in
        ('round_limit', 'rereviews', 'release_rereviews', 'release_review_attempts')})
    if 'freshness-repair.json' in after:
        after['freshness-repair.json']['attempts'] = 0
    for name in originals:
        current = read_object(work / name)
        require(current == originals[name] or (backup.exists() and current == after[name]),
                'conflicting founder reset state')
    if not backup.exists(): atomic_json(backup, originals)
    invalidation_path = work / 'founder-ruling-freshness-invalidations.json'
    if not invalidation_path.exists():
        paths = ['public-search.json', 'freshness-verdict.json']
        paths += [p.relative_to(work).as_posix() for p in work.glob('g2-confirm-*/review-completed.json')]
        atomic_json(invalidation_path, {'paths': sorted(paths)})
    invalidated = read_object(invalidation_path)['paths']
    # Invalidate every legacy success layer once, preserving the originals.
    # A retained verdict file alone cannot certify a completed new-release call.
    for name in invalidated:
        require(name in ('public-search.json', 'freshness-verdict.json') or
                re.fullmatch(r'g2-confirm-[0-9]+/review-completed.json', name),
                'invalid freshness invalidation journal')
        path = work / name; saved = path.with_name(path.name + '.pre-founder-ruling')
        require(not path.is_symlink() and not saved.is_symlink(), 'symlink freshness receipt')
        if path.exists():
            if saved.exists():
                require(saved.read_bytes() == path.read_bytes(), 'conflicting saved freshness receipt')
                path.unlink()
            else:
                path.rename(saved)
    for name, value in after.items(): atomic_json(work / name, value)
    receipt = dict(authorization=accepted, feedback_report_sha256=hashlib.sha256(report.read_bytes()).hexdigest(),
                   reset_once=True, invalidated_freshness_receipts=invalidated,
                   freshness_verdict_granted=False, stress_verdict_granted=False)
    atomic_json(done, receipt)
    return receipt


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
