"""Observe OpenCode, Codex or Claude Code JSON usage and stop the process group at cumulative ceilings.

Ceilings are checked after each response; in-flight requests can overshoot.
Only the exclusive local OpenCode process is supported (never --attach).
Schemas: anomalyco/opencode v2.0.26 packages/cli/src/run/noninteractive.ts;
codex-cli 0.162.1 `exec --json`; Claude Code 2.1.299 `-p --output-format stream-json --verbose`.
"""
from contextlib import contextmanager, nullcontext
import fcntl
import json
import math
import os
import re
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from token_prices import CODEX_PRICES, codex_cost, claude_cost


class BudgetError(RuntimeError):
    pass


# Codex items that end a model response (reasoning items accompany one of these).
CODEX_STEPS = ('agent_message', 'command_execution', 'file_change', 'mcp_tool_call', 'web_search', 'collab_tool_call')


def _save(path, ledger):
    fd, name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as file:
            json.dump(ledger, file, indent=2, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def case_spending(ledger, models_used=None):
    """Whole-case list price, including legacy events; never read transcripts.

    Totals remain authoritative for historical usage not represented by events.
    Legacy roles are attributed only when the recorded model identifies one role.
    """
    ledger = ledger or {}
    roles = {}
    for name, model in (models_used or {}).items():
        roles.setdefault(model, set()).add(invocation_role(name))
    breakdown, estimated, unpriced = {}, 0.0, len(ledger.get('unpriced_invocations', []))
    listed, priced = 0.0, 0.0
    for event in ledger.get('events', []):
        cost = event.get('cost', 0)
        listed_cost = event.get('list_cost_usd', 0)
        estimate = event.get('estimated_subscription_cost_usd', 0)
        model = event.get('configured_model')
        if event.get('priced') == 'subscription' and 'list_cost_usd' not in event and 'estimated_subscription_cost_usd' not in event:
            estimate = codex_cost(model, event.get('tokens', {})) if str(model).startswith('codex/') else None
            if estimate is None: unpriced += 1; estimate = 0
        if not all(_number(v) for v in (cost, listed_cost, estimate)):
            unpriced += 1; continue
        listed += listed_cost; priced += cost; estimated += estimate
        matches = roles.get(model, set())
        role = event.get('role') or (next(iter(matches)) if len(matches) == 1 else 'legacy_unattributed')
        breakdown[role] = breakdown.get(role, 0) + cost + listed_cost + estimate
    for key, observed in (('cost', priced), ('list_cost_usd', listed), ('estimated_subscription_cost_usd', estimated)):
        total = ledger.get(key, observed)
        if not _number(total): unpriced += 1; continue
        if total > observed: breakdown['legacy_unattributed'] = breakdown.get('legacy_unattributed', 0) + total - observed
    breakdown = {role: round(cost, 9) for role, cost in breakdown.items()}
    known = round(sum(breakdown.values()), 9)
    waste = 0.0
    records = ledger.get('infrastructure_waste', [])
    if not isinstance(records, list):
        records = []; unpriced += 1
    for record in records:
        # Only an explicit, evidenced kill correction belongs here. Unknown
        # invocations still fail closed; this never removes them implicitly.
        try:
            evidence = record['derivation']
            maximum = evidence['maximum_observed_writer_list_cost_usd']
            elapsed = evidence['completed_writer_elapsed_seconds']
            killed = evidence['interrupted_seconds']
            amount = record['infrastructure_waste_usd']
            valid = (record['kind'] == 'infrastructure_kill' and bool(record['reason']) and
                     all(_number(v) and v > 0 for v in (maximum, elapsed, killed, amount)) and
                     amount == math.ceil(max(maximum, maximum / elapsed * killed)) and
                     evidence['ledger_events_before'] == evidence['ledger_events_after'] and
                     all(re.fullmatch(r'[0-9a-f]{64}', evidence[k]) for k in ('card_sha256', 'checkpoint_sha256')))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            valid = False
        if not valid: unpriced += 1
        # Retain even a malformed record's numeric amount in the visible total.
        if isinstance(record, dict) and _number(record.get('infrastructure_waste_usd')):
            waste += record['infrastructure_waste_usd']
    waste = round(waste, 9)
    return {'spent_usd': None if unpriced else known, 'breakdown_by_role': breakdown,
            'infrastructure_waste_usd': waste, 'infrastructure_waste': records,
            'total_spent_usd': None if unpriced else round(known + waste, 9),
            **({'unpriced_events': unpriced, 'known_spent_usd': known,
                'known_total_spent_usd': round(known + waste, 9)} if unpriced else {})}


def invocation_role(name):
    return ('writer' if name.startswith('builder') else 'stress_tester' if name.startswith('attacker') else
            'strong_calibrator' if name.startswith('strong-calibrator') else 'easy_calibrator' if name.startswith('easy-calibrator') else
            'reviewer2' if name.startswith('reviewer-2') else 'reviewer')


def require_case_budget(ledger, limit, configured_model=None):
    spent = case_spending(ledger)['spent_usd']
    if spent is None or spent >= limit or (str(configured_model).startswith('codex/') and configured_model not in CODEX_PRICES):
        raise BudgetError('budget_exhausted')


def tool_cpu_ticks(sid):
    """CPU ticks used by the processes in session `sid` other than its leader (the model CLI): the tool
    commands it runs. None where /proc is unavailable (then silence alone decides)."""
    if not os.path.isdir('/proc/self'): return None
    total = 0
    for pid in os.listdir('/proc'):
        if not pid.isdigit() or int(pid) == sid: continue
        try: fields = open(f'/proc/{pid}/stat').read().rsplit(')', 1)[1].split()
        except OSError: continue
        if int(fields[3]) == sid: total += int(fields[11]) + int(fields[12]) + int(fields[13]) + int(fields[14])
    return total


@contextmanager
def _activity(path, resume=False):
    """Protect admission and non-atomic EX→SH conversion separately from execution."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + ".admission.lock", "a") as admission, open(str(path) + ".activity.lock", "a") as lock:
        deadline = time.monotonic() + 10
        while True:
            fcntl.flock(admission, fcntl.LOCK_EX)
            if not resume:
                fcntl.flock(lock, fcntl.LOCK_SH)
                break
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                # Another caller may already have resumed the stopped generation.
                # Join it without erasing its registrations or resetting its limits.
                fcntl.flock(lock, fcntl.LOCK_SH)
                with open(str(path) + '.lock', 'a') as ledger_lock:
                    fcntl.flock(ledger_lock, fcntl.LOCK_EX)
                    ledger = json.loads(path.read_text()) if path.exists() else {}
                    if ledger.get('terminal_stop') in (None, 'running', 'complete'):
                        resume = False
                        break
                fcntl.flock(lock, fcntl.LOCK_UN)
                fcntl.flock(admission, fcntl.LOCK_UN)
                if time.monotonic() >= deadline:
                    raise BudgetError('resume_while_active') from None
                time.sleep(.01)
        # The caller releases admission only after registration and the shared
        # lease are established. flock conversion can momentarily drop EX on Linux.
        yield lock, resume, admission


def resume_ledger(ledger_path):
    """The resume handshake alone, no process: record the previous run's stop and clear it, so the first model calls of a
    resumed run may start in parallel (2026-10-20: a resume whose first calls were G10 ran both testers serially)."""
    path = Path(ledger_path)
    if not path.exists(): return
    with _activity(path, resume=True) as (_, reset, _), open(str(path) + '.lock', 'a') as lock:
        if not reset: return
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger = json.loads(path.read_text())
        previous = ledger.get('terminal_stop')
        if previous not in (None, 'complete'): ledger.setdefault('previous_stops', []).append(previous)
        ledger['terminal_stop'], ledger['zero_token_streak'] = None, 0
        ledger.pop('active', None)
        _save(path, ledger)


def run_budgeted(cmd, cwd, env, transcript_path, ledger_path, timeout,
                 max_cost=3.0, max_calls=100, max_total_calls=300, driver='opencode',
                 progress_timeout=15 * 60, max_zero_tokens=3, configured_model=None, resume=False, concurrent=False, cancel=None, case_budget=50.0, role=None, invocation_name=None):
    # Preserve the original whole-session lock unless concurrency is explicitly enabled.
    settings = locals()
    path = Path(ledger_path)
    with _activity(path, resume=resume) as (activity, reset, admission):
        settings["resume"] = reset
        if concurrent: return _run_budgeted(**settings, _activity_lock=activity, _admission_lock=admission)
        with open(str(path) + '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return _run_budgeted(**settings, _serial_lock=lock, _activity_lock=activity, _admission_lock=admission)


def _run_budgeted(cmd, cwd, env, transcript_path, ledger_path, timeout,
                 max_cost=3.0, max_calls=100, max_total_calls=300, driver='opencode',
                 progress_timeout=15 * 60, max_zero_tokens=3, configured_model=None, resume=False, concurrent=False, cancel=None, case_budget=50.0, role=None, invocation_name=None, _serial_lock=None, _activity_lock=None, _admission_lock=None):
    """Return CompletedProcess, or raise BudgetError without exposing transcript text.

    max_calls limits this invocation; max_total_calls and max_cost span roles.
    max_cost counts priced (opencode) events only: codex/claude are subscriptions
    (Claude list-price totals and estimated Codex token costs recorded separately).
    case_budget is checked only before a role starts; an in-flight role finishes.
    Ledger contains usage metadata only. A terminal failure is sticky unless explicitly
    resumed; resuming preserves all costs/calls and archives the previous stop.
    """
    if driver not in ('opencode', 'codex', 'claude'):
        raise ValueError('Unknown driver')
    if not all(_number(v) for v in (max_cost, max_calls, timeout, max_total_calls, progress_timeout, case_budget)) or not isinstance(max_zero_tokens, int) or max_zero_tokens < 1:
        raise ValueError('Budget ceilings and timeout must be finite and nonnegative')
    if '--attach' in cmd or any(str(arg).startswith('--attach=') for arg in cmd):
        raise ValueError('Budget enforcement requires an exclusive local process')
    if configured_model is None:
        for index, arg in enumerate(cmd[:-1]):
            if arg in ('-m', '--model'): configured_model = cmd[index + 1]
        if driver == 'codex' and not str(configured_model).startswith('codex/'):
            configured_model = 'codex/' + (configured_model or 'unknown')
    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger = None
    invocation = uuid.uuid4().hex

    @contextmanager
    def transaction():
        nonlocal ledger
        with (nullcontext(_serial_lock) if _serial_lock is not None else open(str(path) + '.lock', 'a')) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            ledger = json.loads(path.read_text()) if path.exists() else {
                'cost': 0.0, 'calls': 0, 'events': [], 'terminal_stop': None,
            }
            before = json.dumps(ledger, sort_keys=True)
            try:
                yield
            finally:
                if json.dumps(ledger, sort_keys=True) != before: _save(path, ledger)

    def shared_stop():
        previous = ledger.get('terminal_stop')
        if previous not in (None, 'running', 'complete'):
            raise BudgetError(previous)
        if cancel is not None and cancel.is_set(): raise BudgetError('cancelled')

    with transaction():
        if (not _number(ledger.get('cost')) or not _number(ledger.get('calls'))
                or not isinstance(ledger.get('events'), list)):
            raise BudgetError('Invalid budget ledger; no process started')
        require_case_budget(ledger, case_budget, configured_model)
        previous = ledger.get('terminal_stop')
        if previous not in (None, 'complete') and not (concurrent and previous == 'running' and not resume):
            if not resume: raise BudgetError('Budget ledger stopped: ' + str(previous))
            ledger.setdefault('previous_stops', []).append(previous)
        if resume:
            ledger['zero_token_streak'] = 0
            ledger.pop('active', None)
        cause = ('cost_limit' if ledger['cost'] >= max_cost else
                 'total_call_limit' if ledger['calls'] >= max_total_calls else
                 'call_limit' if max_calls == 0 else
                 'timeout' if timeout == 0 else
                 'stalled' if progress_timeout == 0 else None)
        if cause:
            ledger['terminal_stop'] = cause
            raise BudgetError('Budget stopped: ' + cause)
        ledger['terminal_stop'] = 'running'
        if concurrent: ledger.setdefault('active', []).append(invocation)
    if _activity_lock is not None:
        fcntl.flock(_activity_lock, fcntl.LOCK_SH)
    if _admission_lock is not None:
        fcntl.flock(_admission_lock, fcntl.LOCK_UN)
    seen = {item['id'] for item in ledger['events']}
    provider_model = configured_model or driver + '/unknown'
    with transaction():
        ledger.update(driver=driver, configured_model=configured_model)
    rate_limits = 0
    starts, finishes, responses = set(), set(), set()
    partial_usage = {}
    count = usages = 0
    session = {'id': '', 'turns': 0}
    process = None
    stopped = False
    collecting_usage = False
    pending = b''
    selector = selectors.DefaultSelector()
    last_output = time.monotonic()
    deadline = last_output + timeout
    started_utc, log_checked = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()), last_output

    def silent_limit():
        # OpenCode 1.19 prints nothing and retries forever on a Go usage limit; only its log says so (2026-10-19).
        try: logs = list(Path(env.get('XDG_DATA_HOME') or Path.home() / '.local/share', 'opencode/log').glob('*.log'))
        except OSError: return  # an isolated tester's private log dir: silence alone decides, as before
        for log in logs:
            try: lines = log.read_text(errors='replace').splitlines()[-2000:]
            except OSError: continue
            if any('usage limit exceeded' in l.lower() and l[10:29] >= started_utc for l in lines if l.startswith('timestamp=')):
                raise BudgetError('provider_limit:' + provider_model)

    def check_limits():
        if collecting_usage: return  # accounting buffered output after the process was stopped
        if ledger['cost'] >= max_cost:
            raise BudgetError('cost_limit')
        if ledger['calls'] >= max_total_calls:
            raise BudgetError('total_call_limit')
        if count >= max_calls:
            raise BudgetError('call_limit')

    def tokens_seen(tokens):
        nonlocal rate_limits
        ledger['zero_token_streak'] = 0 if any(tokens) else ledger.get('zero_token_streak', 0) + 1
        if any(tokens): rate_limits = 0
        _save(path, ledger)
        if not collecting_usage and ledger['zero_token_streak'] >= max_zero_tokens: raise BudgetError('zero_tokens')

    def diagnostic(text, response=False, partial=False):
        nonlocal rate_limits
        text = text.lower()
        if driver == 'codex' and not response and (('refresh token' in text and any(s in text for s in (
                'already used', 'expired', 'revoked', 'invalidated', 'could not be refreshed')))
                or 'refresh_token_reused' in text or 'refresh_token_expired' in text
                or 'refresh_token_invalidated' in text
                or 'access token could not be refreshed' in text
                or 'workspace routing discovery unauthorized' in text
                or 'authentication token has expired' in text
                or ('401' in text and ('unauthorized' in text or 'authentication' in text))):
            raise BudgetError('codex_login_expired')
        if driver == 'codex' and 'cybersecurity' in text and any(w in text for w in ('flagged', 'refus', "can't", 'cannot')):
            raise BudgetError('refusal:' + provider_model)
        if response and not re.search(r"gousagelimiterror|insufficient credits|\bhttp [45]\d\d\b|^(?:error[: ]|you(?:'ve| have)? (?:hit|reached|exceeded)|usage limit\b|rate limit\b|limit reached)", text.strip()):
            return False  # Assistant prose may discuss business usage limits.
        if ('gousagelimiterror' in text or 'insufficient credits' in text or re.search(r'\b402\b', text)
                or 'usage limit' in text or 'limit reached' in text
                or re.search(r'\b(?:hit|reached|exceeded) (?:your |the )?(?:usage |rate )?limit\b', text)
                or ('weekly' in text and ('limit' in text or 'quota' in text))):
            raise BudgetError('provider_limit:' + provider_model)
        if 'rate limit' in text or re.search(r'\b429\b', text):
            if partial: return False  # Count an unterminated notice only once, at newline/EOF.
            rate_limits += 1
            if rate_limits >= 2 or provider_model.startswith('openrouter/'):
                raise BudgetError('provider_limit:' + provider_model)
            return True  # Allow one transient rate-limit retry, never an endless loop.
        return False

    def call():
        """A subscription CLI's model response: counted live, usage arrives per turn/run."""
        nonlocal count
        count += 1
        ledger['calls'] += 1
        _save(path, ledger)
        check_limits()

    def subscription_usage(identity, usage, required, list_cost=None, partial=False):
        """Tokens recorded at cost 0, priced 'subscription' (exempt from unpriced_usage)."""
        nonlocal usages
        if not isinstance(usage, dict) or not all(_number(usage.get(k)) for k in required):
            raise BudgetError('missing_usage')
        estimate = (codex_cost(configured_model, usage) if driver == 'codex' else
                    claude_cost(configured_model, usage) if partial else None)
        if (driver == 'codex' or partial) and estimate is None: raise BudgetError('missing_usage')
        finishes.add(identity)
        if identity in seen:
            return
        seen.add(identity)
        usages += 1
        record = {'id': identity, 'cost': 0, 'priced': 'subscription', 'tokens': usage,
                  'configured_model': configured_model, 'calls': count}
        record.update(role=role or 'legacy_unattributed', invocation=invocation_name)
        if partial: record['estimated_from_partial_usage'] = True
        if estimate is not None:
            record['estimated_subscription_cost_usd'] = estimate
            ledger['estimated_subscription_cost_usd'] = ledger.get('estimated_subscription_cost_usd', 0) + estimate
        if list_cost is not None:
            record['list_cost_usd'] = list_cost
            ledger['list_cost_usd'] = ledger.get('list_cost_usd', 0) + list_cost
        ledger['events'].append(record)
        if driver == 'codex': tokens_seen([v for k, v in usage.items() if k.endswith('_tokens') and _number(v)])
        else: _save(path, ledger)
        check_limits()

    def consume_codex(event):
        # 'error' events are retry notices ("Reconnecting..."); turn.failed is terminal.
        kind = event.get('type')
        usage = event.get('usage') or (event.get('item') or {}).get('usage')
        if isinstance(usage, dict):
            partial_usage[session['id'] + ':turn-' + str(session['turns'])] = usage
        if kind == 'thread.started':
            session['id'] = str(event.get('thread_id', ''))
        elif kind == 'turn.started':
            session['turns'] += 1
            starts.add(session['id'] + ':turn-' + str(session['turns']))
        elif kind == 'turn.failed':
            raise BudgetError('codex_error')
        elif kind == 'item.completed' and (event.get('item') or {}).get('type') in CODEX_STEPS:
            # ponytail: exec --json has no per-response usage; parallel tool calls overcount, so limits stop early, never late.
            call()
        elif kind == 'turn.completed':
            subscription_usage(session['id'] + ':turn-' + str(session['turns']), event.get('usage'),
                               ('input_tokens', 'cached_input_tokens', 'output_tokens'))

    def consume_claude(event):
        kind = event.get('type')
        if kind == 'system' and event.get('subtype') == 'init':
            session['id'] = str(event.get('session_id', ''))
            starts.add(session['id'] + ':result')
        elif kind == 'assistant':
            message = event.get('message')
            if not isinstance(message, dict) or not message.get('id') or not isinstance(message.get('usage'), dict):
                starts.add('unverified-stream-usage:' + invocation)
                raise BudgetError('missing_usage')
            key = session['id'] + ':' + str(message['id'])
            usage = message['usage']
            required = ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')
            if not all(_number(usage.get(k)) for k in required):
                starts.add('unverified-stream-usage:' + invocation)
                raise BudgetError('missing_usage')
            # A message can have several content blocks with growing usage.
            prior = partial_usage.setdefault(key, {})
            for k in required: prior[k] = max(prior.get(k, 0), usage[k])
            if key not in responses:  # one response streams as one event per content block
                responses.add(key)
                call()
                tokens_seen([usage[k] for k in required])
        elif kind == 'result':
            if event.get('is_error'):  # API errors arrive as subtype 'success' with is_error
                raise BudgetError('claude_error')
            if not _number(event.get('total_cost_usd')):
                starts.add('unverified-stream-usage:' + invocation)
                raise BudgetError('missing_usage')
            usage = event.get('usage')
            if not isinstance(usage, dict) or not all(_number(usage.get(k)) for k in
                    ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')):
                starts.add('unverified-stream-usage:' + invocation)
                raise BudgetError('missing_usage')
            subscription_usage(str(event.get('session_id') or session['id']) + ':result', event.get('usage'),
                               ('input_tokens', 'output_tokens', 'cache_read_input_tokens',
                                'cache_creation_input_tokens'), list_cost=event['total_cost_usd'])

    def consume(line):
        nonlocal count, usages
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            diagnostic(line.decode(errors='replace') if isinstance(line, bytes) else line)
            return  # Non-JSON diagnostics stay in the sealed transcript.
        if not isinstance(event, dict):
            return
        kind = event.get('type')
        if driver == 'claude' and kind == 'rate_limit_event':
            # Claude names its window reset; a limited case resumes then instead of guessing (2026-10-19).
            info = event.get('rate_limit_info') or {}
            if _number(info.get('resetsAt')): ledger['claude_resets_at'] = info['resetsAt']
            if info.get('status') == 'rejected': raise BudgetError('provider_limit:' + provider_model)
        if driver == 'claude' and event.get('error') in ('rate_limit', 'usage_limit'):
            raise BudgetError('provider_limit:' + provider_model)
        # Never scan tool output or echoed command/prompt text for provider errors.
        if kind == 'error' or (kind == 'system' and event.get('subtype') in ('error', 'api_retry', 'retry')) or (kind == 'result' and event.get('is_error')) or (driver == 'claude' and kind == 'assistant' and event.get('error')):
            if diagnostic(json.dumps(event)): return
        elif driver == 'claude' and kind == 'result':
            diagnostic(str(event.get('result', '')), response=True)
        elif driver == 'codex' and kind == 'turn.failed':
            diagnostic(json.dumps(event.get('error', {})))
        elif driver == 'codex' and kind == 'item.completed' and (event.get('item') or {}).get('type') == 'agent_message':
            diagnostic(str(event['item'].get('text', '')), response=True)
        elif driver == 'opencode' and kind == 'text':
            diagnostic(str((event.get('part') or {}).get('text', '')), response=True)
        if driver == 'codex':
            return consume_codex(event)
        if driver == 'claude':
            return consume_claude(event)
        kind, part = event.get('type'), event.get('part', {})
        if kind == 'error':
            raise BudgetError('opencode_error')
        if kind not in ('step_start', 'step_finish'):
            return
        if not isinstance(part, dict) or not part.get('messageID'):
            raise BudgetError('invalid_usage')
        key = str(event.get('sessionID', part.get('sessionID', ''))) + ':' + part['messageID']
        if kind == 'step_start':
            starts.add(key)
            return
        identity = key + ':' + str(part.get('id', ''))
        if identity in seen:
            finishes.add(key)
            return
        tokens = part.get('tokens')
        if (not part.get('id') or not _number(part.get('cost'))
                or not isinstance(tokens, dict) or not isinstance(tokens.get('cache'), dict)
                or not all(_number(tokens.get(k)) for k in ('input', 'output', 'reasoning'))
                or not all(_number(tokens['cache'].get(k)) for k in ('read', 'write'))):
            raise BudgetError('missing_usage')
        seen.add(identity)
        finishes.add(key)
        count += 1
        usages += 1
        ledger['cost'] += part['cost']
        ledger['calls'] += 1
        ledger['events'].append({
            'id': identity, 'cost': part['cost'], 'tokens': tokens,
            'role': role or 'legacy_unattributed', 'invocation': invocation_name,
            'configured_model': configured_model,
            'model': part.get('model', event.get('model')),
            'modelID': part.get('modelID', event.get('modelID')),
            'providerID': part.get('providerID', event.get('providerID')),
        })
        tokens_seen([tokens[k] for k in ('input', 'output', 'reasoning')] + list(tokens['cache'].values()))
        if (part['cost'] == 0 and any([tokens[k] for k in ('input', 'output', 'reasoning')]
                                           + list(tokens['cache'].values()))
                and not str(configured_model).endswith((':free', '-free'))):
            raise BudgetError('unpriced_usage')
        check_limits()

    def stop_process():
        nonlocal stopped
        if process is not None and not stopped:
            # Kill descendants even if their immediate parent already exited.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                # Darwin can report EPERM after the group has already exited.
                # A live sudo/pilot child may instead require privileged cancellation.
                if process.poll() is None:
                    try:
                        cancellation = subprocess.run(
                            ['sudo', '-n', '/bin/kill', '-KILL', '--', f'-{process.pid}'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                        if cancellation.returncode and process.poll() is None:
                            raise BudgetError('cancellation_failed')
                    except (OSError, subprocess.TimeoutExpired) as error:
                        raise BudgetError('cancellation_failed') from error
            finally:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    raise BudgetError('cancellation_failed') from None
            stopped = True

    try:
        with open(transcript_path, 'wb') as transcript:
            process = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                       start_new_session=True)  # codex exec waits on an open stdin
            selector.register(process.stdout, selectors.EVENT_READ)
            pending = b''
            tool_cpu = tool_cpu_ticks(process.pid)
            while selector.get_map() or process.poll() is None:
                with transaction():
                    shared_stop()
                    check_limits()
                now = time.monotonic()
                if driver == 'opencode' and min(now - last_output, now - log_checked) >= min(60, progress_timeout / 2):
                    log_checked = now; silent_limit()
                if now - last_output >= progress_timeout:
                    # A long tool call (e.g. five strategy runs in one shell command) prints nothing until it
                    # ends; CPU used by the CLI's child processes counts as progress. --agent-timeout still caps.
                    cpu = tool_cpu_ticks(process.pid)
                    if cpu is None or cpu == tool_cpu: raise BudgetError("stalled")  # a child that ended also changes it
                    tool_cpu, last_output = cpu, now
                remaining = deadline - now
                if remaining <= 0:
                    raise BudgetError('timeout')
                for key, _ in selector.select(min(remaining, progress_timeout - (now - last_output), 0.1)):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    last_output = time.monotonic()
                    transcript.write(chunk)
                    transcript.flush()
                    pending += chunk
                    while b'\n' in pending:
                        with transaction():
                            shared_stop()
                            seen.update(item["id"] for item in ledger["events"])
                            line, pending = pending.split(b'\n', 1)
                            consume(line)
                    if pending and not pending.lstrip().startswith(b'{'):
                        diagnostic(pending.decode(errors='replace'), partial=True)
            if pending:
                with transaction():
                    shared_stop()
                    seen.update(item["id"] for item in ledger["events"])
                    line, pending = pending, b''
                    consume(line)
            try:
                returncode = process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise BudgetError('timeout') from None
            if returncode:
                raise BudgetError('process_error')
            if not usages or starts - finishes:
                raise BudgetError('missing_usage')
            with transaction():
                shared_stop()
                if concurrent: ledger['active'].remove(invocation)
                ledger['terminal_stop'] = 'running' if ledger.get('active') else 'complete'
                if not ledger.get('active'): ledger.pop('active', None)
            return subprocess.CompletedProcess(cmd, returncode)
    except BaseException as error:
        if (process is not None and driver in ('codex', 'claude')
                and isinstance(error, BudgetError)
                and str(error) in ('call_limit', 'total_call_limit', 'cost_limit', 'timeout')):
            # Stop first: collecting usage must never grant another model response.
            # Only drain bytes already emitted; no grace period for a missing receipt.
            try:
                stop_process()
            except BaseException as cleanup_error:
                # Cancellation is part of the accounting boundary. A failed stop
                # cannot bypass the durable unknown-usage record below, even if
                # this invocation already recorded an earlier complete turn.
                starts.add('cancellation-failed:' + invocation)
                with transaction():
                    ledger.setdefault('cleanup_errors', []).append({
                        'stage':'process_cancellation', 'error':type(cleanup_error).__name__})
                if isinstance(cleanup_error, Exception):
                    pass  # Keep the first stop; unknown usage still blocks recovery.
                else:
                    error = cleanup_error
            else:
                collecting_usage = True
                complete = True
                try:
                    os.set_blocking(process.stdout.fileno(), False)
                    buffered = 0
                    while True:
                        try: chunk = os.read(process.stdout.fileno(), 65536)
                        except BlockingIOError:
                            complete = False
                            break
                        if not chunk: break
                        with open(transcript_path, 'ab') as transcript: transcript.write(chunk)
                        pending += chunk
                        buffered += len(chunk)
                        if buffered >= 4 * 1024 * 1024:
                            complete = False
                            break
                    for line in pending.splitlines():
                        try:
                            # A killed writer may leave half of a new event after a
                            # valid receipt; do not silently price that tail as zero.
                            if line.lstrip().startswith((b'{', b'[')):
                                if not isinstance(json.loads(line), dict):
                                    raise ValueError('invalid buffered event')
                            with transaction():
                                seen.update(item['id'] for item in ledger['events'])
                                consume(line)
                        except Exception:
                            # Unexpected JSON shapes and oversized numbers must
                            # still reach durable unknown-usage bookkeeping.
                            complete = False
                    pending = b''
                except (OSError, ValueError, TypeError):
                    complete = False
                finally:
                    collecting_usage = False
                if not complete:
                    # An unread/malformed tail could contain another unpriced turn.
                    starts.add('unverified-buffered-usage:' + invocation)
        with transaction():
            collecting_usage = True
            try:
                if driver == 'claude':
                    required = ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')
                    sessions = {key.rsplit(':', 1)[0] for key in partial_usage}
                    for sid in sessions:
                        identity = sid + ':result'
                        if identity in finishes: continue
                        values = [v for key, v in partial_usage.items() if key.rsplit(':', 1)[0] == sid]
                        usage = {k: sum(v[k] for v in values) for k in required}
                        subscription_usage(identity, usage, required, partial=True)
                elif driver == 'codex':
                    for identity, usage in partial_usage.items():
                        if identity not in finishes:
                            subscription_usage(identity, usage, ('input_tokens', 'cached_input_tokens', 'output_tokens'), partial=True)
            except BudgetError:
                pass  # Unknown model or invalid partial usage remains fail-closed below.
            finally:
                collecting_usage = False
            if driver in ('codex', 'claude') and (starts - finishes or (process is not None and not usages)):
                ledger.setdefault('unpriced_invocations', []).append({'role': role, 'model': configured_model})
            if invocation in ledger.get('active', []): ledger['active'].remove(invocation)
            if not ledger.get('active'): ledger.pop('active', None)
            if ledger.get('terminal_stop') in (None, 'running', 'complete'):
                ledger['terminal_stop'] = str(error) if isinstance(error, BudgetError) else type(error).__name__
                if isinstance(error, BudgetError) and str(error) == 'process_error':
                    # Keep the last natural CLI failure diagnosable without exposing transcript text.
                    ledger['last_process_error'] = {'returncode': process.returncode, 'driver': driver,
                                                    'configured_model': configured_model}
        raise error
    finally:
        original = sys.exc_info()[1]
        selector.close()
        try:
            stop_process()
        except Exception as cleanup_error:
            with transaction():
                ledger.setdefault('cleanup_errors', []).append({
                    'stage':'process_cancellation', 'error':type(cleanup_error).__name__})
                # A failure on the success path is itself a stop; never return success.
                if original is None: ledger['terminal_stop'] = 'cancellation_failed'
            if original is None: raise BudgetError('cancellation_failed') from cleanup_error
        finally:
            if process is not None: process.stdout.close()
