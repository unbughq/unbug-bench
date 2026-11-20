"""Worker-local admission for inference; shared paid authorization but no case-ledger bookings or payload logs.

This is not a sandbox for arbitrary Bash/network use of the account credential.
Each upstream attempt holds its whole worst case before network; only complete,
validated provider usage can refund it. No production upstream override exists.
"""
from contextlib import contextmanager
from decimal import Decimal
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import pwd
from pathlib import Path
import secrets
import sys
import socket
import subprocess
import threading
import time

from budget import BudgetError
from token_prices import (GATED_CLAUDE, CLAUDE_PROFILES, CODEX_PROFILES, CLAUDE_CONTEXT, CLAUDE_OUTPUT, claude_profile,
                          CLAUDE_GATE_FIELDS, CLAUDE_PRICES, claude_gate_cost, claude_standard_usage,
                          GATED_OPENROUTER, OPENROUTER_OUTPUT, openrouter_cached_tokens, openrouter_gate_cost, runtime_prices)

ENV_KEYS = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'CLAUDE_CODE_OAUTH_TOKEN',
    'CLAUDE_CONFIG_DIR', 'DISABLE_AUTOUPDATER', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC',
    'CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS', 'CLAUDE_CODE_MAX_OUTPUT_TOKENS',
    'MAX_THINKING_TOKENS', 'CLAUDE_CODE_MAX_RETRIES', 'CLAUDE_CODE_GZIP_REQUEST_BODIES', 'ANTHROPIC_BASE_URL',
    'ANTHROPIC_SMALL_FAST_MODEL', 'FACTORY_STRATEGY_DIAGNOSTIC',
    'FACTORY_STRATEGY_SECONDS', 'FACTORY_STRATEGY_WORKERS')
BETAS = 'claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14,effort-2025-11-24'
HEADROOM = Decimal('0.000001')
# Free 4xx rejections in a row (not 429) after which a call stops as upstream_rejected: a permanent one
# (a prompt too long, a bad request) settles at $0 and would otherwise be retried until the step timeout.
MAX_REJECTIONS = 3
_RETAINED = []  # Unresolved firewall cleanup must never release a reusable port.
BODY_FIELDS = {'model', 'max_tokens', 'messages', 'system', 'tools', 'tool_choice',
    'stream', 'stop_sequences', 'temperature', 'top_p', 'top_k', 'thinking',
    'output_config', 'metadata', 'cache_control', 'service_tier', 'context_management'}
HOP_HEADERS = {'connection', 'transfer-encoding', 'keep-alive', 'trailer', 'upgrade', 'content-length'}
STOP_REASONS = {'end_turn', 'max_tokens', 'stop_sequence', 'tool_use', 'refusal', 'model_context_window_exceeded'}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _json(raw):
    def invalid(_): raise ValueError('nonfinite JSON')
    def number(value):
        result = float(value)
        if not math.isfinite(result): raise ValueError('nonfinite JSON')
        return result
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid, parse_float=number)


def _cache(value):
    if (not isinstance(value, dict) or set(value) - {'type', 'ttl'}
            or value.get('type') != 'ephemeral' or value.get('ttl', '5m') not in ('5m', '1h')):
        raise ValueError('unsupported cache control')


def _content(value):
    if isinstance(value, str): return
    if not isinstance(value, list): raise ValueError('unsupported content')
    fields = {'text': {'type', 'text', 'cache_control'},
        'tool_use': {'type', 'id', 'name', 'input', 'cache_control'},
        'tool_result': {'type', 'tool_use_id', 'content', 'is_error', 'cache_control'},
        'thinking': {'type', 'thinking', 'signature', 'cache_control'},
        'redacted_thinking': {'type', 'data', 'cache_control'},
        'image': {'type', 'source', 'cache_control'},
        'document': {'type', 'source', 'title', 'context', 'citations', 'cache_control'}}
    for block in value:
        if not isinstance(block, dict) or block.get('type') not in fields or set(block) - fields[block['type']]:
            raise ValueError('unsupported content block')
        if 'cache_control' in block: _cache(block['cache_control'])
        if block['type'] == 'tool_result': _content(block.get('content', ''))
        if block['type'] in ('image', 'document'):
            source = block.get('source')
            if (not isinstance(source, dict) or source.get('type') not in ('base64', 'url', 'text')
                    or set(source) - {'type', 'media_type', 'data', 'url'}):
                raise ValueError('unsupported media source')


def request_body(raw, route=GATED_CLAUDE):
    profile = claude_profile(route)
    if profile is None: raise ValueError('unsupported route')
    body = _json(raw)
    if not isinstance(body, dict) or set(body) - BODY_FIELDS or body.get('model') != profile['model'].partition('/')[2]:
        raise ValueError('unsupported request')
    output = body.get('max_tokens')
    if type(output) is not int or not 0 <= output: raise ValueError('invalid output bound')
    body['max_tokens'] = min(output, profile['output'])
    # OAuth organizations may reject inference_geo. The allowance prices absent
    # response geography at the regional ceiling rather than assuming global.
    body.pop('context_management', None)  # No server-side sampling/compaction.
    if 'thinking' in body:
        thinking = body['thinking']
        if not isinstance(thinking, dict): raise ValueError('unsupported thinking')
        if profile['thinking'] is None:
            if thinking.get('type') != 'adaptive': raise ValueError('unsupported thinking')
            body['thinking'] = {'type': 'adaptive'}
        elif thinking.get('type') == 'disabled' and set(thinking) == {'type'}:
            pass
        elif (set(thinking) != {'type', 'budget_tokens'} or thinking.get('type') != 'enabled'
                or type(thinking.get('budget_tokens')) is not int
                or not 1024 <= thinking['budget_tokens'] <= profile['thinking']
                or thinking['budget_tokens'] >= body['max_tokens']):
            raise ValueError('unsupported thinking')
    if body.get('service_tier', 'standard_only') not in ('auto', 'standard_only'):
        raise ValueError('unsupported tier')
    body['service_tier'] = 'standard_only'
    if 'stream' in body and type(body['stream']) is not bool: raise ValueError('invalid stream')
    if 'cache_control' in body: _cache(body['cache_control'])
    config = body.get('output_config', {})
    if (not isinstance(config, dict) or set(config) - {'effort', 'format'}
            or config.get('effort', 'high') not in (('low', 'medium', 'high') if profile['thinking'] is not None
                                                 else ('low', 'medium', 'high', 'xhigh', 'max'))):
        raise ValueError('unsupported output config')
    if 'format' in config and (not isinstance(config['format'], dict)
            or set(config['format']) != {'type', 'schema'} or config['format']['type'] != 'json_schema'):
        raise ValueError('unsupported format')
    metadata = body.get('metadata', {})
    if (not isinstance(metadata, dict) or set(metadata) - {'user_id'}
            or ('user_id' in metadata and (not isinstance(metadata['user_id'], str) or len(metadata['user_id']) > 512))):
        raise ValueError('unsupported metadata')
    for tool in body.get('tools', []):
        if (not isinstance(tool, dict) or set(tool) - {'type', 'name', 'description', 'input_schema', 'cache_control'}
                or tool.get('type', 'custom') != 'custom' or not isinstance(tool.get('input_schema'), dict)):
            raise ValueError('unsupported server tool')
        if 'cache_control' in tool: _cache(tool['cache_control'])
    _content(body.get('system', ''))
    if not isinstance(body.get('messages'), list): raise ValueError('invalid messages')
    for message in body['messages']:
        if (not isinstance(message, dict) or set(message) - {'role', 'content', 'cache_control'}
                or message.get('role') not in ('user', 'assistant', 'system')):
            raise ValueError('unsupported message')
        if 'cache_control' in message: _cache(message['cache_control'])
        _content(message.get('content', ''))
    return body


def empty_usage(route=GATED_CLAUDE):
    return dict(version=1, forwarded_requests=0, validated_requests=0, unknown_requests=0,
        in_flight_requests=0, unsupported_requests=0, settled_usd='0', held_usd='0',
        settled_input_tokens=0, held_input_tokens=0, settled_output_tokens=0,
        held_output_tokens=0, max_request_output_tokens=GATED_OPENROUTER[route]['output'] if route in GATED_OPENROUTER else (claude_profile(route) or {'output': CLAUDE_OUTPUT})['output'], exhausted=False, closed=True)


def worst_request(route, output=None):
    """The usage one request may reach on a gated route; its price is that request's hold."""
    if route in CLAUDE_PROFILES:
        worst = dict.fromkeys(CLAUDE_GATE_FIELDS, 0)
        profile = claude_profile(route)
        incoming = max(range(3), key=lambda i: CLAUDE_PRICES[profile['model']][i])
        worst[CLAUDE_GATE_FIELDS[incoming]] = profile['context']
        worst['output_tokens'] = profile['output'] if output is None else output
        return worst
    # openrouter_body clamps every request's max_tokens to OPENROUTER_OUTPUT, so that (or the request's
    # own smaller bound) is all it can produce, not the model's whole output limit. Holding the model
    # limit (943,718 tokens on GLM 5.3 Flash, $0.63 a request against $0.17) made 19 requests whose
    # stream ended without usage retain $11.95 of a $12.50 window, and 18681d's G10 easy calibrator
    # (12 November) stopped model_call_cap after $0.17 of real spend.
    profile = GATED_OPENROUTER[route]
    output = OPENROUTER_OUTPUT if output is None else output
    return dict(prompt_tokens=profile['context'], completion_tokens=min(output, profile['output']))


def request_hold(route):
    """USD one request on this gated route reserves before it is forwarded, or None if ungated."""
    if route not in CLAUDE_PROFILES and route not in GATED_OPENROUTER: return None
    usage = worst_request(route)
    cost = claude_gate_cost(usage, route) if route in CLAUDE_PROFILES else openrouter_gate_cost(route, usage)
    return None if cost is None else Decimal(cost)


class Allowance:
    def __init__(self, lease, cancel=None, deadline=math.inf):
        self.lease, self.cancel = lease, cancel
        self.lock, self.exhaustion = threading.Lock(), threading.Event()
        self.condition = threading.Condition(self.lock)
        self.deadline = deadline
        self.closed = False
        self.paid_failure = None
        self.rejections, self.rejected = 0, threading.Event()
        self.active, self.connections = {}, {}
        self.forwarded = self.validated = self.unknown = self.unsupported = 0
        self.settled = [Decimal(0), 0, 0]
        self.retained = [Decimal(0), 0, 0]

    def is_set(self):
        return (self.paid_failure is not None or self.exhaustion.is_set() or self.rejected.is_set()
                or (self.cancel is not None and self.cancel.is_set()))

    def rejection(self, status):
        """Count a free rejection; MAX_REJECTIONS in a row (429s excluded, they park as quota) stop the call."""
        with self.condition:
            if status == 429: return
            self.rejections += 1
            if self.rejections >= MAX_REJECTIONS:
                self.rejected.set(); self.condition.notify_all()

    def _held(self):
        return [self.retained[i] + sum(v[i] for v in self.active.values()) for i in range(3)]

    def amount(self, usage):
        if self.lease.route in CLAUDE_PROFILES:
            cost = claude_gate_cost(usage, self.lease.route)
            if cost is None: return None
            return cost, sum(usage[k] for k in CLAUDE_GATE_FIELDS[:3]), usage['output_tokens']
        cost = openrouter_gate_cost(self.lease.route, usage)
        if cost is None: return None
        # The input cap is max_usd / input price, so a cached token counts at its price's share of a full one,
        # as in the cost: whole cached tokens cut 412ba567 at 27.6M of a 28.7M cap (new-cached-window-1).
        incoming, cache_read, _ = map(Decimal, GATED_OPENROUTER[self.lease.route]['prices'])
        cached = openrouter_cached_tokens(usage)
        return cost, usage['prompt_tokens'] - cached + math.ceil(cached * cache_read / incoming), usage['completion_tokens']

    def reserve(self, output):
        allowance = self.amount(worst_request(self.lease.route, output))
        with self.condition:
            maximum = (Decimal(str(self.lease.max_usd)), self.lease.max_input_tokens, self.lease.max_output_tokens)
            while not self.closed and not self.is_set():
                remaining = self.deadline - time.monotonic()
                if remaining <= 0: return None
                if any(self.settled[i] + self.retained[i] + allowance[i] + (HEADROOM if i == 0 else 0) > maximum[i] for i in range(3)):
                    self.exhaustion.set()
                    self.condition.notify_all()
                    return None
                held = self._held()
                if all(self.settled[i] + held[i] + allowance[i] + (HEADROOM if i == 0 else 0) <= maximum[i] for i in range(3)):
                    self.forwarded += 1
                    self.active[self.forwarded] = allowance
                    return self.forwarded
                # Active requests may validate and release W. Contention is not
                # exhaustion; poll cancellation while finish/close notify us.
                self.condition.wait(min(.05, remaining))
            return None

    def finish(self, identity, usage):
        with self.condition:
            allowance = self.active.pop(identity, None)
            if allowance is None: return False  # close already retained it; never refund late.
            amount = self.amount(usage)
            if amount is not None and any(amount[i] > allowance[i] for i in range(3)): amount = None
            target = self.settled if amount is not None else self.retained
            for i in range(3): target[i] += (amount or allowance)[i]
            if amount is None: self.unknown += 1
            else: self.validated += 1
            self.condition.notify_all()
            return amount is not None

    def snapshot(self):
        with self.lock:
            held = self._held()
            result = empty_usage(self.lease.route)
            result.update(forwarded_requests=self.forwarded, validated_requests=self.validated,
                unknown_requests=self.unknown, in_flight_requests=len(self.active),
                unsupported_requests=self.unsupported, settled_usd=format(self.settled[0], 'f'),
                held_usd=format(held[0], 'f'), settled_input_tokens=self.settled[1], held_input_tokens=held[1],
                settled_output_tokens=self.settled[2], held_output_tokens=held[2],
                exhausted=self.exhaustion.is_set(), closed=self.closed)
            return result

    def close(self):
        with self.condition:
            self.closed = True
            for amount in self.active.values():
                for i in range(3): self.retained[i] += amount[i]
                self.unknown += 1
            self.active.clear()
            self.condition.notify_all()
            connections = list(self.connections.items())
        for connection, connected_socket in connections:
            try:
                if connected_socket: connected_socket.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            connection.close()


class Usage:
    """Read trusted response controls only; settle after HTTP EOF, never on partial SSE."""
    def __init__(self, output, streaming, route=GATED_CLAUDE):
        self.profile = claude_profile(route)
        self.output, self.streaming = output, streaming
        self.buffer, self.body = b'', bytearray()
        self.counts, self.seen = {}, set()
        self.geo = None
        self.started = self.stopped = 0
        self.terminal = False
        self.invalid = False

    def merge(self, usage):
        if not claude_standard_usage(usage): self.invalid = True; return
        if 'inference_geo' in usage:
            if self.geo is not None and self.geo != usage['inference_geo']: self.invalid = True
            self.geo = usage['inference_geo']
        for key in CLAUDE_GATE_FIELDS:
            if key not in usage: continue
            value = usage[key]
            maximum = self.output if key == 'output_tokens' else self.profile['context']
            if type(value) is not int or not 0 <= value <= maximum or value < self.counts.get(key, 0):
                self.invalid = True
            else: self.counts[key] = value
        tools = usage.get('server_tool_use', {})
        if not isinstance(tools, dict) or any(type(v) is not int or v != 0 for v in tools.values()): self.invalid = True

    def event(self, event):
        if not isinstance(event, dict) or self.stopped: self.invalid = True; return
        kind = event.get('type')
        if kind == 'error' or (self.terminal and kind != 'message_stop'):
            self.invalid = True; return
        if self.started != 1 and kind not in ('message_start', 'ping'):
            self.invalid = True; return
        if kind not in ('message_start', 'message_delta', 'message_stop'): return
        fingerprint = json.dumps(event, sort_keys=True)
        if fingerprint in self.seen: self.invalid = True; return
        self.seen.add(fingerprint)
        if kind == 'message_start':
            self.started += 1
            message = event.get('message', {})
            if self.started != 1 or message.get('model') != self.profile['model'].partition('/')[2]: self.invalid = True
            self.merge(message.get('usage'))
        elif kind == 'message_delta':
            if self.started != 1: self.invalid = True
            if 'usage' in event: self.merge(event['usage'])
            delta = event.get('delta')
            if not isinstance(delta, dict): self.invalid = True; return
            if delta.get('stop_reason') is not None:
                usage = event.get('usage')
                if (delta['stop_reason'] not in STOP_REASONS or not isinstance(usage, dict)
                        or 'output_tokens' not in usage): self.invalid = True
                else: self.terminal = True
        else:
            self.stopped += 1
            if self.started != 1 or not self.terminal: self.invalid = True

    def feed(self, chunk):
        if self.invalid: return
        if not self.streaming:
            self.body.extend(chunk)
            if len(self.body) > 4 * 1024 * 1024: self.invalid = True; self.body.clear()
            return
        self.buffer += chunk
        if len(self.buffer) > 4 * 1024 * 1024: self.invalid = True; self.buffer = b''; return
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if line.startswith(b'data:'):
                try: self.event(_json(line[5:].strip()))
                except (ValueError, TypeError, RecursionError): self.invalid = True

    def final(self):
        if not self.streaming and not self.invalid:
            try:
                body = _json(self.body)
                if (body.get('type') != 'message' or body.get('model') != self.profile['model'].partition('/')[2]
                        or body.get('stop_reason') not in STOP_REASONS): self.invalid = True
                self.merge(body.get('usage'))
                self.started = self.stopped = 1
                self.terminal = True
            except (ValueError, TypeError, AttributeError, RecursionError): self.invalid = True
        if (self.invalid or self.started != 1 or self.stopped != 1 or not self.terminal or self.buffer.strip()
                or set(self.counts) != set(CLAUDE_GATE_FIELDS)
                or sum(self.counts.get(k, 0) for k in CLAUDE_GATE_FIELDS[:3]) > self.profile['context']):
            return None
        return self.counts | ({'inference_geo': self.geo} if self.geo is not None else {})

    def rejected(self):
        """Whether a 4xx answer is Anthropic's own JSON error and nothing else: no model output or
        usage arrived. Only then was nothing billed; any other 4xx body keeps its hold."""
        if self.streaming or self.invalid or self.started or self.counts: return False
        try: body = _json(self.body)
        except (ValueError, TypeError, RecursionError): return False
        return (isinstance(body, dict) and body.get('type') == 'error' and isinstance(body.get('error'), dict)
                and 'usage' not in body and 'content' not in body)


OPENROUTER_FIELDS = {'model', 'messages', 'tools', 'tool_choice', 'stream', 'stream_options',
    'usage', 'max_tokens', 'max_completion_tokens', 'temperature', 'top_p', 'top_k', 'stop',
    'frequency_penalty', 'presence_penalty', 'repetition_penalty', 'seed', 'min_p',
    'reasoning', 'include_reasoning', 'reasoning_effort', 'response_format'}
REASONING_EFFORTS = {'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'}


def openrouter_body(raw, route, bound_reasoning=False):
    body = _json(raw)
    if not isinstance(body, dict) or set(body) - OPENROUTER_FIELDS or body.get('model') != route.partition('/')[2]:
        raise ValueError('unsupported request')
    profile = GATED_OPENROUTER[route]
    maxima = [body[k] for k in ('max_tokens', 'max_completion_tokens') if k in body]
    if any(type(v) is not int or v < 1 for v in maxima): raise ValueError('invalid output bound')
    body['max_tokens'] = min(OPENROUTER_OUTPUT, *maxima) if maxima else OPENROUTER_OUTPUT
    body.pop('max_completion_tokens', None)
    for key in ('stream', 'include_reasoning'):
        if key in body and type(body[key]) is not bool: raise ValueError('invalid flag')
    for key, allowed in (('stream_options', {'include_usage'}), ('usage', {'include'})):
        if key in body and (not isinstance(body[key], dict) or set(body[key]) - allowed
                or any(type(v) is not bool for v in body[key].values())): raise ValueError('invalid usage control')
    body['usage'] = {'include': True}
    if body.get('stream'): body['stream_options'] = {'include_usage': True}
    else: body.pop('stream_options', None)
    reasoning = body.get('reasoning', {})
    if not isinstance(reasoning, dict) or set(reasoning) - {'enabled', 'exclude', 'effort', 'max_tokens'}:
        raise ValueError('unsupported reasoning')
    for key in ('enabled', 'exclude'):
        if key in reasoning and type(reasoning[key]) is not bool: raise ValueError('invalid reasoning flag')
    if 'effort' in reasoning and reasoning['effort'] not in REASONING_EFFORTS: raise ValueError('invalid effort')
    if 'reasoning_effort' in body and body['reasoning_effort'] not in REASONING_EFFORTS: raise ValueError('invalid effort')
    # Reasoning shares max_tokens with the answer, so a quarter is left for the answer: f46dac-5's
    # diagnosis (14 November) reasoned 31,999 of 32,000 tokens and never wrote its result. A caller's
    # bound is lowered to that. Only a diagnosis gets one added (bound_reasoning): sending max_tokens
    # turns reasoning on, and nothing records which models reason by default. An effort or disabled
    # reasoning is the caller's choice (OpenRouter takes effort or max_tokens, not both).
    room = max(1, body['max_tokens'] * 3 // 4)
    if 'max_tokens' in reasoning:
        if type(reasoning['max_tokens']) is not int or reasoning['max_tokens'] < 1: raise ValueError('invalid reasoning bound')
        reasoning['max_tokens'] = min(reasoning['max_tokens'], room)
    elif bound_reasoning and not ('effort' in reasoning or 'reasoning_effort' in body or reasoning.get('enabled') is False):
        body['reasoning'] = reasoning | {'max_tokens': room}
    for key in ('temperature', 'top_p', 'frequency_penalty', 'presence_penalty', 'repetition_penalty', 'min_p'):
        if key in body and (type(body[key]) not in (int, float) or not math.isfinite(body[key])):
            raise ValueError('invalid sampling')
    for key in ('top_k', 'seed'):
        if key in body and type(body[key]) is not int: raise ValueError('invalid sampling')
    if 'stop' in body and (not isinstance(body['stop'], (str, list))
            or isinstance(body['stop'], list) and any(not isinstance(v, str) for v in body['stop'])):
        raise ValueError('invalid stop')
    messages = body.get('messages')
    if not isinstance(messages, list) or not messages: raise ValueError('invalid messages')
    for message in messages:
        if (not isinstance(message, dict) or set(message) - {'role', 'content', 'name', 'tool_calls', 'tool_call_id', 'reasoning', 'reasoning_details'}
                or message.get('role') not in ('system', 'developer', 'user', 'assistant', 'tool')):
            raise ValueError('unsupported message')
        content = message.get('content')
        if isinstance(content, list):
            if any(not isinstance(v, dict) or set(v) != {'type', 'text'} or v['type'] != 'text'
                   or not isinstance(v['text'], str) for v in content): raise ValueError('text only')
        elif not isinstance(content, str) and not (content is None and message['role'] == 'assistant'):
            raise ValueError('text only')
        for key in ('name', 'tool_call_id', 'reasoning'):
            if key in message and not isinstance(message[key], str): raise ValueError('invalid message text')
        details = message.get('reasoning_details', [])
        if not isinstance(details, list): raise ValueError('invalid reasoning details')
        for detail in details:
            if (not isinstance(detail, dict) or set(detail) - {'type', 'text', 'summary', 'data', 'signature', 'id', 'format', 'index'}
                    or detail.get('type') not in ('reasoning.text', 'reasoning.summary', 'reasoning.encrypted')
                    or any(not isinstance(v, str) and not (k in ('id', 'signature') and v is None) for k,v in detail.items() if k != 'index')
                    or 'index' in detail and type(detail['index']) is not int): raise ValueError('invalid reasoning detail')
        calls = message.get('tool_calls', [])
        if not isinstance(calls, list): raise ValueError('invalid tool calls')
        for call in calls:
            if not isinstance(call, dict) or set(call) != {'id', 'type', 'function'} or call['type'] != 'function' or not isinstance(call['id'], str):
                raise ValueError('unsupported tool call')
            function = call['function']
            if not isinstance(function, dict) or set(function) != {'name', 'arguments'} or any(not isinstance(v, str) for v in function.values()):
                raise ValueError('unsupported tool call')
    tools = body.get('tools', [])
    if not isinstance(tools, list): raise ValueError('invalid tools')
    for tool in tools:
        if not isinstance(tool, dict) or set(tool) != {'type', 'function'} or tool['type'] != 'function':
            raise ValueError('local function tools only')
        function = tool['function']
        if (not isinstance(function, dict) or set(function) - {'name', 'description', 'parameters', 'strict'}
                or not isinstance(function.get('name'), str) or not isinstance(function.get('parameters'), dict)
                or 'description' in function and not isinstance(function['description'], str)
                or 'strict' in function and type(function['strict']) is not bool): raise ValueError('unsupported function')
    choice = body.get('tool_choice', 'auto')
    if isinstance(choice, dict):
        if (set(choice) != {'type', 'function'} or choice['type'] != 'function'
                or not isinstance(choice['function'], dict) or set(choice['function']) != {'name'}
                or not isinstance(choice['function']['name'], str)): raise ValueError('unsupported tool choice')
    elif choice not in ('auto', 'none', 'required'): raise ValueError('unsupported tool choice')
    format_ = body.get('response_format', {'type': 'text'})
    if (not isinstance(format_, dict) or format_.get('type') not in ('text', 'json_object', 'json_schema')
            or set(format_) - {'type', 'json_schema'}): raise ValueError('unsupported format')
    if format_['type'] == 'json_schema':
        schema = format_.get('json_schema')
        if (not isinstance(schema, dict) or set(schema) - {'name', 'description', 'schema', 'strict'}
                or not isinstance(schema.get('schema'), dict)): raise ValueError('unsupported schema')
    incoming, _, outgoing = map(float, profile['prices'])
    # Cheaper endpoints first (founder 2026-11-10), then the pin; max_price stays the pin's tariff, so
    # the per-call bound and the booked amount never rise, and OpenRouter refuses any dearer endpoint.
    endpoints = [*profile.get('cheaper', ()), profile['endpoint']]
    body['provider'] = dict(order=endpoints, only=endpoints, allow_fallbacks=False, require_parameters=True,
                           max_price=dict(prompt=incoming, completion=outgoing, request=0, image=0))
    return body


class OpenRouterUsage:
    """Refund only one complete generation with authoritative terminal usage."""
    def __init__(self, route, streaming):
        self.route, self.streaming = route, streaming
        self.buffer, self.body = b'', bytearray()
        self.invalid = False
        self.identity, self.usage = None, None
        self.terminal = self.done = 0
        self.finish_reason = self.native_finish_reason = None

    def event(self, event):
        if self.identity is None and isinstance(event, dict) and isinstance(event.get('id'), str) and event['id']:
            self.identity = event['id']   # an error frame still names the generation the router looks up
        if self.done or not isinstance(event, dict) or 'error' in event: self.invalid = True; return
        identity = event.get('id')
        if not isinstance(identity, str) or not identity or self.identity is not None and identity != self.identity:
            self.invalid = True; return
        self.identity = identity
        if event.get('model') != self.route.partition('/')[2]: self.invalid = True; return
        choices = event.get('choices')
        if not isinstance(choices, list) or len(choices) > 1: self.invalid = True; return
        if choices:
            choice = choices[0]
            if not isinstance(choice, dict) or type(choice.get('index')) is not int or choice['index'] != 0:
                self.invalid = True; return
            finish = choice.get('finish_reason')
            native = choice.get('native_finish_reason')
            if self.terminal:
                # OpenRouter repeats the terminal choice in its final usage frame.
                # Accept accounting only: no new content, generation or usage report.
                delta = choice.get('delta')
                if (not self.streaming or event.get('usage') is None or self.usage is not None
                        or finish != self.finish_reason or native != self.native_finish_reason
                        or set(choice) - {'index', 'delta', 'finish_reason', 'native_finish_reason', 'logprobs'}
                        or choice.get('logprobs') is not None or not isinstance(delta, dict)
                        or set(delta) - {'role', 'content'} or delta.get('content') not in (None, '')
                        or delta.get('role') not in (None, 'assistant')):
                    self.invalid = True; return
            elif finish is not None:
                if finish not in ('stop', 'length', 'tool_calls', 'content_filter'): self.invalid = True; return
                self.finish_reason, self.native_finish_reason = finish, native
                self.terminal += 1
        if event.get('usage') is not None:
            if self.usage is not None or self.terminal != 1: self.invalid = True; return
            usage = event['usage'];profile = GATED_OPENROUTER[self.route]
            cost = openrouter_gate_cost(self.route, usage)
            if (cost is None or usage['prompt_tokens'] > profile['context'] or usage['completion_tokens'] > profile['output']
                    or type(usage.get('total_tokens')) is not int
                    or usage['total_tokens'] != usage['prompt_tokens'] + usage['completion_tokens']):
                self.invalid = True; return
            # openrouter_gate_cost has checked prompt_tokens_details.cached_tokens (openrouter_cached_tokens).
            for field, key, maximum in (('completion_tokens_details', 'reasoning_tokens', usage['completion_tokens']),):
                if field in usage:
                    details = usage[field]
                    if not isinstance(details, dict): self.invalid = True; return
                    if key in details and (type(details[key]) is not int or not 0 <= details[key] <= maximum):
                        self.invalid = True; return
            self.usage = usage

    def feed(self, chunk):
        if self.invalid: return
        if not self.streaming:
            self.body.extend(chunk)
            if len(self.body) > 4*1024*1024: self.invalid = True; self.body.clear()
            return
        self.buffer += chunk
        if len(self.buffer) > 4*1024*1024: self.invalid = True; self.buffer = b''; return
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if not line.startswith(b'data:'): continue
            data = line[5:].strip()
            if data == b'[DONE]':
                if self.done or self.terminal != 1 or self.usage is None: self.invalid = True
                self.done += 1
            else:
                try: self.event(_json(data))
                except (ValueError, TypeError, RecursionError): self.invalid = True

    def final(self):
        if not self.streaming and not self.invalid:
            try: self.event(_json(self.body)); self.done = 1
            except (ValueError, TypeError, AttributeError, RecursionError): self.invalid = True
        if self.invalid or self.done != 1 or self.terminal != 1 or self.buffer.strip(): return None
        return self.usage


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def handle_error(self, *args): pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args): pass

    def error(self, status, kind, message):
        data = json.dumps({'type': 'error', 'error': {'type': kind, 'message': message}}).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data))); self.send_header('Connection', 'close'); self.end_headers()
        self.wfile.write(data); self.close_connection = True

    def do_POST(self):
        gate = self.server.gate
        paid = gate.route in GATED_OPENROUTER
        self.connection.settimeout(min(15, gate.remaining()))
        auth = self.headers.get_all('Authorization', [])
        if len(auth) != 1 or not hmac.compare_digest(auth[0].encode(), ('Bearer ' + gate.token).encode()):
            self.error(401, 'authentication_error', 'gate_authentication_required'); return
        try:
            if (self.path not in (('/api/v1/chat/completions',) if paid else ('/v1/messages', '/v1/messages?beta=true')) or self.headers.get('Transfer-Encoding')
                    or self.headers.get('Content-Encoding', 'identity') != 'identity'
                    or len(self.headers.get_all('Content-Length', [])) != 1): raise ValueError()
            size = int(self.headers['Content-Length'])
            if not 0 < size <= 16 * 1024 * 1024: raise ValueError()
            raw = self.rfile.read(size)
            if len(raw) != size: raise ValueError()
            body = openrouter_body(raw, gate.route, gate.bound_reasoning) if paid else request_body(raw, gate.route)
        except (ValueError, TypeError, RecursionError):
            with gate.state.lock:
                if not gate.state.closed: gate.state.unsupported += 1
            self.error(400, 'invalid_request_error', 'route_feature_unsupported'); return
        if paid and gate.state.paid_failure:
            self.error(503, 'api_error', 'shared_paid_spend_wait'); return
        identity = gate.state.reserve(body['max_tokens'])
        if identity is None:
            self.error(400, 'invalid_request_error',
                'model_call_cap' if gate.state.exhaustion.is_set() else 'invocation_stopped'); return
        paid_id = None
        if paid:
            import model_router
            paid_id = secrets.token_hex(16)
            definite = False
            try:
                result = model_router._rpc('paid_reserve', dict(lease_id=gate.state.lease.lease_id, request_id=paid_id))
                if result == {'granted': True}: reason = None
                elif (set(result) == {'granted', 'reason'} and result['granted'] is False
                        and result['reason'] in ('credit', 'duplicate', 'binding')):
                    definite = True
                    reason = 'credit' if result['reason'] == 'credit' else 'router_unavailable'
                else: reason = 'router_unavailable'
            except model_router.RouterUnavailable: reason = 'router_unavailable'
            if reason:
                with gate.state.condition:
                    gate.state.paid_failure = reason
                    gate.state.condition.notify_all()
                # A definite refusal proves this attempt never reached upstream.
                # It is a validated zero-cost admission, not provider usage.
                gate.state.finish(identity, dict(prompt_tokens=0, completion_tokens=0) if definite else None)
                self.error(503, 'api_error', 'shared_paid_spend_wait'); return
        encoded = json.dumps(body, allow_nan=False).encode()
        headers = {'Authorization': 'Bearer ' + gate.upstream_token, 'Content-Type': 'application/json', 'Accept-Encoding': 'identity'}
        if not paid: headers.update({'anthropic-version': '2023-06-01', 'anthropic-beta': BETAS})
        for key in ('User-Agent', 'x-app'):
            if self.headers.get(key): headers[key] = self.headers[key]
        connection = http.client.HTTPSConnection('openrouter.ai' if paid else 'api.anthropic.com', timeout=gate.remaining())
        usage, sent, parser, rejected_status = None, False, None, None
        try:
            with gate.state.lock:
                if gate.state.closed: return
                gate.state.connections[connection] = None
            # Explicit one-time connect: close must not let request() silently
            # reconnect after the immutable receipt snapshot. No lock spans I/O.
            connection.connect()
            connection.auto_open = 0
            with gate.state.lock:
                if gate.state.closed: return
                # getresponse() detaches connection.sock for Connection: close.
                # Keep its socket until the response reader finishes so close()
                # can interrupt that reader as well as persistent connections.
                gate.state.connections[connection] = connection.sock
            connection.request('POST', self.path, encoded, headers)
            response = connection.getresponse()
            streaming = 'text/event-stream' in response.getheader('Content-Type', '')
            parser = OpenRouterUsage(gate.route, streaming) if paid else Usage(body['max_tokens'], streaming, gate.route)
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in HOP_HEADERS and not key.lower().startswith('proxy-'): self.send_header(key, value)
            self.send_header('Connection', 'close'); self.end_headers(); sent = True
            while chunk := response.read1(65536):
                parser.feed(chunk)
                self.wfile.write(chunk); self.wfile.flush()
            identity_encoded = response.getheader('Content-Encoding', 'identity') == 'identity'
            if response.status == 200 and identity_encoded: usage = parser.final()
            elif not paid and 400 <= response.status < 500 and identity_encoded and parser.rejected():
                # Anthropic rejected it (a 429 rate or usage limit, a bad request) with its JSON error and
                # no model output: nothing is billed. Holding its worst case ($9.52 on Opus 5.5) booked
                # phantom spend on every quota stop and exhausted a $12.50 window at the first 429.
                # Any other 4xx body, and every 5xx, stays unknown.
                usage = dict.fromkeys(CLAUDE_GATE_FIELDS, 0)
                rejected_status = response.status
        except (OSError, ValueError, http.client.HTTPException):
            if not sent:
                try: self.error(502, 'api_error', 'upstream_unavailable')
                except OSError: pass
        finally:
            self.close_connection = True
            connection.close()
            with gate.state.lock: gate.state.connections.pop(connection, None)
            known = gate.state.finish(identity, usage)
            if rejected_status is not None and known: gate.state.rejection(rejected_status)
            elif known:
                with gate.state.lock: gate.state.rejections = 0
            if paid_id is not None:
                # Complete before downstream EOF; late completion after close
                # cannot refund centrally. Failed RPC leaves the entire hold.
                # An unconfirmed call names its generation, so the router can ask the provider
                # what it really charged instead of booking the whole hold for good.
                generation = getattr(parser, 'identity', None) if not known and paid else None
                if not isinstance(generation, str) or not model_router.GENERATION.fullmatch(generation): generation = None
                try:
                    model_router._rpc('paid_settle', dict(lease_id=gate.state.lease.lease_id,
                        request_id=paid_id, usage=usage if known else None, generation=generation))
                except model_router.RouterUnavailable: pass

    def do_GET(self): self.error(400, 'invalid_request_error', 'route_feature_unsupported')


class Gate:
    bound_reasoning = False   # set for a diagnosis call (model_runtime) before its model starts

    def __init__(self, lease, token, timeout, cancel=None):
        self.route, self.upstream_token = lease.route, token
        self.token = secrets.token_urlsafe(32) if lease.route in GATED_OPENROUTER else token
        self.timeout = max(.01, timeout)
        self.deadline = time.monotonic() + self.timeout
        self.state = Allowance(lease, cancel, self.deadline)
        self.server = Server(('127.0.0.1', 0), Handler); self.server.gate = self
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.05), daemon=True)
        self.thread.start()

    def is_set(self): return self.state.is_set()

    def remaining(self): return max(.01, self.deadline-time.monotonic())

    def close(self, release_socket=True):
        self.state.close(); self.server.shutdown()
        if release_socket: self.server.server_close()
        else: _RETAINED.append(self.server)
        self.thread.join(timeout=1)


@contextmanager
def _wall_access(gate, lease, user):
    attempted = confirmed = False
    revoked = True
    try:
        if user is not None:
            try: uid = pwd.getpwnam(user).pw_uid
            except KeyError: raise BudgetError('model_wall_failed') from None   # no such isolated user
            chain = 'factory-' + user
            rule = ['-m', 'owner', '--uid-owner', str(uid), '-o', 'lo', '-d', '127.0.0.1/32',
                    '-p', 'tcp', '--dport', str(gate.server.server_port),
                    '-m', 'comment', '--comment', 'factory-gate:' + lease.lease_id, '-j', 'ACCEPT']
            attempted = True; revoked = False
            subprocess.run(['sudo', 'iptables', '-w', '5', '-I', chain, '1', *rule],
                           check=True, capture_output=True, timeout=30)
            confirmed = True
        yield
    finally:
        if attempted:
            try:
                subprocess.run(['sudo', 'iptables', '-w', '5', '-D', chain, *rule],
                               check=True, capture_output=True, timeout=30)
                revoked = True
            except BaseException:
                revoked = False
        # Even successful deletion cannot exclude late insertion after a timeout.
        release = not attempted or (confirmed and revoked)
        gate.close(release_socket=release)
        if not release: raise BudgetError('cancellation_failed') from None


def openrouter_environment(lease, env, gate):
    profile = GATED_OPENROUTER[lease.route]
    model = lease.route.partition('/')[2]
    cfg = dict(model=lease.route, small_model=lease.route, enabled_providers=['openrouter'],
        permission={'task': 'deny'}, compaction={'auto': True}, provider={'openrouter': {
            'npm': '@openrouter/ai-sdk-provider', 'whitelist': [model],
            'options': {'baseURL': 'http://127.0.0.1:' + str(gate.server.server_port) + '/api/v1', 'apiKey': gate.token},
            'models': {model: {'id': model, 'name': model, 'limit': {'context': profile['context'], 'output': OPENROUTER_OUTPUT},
                'cost': runtime_prices(lease.route), 'modalities': {'input': ['text'], 'output': ['text']}}}}})
    keys = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
            'FACTORY_STRATEGY_DIAGNOSTIC', 'FACTORY_STRATEGY_SECONDS', 'FACTORY_STRATEGY_WORKERS')
    clean = {k: env[k] for k in keys if k in env}
    clean.update(OPENCODE_CONFIG_CONTENT=json.dumps(cfg), OPENCODE_ENABLE_EXA='1', OPENCODE_PURE='1',
        OPENCODE_DISABLE_PROJECT_CONFIG='1', OPENCODE_DISABLE_MODELS_FETCH='1', OPENCODE_DISABLE_AUTOUPDATE='1')
    return clean


class FreeCall:
    """A free or Codex route's stand-in for Gate: no proxy, no money to hold. It only carries cancellation."""
    def __init__(self, cancel): self.cancel = cancel
    def is_set(self): return self.cancel is not None and self.cancel.is_set()


# A Codex call gets its scratch CODEX_HOME (config.toml without MCP servers, the worker's auth.json) and nothing else.
CODEX_ENV_KEYS = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'CODEX_HOME', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
                  'HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy', 'NO_PROXY', 'no_proxy',
                  'FACTORY_STRATEGY_DIAGNOSTIC', 'FACTORY_STRATEGY_SECONDS', 'FACTORY_STRATEGY_WORKERS')


def free_environment(lease, env):
    """The route's own OpenCode provider only (opencode, or opencode-go for a Go plan route), its one
    model, no user or project config, no self-update. The provider entry (endpoint, key reference,
    prices) comes from the runtime's config for this route."""
    name = lease.route.partition('/')[0]
    try: provider = json.loads(Path(env['OPENCODE_CONFIG']).read_text())['provider'][name]
    except (KeyError, OSError, ValueError, TypeError): raise BudgetError('route_feature_unsupported') from None
    model = lease.route.partition('/')[2]
    cfg = dict(model=lease.route, small_model=lease.route, enabled_providers=[name],
               permission={'task': 'deny'}, compaction={'auto': True}, mcp={},
               provider={name: {**provider, 'whitelist': [model]}})
    keys = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
            'FACTORY_STRATEGY_DIAGNOSTIC', 'FACTORY_STRATEGY_SECONDS', 'FACTORY_STRATEGY_WORKERS')
    clean = {k: env[k] for k in keys if k in env}
    # Only a route that runs on an OpenCode account gets that account's key.
    if lease.account and env.get('OPENCODE_API_KEY'): clean['OPENCODE_API_KEY'] = env['OPENCODE_API_KEY']
    clean.update(OPENCODE_CONFIG_CONTENT=json.dumps(cfg), OPENCODE_ENABLE_EXA='1', OPENCODE_PURE='1',
        OPENCODE_DISABLE_PROJECT_CONFIG='1', OPENCODE_DISABLE_AUTOUPDATE='1')
    return clean


@contextmanager
def enforce(lease, env, cap_used, timeout, cancel=None, *, user=None):
    import model_router
    from token_prices import FREE_ROUTES, GO_ROUTES
    if lease.route in FREE_ROUTES:
        # $0 maximum: any booked cost stops the call (budget.check_reservation), and so does a step
        # from any other provider or model (budget.py). A walled role can reach only a gate's port, so
        # the runtime never leases it a free route; refusing here is the backstop.
        if not model_router.valid_maximum(lease) or lease.max_usd != 0: raise BudgetError('unbounded_route')
        if user is not None: raise BudgetError('route_feature_unsupported')
        # No system or user OpenCode config may reach the call: its scratch XDG dirs replace them.
        if Path('/etc/opencode').exists() or any(not env.get(k) for k in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME')):
            raise BudgetError('route_feature_unsupported')
        clean = free_environment(lease, env)
        env.clear(); env.update(clean)
        yield FreeCall(cancel)
        return
    if lease.route in GO_ROUTES:
        # The founder's Go plan pays (Extra Usage off), so no gate: OpenCode books each step at the
        # OpenRouter twin's list price (model_runtime.opencode_config) and the reservation check stops
        # the call once it passes the lease maximum, as for Codex. A walled role reaches only a gate's
        # port, so the runtime never leases it a Go route; refusing here is the backstop.
        if not model_router.valid_maximum(lease) or lease.max_usd <= 0: raise BudgetError('unbounded_route')
        if user is not None: raise BudgetError('route_feature_unsupported')
        if Path('/etc/opencode').exists() or any(not env.get(k) for k in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME')):
            raise BudgetError('route_feature_unsupported')
        if not lease.account or not env.get('OPENCODE_API_KEY'): raise BudgetError('credential_expiring')
        clean = free_environment(lease, env)
        env.clear(); env.update(clean)
        try: yield FreeCall(cancel)
        except BudgetError as error:
            if str(error) == 'usage_reservation_exceeded': raise BudgetError('model_call_cap') from error
            raise
        return
    if lease.route in CODEX_PROFILES:
        # No gate: Codex's own per-request usage is booked live at list price (budget.py usage_feed) and
        # the reservation check stops the call once it passes the lease maximum. That stop is this
        # call's cap, as the gate's exhaustion is Claude's. Codex's tools stay off (model_runtime CODEX_OFF).
        if not model_router.valid_maximum(lease) or lease.max_usd <= 0: raise BudgetError('unbounded_route')
        if not env.get('CODEX_HOME'): raise BudgetError('route_feature_unsupported')
        clean = {k: env[k] for k in CODEX_ENV_KEYS if k in env}
        env.clear(); env.update(clean)
        try: yield FreeCall(cancel)
        except BudgetError as error:
            if str(error) == 'usage_reservation_exceeded': raise BudgetError('model_call_cap') from error
            raise
        return
    if (lease.route not in CLAUDE_PROFILES and lease.route not in GATED_OPENROUTER) or not model_router.valid_maximum(lease):
        raise BudgetError('unbounded_route')
    paid = lease.route in GATED_OPENROUTER
    if paid and (sys.platform != 'linux' or Path('/etc/opencode').exists()
            or any(not env.get(k) for k in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'))):
        raise BudgetError('route_feature_unsupported')
    token = env.get('OPENROUTER_API_KEY' if paid else 'CLAUDE_CODE_OAUTH_TOKEN', '')
    if not token: raise BudgetError('credential_expiring')
    gate = Gate(lease, token, timeout, cancel)
    if paid: clean = openrouter_environment(lease, env, gate)
    else:
        profile = claude_profile(lease.route)
        clean = {k: env[k] for k in ENV_KEYS if k in env and k != 'MAX_THINKING_TOKENS'}
        if profile['thinking'] is not None: clean['MAX_THINKING_TOKENS'] = str(profile['thinking'])
        clean.update(ANTHROPIC_BASE_URL='http://127.0.0.1:' + str(gate.server.server_port),
            ANTHROPIC_SMALL_FAST_MODEL=profile['model'].partition('/')[2],
            CLAUDE_CODE_MAX_OUTPUT_TOKENS=str(profile['output']), CLAUDE_CODE_MAX_RETRIES='0',
            CLAUDE_CODE_GZIP_REQUEST_BODIES='0', CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS='1',
            CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1', DISABLE_AUTOUPDATER='1')
    env.clear(); env.update(clean)
    failure = None
    try:
        with _wall_access(gate, lease, user): yield gate
    except BudgetError as error:
        failure = error
        raise
    finally:
        cap_used.clear(); cap_used.update(gate.state.snapshot())
        if gate.state.paid_failure and str(failure) != 'cancellation_failed':
            error = BudgetError('shared_paid_spend_wait')
            error.provider_failure = dict(reason=gate.state.paid_failure, model=lease.route, shared_paid=True)
            raise error from None
        if gate.state.exhaustion.is_set() and str(failure) != 'cancellation_failed':
            raise BudgetError('model_call_cap') from None
        if gate.state.rejected.is_set() and str(failure) != 'cancellation_failed':
            raise BudgetError('upstream_rejected') from None
