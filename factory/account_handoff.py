"""Same-worker subscription handoff. Only public account labels are journaled.

The holder supplies the job's authorized accounts; secret bytes arrive on stdin
only for apply, and go straight to push-secrets' stdin, never to disk or argv.
"""
import argparse
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import time

ACCOUNTS = {'opencode': {1: 'opencode-go-key', 2: 'opencode-go-key-2'},
            'claude': {1: 'claude-token', 2: 'claude-factory-token-2', 3: 'claude-factory-token-3'}}
SECRET_ENV = {'opencode': 'OPENCODE_SECRET_NAME', 'claude': 'CLAUDE_SECRET_NAME'}
KEY_ENV = {'opencode': 'OPENCODE_API_KEY', 'claude': 'CLAUDE_CODE_OAUTH_TOKEN'}
SECRETS = Path('/dev/shm/secrets')


def write(path, value):
    staged = path.with_suffix(path.suffix + '.tmp')
    with staged.open('w') as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush(); os.fsync(stream.fileno())
    staged.replace(path)


def current(state):
    if state.exists(): return json.loads(state.read_text())
    if os.environ.get('FACTORY_ACCOUNT_STATE'):
        return json.loads(os.environ['FACTORY_ACCOUNT_STATE'])
    return {'accounts': {p: next(a for a, label in rows.items()
                                if label == os.environ.get(SECRET_ENV[p], rows[1]))
                         for p, rows in ACCOUNTS.items()}, 'limited': {}, 'history': []}


def limited_provider(stop):
    # DeepSeek's old checkpoint/CLI names now use OpenRouter, never a Go handoff.
    if not stop.startswith('provider_limit:'): return None
    model = stop.removeprefix('provider_limit:')
    if model in ('opencode/deepseek-v4.1-flash-free', 'opencode-go/deepseek-v4.1-flash'):
        return None
    return next((p for p in ACCOUNTS if model.startswith(p + '/') or
                 (p == 'opencode' and model.startswith('opencode-go/'))), None)


def initial_state(card, policy, accounts=None):
    """Carry public account history across transports, including explicit selections."""
    observed = {'opencode': 1, 'claude': 1, **(card.get('provider_accounts') or {})}
    history = copy.deepcopy(card.get('account_handoffs') or [])
    selected = dict(observed if accounts is None else accounts)
    return {'accounts': selected, 'limited': {}, 'history': history}


def choose(card, state, policy, held):
    """Transport a router selection; never schedule or blacklist accounts here."""
    wait = card.get('provider_wait') or {}
    label = wait.get('account')
    provider = next((p for p, labels in ACCOUNTS.items() if label in labels.values()), None)
    if provider is None or card.get('terminal_stop') != 'provider_wait': return None
    account = next(a for a, value in ACCOUNTS[provider].items() if value == label)
    if provider == 'claude' and account not in (1, 2): return None
    old = state['accounts'][provider]
    if account == old or account not in policy.get(provider + '_accounts', []) or label not in held: return None
    return {'provider': provider, 'from': old, 'to': account, 'secret': label,
            'stop': 'provider_wait', 'generation': card['sha256']}


def launch_accounts(card, policy, request, held):
    # Bootstrap defaults never override checkpoint state or a router selection.
    selected = {'opencode': policy.get('opencode_account',
                    (policy.get('opencode_accounts') or [None])[0]),
                'claude': 1, **policy.get('initial_accounts', {}),
                **(card.get('provider_accounts') or {})}
    baseline = initial_state(card, policy, {**selected, 'opencode': selected['opencode'] or 1})
    change = choose(card, baseline, policy, held)
    if change:
        selected[change['provider']] = change['to']
    selected.update({p: request[p + '_account'] for p in ACCOUNTS if p + '_account' in request})
    state = initial_state(card, policy, {**selected, 'opencode': selected['opencode'] or 1})
    return selected['opencode'], selected['claude'], state


def prepare(card_path, state_path, retries, remaining, args, held):
    from restart import plan
    card = json.loads(card_path.read_text())
    state = current(state_path)
    policy = json.loads(os.environ.get('FACTORY_ACCOUNT_POLICY', '{}'))
    change = choose(card, state, policy, held)
    result = plan(card_path, retries, remaining, args,
                  opencode_account_handoff=bool(change and change['provider'] == 'opencode'),
                  claude_account_handoff=bool(change and change['provider'] == 'claude'))
    # Bind the plan to the exact collected public card, including its ledger.
    pending = {'card_sha256': hashlib.sha256(card_path.read_bytes()).hexdigest(),
               'change': change, 'plan': result}
    write(state_path.with_suffix('.pending.json'), pending)
    return result


def apply(card_path, state_path, worker, bundle):
    pending = json.loads(state_path.with_suffix('.pending.json').read_text())
    if hashlib.sha256(card_path.read_bytes()).hexdigest() != pending['card_sha256']:
        raise ValueError('collected account handoff generation changed')
    change = pending['change']
    if change is None: return
    state = current(state_path)
    policy = json.loads(os.environ.get('FACTORY_ACCOUNT_POLICY', '{}'))
    # Revalidate authorization and held key at the last responsible moment.
    with tarfile.open(fileobj=io.BytesIO(bundle)) as source:
        held = {m.name for m in source.getmembers() if m.isfile()}
        if choose(json.loads(card_path.read_text()), state, policy, held) != change:
            raise ValueError('account handoff authorization changed')
        member = source.getmember(change['secret'])
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w') as target:
            target.addfile(member, source.extractfile(member))
    # Reserve before transport: a crash/failure must require reconciliation,
    # never silently resume with the old key or repeat an uncertain swap.
    marker = state_path.with_suffix('.applying')
    with marker.open('x'): pass
    subprocess.run([str(Path(__file__).resolve().parents[1] / 'bin/push-secrets'),
                    '--merge', worker, change['secret']],
                   input=base64.b64encode(output.getvalue()), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    provider = change['provider']
    state['accounts'][provider] = change['to']
    state['limited'] = {}  # Historical failures are not current account health.
    state['history'].append(change)
    write(state_path, state)
    marker.unlink()


def exports(state_path):
    state = current(state_path)
    commands = []
    for provider, account in state['accounts'].items():
        label = ACCOUNTS[provider][account]
        commands += ['export ' + SECRET_ENV[provider] + '=' + shlex.quote(label),
                     'export ' + KEY_ENV[provider] + '=$(cat /dev/shm/secrets/' + label + ')']
    commands.append('export FACTORY_ACCOUNT_STATE=' + shlex.quote(json.dumps(state, sort_keys=True)))
    return '; '.join(commands)


def parked(policy_path, job_name, worker, extra):
    """Manual parked restores need the same explicit policy and held-key pipe."""
    import key_holder
    policy = key_holder.policy_load(policy_path)
    job = key_holder.job_template(policy, job_name)
    if job['mode'] != 'case': raise ValueError('parked handoff needs a case job')
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, 'BOAT_CMD': str(root / 'bin/hcloud-boat')}
    metadata = json.loads(subprocess.check_output(['hcloud', 'server', 'describe', worker, '-o', 'json']))
    if metadata.get('labels', {}).get('parked') != job['case']:
        raise ValueError('worker is not parked for this policy case')
    subprocess.run([env['BOAT_CMD'], 'ssh', worker,
        "! pgrep -f '^python3 .*factory/run.py' >/dev/null"], check=True, env=env)
    subprocess.run([str(root / 'factory/collect.sh'), worker], check=True, env=env)
    card_path = root / 'sealed' / job['card']
    card = json.loads(card_path.read_text())
    if card.get('case') != job['case']: raise ValueError('parked case differs from policy')
    # Only provider limits need a key pipe. Ordinary manual resumes keep their
    # existing behavior, but still load the previously selected account labels.
    env['FACTORY_ACCOUNT_POLICY'] = json.dumps(job)
    directory = key_holder.CONTROL_HOME / 'parked-handoffs' / worker
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    state = directory / 'worker.accounts.json'
    lock = (directory / 'controller.lock').open('a+')
    import fcntl
    with lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not state.exists():
            observed = {'opencode': job.get('opencode_account', 1), 'claude': job.get('claude_account', 1),
                        **(card.get('provider_accounts') or {})}
            write(state, initial_state({**card, 'provider_accounts': observed}, job))
        os.environ['FACTORY_ACCOUNT_POLICY'] = env['FACTORY_ACCOUNT_POLICY']
        if card.get('terminal_stop', '').startswith('provider_limit:'):
            count = directory / 'autoresumes'
            retries = int(count.read_text()) if count.exists() else 0
            identity = sys.stdin.buffer.read()
            decrypted = subprocess.run(['age', '-d', '-i', '/dev/stdin',
                env.get('UNBUG_SECRETS_FILE', str(Path.home() / '.config/unbug-bench/secrets.age'))],
                input=identity, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True).stdout
            with tarfile.open(fileobj=io.BytesIO(decrypted)) as source:
                held = set(source.getnames())
            # The original worker expiry remains the deadline for automatic recovery.
            remaining = int(metadata['labels']['expires']) - time.time()
            _, delay, _ = prepare(card_path, state, retries, remaining, shlex.join(job['args'][1:] + extra), held)
            time.sleep(delay)
            count.write_text(str(retries + 1))
            os.environ['BOAT_CMD'] = env['BOAT_CMD']
            apply(card_path, state, worker, decrypted)
        env.update(FACTORY_PARKED_HANDOFF_READY='1', FACTORY_ACCOUNT_STATE=state.read_text())
        # Strip only host lifecycle options. The detached runner must receive the
        # exact policy models, ceilings, seed and counters used by the planner.
        argv = job['args'][1:]
        runner = []
        host_options = {'--restore', '--restore-review', '--qualified-release', '--admission-root',
                        '--ttl-hours', '--max-spend', '--stall-minutes', '--founder-ruling-sha256'}
        index = 0
        while index < len(argv):
            if argv[index] in host_options: index += 2
            else: runner.append(argv[index]); index += 1
        return subprocess.run([str(root / 'factory/resume-in-place.sh'), worker, *runner, *extra], env=env).returncode


def worker_resume(case, bench_sha, args, account_state=None):
    """Worker-only loader: key bytes enter the child's environment, never argv."""
    home = Path.home()
    if account_state:
        state = json.loads(account_state)
    else:
        card = json.loads((home / 'sealed' / (case + '.scorecard.json')).read_text())
        state = initial_state(card, {})
    env = dict(os.environ)
    for key in ('ANTHROPIC_BASE_URL', 'OPENCODE_API_KEY_BASE_URL', 'OPENAI_BASE_URL', 'OPENAI_API_KEY'):
        env.pop(key, None)
    for provider, account in state['accounts'].items():
        label = ACCOUNTS[provider][account]
        env[SECRET_ENV[provider]] = label
        env[KEY_ENV[provider]] = (SECRETS / label).read_text().rstrip('\n')
    if (SECRETS / 'openrouter-key').is_file():
        env['OPENROUTER_API_KEY'] = (SECRETS / 'openrouter-key').read_text().rstrip('\n')
    env.update(FACTORY_ACCOUNT_STATE=json.dumps(state), OPENCODE_DISABLE_AUTOUPDATE='1',
               FACTORY_DEFER_WIPE='1', FACTORY_OPENCODE_BIN='/usr/local/bin/opencode')
    (home / 'sealed/DONE').unlink(missing_ok=True)
    with (home / 'sealed/scorecard.stdout').open('w') as output:
        subprocess.Popen(['python3', str(home / 'factory/run.py'), '--resume', case,
                          '--resume-bench-sha', bench_sha, *args], env=env, stdin=subprocess.DEVNULL,
                         stdout=output, stderr=subprocess.DEVNULL, start_new_session=True)



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('plan', 'apply', 'exports', 'parked', 'resume-worker'))
    parser.add_argument('--state', type=Path)
    parser.add_argument('--card', type=Path)
    parser.add_argument('--worker')
    parser.add_argument('--retries', type=int, default=0)
    parser.add_argument('--remaining', type=float)
    parser.add_argument('--args')
    parser.add_argument('--policy', type=Path)
    parser.add_argument('--job')
    parser.add_argument('--case')
    parser.add_argument('--bench-sha')
    parser.add_argument('--account-state')
    opts, extra = parser.parse_known_args()
    try:
        if opts.operation == 'parked':
            return parked(opts.policy, opts.job, opts.worker, extra[1:] if extra[:1] == ['--'] else extra)
        if opts.operation == 'resume-worker':
            return worker_resume(opts.case, opts.bench_sha, extra[1:] if extra[:1] == ['--'] else extra, opts.account_state)
        if extra or opts.state is None: raise ValueError('unexpected account handoff arguments')
        if opts.operation == 'plan':
            print(*prepare(opts.card, opts.state, opts.retries, opts.remaining, opts.args,
                           set(sys.stdin.read().split())))
        elif opts.operation == 'apply':
            apply(opts.card, opts.state, opts.worker, sys.stdin.buffer.read())
        else: print(exports(opts.state))
    except Exception as error:
        # Child errors can include command arguments; never print credential pipes.
        from restart import CheckpointError
        print('account handoff refused or uncertain; no credential output', file=sys.stderr)
        return 2 if isinstance(error, (CheckpointError, OSError, json.JSONDecodeError)) else 1


if __name__ == '__main__': sys.exit(main())
