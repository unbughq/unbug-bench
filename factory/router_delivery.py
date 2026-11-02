"""Pack shared router credentials into the existing memory-only worker delivery."""
import base64
import io
import json
import os
from pathlib import Path
import ssl
import stat
import sys
import tarfile
from urllib.parse import urlsplit
from model_router import router_request

DEFAULT = Path('/run/unbug-bench/router-client.json')
NAMES = ('factory-router-url', 'factory-router-token', 'factory-router-ca.pem')
LIMIT = 16 * 1024 * 1024


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError()
        result[key] = value
    return result


def read_config(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError()
        raw = stream.read(65537)
    if len(raw) > 65536: raise ValueError()
    value = json.loads(raw, object_pairs_hook=unique)
    if set(value) != {'schema', 'url', 'token', 'ca_pem'} or type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError()
    if any(not isinstance(value[k], str) or not value[k] for k in ('url', 'token', 'ca_pem')): raise ValueError()
    url = urlsplit(value['url'])
    if (url.scheme != 'https' or not url.hostname or url.username is not None or url.password is not None
            or url.query or url.fragment or any(ord(c) <= 32 or ord(c) == 127 for c in value['url'])):
        raise ValueError()
    if any(not 33 <= ord(c) <= 126 for c in value['token']): raise ValueError()
    ssl.create_default_context().load_verify_locations(cadata=value['ca_pem'])
    return value


def pack(encoded, path):
    config = read_config(path)
    status = router_request(config['url'], config['token'], 'status', {}, ca_pem=config['ca_pem'])
    if not {'observed_at', 'health', 'leases', 'paid'} <= status.keys(): raise ValueError()
    raw = base64.b64decode(encoded, validate=False)
    if len(raw) > LIMIT: raise ValueError()
    output = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(raw)) as source, tarfile.open(fileobj=output, mode='w') as target:
        seen = set()
        for member in source:
            name = member.name.removeprefix('./')
            if (not member.isfile() or '/' in name or name.startswith('.') or name in seen or name in NAMES):
                raise ValueError()
            seen.add(name)
            target.addfile(member, source.extractfile(member))
        for name, field in zip(NAMES, ('url', 'token', 'ca_pem')):
            data = config[field].encode()
            member = tarfile.TarInfo(name); member.size = len(data); member.mode = 0o600
            target.addfile(member, io.BytesIO(data))
    return base64.b64encode(output.getvalue())


def main():
    try:
        encoded = sys.stdin.buffer.read(LIMIT + 1)
        if len(encoded) > LIMIT: raise ValueError()
        result = pack(encoded, Path(os.environ.get('UNBUG_ROUTER_CLIENT_FILE', DEFAULT)))
    except Exception:
        print('router delivery refused', file=sys.stderr)
        return 1
    sys.stdout.buffer.write(result)
    return 0


if __name__ == '__main__': sys.exit(main())
