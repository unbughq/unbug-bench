"""Offline lifetime guard for the shared Codex 0.162.1 login. Never refresh here."""
import argparse
import base64
import copy
import datetime
import json
import math
import re
import sys
import tarfile
import time

REFRESH_WINDOW = 300  # login/src/auth/manager.rs at rust-v0.162.1
LAUNCH_MARGIN = 1800  # provisioning, clock skew and collection
REFUSED = 'codex_login_expired: refresh with bin/setup-secrets codex; login must cover worker TTL plus margin'


def validate(auth, seconds, *, now=None, margin=LAUNCH_MARGIN):
    """JWT expiry takes precedence over the CLI's eight-day last_refresh fallback.

    An opaque/malformed token cannot prove a safe lifetime, even when its
    last_refresh is recent. Fail closed without including credential/parser text.
    This decodes metadata only; it does not authenticate the token remotely.
    """
    try:
        if not math.isfinite(seconds) or seconds <= 0: raise ValueError()
        if auth.get('auth_mode') not in (None, 'chatgpt', 'chatgptAuthTokens'): raise ValueError()
        # 0.162.1 get_token_data also requires last_refresh to be present.
        refreshed = datetime.datetime.fromisoformat(auth['last_refresh'].replace('Z', '+00:00'))
        if refreshed.tzinfo is None: raise ValueError()
        token = auth['tokens']['access_token']
        parts = token.split('.')
        if len(parts) != 3 or not parts[0] or not parts[2] or not re.fullmatch(r'[A-Za-z0-9_-]+', parts[1]):
            raise ValueError()
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + '=' * (-len(parts[1]) % 4)))
        expires = payload['exp']
        # The pinned parser uses Option<i64>, not arbitrary JSON numbers.
        if type(expires) is not int: raise ValueError()
        datetime.datetime.fromtimestamp(expires, datetime.timezone.utc)
        if expires <= (time.time() if now is None else now) + seconds + margin + REFRESH_WINDOW:
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise ValueError(REFUSED) from None


def worker_auth(auth):
    """Use pinned CLI external-token mode: no proactive or 401 OAuth refresh.

    Preserve account/id metadata, remove refresh authority from per-call scratch.
    The host alone owns the original bundle; no rotated token is thrown away.
    """
    validate(auth, 1, margin=60)
    result = copy.deepcopy(auth)
    result['auth_mode'] = 'chatgptAuthTokens'
    result['OPENAI_API_KEY'] = None
    result['tokens']['refresh_token'] = ''
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ttl-hours', required=True, type=float)
    args = parser.parse_args()
    try:
        with tarfile.open(fileobj=sys.stdin.buffer, mode='r|*') as archive:
            matches = [json.load(archive.extractfile(m)) for m in archive
                       if m.name == 'codex-auth.json' and m.isfile()]
        if len(matches) != 1: raise ValueError()
        validate(matches[0], args.ttl_hours * 3600)
    except (ValueError, TypeError, KeyError, OSError, tarfile.TarError, EOFError):
        print(REFUSED, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__': sys.exit(main())
