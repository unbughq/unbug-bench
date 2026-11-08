"""Explicit, expiring model changes for the founder-approved existing cohort only."""
import datetime
import json
import pathlib

CONFIG = pathlib.Path(__file__).with_name('free-model-cutover.json')
FREE = {'opencode/minimax-m3.1-flash-free', 'opencode/deepseek-v4.1-flash-free'}
# Each free model keeps the endpoint it already ran on; only the account key is new for DeepSeek and GLM.
ENDPOINTS = {'opencode/deepseek-v4.1-flash-free': 'https://opencode.ai/inference/openai/v1',
             'opencode/minimax-m3.1-flash-free': 'https://opencode.ai/inference/go/openai/v1',
             'opencode/glm-5.3-flash-free': 'https://opencode.ai/zen/v1'}


def provider_config(case, model):
    """Native free routes, each run on one of the two OpenCode accounts (founder 2026-11-08): the
    router leases the account and model_call_gate.free_environment passes only that account's key.
    An NVIDIA route is its own OpenAI-compatible provider ('nvidia') on the nvidia-key account."""
    from token_prices import FREE_ROUTES, NVIDIA_ROUTES
    if model not in FREE_ROUTES:
        raise ValueError('unapproved free route')
    if model in NVIDIA_ROUTES:
        return nvidia_provider(model)
    row = json.loads(CONFIG.read_text()).get('cases', {}).get(case) if CONFIG.is_file() else None
    if row and row.get('opencode_account') not in (1, 2):
        raise ValueError('original OpenCode account not verified')
    options = {'baseURL': ENDPOINTS[model], 'apiKey': '{env:OPENCODE_API_KEY}'}
    return {'options': options, 'whitelist': [model.split('/', 1)[1]]}


def provider_name(model):
    """The OpenCode provider a free route runs on: 'opencode' or 'nvidia'."""
    return model.partition('/')[0]


def nvidia_provider(model):
    """OpenCode's bundled OpenAI-compatible SDK pointed at NVIDIA, this one model only, priced at $0 so
    OpenCode books the reported tokens at no cost; any cost it does book stops the call
    (budget.check_reservation). includeUsage asks for token counts on the streamed reply."""
    from token_prices import NVIDIA_URL
    model_id = model.partition('/')[2]
    return {'npm': '@ai-sdk/openai-compatible', 'name': 'NVIDIA',
            'options': {'baseURL': NVIDIA_URL, 'apiKey': '{env:NVIDIA_API_KEY}', 'includeUsage': True},
            'models': {model_id: {'name': model_id, 'cost': {'input': 0, 'output': 0, 'cache_read': 0, 'cache_write': 0}}},
            'whitelist': [model_id]}


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
