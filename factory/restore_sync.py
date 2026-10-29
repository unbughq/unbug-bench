#!/usr/bin/env python3
"""Ciphertext-only, compare-before-replace publication of this case's results."""
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shlex
import subprocess
import sys
import uuid

# Standalone publication of an existing collection, without editing its bundle.
ROOT = Path(os.environ.get('UNBUG_RESTORE_ROOT', Path(__file__).resolve().parent)).resolve()
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE/'factory'), str(HERE)]
from launch_manifest import COLLECTION_SUFFIXES, collection_files
CONFIG = json.loads((ROOT / 'restore-config.json').read_text())
CASE = CONFIG['case']
VM = 'user@2.31.89.209'
SEALED = '/home/user/unbug-bench/sealed'
OPTIONS = ['-i', str(Path.home() / '.ssh/unbug-bench-hcloud'), '-o', 'IdentitiesOnly=yes',
           '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'UserKnownHostsFile=' + str(Path.home() / '.cache/unbug-bench/hcloud/172111861.known_hosts')]


def sha(path):
    assert path.is_file() and not path.is_symlink(), str(path)
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def prepare():
    inputs = json.loads((ROOT / 'input-sha256.json').read_text())
    # A prior collected generation can be authoritative even if its publication
    # failed. Compare the VM against its verified generation, not the retry input.
    baseline = json.loads((ROOT / 'vm-baseline-sha256.json').read_text())
    assert set(baseline) <= set(inputs), 'VM/input filename sets differ'
    current_path = ROOT / 'vm-current-sha256.json'
    expected = json.loads(current_path.read_text()) if current_path.exists() else baseline
    assert set(baseline) <= set(expected) <= set(inputs), 'VM/current filename sets differ'
    names = collection_files(CASE)
    assert set(inputs) <= names, 'unexpected collection input'
    local = {n: sha(ROOT / 'sealed' / n) for n in names if (ROOT / 'sealed' / n).exists()}
    assert set(inputs) <= set(local), 'missing collected files'
    assert local != inputs, 'no new collected generation; refusing sync of original input'
    card = json.loads((ROOT / 'sealed' / (CASE + '.scorecard.json')).read_text())
    assert card['case'] == CASE and not card.get('checkpoint_error'), 'invalid collected card'
    assert card.get('status') == 'stopped' or card.get('gates', {}).get('G12') == 'pass', 'not a collected terminal card'
    if card.get('sha256') == inputs[CASE + '.checkpoint.tar.gz.age']:
        plan = json.loads((ROOT / 'restore-adjustment.json').read_text())
        assert card == json.loads((ROOT / 'expected-restored-scorecard.json').read_text()), 'not the pinned metadata correction'
        assert card.get('restore_adjustment') == plan and plan['checkpoint_sha256'] == card['sha256']
        assert all(local[n] == digest for n, digest in inputs.items() if not n.endswith(('.scorecard.json', '.scorecard.txt'))), 'correction changed ciphertext/progress'
    assert card['sha256'] in [local.get(CASE + s) for s in ('.checkpoint.tar.gz.age', '.tar.gz.age')], 'collected archive/card mismatch'
    original = json.loads((ROOT / 'input-scorecard.json').read_text())
    def identity(value, hashes, *, original_input=False):
        digest = value.get('statement_sha256') or (value.get('freshness_repair') or {}).get('statement_sha256')
        if digest is None:
            # Older resumed cards omitted the top-level digest. Their sealed
            # search receipt already binds case + statement and its ciphertext.
            public = value.get('public_search') or {}
            if not public:
                # Legacy e15450 kept its exact original search ciphertext but
                # omitted both public identity fields on reseal. Only reuse the
                # separately pinned original receipt when that ciphertext matches.
                # A stop inside ensure_freshness has not resealed search.age.
                # Prefer the immediately preceding card over an older baseline
                # receipt, but only for the exact unchanged input ciphertext.
                prior = original.get('public_search') or {}
                search = CASE + '.search.age'
                if (prior and hashes.get(search) == inputs.get(search) == prior.get('cipher_sha256')):
                    public = prior
                else:
                    provenance = ROOT / 'input-public-search.json'
                    if provenance.exists(): public = json.loads(provenance.read_text())
            if not public and original_input:
                # Canary 6's collected card predates plaintext identity emission.
                # Bind its exact input statement ciphertext; never invent a digest.
                assert value.get('statement_cipher_sha256') == hashes[CASE+'.statement.age'], 'original statement ciphertext mismatch'
                return None
            binding = public.get('binding') or {}
            assert binding.get('case_id') == CASE, 'search receipt case mismatch'
            assert public.get('cipher_sha256') == hashes[CASE + '.search.age'], 'search receipt ciphertext mismatch'
            digest = binding.get('statement_sha256')
        assert isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest), 'missing statement identity'
        return digest
    current_identity = identity(card, local)
    original_identity = identity(original, inputs, original_input=True)
    if original_identity is not None:
        assert current_identity == original_identity, 'restore changed statement identity'
    # Age ciphertext changes on every seal, including the same case key/statement.
    if card.get('statement_cipher_sha256'):
        assert card['statement_cipher_sha256'] == local[CASE + '.statement.age']
    old, current = original['continuation_budget'], card['continuation_budget']
    assert type(current.get('calls')) is int and current['calls'] >= old['calls'], 'usage went backwards'
    assert isinstance(current.get('events'), list) and current['events'][:len(old['events'])] == old['events'], 'historical events changed'
    for key in ('cost', 'list_cost_usd', 'estimated_subscription_cost_usd'):
        if key in old or key in current:
            value = current.get(key)
            assert type(value) in (int, float) and math.isfinite(value) and value >= old.get(key, 0), 'cumulative cost went backwards: ' + key
    if old.get('unpriced_invocations'):
        history = old['unpriced_invocations']
        assert all(item in current.get('unpriced_invocations', []) or any(r.get('original') == item for r in current.get('resolved_unpriced_invocations', [])) for item in history), 'unpriced history changed'
    return {'case': CASE, 'baseline': baseline, 'expected': expected, 'incoming': local,
            'original_plaintext_identity_verified': original_identity is not None}


# This fixed program is sent through ssh stdin, with only public hashes as argv.
# It validates every destination before any overwrite and keeps an immutable
# generation-scoped baseline backup, preserving older .pre-restore files.
REMOTE = r'''
import contextlib,fcntl,hashlib,json,os,pathlib,re,shutil,sys,tempfile
request=json.loads(sys.argv[1]); stage=pathlib.Path(sys.argv[2]); sealed=stage.parent
case=request['case']; baseline=request['baseline']; incoming=request['incoming']; expected=request.get('expected',baseline)
assert re.fullmatch(r'case-[A-Za-z0-9-]+',case)
allowed={case+'.'+s for s in COLLECTION_SUFFIXES}
assert set(incoming)<=allowed and set(baseline)<=set(incoming) and set(baseline)<=set(expected)<=set(incoming)
def sha(p):
 assert p.is_file() and not p.is_symlink(),str(p)
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
with contextlib.ExitStack() as locks:
 # Same per-filename locks as factory/transfer.py, held through publication.
 # Nonblocking acquisition refuses an active collector without deadlocking it.
 for name in ['.'+case+'.restore-sync.lock']+['.'+n+'.transfer.lock' for n in sorted(allowed)]:
  lock=sealed/name; assert not lock.is_symlink()
  guard=locks.enter_context(lock.open('a+'));fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
 generation=hashlib.sha256(json.dumps(baseline,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 backup=sealed/('.'+case+'.pre-restore-'+generation)
 assert not backup.is_symlink()
 backup.mkdir(mode=0o700,exist_ok=True)
 assert backup.is_dir()
 assert {p.name for p in stage.iterdir()}==set(incoming)
 assert {n:sha(stage/n) for n in incoming}==incoming,'staging hash mismatch'
 card=json.loads((stage/(case+'.scorecard.json')).read_text())
 assert card['case']==case and card['sha256'] in [incoming.get(case+s) for s in ('.checkpoint.tar.gz.age','.tar.gz.age')]
 for n,digest in incoming.items():
  dest=sealed/n; previous=backup/n
  if previous.exists() or previous.is_symlink():assert n in baseline and sha(previous)==baseline[n],'conflicting backup: '+n
  if dest.exists() or dest.is_symlink():assert sha(dest) in {digest,baseline.get(n),expected.get(n)},'VM changed independently; refusing: '+n
  else:assert n not in baseline,'canonical baseline missing: '+n
 # Back up all seven inputs first. Existing verified backups make retry safe.
 for n,digest in baseline.items():
  previous=backup/n
  if not previous.exists():
   legacy=sealed/(n+'.pre-restore')
   source=legacy if legacy.exists() and sha(legacy)==digest else sealed/n
   assert sha(source)==digest,'missing baseline backup: '+n
   temporary=None
   try:
    with source.open('rb') as source_stream,tempfile.NamedTemporaryFile(dir=sealed,prefix='.'+case+'.backup-',delete=False) as output:
     temporary=pathlib.Path(output.name)
     shutil.copyfileobj(source_stream,output,1024*1024);output.flush();os.fsync(output.fileno())
    assert sha(temporary)==digest,'backup copy mismatch: '+n
    os.link(temporary,previous)  # atomic and refuses an existing backup
   finally:
    if temporary is not None:temporary.unlink(missing_ok=True)
   assert sha(previous)==digest
 for directory in (backup,sealed):
  fd=os.open(directory,os.O_RDONLY)
  try:os.fsync(fd)
  finally:os.close(fd)
 # Publish the scorecard last; repeat is safe after an interrupted transfer.
 order=sorted(incoming,key=lambda n:n.endswith('.scorecard.json'))
 for n in order:
  if not (sealed/n).exists() or sha(sealed/n)!=incoming[n]:
   os.chmod(stage/n,0o600);os.replace(stage/n,sealed/n)
 assert {n:sha(sealed/n) for n in incoming}==incoming
 fd=os.open(sealed,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)
 print(json.dumps({'canonical_root':str(sealed),'case':case,'verified_sha256':incoming,'pre_restore_checkpoint_sha256':sha(backup/(case+'.checkpoint.tar.gz.age')),'pre_restore_root':str(backup),'pre_restore_sha256':{n:sha(backup/n) for n in baseline},'original_plaintext_identity_verified':request.get('original_plaintext_identity_verified',True)}))
shutil.rmtree(stage)
'''.replace('COLLECTION_SUFFIXES', repr(COLLECTION_SUFFIXES))


def main():
    request = prepare()
    stage = SEALED + '/.' + CASE + '-restore-' + uuid.uuid4().hex
    subprocess.run(['ssh', *OPTIONS, VM, 'umask 077; mkdir ' + shlex.quote(stage)], check=True)
    subprocess.run(['scp', *OPTIONS, *[str(ROOT / 'sealed' / n) for n in sorted(request['incoming'])], VM + ':' + stage + '/'], check=True)
    command = 'python3 -B - ' + shlex.quote(json.dumps(request)) + ' ' + shlex.quote(stage)
    result = subprocess.run(['ssh', *OPTIONS, VM, command], input=REMOTE, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('remote publication rejected (exit ' + str(result.returncode) + '): ' + result.stderr.strip())
    receipt = json.loads(result.stdout)
    assert receipt['verified_sha256'] == request['incoming']
    assert receipt['pre_restore_checkpoint_sha256'] == request['baseline'][CASE + '.checkpoint.tar.gz.age']
    (ROOT / 'sync-result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
