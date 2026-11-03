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
from types import SimpleNamespace

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


class _JobParser(argparse.ArgumentParser):
    def error(self, message): raise ValueError()


def job_parser():
    """run.py's role flags only (run.py is unpinned worker code); other job flags are ignored."""
    p = _JobParser(add_help=False)
    p.add_argument('--rotation-slot', type=int, choices=range(1, 9))
    p.add_argument('--rotation-table', choices=['rotation.json', 'rotation-3writers.json'])
    for flags in (('--builder', '--writer'), ('--attacker', '--stress-tester'), ('--reviewer1',), ('--reviewer2',),
                  ('--strong-calibrator', '--pilot')):
        p.add_argument(*flags, default=None)
    p.add_argument('--easy-calibrator', default='opencode/glm-5.3-flash-free')
    for role in ('builder', 'attacker', 'reviewer1', 'reviewer2', 'strong-calibrator', 'easy-calibrator'):
        p.add_argument('--' + role + '-effort', default=None)
    return p


def codex_role(job_args):
    """True when the resolved roles include codex/, or when the args do not resolve."""
    try:
        import model_runtime
        a, _ = job_parser().parse_known_args(job_args)
        # As practice_preflight.roles(): a factory job skips the free-model cohort, which never changes a Codex role.
        a.batch_release_sha256 = 'resolution-only'
        c = SimpleNamespace(args=a, card={})
        model_runtime.select_models(c, log=lambda *_: None)
        return any(role['model'].startswith('codex/') for role in c.card['roles'].values())
    except Exception:
        return True


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    job = None
    if '--job-args' in argv:
        index = argv.index('--job-args')
        if argv[index + 1:index + 2] != ['--']: return 2
        argv, job = argv[:index], argv[index + 2:]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ttl-hours', required=True, type=float)
    args = parser.parse_args(argv)
    if job is not None and not codex_role(job):
        sys.stdin.buffer.read()  # drain the bundle pipe; no Codex role needs this login
        return 0
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
