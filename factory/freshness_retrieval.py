"""Runner-owned public HTTP evidence; reviewers judge retained bytes, not retrieval claims."""
import datetime
import hashlib
import json
from pathlib import Path
import re
import socket
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from run_validity import InvalidInfra

MAX_BYTES = 8 * 1024 * 1024


def fetch(url, *, deadline=None, access=False):
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise InvalidInfra('unsupported public retrieval URL')
    timeout = 30 if deadline is None else min(30, deadline - time.monotonic())
    if timeout <= 0: raise InvalidInfra('retrieval deadline')
    try:
        with urlopen(Request(url, headers={'User-Agent': 'unbug-bench-retrieval/1'}), timeout=timeout) as response:
            body = response.read(MAX_BYTES + 1)
            # cae763 (17 Nov): a WAF challenge answers 202 with an empty body every time. Under access it is
            # the page's answer (a wall, see access_failure), not transport to retry until the deadline.
            if access and response.status != 200:
                return {'url': url, 'final_url': response.url, 'status': response.status}, body[:MAX_BYTES]
            if response.status != 200 or not body or len(body) > MAX_BYTES:
                raise InvalidInfra('public response unavailable, empty or oversized')
            return {'url': url, 'final_url': response.url, 'status': 200}, body
    except HTTPError as error:
        body = error.read(MAX_BYTES + 1) if access else b''
        error.close()
        if access and error.code not in (404, 410):
            return {'url': url, 'final_url': error.url, 'status': error.code}, body[:MAX_BYTES]
        if error.code in (404, 410):
            return {'url': url, 'final_url': error.url, 'status': error.code}, b''
        raise InvalidInfra('public HTTP access unavailable') from error
    except URLError as error:
        if isinstance(error.reason, socket.gaierror) and error.reason.errno == socket.EAI_NONAME:
            return {'url': url, 'final_url': url, 'status': 'dns_failure'}, b''
        if access: return {'url': url, 'final_url': url, 'status': 'network_error'}, b''
        raise InvalidInfra('public retrieval unavailable') from error
    except (OSError, ValueError) as error:
        if access: return {'url': url, 'final_url': url, 'status': 'network_error'}, b''
        raise InvalidInfra('public retrieval unavailable') from error


def retrieve(rows, directory, *, archive=True, deadline=None, access=False):
    directory = Path(directory)
    if access and directory.exists():
        directory.rename(directory.with_name(directory.name + "-superseded-" + uuid.uuid4().hex))
    directory.mkdir(parents=True, exist_ok=True)
    receipts = []
    for index, row in enumerate(rows):
        receipt = {'url': row['url'], 'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'retrieved_from': 'live', 'live_failure': None, 'archive_available': None,
                   'archive_snapshot_url': None, 'responses': []}
        def retain(url):
            response, body = (fetch(url, deadline=deadline, access=access) if access else fetch(url))
            name = f'{index}-{len(receipt["responses"])}.body'
            (directory / name).write_bytes(body)
            receipt['responses'].append({**response, 'body': name, 'sha256': hashlib.sha256(body).hexdigest()})
            return response, body
        response, _ = retain(row['url'])
        if response['status'] != 200:
            receipt['retrieved_from'] = 'none'
            receipt['live_failure'] = ('http_' + str(response['status']) if type(response['status']) is int
                                       else response['status'])
            if not archive:
                receipts.append(receipt)
                continue
            response, body = retain('https://archive.org/wayback/available?url=' + quote(row['url'], safe=''))
            try:
                payload = json.loads(body)
                snapshots = payload['archived_snapshots']
                if response['status'] != 200 or not isinstance(snapshots, dict): raise ValueError()
                closest = snapshots.get('closest')
                if closest is None and snapshots: raise ValueError()
                if closest is not None:
                    snapshot = closest['url']
                    if (closest.get('available') is not True or str(closest.get('status')) != '200'
                            or not re.fullmatch(r'https?://web\.archive\.org/web/[0-9]{14}(?:id_)?/'
                                                + re.escape(row['url']), snapshot)):
                        raise ValueError()
                    raw_snapshot = re.sub(r'(/web/[0-9]{14})(?:id_)?/', r'\1id_/', snapshot) if access else snapshot
                    response, _ = retain(raw_snapshot)
                    if response['status'] != 200: raise ValueError()
                    receipt.update(retrieved_from='archive', archive_available=True,
                                   archive_snapshot_url=snapshot)
                else:
                    receipt.update(retrieved_from='none', archive_available=False)
            except (ValueError, TypeError, KeyError) as error:
                raise InvalidInfra('archive retrieval inconclusive') from error
        receipts.append(receipt)
    (directory / 'receipts.json').write_text(json.dumps(receipts, sort_keys=True))
    return receipts


def load(directory, rows, *, check_age=True):
    """Validate receipts and bytes; completed terminal proof may disable cache expiry."""
    directory = Path(directory)
    try:
        if directory.is_symlink(): raise ValueError()
        receipts = json.loads((directory / 'receipts.json').read_text())
        if not isinstance(receipts, list) or len(receipts) != len(rows): raise ValueError()
        now = datetime.datetime.now(datetime.timezone.utc) if check_age else None
        for receipt, row in zip(receipts, rows):
            at = datetime.datetime.fromisoformat(receipt['at'])
            if receipt['url'] != row['url'] or at.tzinfo is None: raise ValueError()
            if check_age and not at <= now < at + datetime.timedelta(hours=24): raise ValueError()
            if not receipt['responses']: raise ValueError()
            for response in receipt['responses']:
                name = response['body']
                if Path(name).name != name: raise ValueError()
                path = directory / name
                if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != response['sha256']:
                    raise ValueError()
        return receipts
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise InvalidInfra('missing or changed runner retrieval evidence') from error


def digest(receipts):
    return hashlib.sha256(json.dumps(receipts, sort_keys=True).encode()).hexdigest()


def agrees(answer, receipt):
    source = receipt['retrieved_from']
    return (answer.get('retrieved_from', 'live') == source
            and answer.get('live_failure') == receipt['live_failure']
            and (source == 'live' or (answer.get('archive_checked') is True
                 and answer.get('archive_available') == receipt['archive_available']
                 and answer.get('archive_snapshot_url') == receipt['archive_snapshot_url'])))



def access_failure(receipt):
    failure = receipt.get('live_failure')
    return failure == 'network_error' or bool(isinstance(failure, str) and
        re.fullmatch(r'http_(?:202|401|403|451|429|5[0-9]{2})', failure))


def judgment_projection(receipts):
    """Semantic content identity, independent of clocks and replay/bot-wall noise."""
    rows = []
    for receipt in receipts:
        source = receipt['retrieved_from']
        selected = receipt['archive_snapshot_url']
        raw = re.sub(r'(/web/[0-9]{14})(?:id_)?/', r'\1id_/', selected) if selected else None
        content = [{k: response[k] for k in ('url', 'final_url', 'sha256')}
                   for response in receipt['responses'] if response['status'] == 200 and
                   (source == 'live' and response['url'] == receipt['url'] or
                    source == 'archive' and response['url'] == raw)]
        rows.append({**{k: receipt[k] for k in ('url', 'retrieved_from', 'live_failure',
                    'archive_available', 'archive_snapshot_url')}, 'content': content})
    return rows


def judgment_digest(receipts):
    return digest(judgment_projection(receipts))
