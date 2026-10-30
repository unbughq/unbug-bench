"""Worker-local admission for Claude-owned inference; no ledger bookings or payload logs.

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
import socket
import subprocess
import threading
import time

from budget import BudgetError
from token_prices import (GATED_CLAUDE, CLAUDE_CONTEXT, CLAUDE_OUTPUT,
                          CLAUDE_GATE_FIELDS, CLAUDE_PRICES, claude_gate_cost, claude_standard_usage)

ENV_KEYS = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'CLAUDE_CODE_OAUTH_TOKEN',
    'CLAUDE_CONFIG_DIR', 'DISABLE_AUTOUPDATER', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC',
    'CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS', 'CLAUDE_CODE_MAX_OUTPUT_TOKENS',
    'CLAUDE_CODE_MAX_RETRIES', 'CLAUDE_CODE_GZIP_REQUEST_BODIES', 'ANTHROPIC_BASE_URL',
    'ANTHROPIC_SMALL_FAST_MODEL', 'FACTORY_STRATEGY_DIAGNOSTIC',
    'FACTORY_STRATEGY_SECONDS', 'FACTORY_STRATEGY_WORKERS')
BETAS = 'claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14,effort-2025-11-24'
HEADROOM = Decimal('0.000001')
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


def request_body(raw):
    body = _json(raw)
    if not isinstance(body, dict) or set(body) - BODY_FIELDS or body.get('model') != GATED_CLAUDE.partition('/')[2]:
        raise ValueError('unsupported request')
    output = body.get('max_tokens')
    if type(output) is not int or not 0 <= output: raise ValueError('invalid output bound')
    body['max_tokens'] = min(output, CLAUDE_OUTPUT)
    body['inference_geo'] = 'global'  # Override workspace defaults; forbidden geo must error.
    body.pop('context_management', None)  # No server-side sampling/compaction.
    if 'thinking' in body:
        if not isinstance(body['thinking'], dict) or body['thinking'].get('type') != 'adaptive':
            raise ValueError('unsupported thinking')
        body['thinking'] = {'type': 'adaptive'}
    if body.get('service_tier', 'standard_only') not in ('auto', 'standard_only'):
        raise ValueError('unsupported tier')
    body['service_tier'] = 'standard_only'
    if 'stream' in body and type(body['stream']) is not bool: raise ValueError('invalid stream')
    if 'cache_control' in body: _cache(body['cache_control'])
    config = body.get('output_config', {})
    if (not isinstance(config, dict) or set(config) - {'effort', 'format'}
            or config.get('effort', 'high') not in ('low', 'medium', 'high', 'xhigh', 'max')):
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


def empty_usage():
    return dict(version=1, forwarded_requests=0, validated_requests=0, unknown_requests=0,
        in_flight_requests=0, unsupported_requests=0, settled_usd='0', held_usd='0',
        settled_input_tokens=0, held_input_tokens=0, settled_output_tokens=0,
        held_output_tokens=0, max_request_output_tokens=CLAUDE_OUTPUT, exhausted=False, closed=True)


class Allowance:
    def __init__(self, lease, cancel=None, deadline=math.inf):
        self.lease, self.cancel = lease, cancel
        self.lock, self.exhaustion = threading.Lock(), threading.Event()
        self.condition = threading.Condition(self.lock)
        self.deadline = deadline
        self.closed = False
        self.active, self.connections = {}, set()
        self.forwarded = self.validated = self.unknown = self.unsupported = 0
        self.settled = [Decimal(0), 0, 0]
        self.retained = [Decimal(0), 0, 0]

    def is_set(self):
        return self.exhaustion.is_set() or (self.cancel is not None and self.cancel.is_set())

    def _held(self):
        return [self.retained[i] + sum(v[i] for v in self.active.values()) for i in range(3)]

    def reserve(self, output):
        worst = dict.fromkeys(CLAUDE_GATE_FIELDS, 0)
        incoming = max(range(3), key=lambda i: CLAUDE_PRICES[GATED_CLAUDE][i])
        worst[CLAUDE_GATE_FIELDS[incoming]], worst['output_tokens'] = CLAUDE_CONTEXT, output
        allowance = (claude_gate_cost(worst), CLAUDE_CONTEXT, output)
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
            if allowance is None: return  # close already retained it; never refund late.
            amount = None
            if usage is not None and (cost := claude_gate_cost(usage)) is not None:
                amount = (cost, sum(usage[k] for k in CLAUDE_GATE_FIELDS[:3]), usage['output_tokens'])
                if any(amount[i] > allowance[i] for i in range(3)): amount = None
            target = self.settled if amount is not None else self.retained
            for i in range(3): target[i] += (amount or allowance)[i]
            if amount is None: self.unknown += 1
            else: self.validated += 1
            self.condition.notify_all()

    def snapshot(self):
        with self.lock:
            held = self._held()
            result = empty_usage()
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
            connections = list(self.connections)
        for connection in connections:
            try:
                if connection.sock: connection.sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            connection.close()


class Usage:
    """Read trusted response controls only; settle after HTTP EOF, never on partial SSE."""
    def __init__(self, output, streaming):
        self.output, self.streaming = output, streaming
        self.buffer, self.body = b'', bytearray()
        self.counts, self.seen = {}, set()
        self.started = self.stopped = 0
        self.terminal = False
        self.invalid = False

    def merge(self, usage):
        if not claude_standard_usage(usage): self.invalid = True; return
        for key in CLAUDE_GATE_FIELDS:
            if key not in usage: continue
            value = usage[key]
            maximum = self.output if key == 'output_tokens' else CLAUDE_CONTEXT
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
            if self.started != 1 or message.get('model') != GATED_CLAUDE.partition('/')[2]: self.invalid = True
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
                if (body.get('type') != 'message' or body.get('model') != GATED_CLAUDE.partition('/')[2]
                        or body.get('stop_reason') not in STOP_REASONS): self.invalid = True
                self.merge(body.get('usage'))
                self.started = self.stopped = 1
                self.terminal = True
            except (ValueError, TypeError, AttributeError, RecursionError): self.invalid = True
        if (self.invalid or self.started != 1 or self.stopped != 1 or not self.terminal or self.buffer.strip()
                or set(self.counts) != set(CLAUDE_GATE_FIELDS)
                or sum(self.counts.get(k, 0) for k in CLAUDE_GATE_FIELDS[:3]) > CLAUDE_CONTEXT):
            return None
        return self.counts


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
        self.connection.settimeout(min(15, gate.remaining()))
        auth = self.headers.get_all('Authorization', [])
        if len(auth) != 1 or not hmac.compare_digest(auth[0].encode(), ('Bearer ' + gate.token).encode()):
            self.error(401, 'authentication_error', 'gate_authentication_required'); return
        try:
            if (self.path not in ('/v1/messages', '/v1/messages?beta=true') or self.headers.get('Transfer-Encoding')
                    or self.headers.get('Content-Encoding', 'identity') != 'identity'
                    or len(self.headers.get_all('Content-Length', [])) != 1): raise ValueError()
            size = int(self.headers['Content-Length'])
            if not 0 < size <= 16 * 1024 * 1024: raise ValueError()
            raw = self.rfile.read(size)
            if len(raw) != size: raise ValueError()
            body = request_body(raw)
        except (ValueError, TypeError, RecursionError):
            with gate.state.lock:
                if not gate.state.closed: gate.state.unsupported += 1
            self.error(400, 'invalid_request_error', 'route_feature_unsupported'); return
        identity = gate.state.reserve(body['max_tokens'])
        if identity is None:
            self.error(400, 'invalid_request_error',
                'model_call_cap' if gate.state.exhaustion.is_set() else 'invocation_stopped'); return
        encoded = json.dumps(body, allow_nan=False).encode()
        headers = {'Authorization': auth[0], 'Content-Type': 'application/json',
            'anthropic-version': '2023-06-01', 'anthropic-beta': BETAS, 'Accept-Encoding': 'identity'}
        for key in ('User-Agent', 'x-app'):
            if self.headers.get(key): headers[key] = self.headers[key]
        connection = http.client.HTTPSConnection('api.anthropic.com', timeout=gate.remaining())
        usage, sent = None, False
        try:
            with gate.state.lock:
                if gate.state.closed: return
                gate.state.connections.add(connection)
            # Explicit one-time connect: close must not let request() silently
            # reconnect after the immutable receipt snapshot. No lock spans I/O.
            connection.connect()
            connection.auto_open = 0
            with gate.state.lock:
                if gate.state.closed: return
            connection.request('POST', self.path, encoded, headers)
            response = connection.getresponse()
            parser = Usage(body['max_tokens'], 'text/event-stream' in response.getheader('Content-Type', ''))
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in HOP_HEADERS and not key.lower().startswith('proxy-'): self.send_header(key, value)
            self.send_header('Connection', 'close'); self.end_headers(); sent = True
            while chunk := response.read1(65536):
                parser.feed(chunk)
                self.wfile.write(chunk); self.wfile.flush()
            if response.status == 200 and response.getheader('Content-Encoding', 'identity') == 'identity': usage = parser.final()
        except (OSError, ValueError, http.client.HTTPException):
            if not sent:
                try: self.error(502, 'api_error', 'upstream_unavailable')
                except OSError: pass
        finally:
            self.close_connection = True
            connection.close()
            with gate.state.lock: gate.state.connections.discard(connection)
            gate.state.finish(identity, usage)

    def do_GET(self): self.error(400, 'invalid_request_error', 'route_feature_unsupported')


class Gate:
    def __init__(self, lease, token, timeout, cancel=None):
        self.token, self.timeout = token, max(.01, timeout)
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
            uid = pwd.getpwnam(user).pw_uid
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


@contextmanager
def enforce(lease, env, cap_used, timeout, cancel=None, *, user=None):
    import model_router
    if lease.route != GATED_CLAUDE or not model_router.valid_maximum(lease):
        raise BudgetError('unbounded_route')
    token = env.get('CLAUDE_CODE_OAUTH_TOKEN', '')
    if not token: raise BudgetError('credential_expiring')
    gate = Gate(lease, token, timeout, cancel)
    clean = {k: env[k] for k in ENV_KEYS if k in env}
    clean.update(ANTHROPIC_BASE_URL='http://127.0.0.1:' + str(gate.server.server_port),
        ANTHROPIC_SMALL_FAST_MODEL=GATED_CLAUDE.partition('/')[2],
        CLAUDE_CODE_MAX_OUTPUT_TOKENS=str(CLAUDE_OUTPUT), CLAUDE_CODE_MAX_RETRIES='0',
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
        if gate.state.exhaustion.is_set() and str(failure) != 'cancellation_failed':
            raise BudgetError('model_call_cap') from None
