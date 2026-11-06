"""Public sources for the durable candidate worker release; no credentials."""
import hashlib

WORKER_BENCH = ('bin/bench.py',
 'bin/bench_judging.py',
 'bin/checkpoint',
 'bin/checkpoint_evidence.py',
 'bin/run_validity.py',
 'bin/factory_pool.py',
 'bin/strategy',
 'bin/exam-launch-guards.sh',
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
 'factory/statements-recipient.txt',
 'factory/control-recipient.txt')
WORKER_GLOBS = ('factory/*.py', 'factory/durable/**/*.py', 'factory/prompts/*.md')


def worker_files(root):
    paths = set(WORKER_BENCH + WORKER_CONFIG)
    for pattern in WORKER_GLOBS:
        paths.update(p.relative_to(root).as_posix() for p in root.glob(pattern)
                     if not p.name.startswith('test_'))
    paths.discard('factory/router_delivery.py')  # Host-only credential packer.
    return sorted(paths)


def sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('missing regular manifest input: ' + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()
