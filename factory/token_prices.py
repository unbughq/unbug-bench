"""Pinned USD list prices per million tokens; unknown models fail closed."""
# Source: https://developers.openai.com/api/docs/models/gpt-6.1-sol
# Verified 2026-10-24. Standard list price, not subscription billing.
CODEX_PRICES = {"codex/gpt-6.1-sol": (2.0, 0.10, 10.0)}  # input, cached input, output

# https://platform.claude.com/docs/en/about-claude/pricing (2026-10-25).
# Missing cache TTL uses the dearer one-hour write rate. Results use the CLI receipt.
CLAUDE_PRICES = {"claude/claude-opus-5-5": (4.0, 0.20, 8.0, 20.0)}


def claude_cost(model, usage):
    rates = CLAUDE_PRICES.get(model)
    values = [usage.get(k) for k in ('input_tokens', 'cache_read_input_tokens',
                                    'cache_creation_input_tokens', 'output_tokens')]
    if rates is None or any(type(v) not in (int, float) or not 0 <= v < float('inf') for v in values):
        return None
    # Conservative for fast mode and US-only inference when stream metadata omits them.
    return sum(v * rate for v, rate in zip(values, rates)) * 2 * 1.1 / 1000000


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
