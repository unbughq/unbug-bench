#!/usr/bin/env python3
"""Unlock the three authorized sealed cases and fcde6b's G11 review locally.

Run: python3 tools/unlock_sealed_audit.py
Enter the founder's native age secret identity (AGE-SECRET-KEY-1...), not a
password, recipient, API key, or filename. One hidden terminal entry serves the
batch. Requires the age CLI. No model, network, worker, or cloud calls are made.

The private temporary output retains regular case/judge/calibration evidence,
including fixes, bench results, gate details, verdicts and history. All other
regular evidence is retained too, except agent state, raw logs, credentials,
key files and reasoning files. JSONL transcripts are projected to emitted tool
actions/results and text only; unsupported events are counted and omitted.
coverage.json records every retained/omitted path privately. The terminal's
manifest contains only fixed IDs, ciphertext hashes, output root and counts.
Limits: 256 MiB/member, 4 GiB total declared file bytes, 2,000,000 members/archive,
and ten minutes/batch; exceeding a limit fails the entire batch and removes it.
Original sealed artifacts are never modified. Treat retained content as data.
"""
import argparse
import collections
import getpass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import warnings

ROOT = Path(__file__).resolve().parents[1]
# Exact final generations only: checkpoints and other archives are not accepted.
ALLOWLIST = (
    ('case-20261017T120256Z-86b100', '5e7d716be35403e4f00979612255c6749679d8f5b5df3c8f150f6fc642dcc6f5'),
    ('case-20261017T125556Z-18681d', '90fa095feff8923aed90516356e7e975991ee9e342fb7b8f6176579b2c826a40'),
    ('case-20261017T114426Z-fcde6b', '7f936886fe56d736f09bcfdd4cbffd148b94b0c5e82458f2113f4ea6fa8b49c6'),
    ('g11-review-case-20261017T114426Z-fcde6b', '35de7b723d396e2e71ce09347e73173756f81ff2977d5f86d1ad8350d1387a66'),
)
MAX_FILE = 256 * 1024 * 1024
MAX_TOTAL = 4 * 1024 * 1024 * 1024
# Factory archives include restored workspaces, not only the small case tree.
# Bound entries separately from bytes; a legitimate saved case exceeds 100k.
MAX_MEMBERS = 2_000_000
SECRET_PATH = re.compile(r'(^|[._-])(credentials?|secrets?|tokens?|auth|private[-_]?key)([._-]|$)', re.I)
SECRET_CONTENT = re.compile(rb'AGE-SECRET-KEY-1|-----BEGIN (?:[A-Z0-9 ]*PRIVATE KEY|OPENSSH PRIVATE KEY)-----')
REASON_KEYS = {'reasoning', 'thinking', 'analysis', 'reasoning_content', 'reasoning_details',
               'redacted_thinking', 'reasoning_text', 'signature'}
EVIDENCE_GROUPS = {'case', 'transcripts', 'attacks', 'gate-details', 'diagnostic-budgets',
                   'bench-results', 'calibrators', 'fixes', 'evidence', 'reproductions', 'history'}


def scrub(value):
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k.lower() not in REASON_KEYS}
    if isinstance(value, list):
        return [scrub(v) for v in value if not (isinstance(v, dict) and v.get('type') in REASON_KEYS)]
    return value


def project_transcript(data, counts):
    output = []
    for line in data.splitlines():
        counts['transcript_lines'] += 1
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            counts['malformed_transcript_lines'] += 1
            continue
        if not isinstance(event, dict) or event.get('type') in REASON_KEYS:
            counts['omitted_transcript_events'] += 1
            continue
        part = event.get('part')
        kind = part.get('type') if isinstance(part, dict) else None
        if kind == 'tool':  # OpenCode
            clean = {k: part[k] for k in ('type', 'id', 'callID', 'tool', 'state') if k in part}
            clean = {'part': clean}
        elif kind == 'text' and isinstance(part.get('text'), str):
            clean = {'part': {'type': 'text', 'text': part['text']}}
        elif event.get('type') in {'item.started', 'item.updated', 'item.completed'}:
            item = event.get('item')
            if not isinstance(item, dict) or item.get('type') not in {
                    'agent_message', 'command_execution', 'file_change', 'mcp_tool_call', 'web_search'}:
                counts['omitted_transcript_events'] += 1
                continue
            clean = {'type': event['type'], 'item': item}  # Codex emitted items
        elif event.get('type') in {'assistant', 'user'}:
            message = event.get('message')
            blocks = message.get('content') if isinstance(message, dict) else None
            if not isinstance(blocks, list):
                counts['omitted_transcript_events'] += 1
                continue
            kept = []
            for block in blocks:  # Claude: omit thinking/redacted_thinking blocks.
                if not isinstance(block, dict):
                    continue
                if block.get('type') == 'text':
                    kept.append({'type': 'text', 'text': block.get('text', '')})
                elif block.get('type') == 'tool_use':
                    kept.append({k: block[k] for k in ('type', 'id', 'name', 'input') if k in block})
                elif block.get('type') == 'tool_result':
                    result = {k: block[k] for k in ('type', 'tool_use_id', 'is_error') if k in block}
                    content = block.get('content')
                    result['content'] = ([{'type': 'text', 'text': b.get('text', '')} for b in content
                                          if isinstance(b, dict) and b.get('type') == 'text']
                                         if isinstance(content, list) else content)
                    kept.append(result)
            if not kept:
                counts['omitted_transcript_events'] += 1
                continue
            clean = {'type': event['type'], 'message': {'content': kept}}
        elif event.get('type') == 'result' and isinstance(event.get('result'), str):
            clean = {k: event[k] for k in ('type', 'subtype', 'is_error', 'result') if k in event}
        elif event.get('type') in {'error', 'turn.failed'}:
            clean = {k: event[k] for k in ('type', 'message', 'error') if k in event}
        else:
            counts['omitted_transcript_events'] += 1
            continue
        counts['retained_transcript_events'] += 1
        output.append(json.dumps(scrub(clean), ensure_ascii=True).encode())
    return b'\n'.join(output) + (b'\n' if output else b'')


def omission(parts):
    lower = [x.lower() for x in parts]
    if 'agent-state' in lower:
        return 'agent_state'
    if 'logs' in lower or any(x.endswith('.log') for x in lower):
        return 'raw_logs'
    if any(x in {'.casekey', '.env', '.ssh', '.aws', '.gnupg', 'id_rsa', 'id_ed25519'}
           or x.startswith('.env.') or x.endswith(('.key', '.pem', '.p12', '.pfx', '.age'))
           or SECRET_PATH.search(x) for x in lower):
        return 'credential_or_key_path'
    if any(re.search(r'(^|[._-])(reasoning|thinking)([._-]|$)', x) for x in lower):
        return 'reasoning_file'
    return None


def write_private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('xb') as stream:
        os.chmod(path, 0o600)
        stream.write(data)


def extract_evidence(stream, archive_id, destination):
    counts = collections.Counter()
    inventory, seen = [], set()
    total = 0
    # No extract()/extractall(): archive names never select an existing path.
    expected_root = 'g11-audit' if archive_id.startswith('g11-review-') else archive_id
    with tarfile.open(fileobj=stream, mode='r|gz') as archive:
        for index, member in enumerate(archive, 1):
            if index > MAX_MEMBERS:
                raise ValueError('member limit')
            counts['archive_members'] += 1
            name = member.name.removeprefix('./')
            parts = PurePosixPath(name).parts
            if (not parts or name.startswith('/') or '\\' in name or '..' in parts
                    or any(ord(c) < 32 for c in name)):
                raise ValueError('unsafe member')
            if parts[0] != expected_root:
                raise ValueError('archive root mismatch')
            if member.isdir():
                continue
            if not member.isfile():
                counts['omitted_nonregular_files'] += 1
                inventory.append({'path': name, 'omitted': 'nonregular'})
                continue
            if len(parts) < 2 or name in seen:
                raise ValueError('duplicate or invalid member')
            seen.add(name)
            total += member.size
            if member.size < 0 or member.size > MAX_FILE or total > MAX_TOTAL:
                raise ValueError('size limit')
            counts['regular_files'] += 1
            reason = omission(parts[1:])
            if reason:
                counts['omitted_' + reason] += 1
                inventory.append({'path': name, 'omitted': reason})
                continue
            data = archive.extractfile(member).read(MAX_FILE + 1)
            if len(data) != member.size:
                raise ValueError('truncated member')
            if SECRET_CONTENT.search(data):
                counts['omitted_secret_content'] += 1
                inventory.append({'path': name, 'omitted': 'secret_content'})
                continue
            if 'transcripts' in parts and name.endswith('.jsonl'):
                data = project_transcript(data, counts)
                counts['projected_transcript_files'] += 1
            elif any('transcript' in p.lower() for p in parts):
                counts['omitted_unsupported_transcript_files'] += 1
                inventory.append({'path': name, 'omitted': 'unsupported_transcript'})
                continue
            write_private(destination.joinpath(*parts[1:]), data)
            counts['retained_files'] += 1
            counts['retained_bytes'] += len(data)
            group = parts[1] if parts[1] in EVIDENCE_GROUPS else 'other_evidence'
            counts['retained_' + group + '_files'] += 1
            inventory.append({'path': name, 'retained_bytes': len(data)})
    if not counts['retained_files']:
        raise ValueError('no evidence')
    # Keep the detailed inventory separate from case files to avoid collisions.
    return dict(counts), inventory


def verify_archives(root):
    """Hold the verified descriptors, so replacement paths cannot change inputs."""
    opened = []
    try:
        for archive_id, expected in ALLOWLIST:
            folder = root / 'sealed'
            card_path = folder / (archive_id + '.scorecard.json')
            archive_path = folder / (archive_id + '.tar.gz.age')
            if card_path.is_symlink() or archive_path.is_symlink():
                raise ValueError('linked input')
            card = json.loads(card_path.read_text())
            if (card.get('case') != archive_id.removeprefix('g11-review-')
                    or Path(card.get('archive', '')).name != archive_path.name
                    or card.get('sha256') != expected):
                raise ValueError('generation mismatch')
            stream = archive_path.open('rb')
            opened.append((archive_id, expected, stream))
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise ValueError('ciphertext mismatch')
            stream.seek(0)
        return opened
    except BaseException:
        for _, _, stream in opened:
            stream.close()
        raise


def decrypt_one(age, stream, identity, archive_id, destination):
    fd = stream.fileno()
    process = subprocess.Popen([age, '-d', '-i', '/dev/stdin', '/dev/fd/' + str(fd)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, pass_fds=(fd,))
    try:
        process.stdin.write((identity + '\n').encode('ascii'))
        process.stdin.close()
        coverage, inventory = extract_evidence(process.stdout, archive_id, destination)
        # Authentication must finish even when tar stops before the stream does.
        while process.stdout.read(1024 * 1024):
            pass
        if process.wait(timeout=10) != 0:
            raise RuntimeError('authentication failed')
        return coverage, inventory
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        if not process.stdin.closed:
            process.stdin.close()


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    opened = verify_archives(ROOT)  # ALL hashes checked before any prompt/decrypt.
    private = None
    success = False
    previous = {}
    stage = 'terminal_setup'
    current_archive = 'none'
    try:
        age = shutil.which('age')
        if not age or not sys.stdin.isatty():
            raise RuntimeError('interactive terminal and age required')
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            identity = getpass.getpass('Founder age secret identity (hidden, one entry for all four archives): ').strip()
        stage = 'identity_format'
        if not re.fullmatch(r'AGE-SECRET-KEY-1[0-9A-Z]{20,100}', identity):
            raise ValueError('native age identity required')
        def timeout(*_):
            raise TimeoutError('batch timeout')
        for sig in (signal.SIGALRM, signal.SIGTERM, signal.SIGHUP):
            previous[sig] = signal.signal(sig, timeout)
        signal.alarm(600)
        private = Path(tempfile.mkdtemp(prefix='unbug-sealed-audit-'))
        private.chmod(0o700)
        manifest = {'private_output_root': str(private), 'archives': []}
        inventories = {}
        for archive_id, digest, stream in opened:
            current_archive = archive_id
            stage = 'decrypt_and_extract'
            destination = private / archive_id
            destination.mkdir(mode=0o700)
            coverage, inventory = decrypt_one(age, stream, identity, archive_id, destination)
            inventories[archive_id] = inventory
            manifest['archives'].append({'case_id': archive_id, 'ciphertext_sha256': digest, 'coverage': coverage})
        del identity
        stage = 'write_manifest'
        write_private(private / 'coverage.json', (json.dumps(inventories, indent=2) + '\n').encode())
        write_private(private / 'manifest.json', (json.dumps(manifest, indent=2) + '\n').encode())
        print(json.dumps(manifest, indent=2))
        success = True
    except BaseException as error:
        # Only fixed labels may leave this process; never echo archive paths,
        # content, subprocess stderr, or the supplied identity.
        known = {'archive root mismatch', 'unsafe member', 'member limit',
                 'duplicate or invalid member', 'size limit', 'truncated member',
                 'no evidence', 'authentication failed', 'native age identity required',
                 'interactive terminal and age required', 'batch timeout'}
        label = str(error) if str(error) in known else type(error).__name__
        print(f'Unlock diagnostic: stage={stage}; archive={current_archive}; error={label}', file=sys.stderr)
        raise
    finally:
        signal.alarm(0)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        for _, _, stream in opened:
            stream.close()
        if private and not success:
            shutil.rmtree(private)


if __name__ == '__main__':
    class PrivateParser(argparse.ArgumentParser):
        def error(self, message):
            # argparse's default error includes argv: never echo a misplaced key.
            self.exit(2, 'Unlock accepts only --help; enter the identity at the hidden prompt.\n')
    parser = PrivateParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()  # No key arguments, environment lookup or arbitrary inputs.
    try:
        main()
    except BaseException:
        print('Unlock did not complete; no private output retained.', file=sys.stderr)
        sys.exit(1)
