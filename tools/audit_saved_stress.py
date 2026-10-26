#!/usr/bin/env python3
"""One saved attempt: stream its actions into a content-free operational report.

No extraction, model calls, or worker operations. The founder identity is entered
privately in the terminal and passed to age through stdin, never written to disk.
"""
import collections
import argparse
import datetime
import getpass
import hashlib
import json
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import tarfile
import tempfile
import shutil
from pathlib import PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'factory'))
from attack_findings import classify
EVIDENCE = ROOT / 'results/infrastructure/2026-10-22-provider-routing'
CASE = 'case-20261019T061116Z-3826d5'
SHA = 'c232b2b1e8ea9bf7a798d94cd0e9815c92ac94058b564ee1bf500e7b7327569f'
TRANSCRIPT = CASE + '/transcripts/attacker-1.1792657045460512729.jsonl'
START = 1792657045.461975
ERRORS = {
    'diagnostic_exhausted': 'diagnostic allowance exhausted',
    'diagnostic_failed': 'diagnostic execution failed',
    'diagnostic_timeout': 'diagnostic time allowance exhausted',
    'permission_denied': 'permission denied',
    'command_not_found': 'command not found',
    'module_not_found': 'modulenotfounderror',
    'connection_refused': 'connection refused',
}


def numeric(value):
    return value if type(value) in (int, float) else None


def category(tool, command):
    if tool in ('read', 'glob', 'grep'): return 'inspect_files'
    if tool in ('write', 'edit', 'apply_patch'): return 'write_or_edit'
    if tool in ('websearch', 'webfetch'): return 'public_search'
    if tool != 'bash': return 'other_tool'
    for label, pattern in (
        ('checkpoint', r'bin/checkpoint\b'),
        ('strategy', r'bin/strategy\b'),
        ('tests', r'\b(pytest|vitest|jest)\b|npm (run )?test\b'),
        ('runtime_setup', r'\bdocker\b|bin/(setup|reset)\b|npm (install|ci)\b'),
        ('inspect_files', r'\b(cat|sed|head|tail|rg|grep|find|ls)\b'),
    ):
        if re.search(pattern, command): return label
    return 'other_shell'


def analyze(stream):
    # Store only projected metadata. Raw inputs/results are used for fixed labels
    # and duplicate detection, never retained in the report. Reasoning text ignored.
    rows, seen, duplicates = [], set(), {}
    malformed = 0
    for line in stream:
        try: event = json.loads(line)
        except (ValueError, UnicodeError): malformed += 1; continue
        if not isinstance(event, dict): continue
        part = event.get('part')
        if not isinstance(part, dict) or part.get('type') != 'tool': continue
        state = part.get('state') or {}
        if state.get('status') not in ('completed', 'error'): continue
        identity = part.get('id') or part.get('callID')
        if identity and identity in seen: continue
        if identity: seen.add(identity)
        inputs = state.get('input') or {}
        tool = part.get('tool', '')
        command = inputs.get('command', '') if isinstance(inputs, dict) else ''
        if not isinstance(command, str): command = ''
        fingerprint = hashlib.sha256(json.dumps([tool, inputs], sort_keys=True).encode()).digest()
        prior = duplicates.get(fingerprint)
        duplicates.setdefault(fingerprint, len(rows) + 1)
        output = state.get('output', '')
        error = state.get('error', '')
        text = (str(output) + '\n' + str(error)).lower()
        timing = state.get('time') or {}
        start, end = numeric(timing.get('start')), numeric(timing.get('end'))
        metadata = state.get('metadata') or {}
        rows.append({
            'action': len(rows) + 1, 'category': category(tool, command),
            'status': state['status'],
            'started_at_ms': start, 'ended_at_ms': end,
            'seconds': max(0, end - start) / 1000 if start is not None and end is not None else None,
            'exit_code': numeric(metadata.get('exit', metadata.get('exitCode'))),
            'same_input_as_action': prior,
            'result_bytes': len(str(output).encode()),
            'result_error_markers': [k for k, marker in ERRORS.items() if marker in text],
        })
    return {
        'completed_tool_actions': len(rows), 'malformed_lines': malformed,
        'category_counts': dict(collections.Counter(r['category'] for r in rows)),
        'exact_repeated_inputs': sum(r['same_input_as_action'] is not None for r in rows),
        'result_error_marker_counts': dict(collections.Counter(k for r in rows for k in r['result_error_markers'])),
        'actions': rows,
        'limits': ['Repeated inputs may be legitimate verification; they are not automatically wasted work.',
                   'Error markers describe tool result strings, not verified root causes.',
                   'Categories are heuristic; other_shell remains unclassified.',
                   'This report cannot judge the semantic validity of a bug finding.'],
    }


def retain_member(member, stream, destination):
    """Retain authorized evidence only, never archive links or credentials."""
    name = member.name.removeprefix('./')
    parts = PurePosixPath(name).parts
    allowed = {'case', 'transcripts', 'attacks', 'gate-details', 'diagnostic-budgets'}
    if (not member.isfile() or len(parts) < 3 or parts[0] != CASE
            or parts[1] not in allowed or '..' in parts or name.startswith('/')
            or any(x in {'.casekey', '.env', 'auth.json', 'credentials.json', 'secrets.age'} for x in parts)):
        return
    if member.size > 64 * 1024 * 1024:
        raise ValueError('Evidence member exceeds size limit')
    data = stream.read()
    if parts[1] == 'transcripts':
        # Only emitted actions/results and visible answers; do not retain reasoning text.
        clean = []
        for line in data.splitlines():
            try: event = json.loads(line)
            except (ValueError, UnicodeError): continue
            if not isinstance(event, dict): continue
            part = event.get('part')
            if event.get('type') == 'reasoning' or not isinstance(part, dict) or part.get('type') not in {'tool','text','step-start','step-finish'}:
                continue
            clean.append(json.dumps(event).encode())
        data = b'\n'.join(clean) + b'\n'
    target = destination.joinpath(*parts[1:])
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with target.open('xb') as output:
        output.write(data)
    target.chmod(0o600)


def main(private_evidence=False):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if not sys.stdin.isatty():
        raise RuntimeError('Run interactively for private identity entry')
    archive = ROOT / 'sealed' / (CASE + '.checkpoint.tar.gz.age')
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != SHA:
            raise RuntimeError('Checkpoint differs from the audited generation')
    identity = getpass.getpass('Founder age identity (hidden; used only for this audit): ')
    if not re.fullmatch(r'AGE-SECRET-KEY-1[0-9A-Z]+', identity.strip()):
        raise RuntimeError('Expected an age identity, not a password')
    process = subprocess.Popen(['age', '-d', '-i', '/dev/stdin', str(archive)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
    def timeout(*_): raise TimeoutError('Audit exceeded ten minutes')
    previous = signal.signal(signal.SIGALRM, timeout)
    signal.alarm(600)
    result, report_counts, diagnostic = None, [], None
    private = Path(tempfile.mkdtemp(prefix='unbug-case-audit-')) if private_evidence else None
    published = False
    try:
        process.stdin.write((identity.strip() + '\n').encode()); process.stdin.close()
        del identity
        with tarfile.open(fileobj=process.stdout, mode='r|gz') as archive_stream:
            for member in archive_stream:
                name = member.name.removeprefix('./')
                if not member.isfile(): continue
                # Streaming tar members cannot be read twice. Keep only selected
                # bounded evidence in memory while producing both outputs.
                if private and len(PurePosixPath(name).parts) >= 3 and PurePosixPath(name).parts[1] in {'case','transcripts','attacks','gate-details','diagnostic-budgets'}:
                    import io
                    if member.size > 64 * 1024 * 1024: raise ValueError('Evidence member exceeds size limit')
                    data = archive_stream.extractfile(member).read()
                    retain_member(member, io.BytesIO(data), private)
                    read_member = lambda: io.BytesIO(data)
                else:
                    read_member = lambda: archive_stream.extractfile(member)
                if name == TRANSCRIPT:
                    if result is not None: raise RuntimeError('Duplicate transcript member')
                    result = analyze(read_member())
                elif (name.startswith(CASE + '/attacks/round-1-') and name.endswith('.json')
                      and '/' not in name.removeprefix(CASE + '/attacks/') and member.mtime >= START):
                    if member.size > 2_000_000: continue
                    try: report = json.load(read_member())
                    except ValueError: continue
                    report = classify(report)
                    if report is None: continue
                    report_counts.append({'mtime': member.mtime,
                        'blocking_count': len(report['blocking']),
                        'unfinished_validation_count': len(report['unfinished_validation']),
                        'non_blocking_count': len(report['non_blocking']) if isinstance(report.get('non_blocking'), list) else None,
                        'cheats_tried_count': len(report['cheats_tried']) if isinstance(report.get('cheats_tried'), list) else None,
                        'search_count': numeric(report.get('searches'))})
                elif name == CASE + '/diagnostic-budgets/attacker-1/status.json':
                    if member.size > 10000: continue
                    data = json.load(read_member())
                    diagnostic = {'mtime': member.mtime, 'from_this_attempt': member.mtime >= START,
                        'status': data.get('status') if data.get('status') in ('running','error','timeout','completed') else None,
                        **{k: numeric(data.get(k)) for k in ('runs','workers','limit_seconds','elapsed_seconds')}}
        # Drain ciphertext authentication to completion; a partial stream is no result.
        while process.stdout.read(1024 * 1024): pass
        if process.wait(timeout=10) != 0: raise RuntimeError('Archive authentication failed')
        if result is None: raise RuntimeError('Exact attempt transcript missing')
        result.update(case=CASE, worker='bx_n8sezr7t', checkpoint_sha256=SHA,
                      observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      current_attempt_reports=report_counts, diagnostic=diagnostic)
        if private: result['private_evidence_dir'] = str(private)
        target = EVIDENCE / 'stress-actions-audit.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, indent=2) + '\n'); temporary.replace(target)
        published = True
        print('Saved content-free audit: ' + str(target))
        if private: print('Private case audit evidence is ready; no key was saved.')
    finally:
        signal.alarm(0); signal.signal(signal.SIGALRM, previous)
        if process.poll() is None: process.kill()
        process.wait()
        process.stdout.close()
        if private and not published: shutil.rmtree(private)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-evidence', action='store_true', help='Retain authorized case/action evidence in a private local folder, without reasoning text')
    args = parser.parse_args()
    try: main(args.private_evidence)
    except BaseException as error:
        # No tracebacks or archive/command contents on any failure path.
        print('Audit did not complete (' + type(error).__name__ + '); no new report published.', file=sys.stderr)
        sys.exit(1)
