#!/usr/bin/env python3
"""Read-only input admission snapshot. This does not authorize activation."""
import argparse
from contextlib import ExitStack
import fcntl
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'factory'))
import batch_holder as holder
import batch_money as money
import batch_service as service


def qualify(policy, root, home, job, checkpoint=None):
    report = dict(schema=1, eligible=False, launch_ready=False,
                  input_kind='empty' if checkpoint is None else 'checkpoint',
                  observation='input_refused', admission='refused')
    try:
        record = money.manifest(policy, root)
        directory = home / 'batches' / record['id']
        with ExitStack() as stack:
            if directory.exists() or directory.is_symlink():
                if directory.is_symlink(): return report
                report['observation'] = 'state_unlocked'
                lock = stack.enter_context(service._regular(directory / 'lock'))
                fcntl.flock(lock, fcntl.LOCK_SH)
                report['observation'] = 'journal_present' if (directory / 'journal.json').exists() else 'journal_absent'
            else:
                report['observation'] = 'batch_absent'
            ops = holder._operations(directory, record, policy)
            state = money.load_locked(directory, record, policy['batch']['manifest_sha256'])
            holder._admit(directory, record, policy, root, ops, state, job, checkpoint)
            identity = holder.operation_id(policy, job, checkpoint)
            if identity in ops:
                op = ops[identity]
                if op['state'] == 'failed' or op['retirement'] is not None or op['incident'] is not None:
                    return report
                report['admission'] = 'replay'
            else:
                report['admission'] = 'new'
            report['eligible'] = True
    except ValueError as error:
        if str(error) == holder.PILOT_ROLE_ERROR: report['observation'] = holder.PILOT_ROLE_ERROR
    except (OSError, KeyError, TypeError, IndexError):
        pass  # Never export arbitrary exception text or private state.
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--job', required=True)
    parser.add_argument('--checkpoint')
    args = parser.parse_args(argv)
    try:
        import key_holder
        policy = key_holder.policy_load(args.policy)
        report = qualify(policy, key_holder.ROOT, args.home, args.job, args.checkpoint)
    except (OSError, ValueError, KeyError, TypeError):
        report = dict(schema=1, eligible=False, launch_ready=False, observation='input_refused', admission='refused')
    print(json.dumps(report, sort_keys=True))
    return 0 if report['eligible'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
