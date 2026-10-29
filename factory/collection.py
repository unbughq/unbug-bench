"""Verify exactly the archives named by this collection's public cards."""
import hashlib
import json
from pathlib import Path
import re
import sys


def verify(directory, names, *, work_cases=(), has_work=False):
    directory, names = Path(directory), set(names)
    verified = set()
    for name in sorted(names):
        if not name.endswith('.scorecard.json'): continue
        card_path = directory / name
        if card_path.is_symlink(): raise ValueError('linked scorecard')
        card = json.loads(card_path.read_text())
        case = name.removesuffix('.scorecard.json')
        if not isinstance(card, dict): raise ValueError('invalid scorecard')
        probe = card.get('kind') == 'provider-preflight' and card.get('scope') == 'availability_only'
        startup = card.get('status') == 'startup_failed' and card.get('gates') == {}
        if not has_work and (probe or startup) and not card.get('sha256') and not card.get('archive'):
            continue
        if card.get('case') != case and not (card.get('kind') == 'g11-independent-review'
                                             and case == 'g11-review-' + str(card.get('case'))):
            raise ValueError('scorecard identity mismatch')
        want = card.get('sha256')
        if not isinstance(want, str) or not re.fullmatch('[a-f0-9]{64}', want):
            raise ValueError('scorecard has no archive digest')
        allowed = {case + '.tar.gz.age', case + '.checkpoint.tar.gz.age'}
        archive = card.get('archive')
        if archive is not None:
            if not isinstance(archive, str) or Path(archive).name not in allowed:
                raise ValueError('scorecard names a foreign archive')
            allowed = {Path(archive).name}
        matches = []
        for candidate in allowed & names:
            path = directory / candidate
            if path.is_symlink() or not path.is_file(): continue
            h = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
            if h.hexdigest() == want: matches.append(candidate)
        if len(matches) != 1: raise ValueError('missing, stale or ambiguous exact archive for ' + case)
        verified.add(case)
    if has_work and (not work_cases or not verified or not set(work_cases) <= verified):
        raise ValueError('unsealed work lacks its exact verified card/archive')
    return verified


if __name__ == '__main__':
    try:
        verify(sys.argv[1], sys.argv[3].split(), has_work=sys.argv[2] == 'yes',
               work_cases=sys.argv[4].split())
    except (ValueError, OSError) as error:
        sys.exit(str(error))
