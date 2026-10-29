"""Runner-owned public HTTP evidence; reviewers judge retained bytes, not retrieval claims."""
import datetime
import hashlib
import json
from pathlib import Path
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from run_validity import InvalidInfra

MAX_BYTES = 8 * 1024 * 1024


def fetch(url):
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise InvalidInfra('unsupported public retrieval URL')
    try:
        with urlopen(Request(url, headers={'User-Agent': 'unbug-bench-retrieval/1'}), timeout=30) as response:
            body = response.read(MAX_BYTES + 1)
            if response.status != 200 or not body or len(body) > MAX_BYTES:
                raise InvalidInfra('public response unavailable, empty or oversized')
            return {'url': url, 'final_url': response.url, 'status': 200}, body
    except HTTPError as error:
        error.close()
        if error.code in (404, 410):
            return {'url': url, 'final_url': error.url, 'status': error.code}, b''
        raise InvalidInfra('public HTTP access unavailable') from error
    except URLError as error:
        if isinstance(error.reason, socket.gaierror) and error.reason.errno == socket.EAI_NONAME:
            return {'url': url, 'final_url': url, 'status': 'dns_failure'}, b''
        raise InvalidInfra('public retrieval unavailable') from error
    except (OSError, ValueError) as error:
        raise InvalidInfra('public retrieval unavailable') from error


def retrieve(rows, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    receipts = []
    for index, row in enumerate(rows):
        receipt = {'url': row['url'], 'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'retrieved_from': 'live', 'live_failure': None, 'archive_available': None,
                   'archive_snapshot_url': None, 'responses': []}
        def retain(url):
            response, body = fetch(url)
            name = f'{index}-{len(receipt["responses"])}.body'
            (directory / name).write_bytes(body)
            receipt['responses'].append({**response, 'body': name, 'sha256': hashlib.sha256(body).hexdigest()})
            return response, body
        response, _ = retain(row['url'])
        if response['status'] != 200:
            receipt['live_failure'] = ('http_' + str(response['status']) if type(response['status']) is int
                                       else response['status'])
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
                    response, _ = retain(snapshot)
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


def load(directory, rows):
    """Validate the runner receipt and every retained byte before judgment or reuse."""
    directory = Path(directory)
    try:
        if directory.is_symlink(): raise ValueError()
        receipts = json.loads((directory / 'receipts.json').read_text())
        if not isinstance(receipts, list) or len(receipts) != len(rows): raise ValueError()
        now = datetime.datetime.now(datetime.timezone.utc)
        for receipt, row in zip(receipts, rows):
            at = datetime.datetime.fromisoformat(receipt['at'])
            if receipt['url'] != row['url'] or not at <= now < at + datetime.timedelta(hours=24): raise ValueError()
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
