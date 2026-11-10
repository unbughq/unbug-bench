"""Explicit, expiring model changes for the founder-approved existing cohort only."""
import datetime
import json
import pathlib

CONFIG = pathlib.Path(__file__).with_name('free-model-cutover.json')
FREE = {'opencode/minimax-m3.1-flash-free', 'opencode/deepseek-v4.1-flash-free'}


def provider_config(case, model):
    """Native free routes; the Go reference uses the run's already-selected account."""
    if model not in FREE:
        raise ValueError('unapproved free route')
    row = json.loads(CONFIG.read_text()).get('cases', {}).get(case) if CONFIG.is_file() else None
    if not row:  # 2026-10-20 founder: new cases use the free models too, on the run's own OpenCode account
        row = {'opencode_account': 0}
    elif row.get('opencode_account') not in (1, 2):
        raise ValueError('original OpenCode account not verified')
    # Both run on the lease's OpenCode account (the router leases them only on an account pool).
    options = {'baseURL': 'https://opencode.ai/inference/openai/v1', 'apiKey': '{env:OPENCODE_API_KEY}'}
    if model == 'opencode/minimax-m3.1-flash-free':
        options['baseURL'] = 'https://opencode.ai/inference/go/openai/v1'
    return {'options': options, 'whitelist': [model.split('/', 1)[1]]}


def selected(case, args):
    if not CONFIG.is_file():
        return None
    config = json.loads(CONFIG.read_text())
    row = config.get('cases', {}).get(case)
    if not row:
        return None
    if datetime.datetime.now(datetime.timezone.utc) >= datetime.datetime.fromisoformat(config['expires_utc'].replace('Z', '+00:00')):
        raise ValueError('approved free-model cohort deadline reached')
    for flag, limit in row['caps'].items():
        if float(getattr(args, flag[2:].replace('-', '_'))) != float(limit):
            raise ValueError('free-model transition must preserve issued caps')
    before, after = row['before'], row['after']
    if set(before) != set(after):
        raise ValueError('free-model transition changed role set')
    for role, old in before.items():
        new = after[role]
        if old['model'].startswith(('claude/', 'codex/')) or role in ('strong_calibrator', 'easy_calibrator') or old['model'].endswith(('-free', ':free')):
            if new != old:
                raise ValueError('protected role changed')
        elif new['model'] not in FREE or new.get('effort') != 'default':
            raise ValueError('unapproved free replacement')
    return row


def signature(roles):
    return {k: (v['model'], v.get('effort', 'default')) for k, v in roles.items()}


def apply(c, roles):
    row = selected(getattr(c, 'case_id', None), c.args)
    # 2026-10-20 founder: the rotation itself now assigns the free models; only a case issued the old paid rotation
    # (roles equal to `before`) takes this row's `after`. Anything else keeps the rotation's roles.
    if not row or signature(roles) != signature(row['before']):
        return roles
    c.card['model_transition'] = {'kind': 'approved-paid-to-free', 'before': row['before'], 'after': row['after'], 'caps': row['caps']}
    return {k: dict(v) for k, v in row['after'].items()}
