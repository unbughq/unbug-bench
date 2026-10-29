"""Thin paid rehearsal entry point on a separately prepared public practice case.

The caller provisions the disposable worker, real model drivers/UID walls, a
complete public case + truthful freshness evidence, and a throwaway age recipient.
No fixture verdict, failed attempt or gate credit is synthesized here.
"""
from registry import atomic_json

PREFIX = 'case-late-rehearsal-'


def recipient(value):
    """Validate an age X25519 public recipient, including its Bech32 checksum."""
    alphabet = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'
    if not isinstance(value,str) or not value.startswith('age1') or len(value)!=62:
        raise ValueError('rehearsal requires an explicit age public recipient')
    if any(char not in alphabet for char in value[4:]): raise ValueError('invalid rehearsal recipient')
    numbers = [alphabet.index(char) for char in value[4:]]
    check = 1
    for item in [ord(c)>>5 for c in 'age']+[0]+[ord(c)&31 for c in 'age']+numbers:
        top = check>>25
        check = ((check & 0x1ffffff)<<5)^item
        for bit,poly in enumerate((0x3b6a57b2,0x26508e6d,0x1ea119fa,0x3d4233dd,0x2a1462b3)):
            if (top>>bit)&1: check ^= poly
    if check!=1 or numbers[-7]&15: raise ValueError('invalid rehearsal recipient checksum')
    return value


def check(c):
    from restore_ledger import read_object
    if (not c.case_id.startswith(PREFIX) or c.args.dry_run or
            c.args.audit_fairness or c.args.rehearse_only or c.args.concurrent_roles or
            c.args.pilot_tries != 1 or c.args.runs != 1 or c.args.pilot_runs != 1 or
            c.args.calibrator_minutes > 3 or c.args.case_budget > 25):
        raise ValueError('rehearsal requires isolated namespace, serial one-try/one-run caps, <=3 minutes and <=$25')
    source = read_object(c.work / 'rehearsal-source.json')
    if source.get('kind') != 'public-practice' or source.get('real_case') is not False:
        raise ValueError('rehearsal requires explicit public-practice provenance')
    if c.card.get('audit_source') or c.card.get('founder_ruling'):
        raise ValueError('rehearsal cannot inherit real-case gates or rulings')
    # Both branches use ordinary whole-case accounting. The adapter is no budget bypass.
    if not getattr(c.args, 'no_early_probe', False): raise ValueError('disable early probe for short rehearsal')


def after_attempt(c, folder):
    """Interrupt exactly once after a real atomic G10 commit; the receipt survives restore."""
    if folder != 'strong_calibrator' or not getattr(c.args, 'rehearsal_interrupt_g10', False): return
    from run import PauseRequested, jload
    from late_recovery import sha
    marker = c.work / 'rehearsal-g10-interruption.json'
    if marker.exists(): return
    atomic_json(marker, dict(results_sha256=sha(c.work / folder / 'results.json'),
        calls=jload(c.ledger, {}).get('calls'), case=c.case_id, intentional=True))
    raise PauseRequested()


def run(c, r):
    check(c)
    # Production build performs deferred G2 before stress recovery. A complete
    # practice fixture must have honest, flagged search rows to exercise confirmation.
    if not any(row.get('hit') or row.get('ambiguous') for row in r.freshness_lines(c)):
        raise ValueError('deferred G2 rehearsal requires truthful flagged public evidence')
    r.build(c)
    if c.card.get('build_deferred') != 'existing_public_match_requires_G2':
        raise ValueError('deferred G2 was not exercised')
    ok, info = r.g3(c)
    if not ok: raise ValueError('rehearsal runtime preparation failed')
    c.audit_gates = ['G16', 'G10', 'G17', 'G11']
    r.validate_and_repair(c)
    if c.card.get('failed_gate') or c.stopped: return
    if not getattr(c, 'pilot_passes', None):
        raise ValueError('G11 rehearsal needs an actual solved tester guard')
    # G12 follows through main's ordinary retain_delivery + age seal. A no-op
    # G17 remains explicitly uncovered; rehearse its review on a genuine failed
    # attempt separately and retain its verdict/crash evidence before restaging.
    c.card['late_rehearsal'] = dict(real_cases_used=False,
        g17_review_exercised=bool(c.card.get('gate_results', {}).get('G17', {}).get('needed')),
        g11_solved_guard=True, interruption_recorded=(c.work/'rehearsal-g10-interruption.json').exists())
