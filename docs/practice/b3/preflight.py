"""Validate preparation pins offline; deliberately never return success to launchers."""
import copy
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import sys
import tempfile


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if len(sys.argv) != 3:
        print('usage: preflight.sh ABSOLUTE_CHECKOUT ABSOLUTE_RELEASE', file=sys.stderr)
        return 2
    root_arg, release_arg = map(Path, sys.argv[1:])
    require(root_arg.is_absolute() and release_arg.is_absolute(), 'absolute paths required')
    root, release = root_arg.resolve(), release_arg.resolve()
    here = Path(__file__).resolve().parent
    require(root == here.parents[2], 'checkout differs from preflight repository')
    sys.path.insert(0, str(root / 'factory'))
    import batch
    import batch_holder
    import batch_service
    import key_holder
    require(key_holder.ROOT.resolve() == root, 'import root differs from checkout')
    load = lambda name: json.loads((here / name).read_text())
    bounds, draft, pins = map(load, ('practice-bounds.json', 'item8-draft.json', 'release-pins.json'))
    for obj in (bounds, draft, pins):
        require(obj['schema'] == 1 and obj['launch_ready'] is False, 'not blocked schema 1 preparation')
    require(all(all(r[k] is None for k in ('commit', 'sha256', 'batch')) for r in draft['releases']), 'draft release unexpectedly populated')
    require(all(s['input'] is None for s in draft['scenarios']), 'draft input unexpectedly populated')
    files = {'batch-release.json', 'install-source.py', 'source-manifest.json', 'public-source.tar.gz', 'worker-release-manifest.json', 'deploy.py'}
    require(set(pins['files']) == files, 'six release pins required')
    require(all(sha(release / n) == h for n, h in pins['files'].items()), 'pins stale: release files changed')
    record = batch.verify(release, pins['batch_release_sha256'], root)
    require(record['commit'] == pins['build_commit'], 'build commit differs')
    manifest_path = root / 'factory/batches/b-practice-20261031.json'
    require(sha(manifest_path) == pins['manifest_sha256'], 'pins stale: manifest changed')
    require(key_holder.fingerprint(root) == pins['trusted_code_sha256'], 'pins stale: trusted code changed')
    require(not batch_holder.HOLDER_ENABLED and not batch_service.DIAGNOSIS_ENABLED, 'preparation flags changed')
    manifest = json.loads(manifest_path.read_text())
    require('--dry-run' in manifest['jobs']['practice']['args'] and not manifest['replacement_policy']['enabled'], 'preparation job changed')
    policy_path = here / 'practice-policy.json'
    policy = load('practice-policy.json')
    require(policy['root'] == '/BLOCKED/b3-not-approved-for-launch', 'policy lacks refusal sentinel')
    try:
        key_holder.policy_load(policy_path)
    except ValueError:
        pass
    else:
        raise ValueError('committed policy unexpectedly loadable')
    translated = copy.deepcopy(policy)
    translated['root'] = str(root)
    translated['batch']['release'] = str(release)
    normalized = copy.deepcopy(translated)
    normalized['root'] = policy['root']
    normalized['batch']['release'] = policy['batch']['release']
    require(normalized == policy, 'translation changed additional fields')
    with tempfile.TemporaryDirectory(prefix='b3-policy-check-') as tmp:
        path = Path(tmp) / 'policy.json'
        path.write_text(json.dumps(translated))
        key_holder.policy_load(path)
    require(D(bounds['case_incremental_usd']) + D(bounds['probe_usd']) == D(bounds['model_usd']) == D('20'), 'practice model allocation mismatch')
    require(D(bounds['model_usd']) + D(bounds['infrastructure_usd']) == D(bounds['total_usd']) == D('25'), 'practice total mismatch')
    scenarios = draft['scenarios']
    require([s['number'] for s in scenarios] == list(range(1, 8)), 'scenario order changed')
    require([D(s['model_usd']) for s in scenarios] == list(map(D, ('10','10','5','15','15','25','10'))), 'scenario caps changed')
    require([s['workers'] for s in scenarios] == [3,2,1,2,4,6,2], 'worker slots changed')
    require([s['execution_minutes'] for s in scenarios] == [10,10,5,10,15,15,5], 'execution windows changed')
    require(all(D(s['root_incremental_usd']) + D(s['replacement_incremental_usd']) == D(s['model_usd']) for s in scenarios), 'root/child allocations disagree')
    require([D(s['root_incremental_usd']) for s in scenarios[4:]] == list(map(D, ('7.5','12.5','5'))), 'beta halves changed')
    require(sum(D(s['model_usd']) for s in scenarios) == D(draft['model_usd']) == D('90'), 'model envelope changed')
    require(sum(s['workers'] for s in scenarios) == draft['max_workers'] == 20, 'creation ceiling changed')
    require(D(draft['worker_slot_usd']) * draft['max_workers'] + D(draft['shared_infrastructure_usd']) == D(draft['infrastructure_usd']) == D('10'), 'infrastructure envelope changed')
    require(D(draft['model_usd']) + D(draft['infrastructure_usd']) == D(draft['total_usd']) == D('100'), 'qualification total changed')
    require(draft['order'] == [1,2,3,4,5,7,6], 'qualification order changed')
    require((draft['wall_minutes'], draft['worker_lifetime_minutes'], draft['overhead_minutes']) == (480,120,15), 'qualification deadlines changed')
    require(sha(root / draft['source']['path']) == draft['source']['sha256'], 'item8 source drift: review draft again')
    print('PREPARATION VALID — LAUNCH BLOCKED:')
    for blocker in pins['blockers']:
        print('- ' + blocker)
    print('- Expected replacement: old $20 case authority -> authenticated S + E with E <= $19.99; separate $0.01 probe.')
    print('- Expected replacement: old Claude [2] -> reviewed [2,1], initial account 2 and rate-only fallback.')
    return 3


if __name__ == '__main__':
    try:
        code = main()
    except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
        print('PREPARATION INVALID / PINS STALE: ' + str(error), file=sys.stderr)
        code = 1
    sys.exit(code)
