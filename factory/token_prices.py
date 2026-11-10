"""Pinned USD list prices per million tokens; unknown models fail closed."""
import json
from decimal import Decimal, InvalidOperation, ROUND_CEILING
# Source: https://developers.openai.com/api/docs/models/gpt-6.1-sol
# Verified 2026-10-24. Standard list price, not subscription billing.
CODEX_PRICES = {"codex/gpt-6.1-sol": (2.0, 0.10, 10.0)}  # input, cached input, output

# https://platform.claude.com/docs/en/about-claude/pricing (2026-10-30).
# Missing cache TTL uses the dearer one-hour write rate. Results use the CLI receipt.
CLAUDE_PRICES = {"claude/claude-opus-5-5": (4.0, 0.20, 8.0, 20.0),
                 "claude/claude-opus-4-5-20251101": (5.0, 0.5, 10.0, 25.0)}

# OpenRouter endpoint quotes and primary limit contracts, checked 2026-10-30.
# Full source records: tests/factory/fixtures/router-cheap-{price-records,source-evidence}.json.gz.
# Output holds deliberately exceed the requested cap; reasoning mapping is not assumed.
OPENROUTER_OUTPUT = 32768
GATED_OPENROUTER = {
    # Current official-provider contract: router-minimax-price-record.json.gz.
    # cheaper: endpoints tried before the pin, each at or below the pin's input and output price, same
    # or better precision, tools/tool_choice/max_tokens/reasoning supported, healthy (live /endpoints, 2026-11-10 09:16Z).
    'openrouter/minimax/minimax-m3.1-flash': dict(endpoint='minimax', cheaper=('gmicloud/fp8', 'streamlake/fp8'),
        prices=('0.15', '0.015', '0.6'), context=1048576, output=524288, windows=3,
        cache_write='0', source_date='2026-11-06'),
    'openrouter/xiaomi/mimo-v2.6-pro': dict(endpoint='xiaomi/fp8', cheaper=('deepinfra/fp8',),
        prices=('0.435', '0.0036', '0.87'), context=1048576, output=131072, windows=3, cache_write='0'),
    'openrouter/deepseek/deepseek-v4.1-flash': dict(endpoint='deepinfra/fp8', cheaper=('morph/fp8',),
        prices=('0.14', '0.0042', '0.42'), context=1048576, output=1048576, windows=2, cache_write='0'),
    # Pinned primary endpoint quote: router-glm-price-record.json.gz.
    'openrouter/z-ai/glm-5.3-flash': dict(endpoint='deepinfra/fp4', cheaper=('relace/fp4', 'morph/fp8'),
        prices=('0.15', '0.03', '0.5'), context=1048576, output=943718, windows=2,
        cache_write='0', source_date='2026-11-06'),
    # OpenRouter /api/v1/models/meta/muse-spark-1.3-contributor/endpoints, read 2026-11-09: one endpoint,
    # Meta (meta/muse-spark-1.3-contributor-20260902), $0.10 in / $0.002 cache read / $0.20 out, no cache write.
    'openrouter/meta/muse-spark-1.3-contributor': dict(endpoint='meta',
        prices=('0.1', '0.002', '0.2'), context=1048576, output=943718, windows=2,
        cache_write='0', source_date='2026-11-09'),
}


# OpenCode's free routes (founder 2026-11-08). They have no gate: their money maximum is $0, and the
# per-call reservation check (budget.check_reservation) stops a call the moment it books any cost.
FREE_ROUTES = frozenset({'opencode/deepseek-v4.1-flash-free', 'opencode/minimax-m3.1-flash-free',
                         'opencode/glm-5.3-flash-free'})


def free_maximum(route):
    if route not in FREE_ROUTES: return None
    return dict(max_usd=0.0, max_input_tokens=0, max_output_tokens=0, price_source='free:' + route)


# OpenCode Go plan routes (founder 2026-11-09: "move everything over to opencode so we stop burning
# money on openrouter"). The founder's two Go accounts pay from their plan allowance, so no money moves
# while "Extra Usage" stays off. A Go call is bounded at its OpenRouter twin's pinned list price, so it
# has its twin's maximum, but it books what the plan bills, $0, to case and batch money (budget.py,
# "book Go at cost", founder 2026-11-09). Its list value is kept and reported as plan_list_cost_usd.
GO_TWINS = {'opencode-go/deepseek-v4.1-flash': 'openrouter/deepseek/deepseek-v4.1-flash',
            'opencode-go/minimax-m3.1-flash': 'openrouter/minimax/minimax-m3.1-flash',
            'opencode-go/mimo-v2.6-pro': 'openrouter/xiaomi/mimo-v2.6-pro',
            'opencode-go/glm-5.3-flash': 'openrouter/z-ai/glm-5.3-flash',
            'opencode-go/muse-spark-1.3-contributor': 'openrouter/meta/muse-spark-1.3-contributor'}
GO_ROUTES = frozenset(GO_TWINS)


def go_maximum(route):
    maximum = openrouter_gate_maximum(GO_TWINS[route]) if route in GO_TWINS else None
    if maximum is None: return None
    return dict(maximum, price_source='opencode-go:' + route.partition('/')[2] + ':twin=' + maximum['price_source'])


def go_step_cost(route, tokens):
    """One OpenCode step on a Go plan route at its twin's list price. Reasoning is billed as output,
    and a cache write at the full input rate (OpenRouter's twins quote no write price)."""
    prices = runtime_prices(route)
    return ((tokens['input'] + tokens['cache']['write']) * prices['input'] + (tokens['output'] + tokens['reasoning']) * prices['output']
            + tokens['cache']['read'] * prices['cache_read']) / 1_000_000


def openrouter_gate_maximum(route):
    profile = GATED_OPENROUTER.get(route)
    if profile is None or Decimal(profile['cache_write']) != 0: return None
    incoming, cached, outgoing = map(Decimal, profile['prices'])
    worst = (profile['context'] * incoming + profile['output'] * outgoing) / 1_000_000
    maximum = (profile['windows'] * worst + Decimal('.000001')).quantize(Decimal('.000000001'), rounding=ROUND_CEILING)
    return dict(max_usd=float(maximum), max_input_tokens=int(maximum * 1_000_000 / incoming),
                max_output_tokens=int(maximum * 1_000_000 / outgoing),
                price_source='token_prices:' + profile.get('source_date', '2026-10-30') + ':' + route.replace('/', ':', 1) + ':' + profile['endpoint'] + ':'
                             + ','.join(profile['prices']) + ':joint-gate-v1')


def openrouter_gate_cost(route, usage):
    if route not in GATED_OPENROUTER or not isinstance(usage, dict): return None
    incoming, _, outgoing = map(Decimal, GATED_OPENROUTER[route]['prices'])
    values = [usage.get(k) for k in ('prompt_tokens', 'completion_tokens')]
    if any(type(v) is not int or v < 0 for v in values): return None
    amount = (values[0] * incoming + values[1] * outgoing) / 1_000_000
    if 'cost' in usage:
        cost = usage['cost']
        if type(cost) not in (int, float) or not 0 <= cost < float('inf') or Decimal(str(cost)) > amount: return None
    return amount


def runtime_prices(route):
    route = GO_TWINS.get(route, route)
    if route in GATED_OPENROUTER:
        incoming, cached, outgoing = map(float, GATED_OPENROUTER[route]['prices'])
        return dict(input=incoming, output=outgoing, cache_read=cached, cache_write=0)
    raise KeyError(route)


def invocation_maximum(model, bounds):
    """Price E/A's enforced bounds; missing bounds/prices never become zero.

    This helper grants no admission. Runtime admission uses only a valid_lease-
    checked Lease.max_usd (model_runtime.invocation_maximum).
    """
    if not isinstance(bounds, dict): return None
    names = ('requests', 'input_tokens', 'output_tokens')
    if any(type(bounds.get(k)) is not int or bounds[k] < 0 for k in names) or bounds['requests'] < 1:
        return None
    try:
        fee = Decimal(str(bounds['tool_fees_usd']))
        if not fee.is_finite() or fee < 0: return None
    except (KeyError, InvalidOperation, ValueError): return None
    if model in CODEX_PRICES:
        # Same published long-context tariff used by codex_cost below. Apply
        # its highest rate even if the enforced input bound is shorter.
        incoming, cached, outgoing = CODEX_PRICES[model]
        rates = max(incoming, cached) * 2, outgoing * 1.5
    elif model in CLAUDE_PRICES:
        # Standard/global gate tariff, including the dearer one-hour cache write.
        incoming, cached, written, outgoing = CLAUDE_PRICES[model]
        rates = max(incoming, cached, written), outgoing
    elif model in GATED_OPENROUTER:
        prices = GATED_OPENROUTER[model]['prices']; rates = prices[0], prices[2]
    elif isinstance(model, str) and model.endswith(('-free', ':free')): rates = (0, 0)
    else: return None
    maximum = bounds['requests'] * (bounds['input_tokens'] * Decimal(str(rates[0]))
        + bounds['output_tokens'] * Decimal(str(rates[1]))) / 1000000 + fee
    return maximum.quantize(Decimal('.000000001'), rounding=ROUND_CEILING)

# Provider-enforced context/output, plus the worker gate's joint allowance.
# https://platform.claude.com/docs/en/models/opus-5-5/overview (2026-10-30).
GATED_CLAUDE = 'claude/claude-opus-5-5'
GATED_CLAUDE45 = 'claude/claude-opus-4-5-20251101'
CLAUDE_CONTEXT, CLAUDE_OUTPUT = 1_000_000, 32768
CLAUDE_CALL_USD = Decimal('50')
CLAUDE_PROFILES = {GATED_CLAUDE: CLAUDE_CALL_USD,
    GATED_CLAUDE + ':small': Decimal('10'),
    GATED_CLAUDE + ':medium': Decimal('15'),
    GATED_CLAUDE45 + ':compact': Decimal('3'),
    GATED_CLAUDE45 + ':small': Decimal('5')}


def claude_profile(route):
    if route not in CLAUDE_PROFILES: return None
    model = route.partition(':')[0]
    return dict(model=model, context=200000 if model == GATED_CLAUDE45 else CLAUDE_CONTEXT,
                output=16384 if model == GATED_CLAUDE45 else CLAUDE_OUTPUT,
                thinking=8192 if model == GATED_CLAUDE45 else None)

CLAUDE_GATE_FIELDS = ('input_tokens', 'cache_read_input_tokens',
                      'cache_creation_input_tokens', 'output_tokens')


def claude_standard_usage(usage):
    """Recognize standard-speed usage; unavailable geo receives a conservative gate charge."""
    return (isinstance(usage, dict) and usage.get('speed', 'standard') == 'standard'
            and usage.get('inference_geo', 'global') in ('global', 'not_available'))


def _claude_list_cost(model, usage):
    rates = CLAUDE_PRICES.get(model)
    if rates is None or not claude_standard_usage(usage): return None
    values = [usage.get(k) for k in CLAUDE_GATE_FIELDS]
    if any(type(v) not in (int, float) or not 0 <= v < float('inf') for v in values): return None
    return sum(Decimal(str(v)) * Decimal(str(rate)) for v, rate in zip(values, rates)) / 1_000_000


def claude_gate_cost(usage, route=GATED_CLAUDE):
    """Bound OAuth usage even when the organization does not report geography."""
    profile = claude_profile(route)
    amount = None if profile is None else _claude_list_cost(profile['model'], usage)
    # Without explicit global evidence, cover the documented 1.1x US uplift.
    # Old models have no regional surcharge. This never widens the lease.
    if amount is not None and profile['thinking'] is None and usage.get('inference_geo') != 'global':
        amount *= Decimal('1.1')
    return amount


def claude_gate_maximum(route=GATED_CLAUDE):
    maximum = CLAUDE_PROFILES.get(route)
    if maximum is None: return None
    suffix = ('' if route == GATED_CLAUDE else
              f':profile={route.rsplit(":", 1)[1]}:usd={maximum}')
    profile = claude_profile(route)
    rates = [Decimal(str(v)) for v in CLAUDE_PRICES[profile['model']]]
    source = ('token_prices:2026-10-31:claude-opus-4-5-20251101:' + ','.join(map(str, rates))
              + ':context=200000:output=16384:standard-global:joint-gate-v1'
              if profile['model'] == GATED_CLAUDE45 else
              'token_prices:2026-10-30:claude-opus-5-5:' + ','.join(map(str, rates)) + ':1.0:standard-global:joint-gate-v1')
    return dict(max_usd=float(maximum),
                max_input_tokens=int(maximum * 1_000_000 / min(rates[:3])),
                max_output_tokens=int(maximum * 1_000_000 / rates[3]),
                price_source=source + suffix)


def claude_cost(model, usage):
    profile = claude_profile(model)
    amount = _claude_list_cost(profile['model'] if profile else model, usage)
    return None if amount is None else float(amount)


def codex_cost(model, usage, long_context=None):
    """List value of Codex usage. long_context=None decides from the usage itself; True forces the
    long-context tariff (tokens whose request sizes are unknown)."""
    rates = CODEX_PRICES.get(model)
    if rates is None:
        return None
    incoming, cached, outgoing = (usage.get(k) for k in ("input_tokens", "cached_input_tokens", "output_tokens"))
    if any(type(v) not in (int, float) or not 0 <= v < float("inf") for v in (incoming, cached, outgoing)) or cached > incoming:
        return None
    # CLI aggregates a whole turn: conservatively use long-context rates when its
    # total exceeds 272K, even if individual requests may have been shorter.
    if long_context is None: long_context = incoming > 272000
    return ((incoming - cached) * rates[0] * (2 if long_context else 1)
            + cached * rates[1] * (2 if long_context else 1)
            + outgoing * rates[2] * (1.5 if long_context else 1)) / 1000000


# Codex on the ChatGPT subscription, for the strong calibrator (2026-11-08). Like the free routes there is
# no gate: Codex's own per-request usage (its session log's token_count events) is priced at the
# CODEX_PRICES list rates and booked as each request lands, and the per-call reservation check
# (budget.check_reservation) stops the call once the booked value passes this maximum.
CODEX_CALL_USD = Decimal('50')
CODEX_PROFILES = {'codex/gpt-6.1-sol': CODEX_CALL_USD}
CODEX_USAGE_FIELDS = ('input_tokens', 'cached_input_tokens', 'output_tokens')


def codex_gate_maximum(route):
    maximum = CODEX_PROFILES.get(route)
    if maximum is None or route not in CODEX_PRICES: return None
    incoming, cached, outgoing = (Decimal(str(v)) for v in CODEX_PRICES[route])
    # Token maxima at the dearest (long-context) tariff: 2x input, 1.5x output.
    return dict(max_usd=float(maximum),
                max_input_tokens=int(maximum * 1_000_000 / (max(incoming, cached) * 2)),
                max_output_tokens=int(maximum * 1_000_000 / (outgoing * Decimal('1.5'))),
                price_source='token_prices:2026-10-24:' + route.replace('/', ':', 1) + ':'
                             + ','.join(map(str, CODEX_PRICES[route])) + ':long-context=2,1.5:self-reported-v1')


def codex_request_usages(rollouts):
    """Per-request token usage from Codex session logs (rollout-*.jsonl): one token_count event closes
    one API call. A repeated token_count event (same cumulative total) is not a new request."""
    usages, previous = [], None
    for line in rollouts.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "event_msg":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count" or not isinstance(payload.get("info"), dict):
            continue
        last, total = payload["info"].get("last_token_usage"), payload["info"].get("total_token_usage")
        if not isinstance(last, dict) or total == previous:
            continue
        previous = total
        usages.append(last)
    return usages
