"""Public launch/restore file manifest. No secrets, case contents or cloud calls.

Keep file selection here. Hashes are generated from these paths when staging;
launcher-sha256.json is itself bound by the founder-approved holder fingerprint.
Qualified release inventories remain immutable evidence, not another hand list.
"""
import hashlib
import json

CHECKED_HELPERS = ('bin/qualified-release.py', 'tools/boat_readiness.py')
HASH_FILE = 'factory/launcher-sha256.json'
TRUSTED_FILES = ('factory/control_resume.py',
 'factory/key_holder.py',
 'factory/batch.py',
 'factory/batch_money.py',
 'factory/job_config.py',
 'factory/launch.sh',
 'factory/collect.sh',
 'factory/collection.py',
 'bin/boat-launch-guards.sh',
 'bin/boat-call',
 'bin/processes.py',
 'bin/boat-name',
 'bin/boat-spend',
 'bin/hcloud-boat',
 'bin/hcloud-park',
 'bin/push-secrets',
 'factory/sealed_audit.py',
 'factory/ttl_continuation.py',
 'factory/coordinator.py',
 'factory/restart.py',
 'factory/recovery.py',
 'factory/registry.py',
 'factory/statement_round.py',
 'factory/admission.py',
 'factory/calibration.py',
 'factory/account_handoff.py',
 'factory/model_router.py',
 'factory/codex_login.py',
 'factory/launch_manifest.py',
 'factory/transfer.py',
 'bin/factory-adopt',
 'bin/r2-presign') + (HASH_FILE,) + CHECKED_HELPERS
# Preserve the holder's boundary: worker code is qualified separately.
HOST_FILES = TRUSTED_FILES + ('factory/run.py', 'factory/worker_release.py')

REQUIRED_RELEASE = ('factory/model_runtime.py',
 'factory/model_router.py',
 'factory/restore_ledger.py',
 'factory/founder_ruling.py',
 'factory/run.py',
 'factory/fairness.py',
 'factory/recovery.py',
 'factory/late_recovery.py',
 'factory/founder_decisions.py',
 'factory/restore_bundle.py',
 'factory/gate_pipeline.py',
 'bin/fake-pass-check')

WORKER_BENCH = ('bin/bench.py',
 'bin/bench_judging.py',
 'bin/checkpoint',
 'bin/checkpoint_evidence.py',
 'bin/run_validity.py',
 'bin/factory_pool.py',
 'bin/strategy',
 'bin/boat-launch-guards.sh',
 'bin/boat-call',
 'bin/processes.py',
 'bin/push-secrets',
 'bin/setup',
 'bin/reset',
 'bin/check',
 'bin/verify-negative',
 'projects/medusa/package.json',
 'projects/medusa/package-lock.json',
 'projects/medusa/compose.yaml',
 'projects/medusa/verify-lock.mjs',
 'projects/medusa/Dockerfile',
 'projects/medusa/Dockerfile.deps',
 'projects/medusa/medusa-config.ts')
WORKER_CONFIG = ('factory/invalid-runs-compat.json',
 'factory/free-model-cutover.json',
 'factory/rotation.json',
 'factory/rotation-3writers.json',
 'factory/worker-release.json',
 'factory/statements-recipient.txt', 'factory/control-recipient.txt')
WORKER_GLOBS = ('factory/*.py', 'factory/*.sh', 'factory/prompts/*.md', 'factory/batches/*.json')
# Public tracked source only; never export sealed/, results/ or local credentials.
BATCH_SOURCE = ('bin', 'cases', 'factory', 'guards', 'harbor', 'projects',
                'scenarios', 'tests', 'CONTESTANT.md', 'SPEC.md', 'README.md')

INHERITED_HELPERS = ('founder-run.py', 'start-in-terminal.sh', 'sync-to-vm.sh')
PUBLISHER = {'sync-to-vm.py': 'factory/restore_sync.py'}
D4_HOST_FILES = ('factory/restore_bundle.py', 'factory/founder_decisions.py',
                 'tests/tools/test_late_restore_bundle.py')
RECONCILIATION_FILES = ('prior-reservations.json', 'failed-launch-reconciliation.json')
RESTORE_METADATA = ('founder-decisions.json', *RECONCILIATION_FILES)
FINALIZATION_INPUTS = ('vm-baseline-sha256.json', 'input-public-search.json',
                       'input-counter-metadata.json', 'input-counter-observation-card.json')
WRAPPERS = {'finalize.py': 'finalize', 'validate-offline.py': 'verify'}
GENERATED_HELPERS = (*WRAPPERS,
 'policy.restore.pending.json',
 'restore-config.json',
 'source-binding.json',
 'rehearsal.json')
COLLECTION_SUFFIXES = ('casekey.age', 'checkpoint.tar.gz.age', 'progress.json', 'scorecard.json', 'scorecard.txt', 'search.age', 'statement.age', 'tar.gz.age')

RUNTIME_PATHS = {'sealed': 'created by finalization/collection; selected card/archive verified separately',
 'sealed/$restore.checkpoint.tar.gz.age': 'selected archive verified by collected()',
 'sealed/$restore.tar.gz.age': 'alternative selected archive verified by collected()',
 'sealed/$restore.scorecard.json': 'selected card verified by collected()',
 'sealed/$c.scorecard.json': 'separate cohort restore-cases wrapper; selected case verified '
                             'individually',
 'sealed/$resume_case.scorecard.json': 'collected runtime continuation card',
 'sealed/$restore.casekey.age': 'required wrapped case key; archive decryption runs only on worker',
 'sealed/g11-review-$restore.casekey.age': 'required wrapped key for the selected audit namespace',
 'sealed/g11-review-$restore.scorecard.json': 'only --restore-review, outside this restore '
                                              'policy',
 'sealed/g11-review-$restore.tar.gz.age': 'only --restore-review, outside this restore policy',
 'results/spend/$': 'guard_init creates timestamped spend outputs',
 'results/ttl-retirements/$id.json': 'optional TTL continuation receipt; guarded by -f',
 'results/factory': 'output directory for separate cohort launch wrappers',
 'results/factory/adopt.log': 'output of separate Hetzner resume-in-place wrapper',
 'founder-ruling.json': 'optional operator-supplied ruling; required only when policy '
                        'requests it'}

def worker_files(root):
    paths = set(WORKER_BENCH + WORKER_CONFIG)
    for pattern in WORKER_GLOBS:
        paths.update(p.relative_to(root).as_posix() for p in root.glob(pattern)
                     if not p.name.startswith('test_'))
    return sorted(paths)


def sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('missing regular manifest input: ' + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_helpers(root):
    pins = {name: sha(root/name) for name in CHECKED_HELPERS}
    (root/HASH_FILE).write_text(json.dumps(pins, indent=2, sort_keys=True) + '\n')


def collection_files(case):
    return {case + '.' + suffix for suffix in COLLECTION_SUFFIXES}


def worker_upload(root, release_manifest, output):
    """Ship only declared factory sources; never archive an arbitrary factory tree."""
    import tarfile
    with tarfile.open(output, 'w:gz') as archive:
        for name in worker_files(root):
            if name.startswith('factory/'):
                sha(root/name)  # same regular-file boundary as release stamping
                archive.add(root/name, arcname=name, recursive=False)
        archive.add(release_manifest, arcname='worker-release-manifest.json', recursive=False)


def verify_worker_runtime(root, bundle):
    """The launcher must never detach a supervisor absent from the frozen release."""
    import tarfile
    with tarfile.open(bundle) as archive:
        manifest = json.load(archive.extractfile('worker-release-manifest.json'))
    for name in ('factory/runner_supervisor.py', 'bin/processes.py'):
        if manifest.get('files', {}).get(name) != sha(root / name):
            raise ValueError('frozen worker runtime is incompatible with launcher: ' + name)
