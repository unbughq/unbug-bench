"""Authenticated gate-only recovery and private late-defect handoff."""
import hashlib
import json
from carry_over import digest, require
from registry import atomic_json


def sha(path):
    require(path.is_file() and not path.is_symlink(), "missing regular recovery evidence")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gate_marker(c):
    from run import attack_report, case_hash
    from restore_ledger import read_object
    path = c.work / 'attack-state.json'
    if not path.exists(): return  # practice/legacy inputs earn no gate-only allowance
    attack = read_object(path)
    if 'review_attempt' not in attack: return
    report = c.work / 'attacks' / attack['report']
    parsed = attack_report(report)
    completed = attack.get('review_completed') or {}
    clearance = {}
    if parsed is not None and parsed['blocking']:
        parsed, clearance = cleared_stress(c, attack, report, parsed)
    require(parsed is not None and parsed['complete'] and not parsed['blocking'] and
            not parsed['unfinished_validation'] and not attack.get('review_pending') and
            not attack.get('repair_pending') and not attack.get('final_repair') and
            completed.get('attempt') == attack.get('review_attempt') and
            completed.get('binding') == hashlib.sha256(json.dumps(attack['binding'], sort_keys=True).encode()).hexdigest() and
            completed.get('report_sha256') == sha(report) and
            attack['binding'].get('case') == case_hash(c), 'gate continuation requires completed stress')
    marker = dict(version=1, phase='final_gates', round=attack['round'], case_sha256=case_hash(c),
                  stress_receipt_sha256=sha(path), report_sha256=sha(report), **clearance)
    return marker


def mark_gates(c):
    marker = gate_marker(c)
    if marker is None: return
    atomic_json(c.work / 'gate-continuation.json', marker)
    c.card['gate_continuation'] = marker


def authenticate_gates(c, card):
    from restore_ledger import read_object
    marker = card.get('gate_continuation')
    if marker is None: return
    require(marker == read_object(c.work / 'gate-continuation.json'), 'gate continuation differs from archive')
    require(gate_marker(c) == marker, 'gate continuation evidence changed')
    c.card['gate_continuation'] = marker


def invalidate(c):
    c.card.pop('gate_continuation', None)
    (c.work / 'gate-continuation.json').unlink(missing_ok=True)


def cleared_stress(c, attack, report, original):
    """A freshness-only request may be cleared only by its completed independent review."""
    from restore_ledger import read_object
    from run import attack_report, checked_freshness_verdict, case_hash, freshness_only_clearance
    from admission import search_binding
    from types import SimpleNamespace
    import re
    path = report.with_suffix('.clearance.json')
    proof = read_object(path)
    relative = proof.get('verdict_path')
    require(isinstance(relative, str) and re.fullmatch(r'g2-confirm-[0-9]+/verdict.json', relative),
            'invalid stress freshness clearance path')
    verdict = c.work / relative
    receipt = proof['confirmation']
    binding = receipt['binding']
    snapshot = SimpleNamespace(case=c.case,case_id=attack['binding']['case_id'],
        models=binding['models'],admission_binding=binding.get('reservation'),freshness_confirmed_hits=0)
    rows = proof['rows']
    require(proof.get('source_sha256') == sha(report) and
            receipt.get('verdict_path') == relative and
            read_object(verdict.parent/'review-completed.json') == {'binding':binding} and
            read_object(verdict).get('hits') == receipt.get('hits') and
            binding == {**search_binding(snapshot,rows),'confirmation_contract':1} and
            rows and not checked_freshness_verdict(snapshot,rows,receipt.get('hits')) and
            not snapshot.freshness_confirmed_hits and
            proof.get('case_sha256') == case_hash(c), 'unverified stress freshness clearance')
    resolved = report.with_name(report.stem+'-writer.json')
    parsed = attack_report(resolved)
    require(proof.get('resolved_sha256') == sha(resolved) and
            parsed == freshness_only_clearance(original), 'stress clearance changed findings')
    return parsed, {'clearance_sha256':sha(path)}


def stop_defect(c, gate):
    from run import BudgetError, case_hash
    detail = c.card.get('failed_detail')
    record = dict(version=1, gate=gate, detail=detail, case_sha256=case_hash(c),
                  round_limit=c.args.rounds, builder_rounds=c.card.get('builder_rounds', 0),
                  stress_receipt_sha256=sha(c.work / 'attack-state.json'))
    atomic_json(c.work / 'late-defect.json', record)
    # Detailed findings belong only to the encrypted checkpoint.
    c.card['late_defect'] = dict(gate=gate, record_sha256=digest(record))
    c.card['gates'].pop(gate, None)
    c.card.get('gate_results', {}).pop(gate, None)
    c.card.pop('failed_gate', None)
    c.card.pop('failed_detail', None)
    invalidate(c)
    c.stopped = True
    raise BudgetError('late_defect_needs_ruling:' + gate)
