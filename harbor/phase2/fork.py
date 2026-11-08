"""Paired C0: continue Unbug arm C's own first session instead of running a new one.

EXAM.md section 7: the one-shot arm "starts from the same initial work as Unbug on Claude".
Harbor 0.24 cannot clone a live environment, so this patches MultiStepTrial (no package edits):

UNBUG_FORK_SAVE=<dir>  (arm C)  after step 1 (agent + judge) finishes cleanly, archive nested
    tmpfs state, freeze `main` with docker pause, commit its filesystem, copy its nested-Docker
    volume (the contestant's live shop: Postgres, Redis, Medusa), the audit proxy's CA volumes,
    note the nested containers that were running, and copy the trial's host-side judge
    siblings (pending-state ledger, deployment-state receipts). Unpause; C continues.
UNBUG_FORK_FROM=<dir>  (arm C0) the trial runs on that image and volume copy (run-exam stages
    the task and a Compose overlay). Step 1 runs no setup, agent or judge: the nested shop is
    restarted, the judge siblings are restored, the frozen Unbug runtime converts the
    workspace with `fork-oneshot`, and step 1 carries C's own judge rewards. Steps 2.. run
    OneShotAgent normally. run-exam copies C's step-1 scorecard row into C0's.
"""
import asyncio
import json
import os
from pathlib import Path
import shutil

READY = '/tmp/runtime-images-ready'  # main's healthcheck flag (environment/start-dockerd.sh)
JUDGE_SIBLINGS = ('pending-state', 'deployment-state')
RUNTIME = '/installed-agent/unbug-runtime.py'
# The audit proxy's CA: webproxy/start-main.sh writes it into projects/medusa/.env, which the
# frozen runtime fingerprints, so C0 must start with C's CA or fork-oneshot rightly refuses.
CA_VOLUMES = {'/private-ca': 'webproxy-private-ca', '/ca-public': 'webproxy-public-ca'}
# Nested services may keep state in tmpfs (marketplace /data), which a /var/lib/docker copy
# loses. Archived inside main before the commit, restored in place after C0 restarts them.
TMPFS_DIR = '/var/tmp/unbug-fork'
TMPFS_SAVE = r'''set -eu
rm -rf {d}; mkdir -p {d}; : > {d}/index
for c in $(docker ps -q --no-trunc); do
  for m in $(docker inspect -f '{{{{range $k, $v := .HostConfig.Tmpfs}}}}{{{{$k}}}} {{{{end}}}}{{{{range .Mounts}}}}{{{{if eq .Type "tmpfs"}}}}{{{{.Destination}}}} {{{{end}}}}{{{{end}}}}' "$c"); do
    n=$(printf '%s %s' "$c" "$m" | sha256sum | cut -c1-16)
    docker exec "$c" tar -C "$m" -cf - . > {d}/$n.tar
    printf '%s %s %s
' "$c" "$m" "$n" >> {d}/index
  done
done'''.format(d=TMPFS_DIR)
TMPFS_RESTORE = r'''set -eu
while read -r c m n; do
  docker exec -i "$c" sh -c 'set -eu; r="$1/.unbug-fork"; rm -rf "$r"; mkdir "$r"; tar -C "$r" -xf -
    cd "$r"; find . -type d | while read -r x; do mkdir -p "$1/$x"; done
    find . ! -type d | while read -r x; do mv -f "$x" "$1/$x"; done; cd /; rm -rf "$r"' _ "$m" < {d}/$n.tar
done < {d}/index
rm -rf {d}'''.format(d=TMPFS_DIR)


def ca_volume(volume, mount):
    return f'{volume}-{CA_VOLUMES[mount]}'


async def copy_volume(image, source, target):
    await run('docker', 'volume', 'create', target)
    await run('docker', 'run', '--rm', '--privileged', '--network', 'none', '--entrypoint', 'cp',
              '-v', f'{source}:/from:ro', '-v', f'{target}:/to', image, '-a', '/from/.', '/to/')


async def run(*args, timeout=1800):
    process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError(f'{args[:3]} failed: {err.decode()[-2000:]}')
    return out.decode().strip()


async def must(environment, command, timeout=600, user='root'):
    result = await environment.exec(command=command, timeout_sec=timeout, user=user)
    if result.return_code:
        raise RuntimeError(f'fork step failed ({result.return_code}): {(result.stdout or "")[-1000:]} {(result.stderr or "")[-1000:]}')
    return (result.stdout or '').strip()


async def save(trial, step_result, target):
    target = Path(target)
    spec = json.loads((target / 'request.json').read_text())
    main = await trial.agent_environment._platform._resolve_service_container('main')
    running = (await must(trial.agent_environment, 'docker ps -q --no-trunc')).split()
    mount = lambda container, path: run('docker', 'inspect', '--format',
        '{{range .Mounts}}{{if eq .Destination "%s"}}{{.Name}}{{end}}{{end}}' % path, container)
    volume = await mount(main, '/var/lib/docker')
    proxy = await trial.agent_environment._platform._resolve_service_container('webproxy')
    ca = {path: await mount(proxy, path) for path in CA_VOLUMES}
    if not volume or not all(ca.values()):
        raise RuntimeError('main or webproxy lacks a volume the C0 fork must copy')
    await must(trial.agent_environment, TMPFS_SAVE)
    # C0's healthcheck must wait for its own dockerd, not pass on C's leftover flag.
    await must(trial.agent_environment, f'rm -f {READY}')
    await run('docker', 'pause', main)
    try:
        await run('docker', 'commit', '--pause=false', main, spec['image'])
        await copy_volume(spec['image'], volume, spec['volume'])
    finally:
        await run('docker', 'unpause', main)
        await must(trial.agent_environment, f'touch {READY}; rm -rf {TMPFS_DIR}')
    for path, source in ca.items():
        await copy_volume(spec['image'], source, ca_volume(spec['volume'], path))
    for name in JUDGE_SIBLINGS:
        source = trial.paths.trial_dir / name
        if source.is_dir():
            shutil.copytree(source, target / name, symlinks=True)
    rewards = step_result.verifier_result.rewards if step_result.verifier_result else None
    (target / 'fork.json').write_text(json.dumps({'image': spec['image'], 'volume': spec['volume'],
        'running': running, 'step': step_result.step_name, 'rewards': rewards}) + '\n')


async def seed(trial, step, step_result, source):
    from harbor.models.verifier.result import VerifierResult
    source = Path(source)
    fork = json.loads((source / 'fork.json').read_text())
    if fork['step'] != step.name:
        raise RuntimeError('C0 fork step differs from the C step it continues')
    environment = trial.agent_environment
    await must(environment, 'for i in $(seq 300); do docker info >/dev/null 2>&1 && break; sleep 1; done; docker info >/dev/null')
    if fork['running']:
        await must(environment, 'docker start ' + ' '.join(fork['running']))
    await must(environment, TMPFS_RESTORE)
    for name in JUDGE_SIBLINGS:
        if (source / name).is_dir():
            shutil.copytree(source / name, trial.paths.trial_dir / name, symlinks=True, dirs_exist_ok=True)
    # The frozen runtime checks C's first checkpoint completed and the workspace is unchanged,
    # stops any copied watcher record and switches the attempt to oneshot with C's spend.
    out = await must(environment, f'python3 {RUNTIME} --root /app fork-oneshot --confirm-cloned-workspace',
                     timeout=60, user=environment.default_user)
    (trial.paths.trial_dir / 'fork-oneshot.json').write_text(out + '\n')
    step_result.verifier_result = VerifierResult(rewards=fork['rewards'])


def install():
    from harbor.trial.multi_step import MultiStepTrial
    original = MultiStepTrial._run_step
    save_dir, from_dir = os.environ.get('UNBUG_FORK_SAVE'), os.environ.get('UNBUG_FORK_FROM')
    if save_dir and from_dir:
        raise RuntimeError('a trial is either the C fork source or the C0 fork, not both')
    if not (save_dir or from_dir):
        return

    async def run_step(self, step, step_result, *, index, total):
        if from_dir and index == 1:
            from harbor.models.trial.result import ExceptionInfo
            self._create_step_dirs(step)
            try:
                await seed(self, step, step_result, from_dir)
                ensure = getattr(self, '_phase2_ensure_monitors', None)
                if ensure:
                    await ensure()
            except Exception as error:
                step_result.exception_info = ExceptionInfo.from_exception(error)
            self._archive_step_outputs(step)
            return
        await original(self, step, step_result, index=index, total=total)
        if save_dir and index == 1 and index < total and step_result.exception_info is None:
            try:
                await save(self, step_result, save_dir)
            except Exception as error:  # C itself stays valid; only its C0 pairing is lost
                Path(save_dir, 'error.txt').write_text(f'{type(error).__name__}: {error}\n')

    MultiStepTrial._run_step = run_step
