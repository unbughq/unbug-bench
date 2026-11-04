#!/usr/bin/env python3
"""Read-only sealed-case qualification inventory from public evidence only.

  python3 -B tools/sealed_inventory.py [--cards DIR] [--inventory JSON] [--registry JSON] [--markdown]
  python3 -B tools/sealed_inventory.py --round round.json [--expect 24]

--inventory and --registry default to the committed 2026-10-30 ciphertext inventory
and registry index. A freeze-time run must pass snapshots taken after the last case
sealed; a case absent from a stale snapshot stays non-eligible.

Reads public scorecards, the 2026-10-29 VM card record, the 2026-10-30 ciphertext
inventory and the statement registry index. Never opens a .age file or a key file
and makes no network, Docker, model or cloud call. Public evidence can disqualify a
case or make it eligible for the decrypting audit; it never qualifies one.
Design: docs/designs/sealed-audit-exam-packaging.md.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'factory'))

VM_CARDS = ROOT / 'docs/designs/stream-d-cost-evidence.json'
CIPHERTEXTS = ROOT / 'docs/reports/batch-service-inventory-20261030.json'
REGISTRY = ROOT / 'sealed/statement-registry/registry.json'
REAL_SOURCES = {'port', 'hunt'}
WIPE_ZERO = ('plaintext_files_left', 'named_dirs_left')
WIPE_FALSE = ('guard_image_left', 'db_volume_left')
CRITERIA = ('distinct_bug', 'reference_fix', 'legitimate_behavior', 'discoverable',
            'deterministic_scorer', 'adversarial_checks', 'complete_evidence', 'separation')
HEADINGS = ('Distinct bug', 'Reference fix', 'Legitimate behavior', 'Discoverable',
            'Deterministic scorer', 'Adversarial', 'Complete evidence', 'Separation')


def load(path):
    return json.loads(Path(path).read_text())


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(card):
    return hashlib.sha256(json.dumps(card, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def gate(card, name):
    value = (card.get('gates') or {}).get(name)
    return 'pass' if value == 'pass' else 'fail:' + name if value == 'fail' else 'missing:' + name


def parts(*items):
    """Every non-pass part, in order; the table cell is the first or 'pass'."""
    values = (item() if callable(item) else item for item in items)
    return [value for value in values if value != 'pass']


def excluded(card, case):
    if card.get('dry_run') is True:
        return 'dry_run'
    if card.get('source') not in REAL_SOURCES:
        return 'source=' + str(card.get('source'))
    if re.search('practice|smoke', case):
        return 'practice/smoke id'
    return None


def metadata(card, case):
    from sealed_audit import verify_exam_metadata
    try:
        verify_exam_metadata(card, case)
        return 'ok'
    except ValueError as error:  # Any other exception is a malformed card: abort with its ID.
        return str(error)
    except Exception as error:
        raise RuntimeError(f'{case}: {type(error).__name__}: {error}') from error


def evidence(ciphertexts=CIPHERTEXTS, registry=REGISTRY):
    vm = {Path(c['path']).name[:-len('.scorecard.json')]: c['canonical_json_sha256']
          for c in load(VM_CARDS)['vm_cards']}
    ciphertext, cards = {}, {}
    record = load(ciphertexts)
    for side in ('mac', 'vm'):
        for entry in record[side]['checkpoints']:
            cards.setdefault(entry['case'], set()).add(entry['card_sha256'])
            for item in entry['files']:  # Final sealed archives only, never checkpoints.
                if item['name'] == entry['case'] + '.tar.gz.age':  # This case's own archive.
                    ciphertext.setdefault((entry['case'], item['sha256']), set()).add(side)
    return vm, ciphertext, cards, load(registry)['entries']


def registry_cell(entry):
    """Pass only a fresh reservation that finished screening (factory/registry.py)."""
    if entry is None:
        return 'missing:registry-entry'
    if entry.get('status') == 'released':
        return 'fail:registry-released'
    return 'pass' if entry.get('complete') is True and entry.get('status') == 'completed' \
        else 'missing:registry-screening'


def cells(card, case, meta, sides, registry):
    def dedup():
        value = card.get('dedup')
        if not isinstance(value, dict):
            return 'missing:dedup'
        return 'pass' if value.get('duplicate_of') is None else 'fail:duplicate_of=' + str(value['duplicate_of'])

    def screening():
        return registry_cell(registry.get(case))

    def wipe():
        value = card.get('wipe')
        clean = (isinstance(value, dict) and all(value.get(k) == 0 for k in WIPE_ZERO) and
                 all(value.get(k) is False for k in WIPE_FALSE) and value.get('factory_cleanup_ok') is True)
        return 'pass' if clean else 'missing:wipe-record'

    g = lambda name: gate(card, name)
    return {
        'distinct_bug': parts(g('G2'), g('G4'), dedup, screening, 'unavailable:screening-verdict-content'),
        'reference_fix': parts(g('G5')),
        'legitimate_behavior': parts(g('G5'), g('G9')),
        'discoverable': parts(g('G8'), g('G16')),
        'deterministic_scorer': parts(g('G7')),
        'adversarial_checks': parts(*(g(n) for n in ('G6', 'G11', 'G13', 'G14', 'G15'))),
        'complete_evidence': parts(g('G10'), g('G12'), g('G17'),
                                   'pass' if meta == 'ok' else 'fail:metadata',
                                   'pass' if sides else 'missing:ciphertext-inventory',
                                   'unavailable:archive-backed-verify_exam'),
        'separation': parts(wipe, 'unavailable:no-exposure-attestation'),
    }


def inventory(cards_dir=ROOT / 'sealed', ciphertexts=CIPHERTEXTS, registry_path=REGISTRY):
    cards_dir = Path(cards_dir)
    vm, ciphertext, recorded_cards, registry = evidence(ciphertexts, registry_path)
    reviews = {}
    for path in sorted(cards_dir.glob('g11-review-*.scorecard.json')):
        review = load(path)
        reviews.setdefault(review.get('case'), []).append(
            {'status': review.get('status'), 'verdict': review.get('verdict')})
    hidden, skipped = [], []
    for path in sorted(cards_dir.glob('case-*.scorecard.json')):
        raw = path.read_bytes()
        card = json.loads(raw)
        case = path.name[:-len('.scorecard.json')]
        if card.get('case') != case:
            raise ValueError('card names a different case: ' + path.name)
        file_hash = hashlib.sha256(raw).hexdigest()
        vm_hash = 'not-recorded' if case not in vm else 'match' if vm[case] == canonical(card) else 'differs'
        reason = excluded(card, case)
        if reason:
            skipped.append({'case': case, 'reason': reason, 'card_sha256': file_hash,
                            'hashes': {'vm_20261029': vm_hash}})
            continue
        meta = metadata(card, case)
        sides = sorted(ciphertext.get((case, card.get('sha256')), ()))
        findings = cells(card, case, meta, sides, registry)
        criteria = {k: v[0] if v else 'pass' for k, v in findings.items()}
        recorded = recorded_cards.get(case)
        hidden.append({
            'case': case,
            'card_sha256': file_hash,
            'stop': card.get('terminal_stop') or card.get('failed_gate') and 'failed ' + card['failed_gate']
                    or card.get('status') or 'none',
            'gates_passed': sorted((k for k, v in (card.get('gates') or {}).items() if v == 'pass'),
                                   key=lambda k: int(k[1:])),
            'metadata': meta,
            'criteria': criteria,
            'findings': findings,
            'public_eligible': all(v.startswith('unavailable:') for f in findings.values() for v in f),
            'qualified': not any(findings.values()),
            'hashes': {
                'vm_20261029': vm_hash,
                'card_20261030': 'not-recorded' if not recorded else
                                 'match' if recorded == {file_hash} else 'differs',
                'ciphertext_20261030': sides},
            'g11_reviews': reviews.get(case, [])})
    elsewhere = sorted(set(vm) - {p.name[:-len('.scorecard.json')] for p in cards_dir.glob('case-*.scorecard.json')}) \
        if cards_dir.resolve() == (ROOT / 'sealed').resolve() else []
    return {'cards': str(cards_dir), 'inputs': {
                'ciphertext_inventory': {'path': str(ciphertexts), 'sha256': file_sha(ciphertexts)},
                'registry': {'path': str(registry_path), 'sha256': file_sha(registry_path)},
                'vm_cards_20261029': {'path': str(VM_CARDS), 'sha256': file_sha(VM_CARDS)}},
            'hidden': hidden, 'excluded': skipped,
            'recorded_elsewhere_20261029': elsewhere,
            'counts': {'hidden': len(hidden), 'excluded': len(skipped),
                       'public_eligible': sum(c['public_eligible'] for c in hidden),
                       'qualified': sum(c['qualified'] for c in hidden)}}


def markdown(result):
    short = lambda v: v.replace('unavailable:', 'unavail:')
    lines = ['| Case | Stop | Gates passed | ' + ' | '.join(HEADINGS) + ' | Public-eligible |',
             '|---|---|---|' + '---|' * len(HEADINGS) + '---|']
    for c in result['hidden']:
        gates = ','.join(c['gates_passed']) or '-'
        lines.append(f"| `{c['case']}` | {c['stop']} | {gates} | " +
                     ' | '.join(short(c['criteria'][k]) for k in CRITERIA) +
                     f" | {'yes' if c['public_eligible'] else 'no'} |")
    counts = result['counts']
    lines += ['', f"Hidden {counts['hidden']}, excluded {counts['excluded']}, public-eligible "
              f"{counts['public_eligible']}, qualified {counts['qualified']}.", '']
    lines += [f"- Excluded `{e['case']}`: {e['reason']}" for e in result['excluded']]
    return '\n'.join(lines) + '\n'


def check_round(path, result, expect=24):
    spec = load(path)
    cases = [Path(c['archive']).name.removesuffix('.tar.gz.age') for c in spec.get('cases', [])]
    hidden = {c['case']: c for c in result['hidden']}
    skipped = {e['case']: e['reason'] for e in result['excluded']}
    errors, seen = [], set()
    for case in cases:
        if case in seen:
            errors.append('duplicate ' + case)
            continue
        seen.add(case)
        if case in skipped:
            errors.append(f'not hidden {case}: {skipped[case]}')
        elif case not in hidden:
            errors.append('unknown case ' + case)
        elif not hidden[case]['public_eligible']:
            cell = next(v for f in hidden[case]['findings'].values() for v in f
                        if not v.startswith('unavailable:'))
            errors.append(f'not eligible {case}: {cell}')
    if len(cases) != expect:
        errors.append(f'expected {expect} cases, got {len(cases)}')
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--cards', type=Path, default=ROOT / 'sealed')
    parser.add_argument('--inventory', type=Path, default=CIPHERTEXTS, help='ciphertext inventory JSON')
    parser.add_argument('--registry', type=Path, default=REGISTRY, help='statement registry index JSON')
    parser.add_argument('--markdown', action='store_true')
    parser.add_argument('--round', type=Path)
    parser.add_argument('--expect', type=int, default=24)
    args = parser.parse_args(argv)
    result = inventory(args.cards, args.inventory, args.registry)
    if args.round:
        errors = check_round(args.round, result, args.expect)
        for line in errors:
            print(line)
        return 1 if errors else 0
    sys.stdout.write(markdown(result) if args.markdown else json.dumps(result, indent=2, sort_keys=True) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
