"""Pinned USD list prices per million tokens; unknown models fail closed."""
from decimal import Decimal, InvalidOperation, ROUND_CEILING
# Source: https://developers.openai.com/api/docs/models/gpt-6.1-sol
# Verified 2026-10-24. Standard list price, not subscription billing.
CODEX_PRICES = {"codex/gpt-6.1-sol": (2.0, 0.10, 10.0)}  # input, cached input, output

# https://platform.claude.com/docs/en/about-claude/pricing (2026-10-30).
# Missing cache TTL uses the dearer one-hour write rate. Results use the CLI receipt.
CLAUDE_PRICES = {"claude/claude-opus-5-5": (4.0, 0.20, 8.0, 20.0)}

# These are the existing runtime's pinned overrides, not new provider quotes.
PAID_PRICES = {'openrouter/deepseek/deepseek-v4.1-flash': (.02, 1.0),
               'openrouter/meta/muse-spark-1.3-contributor': (.10, .20, .002, .10)}
PAID_PRICES['opencode-go/muse-spark-1.3-contributor'] = PAID_PRICES['openrouter/meta/muse-spark-1.3-contributor']


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
    elif model in PAID_PRICES: rates = PAID_PRICES[model][:2]
    elif isinstance(model, str) and model.endswith(('-free', ':free')): rates = (0, 0)
    else: return None
    maximum = bounds['requests'] * (bounds['input_tokens'] * Decimal(str(rates[0]))
        + bounds['output_tokens'] * Decimal(str(rates[1]))) / 1000000 + fee
    return maximum.quantize(Decimal('.000000001'), rounding=ROUND_CEILING)

# Provider-enforced context/output, plus the worker gate's joint allowance.
# https://platform.claude.com/docs/en/models/opus-5-5/overview (2026-10-30).
GATED_CLAUDE = 'claude/claude-opus-5-5'
CLAUDE_CONTEXT, CLAUDE_OUTPUT = 1_000_000, 32768
CLAUDE_CALL_USD = Decimal('50')
CLAUDE_GATE_FIELDS = ('input_tokens', 'cache_read_input_tokens',
                      'cache_creation_input_tokens', 'output_tokens')


def claude_standard_usage(usage):
    """Absent mode fields mean defaults; explicit unknown/premium modes do not."""
    return (isinstance(usage, dict) and usage.get('speed', 'standard') == 'standard'
            and usage.get('inference_geo', 'global') == 'global')


def _claude_list_cost(model, usage):
    rates = CLAUDE_PRICES.get(model)
    if rates is None or not claude_standard_usage(usage): return None
    values = [usage.get(k) for k in CLAUDE_GATE_FIELDS]
    if any(type(v) not in (int, float) or not 0 <= v < float('inf') for v in values): return None
    return sum(Decimal(str(v)) * Decimal(str(rate)) for v, rate in zip(values, rates)) / 1_000_000


def claude_gate_cost(usage):
    """Same standard/global list tariff as partial CLI estimates; book nothing."""
    return _claude_list_cost(GATED_CLAUDE, usage)


def claude_gate_maximum():
    rates = [Decimal(str(v)) for v in CLAUDE_PRICES[GATED_CLAUDE]]
    return dict(max_usd=float(CLAUDE_CALL_USD),
                max_input_tokens=int(CLAUDE_CALL_USD * 1_000_000 / min(rates[:3])),
                max_output_tokens=int(CLAUDE_CALL_USD * 1_000_000 / rates[3]),
                price_source='token_prices:2026-10-30:claude-opus-5-5:' + ','.join(map(str, rates)) + ':1.0:standard-global:joint-gate-v1')


def claude_cost(model, usage):
    amount = _claude_list_cost(model, usage)
    return None if amount is None else float(amount)


def codex_cost(model, usage):
    rates = CODEX_PRICES.get(model)
    if rates is None:
        return None
    incoming, cached, outgoing = (usage.get(k) for k in ("input_tokens", "cached_input_tokens", "output_tokens"))
    if any(type(v) not in (int, float) or not 0 <= v < float("inf") for v in (incoming, cached, outgoing)) or cached > incoming:
        return None
    # CLI aggregates a whole turn: conservatively use long-context rates when its
    # total exceeds 272K, even if individual requests may have been shorter.
    long_context = incoming > 272000
    return ((incoming - cached) * rates[0] * (2 if long_context else 1)
            + cached * rates[1] * (2 if long_context else 1)
            + outgoing * rates[2] * (1.5 if long_context else 1)) / 1000000
