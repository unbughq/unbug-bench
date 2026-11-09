"""Read encrypted evidence in worker memory and export only operational codes/numbers.

stdin: {key: base64 scope key, ref: contract Ref, ciphertext: base64 age blob}.
Never extracts the archive or returns prompts, messages, paths or case files.
"""
import base64
import io
import json
import math
from pathlib import Path
import re
import sys
import tarfile
from decimal import Decimal, InvalidOperation

from durable.artifacts import AgeSealer
from durable.contract import Ref, ArtifactKind

REASONS = {'quota', 'rate', 'credit', 'outage', 'credential_expiring', 'unbounded_route', 'router_unavailable', 'seats_busy'}
STOPS = {'provider_wait', 'process_error', 'claude_error', 'codex_error', 'opencode_error',
         'budget_exhausted', 'cost_limit', 'timeout', 'stalled', 'zero_tokens'}
HINTS = {'authentication': r'authentication|invalid api key|oauth token.*expired|unauthorized',
         'rate_limit': r'rate.limit|usage limit|hit your limit|too many requests',
         'model_unavailable': r'model.not.found|unknown model|model.*not available',
         'context_limit': r'context.length|prompt.*too long',
         'spending_limit': r'max.budget|budget.*exceeded|spend.*limit',
         'request_invalid': r'invalid.request|unsupported.parameter|unrecognized.*field',
         'geo_unsupported': r'inference_geo.*not supported.*organization',
         'connection_failure': r'connection refused|econnrefused|enotfound|fetch failed|connection reset',
         'server_failure': r'internal.server.error|service.unavailable|overloaded',
         'request_denied': r'forbidden|request.not.allowed|access.denied',
         'tls_failure': r'certificate|self.signed|unable.to.verify|tls.handshake',
         'interrupted': r'\baborted\b|aborterror|\bcancelled\b',
         'cli_arguments': r'unknown.option|unexpected.argument|unrecognized.option',
         'permission_failure': r'permission.denied|eacces|eperm'}


def _error_fields(event):
    kind = event.get('type')
    if not (kind in ('error', 'turn.failed') or event.get('is_error') is True
            or kind == 'assistant' and event.get('error')
            or kind == 'system' and event.get('subtype') in ('error', 'api_retry', 'retry')):
        return None
    error = event.get('error')
    rows = [event] + ([error] if isinstance(error, dict) else [])
    if isinstance(error, dict) and isinstance(error.get('data'), dict): rows.append(error['data'])
    texts, statuses = [], []
    for row in rows:
        for key in ('message', 'result', 'name', 'error_type', 'code'):
            if isinstance(row.get(key), str): texts.append(row[key])
        for key in ('statusCode', 'status_code', 'http_status', 'error_status'):
            if type(row.get(key)) is int and 400 <= row[key] <= 599: statuses.append(row[key])
    if isinstance(error, str): texts.append(error)
    # Claude puts the provider error inside an assistant message. Only inspect
    # its text blocks when the envelope explicitly marks it as an error.
    message = event.get('message')
    if kind == 'assistant' and event.get('error') and isinstance(message, dict):
        content = message.get('content')
        if isinstance(content, list):
            texts += [block['text'] for block in content if isinstance(block, dict)
                      and block.get('type') == 'text' and isinstance(block.get('text'), str)]
    if isinstance(event.get('errors'), list): texts += [s for s in event['errors'] if isinstance(s, str)]
    text = '\n'.join(texts)
    statuses += [int(code) for code in re.findall(r'\b(?:API Error:|HTTP(?:/\d(?:\.\d)?)?)\s*([45]\d\d)\b', text, re.I)]
    return text, statuses


def _numbers(value):
    keys = {'cost', 'list_cost_usd', 'estimated_subscription_cost_usd', 'forwarded_requests',
            'validated_requests', 'unsupported_requests', 'in_flight_requests', 'unknown_requests',
            'held_usd', 'settled_usd', 'settled_input_tokens', 'settled_output_tokens',
            'held_input_tokens', 'held_output_tokens'}
    result = {}
    for key in keys & value.keys():
        v = value[key]
        if type(v) is str and len(v) <= 64:
            try: v = float(Decimal(v))
            except (InvalidOperation, ValueError, OverflowError): continue
        if type(v) in (float, int) and math.isfinite(v): result[key] = v
    for key in ('exhausted', 'closed'):
        if type(value.get(key)) is bool: result[key] = value[key]
    return result


def cleanup_errors(card):
    """Fixed operational labels only; paths and exception messages stay sealed."""
    from durable.classify import CLEANUP_STAGES
    stages={'model_scratch','model_process','model_join','model_containment','lease_finish',
            *('diagnosis_'+stage for stage in CLEANUP_STAGES),   # diagnosis_invocation.invoke
            'pilot_home'}   # run.early_probe
    errors={'TimeoutExpired','TimeoutError','CalledProcessError','PermissionError','FileNotFoundError',
            'OSError','RuntimeError','RouterUnavailable','BudgetError','ValueError','PilotHomeError',
            'containment_unavailable','cancellation_failed'}
    rows=card.get('cleanup_errors',[]) if isinstance(card,dict) else []
    if not isinstance(rows,list):return []
    return [{'stage':row['stage'],'error':row['error']} for row in rows[:32]
            if isinstance(row,dict) and row.get('stage') in stages and row.get('error') in errors]


def _scan_errors(report, lines):
    for line in lines:
        try: event = json.loads(line)
        except (ValueError, UnicodeError): continue
        if not isinstance(event, dict): continue
        fields = _error_fields(event)
        if fields is None: continue
        report['typed_error_count'] += 1
        text, statuses = fields
        report['http_statuses'] = sorted(set(report['http_statuses']) | set(statuses))
        for code, pattern in HINTS.items():
            if re.search(pattern, text, re.I) and code not in report['error_hints']:
                report['error_hints'].append(code)


def inspect_transcripts(directory):
    """The same safe error summary for normal worker diagnostics and saved evidence."""
    report = {'typed_error_count': 0, 'http_statuses': [], 'error_hints': []}
    for path in sorted(Path(directory).glob('*.jsonl'))[-32:]:
        if path.is_file() and path.stat().st_size <= 16 * 1024 * 1024:
            with path.open('rb') as stream: _scan_errors(report, stream)
    return report


def answer_retry_state(state):
    """Retained-answer progress, without bindings, paths, routes, answers or error text."""
    if not isinstance(state, dict) or not isinstance(state.get('binding'), dict): return None
    kind = state['binding'].get('kind')
    if kind not in ('dedup', 'idea', 'panel', 'freshness', 'stress'): return None
    attempts, routes = state.get('attempts'), state.get('spent_routes')
    if not isinstance(attempts, list) or not isinstance(routes, list): return None
    errors = {'schema validation failed': 'schema_invalid',
              'repair changed scientific decision': 'decision_changed', 'duplicate JSON key': 'duplicate_key'}
    rows = []
    for row in attempts[-32:]:
        if not isinstance(row, dict) or row.get('kind') not in ('judgment', 'repair') \
                or row.get('phase') not in ('pending', 'completed', 'invalid'): continue
        result = {'kind': row['kind'], 'phase': row['phase']}
        if isinstance(row.get('validation_error'), str):
            result['validation'] = errors.get(row['validation_error'], 'other')
        rows.append(result)
    return {'kind': kind, 'spent_routes': len(routes), 'attempts': rows}


def inspect_snapshot(raw):
    report = {'schema': 1, 'receipts': [], 'error_hints': [], 'typed_error_count': 0, 'http_statuses': []}
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:*') as archive:
        for member in archive:
            if not member.isfile() or member.size > 16 * 1024 * 1024:
                continue
            name = member.name.removeprefix('./')
            if name == 'continuation-budget.json':
                ledger = json.load(archive.extractfile(member))
                stop = ledger.get('terminal_stop')
                if isinstance(stop, str) and stop.partition(':')[0] in STOPS:
                    report['ledger_stop'] = stop.partition(':')[0]
                failure = ledger.get('provider_failure') or {}
                if failure.get('reason') in REASONS: report['provider_reason'] = failure['reason']
                report['model_calls'] = ledger.get('calls') if type(ledger.get('calls')) is int else None
            elif name == 'scorecard.json':
                failures=cleanup_errors(json.load(archive.extractfile(member)))
                if failures:report['cleanup_errors']=failures
            elif re.fullmatch(r'usage-receipts/[a-f0-9-]+\.json', name):
                receipt = json.load(archive.extractfile(member))
                row = {'final_usage_known': receipt.get('final_usage_known') is True}
                if receipt.get('outcome') in ('done', 'denied', 'interrupted'): row['outcome'] = receipt['outcome']
                if receipt.get('failure_reason') in REASONS: row['failure_reason'] = receipt['failure_reason']
                if receipt.get('source_stop') in STOPS: row['source_stop'] = receipt['source_stop']
                row['usage'] = _numbers(receipt.get('usage_delta') or {})
                row['cap_used'] = _numbers(receipt.get('cap_used') or {})
                report['receipts'].append(row)
            elif re.fullmatch(r'ordinary-retries/[a-f0-9]{64}/state\.json', name):
                if len(report.get('answer_retries', [])) >= 32: continue
                try: state = answer_retry_state(json.load(archive.extractfile(member)))
                except (ValueError, UnicodeError):
                    report['answer_retry_state_invalid'] = True
                    continue
                if state is not None: report.setdefault('answer_retries', []).append(state)
            elif name.startswith('transcripts/'):
                _scan_errors(report, archive.extractfile(member))
    return report


def inspect_diagnostic(raw):
    value=json.loads(raw)
    operational=value.get('operational') or {}
    if not isinstance(operational,dict):operational={}
    count=operational.get('typed_error_count')
    report={'schema':1,'typed_error_count':count if type(count) is int and count>=0 else 0,
            'http_statuses':sorted({s for s in operational.get('http_statuses',[]) if type(s) is int and 400<=s<=599}),
            'error_hints':[h for h in operational.get('error_hints',[]) if isinstance(h,str) and h in HINTS]}
    failures=cleanup_errors(operational)
    if failures:report['cleanup_errors']=failures
    return report


def main():
    try:
        packet = json.load(sys.stdin)
        ref=Ref(**packet['ref'])
        raw = AgeSealer().open(base64.b64decode(packet['key'], validate=True), ref,
                              base64.b64decode(packet['ciphertext'], validate=True))
        report=inspect_diagnostic(raw) if ref.kind is ArtifactKind.DIAGNOSTIC else inspect_snapshot(raw)
        print(json.dumps(report, sort_keys=True))
    except Exception:
        print('{"error":"diagnostic_inspection_failed"}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
