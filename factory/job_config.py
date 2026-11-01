"""Current holder authority comes from verified RAM, case money from checkpoints."""
from copy import deepcopy
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

from batch_money import check_manifest, amount
from registry import atomic_json

FACTORY = Path(__file__).resolve().parent


def read_file(path, expected, *, private=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or (private and (
                info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600)):
            raise ValueError()
        raw = file.read()
    if not isinstance(expected, str) or hashlib.sha256(raw).hexdigest() != expected: raise ValueError()
    return json.loads(raw)


def host_check(path, digest, case, generation, release):
    """Precreation check: the config agrees with what launch.sh will actually do."""
    value = read_file(path, digest, private=True)
    if (value['case_id'] != case or value['source_generation'] != generation or
            value['batch_release_sha256'] != release):
        raise ValueError('job configuration differs from launch')
    return value


def verified_config(path, digest, case, release_sha, *, generation=...):
    from job_authority import read
    current = read_file(Path(path), digest, private=True)
    fields = {'schema', 'batch_id', 'job_id', 'case_id', 'batch_deadline', 'source_generation',
              'batch_release_sha256', 'manifest_sha256', 'job_money'}
    if set(current) != fields or type(current['schema']) is not int or current['schema'] != 1:
        raise ValueError()
    if (current['case_id'] != case or current['batch_release_sha256'] != release_sha or
            not re.fullmatch('[a-z0-9-]+', current['batch_id']) or
            not re.fullmatch('[a-z0-9-]+', current['job_id'])):
        raise ValueError()
    release = read_file(FACTORY.parent / 'batch-release.json', release_sha)
    worker = read_file(FACTORY.parent / 'worker-release-manifest.json',
                       release['files']['worker-release-manifest.json'])
    relative = 'factory/batches/' + current['batch_id'] + '.json'
    if worker['files'][relative] != current['manifest_sha256']: raise ValueError()
    record = check_manifest(read_file(FACTORY / 'batches' / (current['batch_id'] + '.json'),
                                      current['manifest_sha256']))
    if (record['id'] != current['batch_id'] or record['batch_deadline'] != current['batch_deadline'] or
            __import__('batch_service').resolve_job(record, current['job_id'])['case'] != case or
            record['restore_recipient'] != (FACTORY / 'control-recipient.txt').read_text().strip()):
        raise ValueError()
    incoming = current['job_money']
    for field, key in (('batch_id', 'batch'), ('job_id', 'job'), ('case_id', 'case'),
                       ('batch_deadline', 'batch_deadline'), ('source_generation', 'source_generation')):
        if current[field] != incoming[key]: raise ValueError()
    read(incoming, incoming)  # Authentication above; D now validates its owned consumer contract.
    if amount(incoming['committed_total_usd']) > amount(record['money_limit_usd']): raise ValueError()
    if generation is not ... and current['source_generation'] != generation: raise ValueError()
    return current, record


def install(c, args):
    """Must run after restore authentication and before any D/model admission."""
    from budget import BudgetError
    if not getattr(args, 'batch_release_sha256', None):
        if getattr(args, 'factory_job_config', None) or getattr(args, 'factory_job_config_sha256', None):
            raise BudgetError('money_wait')
        return
    c.authenticated_job_config = {}
    c.batch_id = c.job_id = c.batch_deadline = c.source_generation = None
    try:
        from job_authority import read
        if not args.factory_job_config or not args.factory_job_config_sha256: raise ValueError()
        current, record = verified_config(args.factory_job_config, args.factory_job_config_sha256, c.case_id, args.batch_release_sha256)
        incoming = current['job_money']
        spec = record.get('carry_from', {}).get('jobs', {}).get(current['job_id'])
        importing = bool(spec and spec['generation'] is not None and spec['generation'] == incoming['source_generation'])
        if not importing and (c.card.get('terminal_stop') == 'retired_batch_bound' or
                getattr(c, 'checkpoint_card', {}).get('terminal_stop') == 'retired_batch_bound'):
            raise ValueError()
        if getattr(args, 'resume', None) and hasattr(c, 'checkpoint_card'):
            expected = record['carry_from']['policy']['batch']['sha256'] if importing else args.batch_release_sha256
            if c.checkpoint_card.get('batch_release_sha256') != expected: raise ValueError()
        saved_path = c.work / 'job-money.json'
        history_path = c.work / 'job-money-history.json'
        if getattr(args, 'resume', None):
            # Missing old money is a legacy import, deliberately unsupported here.
            saved = json.loads(saved_path.read_text())
            cross_batch = saved['batch'] != incoming['batch']
            if cross_batch:
                from batch_transfer import predecessor
                from batch_money import channel
                old_policy, old_record = predecessor(record)
                if not importing: raise ValueError()
                channel(saved, old_record, current['job_id'])
                if (saved['case'] != incoming['case'] or saved['job'] != incoming['job'] or
                        saved['reservation_id'] == incoming['reservation_id'] or incoming['revision'] != 1 or
                        spec['committed_total_usd'] != incoming['committed_total_usd']): raise ValueError()
            else:
                for key in ('batch', 'job', 'case', 'reservation_id', 'batch_deadline'):
                    if saved[key] != incoming[key]: raise ValueError()
            read(saved, saved)
            history = json.loads(history_path.read_text()) if history_path.exists() else {}
            if not isinstance(history, dict): raise ValueError()
            if saved != incoming:
                from batch_accounting import card_total
                from carry_over import digest as public_digest
                sealed = Path(c.ledger).parent
                receipt = json.loads((sealed / (c.case_id + '.restore-accounting.json')).read_text())
                public = json.loads((sealed / (c.case_id + '.restore-scorecard.json')).read_text())
                if (receipt.get('accounting_authenticated') is not True or receipt.get('case') != c.case_id or
                        receipt.get('generation') != incoming['source_generation'] or
                        receipt.get('public_card_sha256') != public_digest(public) or
                        public.get('sha256') != incoming['source_generation'] or public.get('job_money') != saved or
                        incoming['source_generation'] is None or incoming['source_generation'] == saved['source_generation'] or
                        incoming['committed_total_usd'] != saved['committed_total_usd']): raise ValueError()
                expected_release = old_policy['batch']['sha256'] if cross_batch else args.batch_release_sha256
                if cross_batch and (public.get('batch_release_sha256') != expected_release or
                        getattr(c, 'checkpoint_card', {}).get('batch_release_sha256') != expected_release): raise ValueError()
                expected_revision = 1 if cross_batch else saved['revision'] + (card_total(public) is not None)
                if incoming['revision'] != expected_revision: raise ValueError()
                key = incoming['reservation_id'] + '/' + str(incoming['revision']) + '/' + incoming['source_generation']
                transition = dict(old=saved, new=incoming, config_sha256=args.factory_job_config_sha256,
                                  source_generation=current['source_generation'])
                for existing_key, item in history.items():
                    if existing_key == key:
                        if item != transition: raise ValueError()
                    elif incoming['source_generation'] in (item['old']['source_generation'], item['new']['source_generation']):
                        raise ValueError()
                history[key] = transition
                atomic_json(history_path, history)
        elif current['source_generation'] is not None or saved_path.exists():
            raise ValueError()
        atomic_json(saved_path, incoming)
        # Separate objects: a model cannot turn persisted case state into current authority.
        c.authenticated_job_config = deepcopy(current)
        c.authenticated_batch_manifest = deepcopy(record)
        c.job_money = deepcopy(incoming)
        c.batch_id, c.job_id = current['batch_id'], current['job_id']
        c.batch_deadline, c.source_generation = current['batch_deadline'], current['source_generation']
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError):
        raise BudgetError('money_wait') from None


def deliver(raw, expected, destination):
    if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('job configuration transfer changed')
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = destination.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('unsafe RAM directory')
    staged = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as file:
            staged = Path(file.name)
            file.write(raw); file.flush(); os.fsync(file.fileno())
        os.replace(staged, destination)
        fd = os.open(destination.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if staged is not None: staged.unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('op', choices=('check', 'deliver'))
    p.add_argument('--path', type=Path)
    p.add_argument('--sha256', required=True)
    p.add_argument('--case')
    p.add_argument('--generation', default='')
    p.add_argument('--release')
    a = p.parse_args()
    try:
        if a.op == 'check':
            host_check(a.path, a.sha256, a.case, a.generation or None, a.release)
        else:
            deliver(sys.stdin.buffer.read(65537), a.sha256, Path('/dev/shm/secrets/factory-job.json'))
    except (OSError, ValueError, KeyError, TypeError):
        print('job configuration refused', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
