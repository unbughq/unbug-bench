"""Host transport for stopped candidate workers: ciphertext and public hashes only.

Run through statements-round.sh after collection. Hetzner discovers parked workers;
Boat requires explicit worker IDs. Delivery never resumes a run: the approved launcher
must preserve its pinned configuration and cumulative budget. No host decryption occurs.
"""
import argparse
import hashlib
import json
import pathlib
import re
import shlex
import subprocess
import tarfile
import tempfile
import uuid
from registry import Registry, identifier


PUBLIC_CARDS = """import glob,json
out=[]
for p in glob.glob('/home/user/sealed/case-*.scorecard.json'):
 c=json.load(open(p))
 if c.get('terminal_stop') in ('statement-ready','admission_registry_unavailable'):
  out.append({'case_id':c.get('case_id', c.get('case')), 'statement_sha256':c.get('statement_sha256')})
print(json.dumps(out))
"""


def prepare_restore(root, case, archive, destination, *, history_root=None):
    """Preflight a collected statement handoff without opening any case ciphertext.

    Other restore modes retain their existing path. A reservation stays immutable
    on retries; prepare imports history before making a new reservation.
    """
    root, archive = pathlib.Path(root), pathlib.Path(archive)
    case = identifier(case)
    sealed = root / 'sealed'
    card_path = sealed / (case + '.scorecard.json')
    if not card_path.is_file() or card_path.is_symlink():
        raise ValueError('missing collected restore scorecard')
    card = json.loads(card_path.read_text())
    if not isinstance(card, dict): raise ValueError('invalid restore scorecard')
    waiting = (card.get('terminal_stop') in ('statement-ready', 'admission_registry_unavailable') or
               card.get('admission', {}).get('status') in ('waiting', 'awaiting_shared_reservation'))
    if not waiting:
        return None
    identities = [card[key] for key in ('case', 'case_id') if key in card]
    digest = card.get('statement_sha256')
    if (not identities or any(value != case for value in identities) or
            not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest) or
            card.get('status') != 'stopped'):
        raise ValueError('candidate scorecard identity or statement digest mismatch')
    if (archive not in (sealed / (case + '.checkpoint.tar.gz.age'), sealed / (case + '.tar.gz.age')) or
            not archive.is_file() or archive.is_symlink()):
        raise ValueError('missing or ambiguous collected candidate archive')
    with archive.open('rb') as stream:
        if not stream.read(64).startswith((b'age-encryption.org/v1', b'-----BEGIN AGE ENCRYPTED FILE-----')):
            raise ValueError('candidate archive must be age ciphertext')
        stream.seek(0)
        if hashlib.file_digest(stream, 'sha256').hexdigest() != card.get('sha256'):
            raise ValueError('candidate archive scorecard digest mismatch')
    candidate = sealed / (case + '.statement.age')
    if not candidate.is_file(): raise ValueError('missing collected candidate statement ciphertext')
    for ciphertext in sealed.glob('*.statement.age'):
        if (not ciphertext.is_file() or ciphertext.is_symlink() or not ciphertext.read_bytes().startswith(
                (b'age-encryption.org/v1', b'-----BEGIN AGE ENCRYPTED FILE-----'))):
            raise ValueError('invalid collected statement ciphertext')
    # Older cards have only the worker's plaintext digest. The worker verifies the
    # restored statement against the reservation before its first admission call.
    if (card.get('statement_cipher_sha256') is not None and
            hashlib.sha256(candidate.read_bytes()).hexdigest() != card['statement_cipher_sha256']):
        raise ValueError('candidate statement ciphertext scorecard digest mismatch')
    history = pathlib.Path(history_root) / 'sealed' if history_root is not None else sealed
    snapshots = prepare(sealed, history / 'statement-registry', {case: digest}, destination,
                        history_sealed=history)
    return snapshots[case]


def prepare(sealed, registry_root, candidates, destination, *, history_sealed=None):
    """Import all collected historical ciphertext before reserving this wave in stable order."""
    sealed, destination = pathlib.Path(sealed), pathlib.Path(destination)
    candidates = dict(candidates)
    registry = Registry(registry_root)
    history = pathlib.Path(history_sealed) if history_sealed is not None else sealed
    ciphertexts = {p.name.removesuffix('.statement.age'): p for p in history.glob('*.statement.age')}
    ciphertexts.update({case: sealed / (case + '.statement.age') for case in candidates
                        if (sealed / (case + '.statement.age')).is_file()})
    if not candidates or not set(candidates) <= set(ciphertexts):
        raise ValueError('collect every candidate statement ciphertext before admission')
    for case in sorted(ciphertexts):
        identifier(case)
        if case not in candidates:
            card = history / (case + '.scorecard.json')
            digest = json.loads(card.read_text()).get('statement_sha256') if card.exists() else None
            registry.import_historical(case, ciphertexts[case], statement_sha256=digest)
    snapshots = {}
    for case, digest in sorted(candidates.items()):
        card_path = sealed / (case + '.scorecard.json')
        card = json.loads(card_path.read_text()) if card_path.exists() else {}
        rejected = [row.get('statement_sha256') for row in card.get('rejected_candidates', [])]
        if len(rejected) > 3: raise ValueError('candidate selection bound exceeded')
        registry.replace_rejected(case, digest, ciphertexts[case], rejected)
        search = sealed / (case + '.search.age')
        metadata = card.get('public_search')
        if search.is_file() and metadata:
            # A newly selected candidate cannot inherit the previous candidate's evidence.
            if metadata.get('binding', {}).get('statement_sha256') == digest:
                registry.search_receipt(case, metadata, search)
        snapshot = destination / case
        registry.export(case, snapshot)
        snapshots[case] = snapshot
    return snapshots


def command(args, capture=False, stdin=None):
    result = subprocess.run(args, check=True, text=True, stdin=stdin if stdin is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout if capture else None


def worker_id(value, provider):
    pattern = r'[0-9]+' if provider == 'hetzner' else r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}'
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError('invalid worker id')
    return value


def install(boat, server, snapshot, provider='hetzner', *, guard='', idempotent=False):
    """Upload a new complete private snapshot, then replace the parked worker's directory."""
    worker_id(str(server), provider)
    files = sorted(pathlib.Path(snapshot).iterdir())
    if not any(file.name in ('admission.json', 'selection-board.json') for file in files):
        raise ValueError('missing admission attestation')
    for file in files:
        if (not file.is_file() or file.is_symlink() or
                (file.name not in ('admission.json', 'selection-board.json', 'search.age') and not re.fullmatch(r'case-[A-Za-z0-9-]+\.statement\.age', file.name))):
            raise ValueError('unexpected registry snapshot file')
        if file.name.endswith('.age') and not file.read_bytes().startswith(
                (b'age-encryption.org/v1', b'-----BEGIN AGE ENCRYPTED FILE-----')):
            raise ValueError('snapshot statement must be age ciphertext')
    hashes = {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in files}
    if idempotent:
        check = guard + ("import pathlib,hashlib; p=pathlib.Path('/home/user/statements'); "
                f"expected={hashes!r}; "
                "actual={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in p.iterdir() if f.is_file()} if p.is_dir() else {}; "
                "print('installed' if actual==expected else 'missing')")
        if command([boat, 'ssh', str(server), 'python3 -c ' + shlex.quote(check)], capture=True).strip() == 'installed':
            return
    stage = '.statements-stage-' + uuid.uuid4().hex
    if provider == 'boat':
        # One bounded stream replaces one connection per statement; the same hash fence follows.
        with tempfile.TemporaryFile() as bundle:
            with tarfile.open(fileobj=bundle, mode='w:gz') as archive:
                for file in files: archive.add(file, arcname=file.name, recursive=False)
            bundle.seek(0)
            command([boat, '--stdin', 'ssh', str(server),
                     f'set -eu; umask 077; mkdir /home/user/{stage}; tar -xzf - -C /home/user/{stage}'], stdin=bundle)
    else:
        command([boat, 'ssh', str(server), f'umask 077; mkdir /home/user/{stage}'])
        for file in files:
            command([boat, 'scp', str(file), f'{server}:/home/user/{stage}/{file.name}'])
    swap = guard + ("import pathlib,shutil,hashlib; h=pathlib.Path('/home/user'); "
            f"s=h/{stage!r}; p=h/'statements'; old=h/{(stage + '-previous')!r}; "
            f"expected={hashes!r}; "
            "actual={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in s.iterdir() if f.is_file()}; "
            "assert actual == expected, 'snapshot transfer digest mismatch'; "
            "p.rename(old) if p.exists() else None; s.rename(p); "
            "shutil.rmtree(old) if old.exists() else None")
    command([boat, 'ssh', str(server), 'python3 -c ' + shlex.quote(swap)])


def stopped_guard(proof, snapshot=None):
    """Worker-side checks repeated before snapshot swap and under the resume lock."""
    expected = {key: proof[key] for key in ('case', 'card_sha256', 'archive', 'generation',
                                           'statement_sha256', 'statement_cipher_sha256')}
    expected['budget_sha256'] = hashlib.sha256(json.dumps(proof['budget'], sort_keys=True).encode()).hexdigest()
    code = "import pathlib,json,hashlib,subprocess; h=pathlib.Path.home(); "
    code += f"e={expected!r}; c=e['case']; sealed=h/'sealed'; "
    if proof.get('lock_owner'):
        code += f"assert (sealed/'.factory-restart.lock/owner').read_text()=={proof['lock_owner']!r}, 'restart lock owner changed'; "
    code += "assert (sealed/'DONE').read_text().strip()==c, 'wrong DONE'; "
    code += "assert subprocess.run(['pgrep','-f','^python3 .*factory/'+'run'+'.py'],stdout=subprocess.DEVNULL).returncode==1, 'live or uncertain runner'; "
    code += "sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest(); "
    code += "assert sha(sealed/(c+'.scorecard.json'))==e['card_sha256'], 'stale card'; "
    code += "assert sha(sealed/e['archive'])==e['generation'], 'stale archive'; "
    code += "assert sha(sealed/(c+'.statement.age'))==e['statement_cipher_sha256'], 'stale statement ciphertext'; "
    code += "assert sha(h/'work'/c/'case/statement.md')==e['statement_sha256'], 'stale selected statement'; "
    code += "assert hashlib.sha256(json.dumps(json.loads((sealed/(c+'.continuation-budget.json')).read_text()),sort_keys=True).encode()).hexdigest()==e['budget_sha256'], 'stale or active budget'; "
    if snapshot is not None:
        code += f"expected_snapshot={snapshot!r}; "
        code += "assert {p.name:sha(p) for p in (h/'statements').iterdir()}==expected_snapshot, 'stale reservation snapshot'; "
    return code


def same_worker_handoff(root, history_root, worker, case, remaining, args, handoffs, *, proof_path=None):
    """Collected checkpoint -> authoritative reservation -> same stopped worker.

    Uncertain results keep the VM. A journal can reclaim its token and verify an
    already-installed snapshot without repeating the swap.
    No model call, host decryption, budget reset or worker creation is performed here.
    """
    from restart import plan
    root, history_root = pathlib.Path(root), pathlib.Path(history_root)
    worker_id(worker, 'boat'); identifier(case)
    sealed = root / 'sealed'
    card_path = sealed / (case + '.scorecard.json')
    if card_path.is_symlink(): raise ValueError('symlink candidate card')
    card = json.loads(card_path.read_text())
    if card.get('terminal_stop') != 'admission_registry_unavailable':
        raise ValueError('not an admission handoff')
    # Require the complete current configuration, rather than inventing legacy limits.
    config = card.get('recovery_config')
    if not isinstance(config, dict) or config.get('version') != 1:
        raise ValueError('missing admission recovery configuration')
    argv = shlex.split(args)
    def option(flag):
        values = [argv[i + 1] for i, value in enumerate(argv[:-1]) if value == flag]
        values += [value.split('=', 1)[1] for value in argv if value.startswith(flag + '=')]
        if len(values) != 1: raise ValueError('missing or ambiguous original option: ' + flag)
        return values[0]
    for name, value in config.items():
        if name != 'version' and float(option('--' + name.replace('_', '-'))) != float(value):
            raise ValueError('admission configuration changed')
    if option('--source') != card.get('source') or int(option('--rotation-slot')) != card.get('rotation_slot'):
        raise ValueError('admission source or rotation changed')
    for role, flag in (('writer', 'builder'), ('stress_tester', 'attacker'),
                       ('strong_calibrator', 'strong-calibrator'), ('reviewer', 'reviewer1'),
                       ('easy_calibrator', 'easy-calibrator')):
        for key, suffix in (('model', ''), ('effort', '-effort')):
            if option('--' + flag + suffix) != card['roles'][role][key]:
                raise ValueError('admission model or effort changed')
    if '--seed' in argv and int(option('--seed')) != card.get('seed'):
        raise ValueError('admission seed changed')
    archive = next((p for p in (sealed / (case + suffix) for suffix in
                    ('.checkpoint.tar.gz.age', '.tar.gz.age'))
                    if p.is_file() and not p.is_symlink() and
                    hashlib.sha256(p.read_bytes()).hexdigest() == card.get('sha256')), None)
    if archive is None: raise ValueError('missing verified admission checkpoint')
    cipher = sealed / (case + '.statement.age')
    cipher_sha = hashlib.sha256(cipher.read_bytes()).hexdigest()
    if cipher.is_symlink() or card.get('statement_cipher_sha256') != cipher_sha:
        raise ValueError('missing authenticated statement ciphertext digest')
    proof = dict(case=case, worker=worker, generation=card['sha256'], archive=archive.name,
        card_sha256=hashlib.sha256(card_path.read_bytes()).hexdigest(),
        statement_sha256=card.get('statement_sha256'), statement_cipher_sha256=cipher_sha,
        budget=card.get('continuation_budget'), candidate_attempts=card.get('candidate_attempts'),
        handoffs=handoffs, snapshot_sha256='pending', lock_owner=uuid.uuid4().hex)
    plan(card_path, 0, remaining, args, admission_proof=proof)  # before any remote/registry mutation
    history = history_root / 'sealed'
    registry = history / 'statement-registry/registry.json'
    if not history.is_dir() or not registry.is_file() or registry.is_symlink():
        raise ValueError('missing authoritative shared statement registry')
    historical = {p.name.removesuffix('.statement.age'): p for p in history.glob('*.statement.age')
                  if p.name != case + '.statement.age'}
    if not historical or any(p.is_symlink() or not p.is_file() or
            not (history / (name + '.scorecard.json')).is_file()
            for name, p in historical.items()):
        raise ValueError('missing or unsafe global statement history')
    # A missing known statement must never silently shrink an isolated corpus. The
    # registry object store is authoritative; a loose copy is optional (e.g. another
    # worker's reservation), but its registry object must exist and verify.
    state = json.loads(registry.read_text())
    objects = registry.parent / 'objects'
    def stored(digest):
        obj = objects / (digest + '.age')
        return (obj.is_file() and not obj.is_symlink() and
                hashlib.sha256(obj.read_bytes()).hexdigest() == digest)
    if any(name not in historical and not stored(entry['cipher_sha256'])
           for name, entry in state['entries'].items()
           if name != case and entry['status'] != 'released'):
        raise ValueError('incomplete global statement history')
    if proof_path is not None:
        from registry import atomic_json
        journal = pathlib.Path(str(proof_path) + '.pending')
        if journal.exists():
            previous = json.loads(journal.read_text())
            if any(previous.get(k) != v for k, v in proof.items() if k not in ('lock_owner', 'snapshot_sha256')):
                raise ValueError('stale handoff journal')
            proof = previous
        else:
            atomic_json(journal, proof)
        # Journal the token before any transport. A reboot can safely reclaim only this token.
        pathlib.Path(str(proof_path).removesuffix('.json') + '.attempted').touch()
    boat = str(root / 'bin/boat-call')
    guard = stopped_guard(proof)
    # Claim once and retain ownership through transfer, swap and detached startup.
    # A failed/uncertain operation leaves the token in place for reconciliation.
    claim = ("import pathlib; lock=pathlib.Path.home()/'sealed/.factory-restart.lock'; "
             f"token={proof['lock_owner']!r}; ")
    if proof_path is None:
        claim += "lock.mkdir(); (lock/'owner').write_text(token); "
    else:
        claim += ("assert not lock.exists() or (lock/'owner').read_text()==token, 'restart lock owner changed'; "
                  "None if lock.exists() else (lock.mkdir(), (lock/'owner').write_text(token)); ")
    command([boat, 'ssh', worker, 'python3 -c ' + shlex.quote(claim + guard)])
    with tempfile.TemporaryDirectory(prefix='factory-admission-handoff-') as tmp:
        snapshot = prepare_restore(root, case, archive, tmp, history_root=history_root)
        attestation = json.loads((snapshot / 'admission.json').read_text())
        if not set(historical) <= set(attestation['statements']):
            raise ValueError('reservation omits global statement history')
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshot.iterdir()}
        proof['snapshot_sha256'] = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
        install(boat, worker, snapshot, 'boat', guard=guard, idempotent=proof_path is not None)
    proof['resume_guard'] = 'python3 -c ' + shlex.quote(stopped_guard(proof, hashes))
    cleanup = ("import pathlib; lock=pathlib.Path.home()/'sealed/.factory-restart.lock'; "
               f"assert (lock/'owner').read_text()=={proof['lock_owner']!r}, 'restart lock owner changed'; "
               "(lock/'owner').unlink(); lock.rmdir()")
    proof['resume_trap'] = 'trap ' + shlex.quote('python3 -c ' + shlex.quote(cleanup)) + ' 0'
    plan(card_path, 0, remaining, args, admission_proof=proof)
    return proof


def main(argv=None):
    import sys
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == '--same-worker-handoff':
        p = argparse.ArgumentParser()
        p.add_argument('--same-worker-handoff', action='store_true')
        p.add_argument('--root', type=pathlib.Path, required=True)
        p.add_argument('--history-root', type=pathlib.Path, required=True)
        p.add_argument('--worker', required=True)
        p.add_argument('--case', required=True)
        p.add_argument('--remaining', type=float, required=True)
        p.add_argument('--args', required=True)
        p.add_argument('--handoffs', type=int, required=True)
        p.add_argument('--proof', type=pathlib.Path, required=True)
        a = p.parse_args(argv)
        proof = same_worker_handoff(a.root, a.history_root, a.worker, a.case,
                                   a.remaining, a.args, a.handoffs, proof_path=a.proof)
        from registry import atomic_json
        atomic_json(a.proof, proof)
        return
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent.parent)
    p.add_argument('--registry-root', type=pathlib.Path)
    p.add_argument('--provider', choices=('hetzner', 'boat'), default='hetzner')
    p.add_argument('--worker-id', action='append', default=[], help='explicit Boat worker ID; repeat for a wave')
    a = p.parse_args(argv)
    if a.provider == 'boat' and not a.worker_id:
        p.error('Boat requires at least one explicit --worker-id')
    if a.provider == 'hetzner' and a.worker_id:
        p.error('--worker-id is only used with --provider boat')
    boat = str(a.root / ('bin/boat-call' if a.provider == 'boat' else 'bin/hcloud-boat'))
    if a.provider == 'boat':
        workers = [worker_id(value, a.provider) for value in a.worker_id]
        if len(set(workers)) != len(workers): raise ValueError('duplicate worker id')
    else:
        servers = json.loads(command(['hcloud', 'server', 'list', '-l', 'unbug-bench=1', '-o', 'json'], capture=True)) or []
        workers = [worker_id(str(server['id']), a.provider) for server in servers
                   if (server.get('labels') or {}).get('parked', '').startswith('case-')]
    ready = {}
    for worker in workers:
        # A live run may replace a statement after discovery; only stopped workers
        # with their terminal marker can receive an admission snapshot.
        probe = "test -f /home/user/sealed/DONE && ! pgrep -f '^python3 .*factory/run.py' >/dev/null && python3 -c " + shlex.quote(PUBLIC_CARDS)
        rows = json.loads(command([boat, 'ssh', worker, probe], capture=True))
        for row in rows:
            case = identifier(row['case_id'])
            if case in ready: raise ValueError('candidate appears on multiple workers')
            ready[case] = (worker, row['statement_sha256'])
        if a.provider == 'boat' and not rows:
            raise ValueError('selected worker has no candidate waiting at the statement step')
        if len(rows) > 1:
            raise ValueError('worker has multiple candidates; cannot install one admission directory')
    if not ready: raise ValueError('no parked worker waiting at the statement step')
    with tempfile.TemporaryDirectory(prefix='factory-registry-snapshots-') as tmp:
        snapshots = prepare(a.root / 'sealed', a.registry_root or a.root / 'sealed/statement-registry',
                            {case: data[1] for case, data in ready.items()}, tmp)
        for case, snapshot in snapshots.items(): install(boat, ready[case][0], snapshot, a.provider)
        print(json.dumps({'status': 'ready_for_authorized_resume', 'provider': a.provider,
                          'workers': {case: ready[case][0] for case in sorted(ready)},
                          'resume_required': 'approved launcher preserving pinned settings and cumulative budget'}))


if __name__ == '__main__': main()
