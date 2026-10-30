"""Read-only batch status. Collection state never masquerades as launch state."""
import argparse
from collections import Counter
from datetime import datetime
import fcntl
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

import batch_money
import batch_service
from job_config import read_file
from public_progress import _stage, _row

ROOT = Path(__file__).resolve().parents[1]
THRESHOLDS = dict(stage_seconds=5 * 3600, pending_seconds=30 * 60,
                  overdue_seconds=30 * 60, near_limit=0.8, read_seconds=30)
STOPS = {None: 'stopped', 'complete': 'complete', 'paused': 'paused',
         'provider_wait': 'waiting for provider', 'provider_wait_unrecoverable': 'provider unavailable',
         'provider_wait_deadline': 'provider wait deadline', 'money_wait': 'waiting for money',
         'retired_batch_bound': 'batch bound reached', 'ttl_retired': 'worker lifetime reached',
         'total_call_limit': 'historical call limit', 'call_limit': 'call limit',
         'stalled': 'stalled', 'budget_exhausted': 'budget exhausted',
         'factory_bug_held': 'factory bug held'}
COUNTS = ('running', 'waiting', 'rejected', 'stopped', 'not collected', 'unreadable')


def _stamp(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return stamp.timestamp() if stamp.tzinfo else None
    except (ValueError, TypeError, AttributeError, OverflowError): return None


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _pair(numerator, denominator, *, money=False):
    if not (_number(numerator) and _number(denominator) and denominator > 0): return '—'
    return ('$' + f'{numerator:.2f} / ' + '$' + f'{denominator:.2f}' if money
            else f'{numerator:g} / {denominator:g}')


def _near(numerator, denominator):
    return (_number(numerator) and _number(denominator) and denominator > 0 and
            numerator / denominator >= THRESHOLDS['near_limit'])


def _block(card, name):
    value = card.get(name)
    return value if isinstance(value, dict) else {}


def _boat(args):
    result = subprocess.run([str(ROOT / 'bin/boat-call'), *args], capture_output=True,
                            timeout=THRESHOLDS['read_seconds'], check=True,
                            env={**os.environ, 'BOAT_COMMAND_TIMEOUT_SECONDS': str(THRESHOLDS['read_seconds'])})
    return json.loads(result.stdout)


def observe(rows, transport=_boat):
    """One inventory, then one public progress read per present running worker.

    Running rows are normalized holder views. The current core read adapter
    never emits them; no extra journal fields are trusted by this function.
    """
    try:
        inventory = transport(['list', '--json'])
        if inventory['pageInfo']['hasMore'] is not False: raise ValueError()
        workers = [row['id'] for row in inventory['sandboxes']]
        if (not isinstance(inventory['sandboxes'], list) or len(set(workers)) != len(workers) or
                any(not isinstance(w, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', w) for w in workers)):
            raise ValueError()
        workers = set(workers)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None, {}
    progress = {}
    for row in rows:
        if row['phase'] != 'running' or row.get('worker_id') not in workers: continue
        case, worker = row['case'], row['worker_id']
        if not re.fullmatch(r'case-[A-Za-z0-9-]+', case): continue
        try:
            progress[case] = transport(['ssh', worker, 'cat ~/sealed/' + case + '.progress.json'])
        except (OSError, ValueError, subprocess.SubprocessError):
            progress[case] = None
    return workers, progress


def render(target, rows, workers, progress, *, now=None):
    """Format unmodified public cards plus an explicit normalized lifecycle view."""
    now = time.time() if now is None else now
    counts, lines, flags = Counter(), [], []
    if workers is None: flags.append('batch: boat unreadable')
    for row in rows:
        case, phase = row['case'], row['phase']
        card = row.get('card') or {}
        budget, recovery = _block(card, 'case_budget'), _block(card, 'recovery_config')
        continuation = _block(card, 'continuation_budget')
        calls = continuation.get('calls')
        calls = '—' if 'calls' not in continuation else str(calls) if type(calls) is int and calls >= 0 else '?'
        spent = _pair(budget.get('spent_usd'), budget.get('limit_usd'), money=True)
        rounds = _pair(card.get('builder_rounds'), recovery.get('rounds'))
        stage, duration, reason, actions = '—', '—', phase, []
        bucket = phase if phase in COUNTS else 'stopped'
        if phase == 'unreadable': actions.append('unreadable')
        elif phase == 'running':
            worker = row.get('worker_id')
            if worker is None: actions.append('unreadable')
            elif workers is not None and worker not in workers: actions.append('worker gone')
            elif workers is not None:
                live = progress.get(case)
                stages = live.get('stages') if isinstance(live, dict) else None
                if not isinstance(stages, dict):
                    actions.append('unreadable')
                else:
                    active = []
                    for name, value in stages.items():
                        clean = _row(value)
                        if not _stage(name) or clean is None:
                            actions.append('unreadable'); continue
                        if clean['status'] == 'running':
                            active.append((name, _stamp(clean['updated_at'])))
                    if active:
                        stage = ','.join(sorted(name for name, _ in active))
                        age = max(0, now - min(stamp for _, stamp in active))
                        duration = f'{int(age // 3600)}h {int(age % 3600 // 60)}m'
                        if age > THRESHOLDS['stage_seconds']: actions.append('check case')
        elif phase in ('pending', 'failed'):
            since = _stamp(row.get('pending_since'))
            if since is not None and now - since > THRESHOLDS['pending_seconds']:
                actions.append('launch stuck')
        elif phase == 'stopped':
            failed, stop = card.get('failed_gate'), card.get('terminal_stop')
            if stop == 'factory_bug_held':
                reason = STOPS[stop]
                finding = _block(card, 'factory_bug').get('finding_id')
                actions.append('factory bug: see finding ' + finding if isinstance(finding, str)
                               and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', finding)
                               else 'factory bug: finding unreadable')
            elif failed:
                bucket, reason = 'rejected', 'rejected'
                if isinstance(failed, str) and _stage(failed):
                    stage, reason = failed, 'rejected at ' + failed
            elif _block(card, 'gates').get('G12') == 'pass' and stop in (None, 'complete'):
                bucket, stage, reason = 'sealed', 'G12', 'sealed'
            else:
                if stop == 'provider_wait':
                    bucket = 'waiting'
                    retry = _stamp(_block(card, 'provider_wait').get('retry_after'))
                    if retry is not None and now - retry > THRESHOLDS['overdue_seconds']:
                        actions.append('relaunch overdue')
                if isinstance(stop, str) and (stop.startswith('stress_review_unresolved:') or
                        stop in ('freshness_unresolved', 'freshness_review_unavailable')):
                    reason = 'review unresolved'; actions.append('needs ruling')
                elif isinstance(stop, str) and stop.startswith('provider_limit:'):
                    reason = 'provider limit'
                elif stop is None or isinstance(stop, str) and stop in STOPS:
                    reason = STOPS[stop]
                else:
                    reason = 'unknown stop'; actions.append('check case')
                if stop == 'provider_wait_unrecoverable': actions.append('top up / re-login')
        if bucket not in ('rejected', 'not collected', 'unreadable') and (
                _near(budget.get('spent_usd'), budget.get('limit_usd')) or
                _near(card.get('builder_rounds'), recovery.get('rounds'))):
            actions.append('near limit')
        counts[bucket] += 1
        flags.extend(case + ': ' + action for action in sorted(set(actions)))
        lines.append(f'{case} | {stage} | {duration} | {spent} | rounds {rounds} | calls {calls} | {reason}')
    heading = f"Sealed {counts['sealed']} / {target}"
    summary = ', '.join(f'{counts[name]} {name}' for name in COUNTS)
    attention = '; '.join(flags) if flags else 'nothing needs you'
    return '\n'.join([heading, summary, 'Needs attention: ' + attention,
                      'Spend, rounds and calls are as of the last collected card.', *lines])


def _card(directory, entry, record, release):
    """Read only the pinned public metadata, not the potentially huge archive."""
    path = directory / 'generations' / entry['case'] / entry['generation']
    if path.is_symlink(): raise ValueError()
    manifest = read_file(path / 'manifest.json', entry['manifest_sha256'])
    for key, expected in (('schema', 1), ('case', entry['case']), ('job', entry['job']),
                          ('batch', record['id']), ('generation', entry['generation']),
                          ('batch_release_sha256', release)):
        if manifest[key] != expected: raise ValueError()
    name = entry['case'] + '.scorecard.json'
    card = read_file(path / name, manifest['files'][name]['sha256'])
    if (card['case'] != entry['case'] or card['sha256'] != entry['generation'] or
            card.get('batch_release_sha256') != release): raise ValueError()
    return card


def read_rows(policy, root, home):
    record = batch_money.manifest(policy, root)
    directory = home / 'batches' / record['id']
    if not (directory / 'journal.json').is_file(): raise ValueError('missing journal')
    # Status never creates the writer's lock or repairs a projection.
    with batch_service._regular(directory / 'lock') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        state = batch_service._load(directory, record, policy['batch']['manifest_sha256'])
        jobs = set(record['jobs']) | {r['child_job'] for r in state['derivations'].values()}
        rows = []
        for name in sorted(jobs):
            case = batch_service.resolve_job(record, name)['case']
            entries = [e for e in state['entries'].values() if e['job'] == name]
            row = dict(case=case, phase='not collected', card=None)
            try:
                pointer = directory / 'current' / (case + '.json')
                if pointer.exists() or pointer.is_symlink():
                    value = batch_service._json(pointer)
                    if set(value) != {'generation', 'manifest_sha256'}: raise ValueError()
                    entry = state['entries'][case + '/' + value['generation']]
                    if entry['case'] != case or entry['manifest_sha256'] != value['manifest_sha256']:
                        raise ValueError()
                elif len(entries) == 1: entry = entries[0]
                elif not entries:
                    rows.append(row); continue
                else: raise ValueError('ambiguous generation')
                row.update(phase='stopped', card=_card(directory, entry, record, policy['batch']['sha256']))
            except (OSError, ValueError, KeyError, TypeError):
                row.update(phase='unreadable')
            rows.append(row)
    return record['target_slots'], rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('status',))
    parser.add_argument('--control-home', type=Path, default=Path(os.environ.get(
        'UNBUG_CONTROL_HOME', str(Path.home() / '.unbug-control'))))
    args = parser.parse_args(argv)
    try:
        policy = batch_service._json(args.control_home / 'policy.json')
        target, rows = read_rows(policy, ROOT, args.control_home)
    except (OSError, ValueError, KeyError, TypeError):
        print('Batch unreadable\nNeeds attention: unreadable')
        return 1
    workers, progress = observe(rows)
    print(render(target, rows, workers, progress))
    return 0


if __name__ == '__main__': raise SystemExit(main())
