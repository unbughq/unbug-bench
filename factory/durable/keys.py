"""WP7: the key service (docs/designs/durable-execution-wp7.md).

Implements contract.KeyService. A scope key is 32 random bytes, generated once per scope
and stored only age-wrapped to the scoped VM restore recipient (approved by the founder on
2026-10-29) and the founder recipient. It is unwrapped through pipes into this process's
memory and nowhere else. Nothing here logs, and every error is fixed text plus the scope
ID, so no key reaches a log, an engine record or an exception.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import threading

import sqlalchemy as sa

from durable.contract import BATCH_ID, CASE_ID
from durable.ledger import _make_engine

RECIPIENT = re.compile(r"age1[0-9a-z]{58}")
FORMAT = b"unbug-durable/scope-key/v1"
AGE_TIMEOUT_S = 30


class KeyServiceError(RuntimeError):
    """Fixed text plus a scope ID only: never a key, a wrapped key or age's own output."""


_META = sa.MetaData()

SCOPE_KEYS = sa.Table(
    "durable_scope_key", _META,
    sa.Column("scope", sa.String(96), primary_key=True),
    sa.Column("wrapped", sa.LargeBinary, nullable=False),
)


def _scope(scope) -> str:
    if not (type(scope) is str and (CASE_ID.fullmatch(scope) or BATCH_ID.fullmatch(scope))):
        raise KeyServiceError("scope must be a case ID or a batch ID")
    return scope


def _age(args, data: bytes, failure: str) -> bytes:
    try:
        done = subprocess.run(args, input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=AGE_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        raise KeyServiceError(failure) from None
    if done.returncode != 0:
        raise KeyServiceError(failure)
    return done.stdout


def _check_identity_file(path: Path) -> None:
    try:
        st = os.lstat(path)
    except OSError:
        raise KeyServiceError("restore identity file is missing") from None
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o600:
        raise KeyServiceError("restore identity must be a regular 0600 file owned by the current user")


def recipients_from_repo(root) -> tuple[str, str]:
    """(restore recipient, founder recipient): the tracked public keys, read as launch.sh does."""
    root = Path(root)
    restore = (root / "factory/control-recipient.txt").read_text().strip()
    found = re.search(r'^FOUNDER_RECIPIENT = "(age1[a-z0-9]*)"', (root / "factory/run.py").read_text(), re.M)
    founder = found.group(1) if found else ""
    if not (RECIPIENT.fullmatch(restore) and RECIPIENT.fullmatch(founder)):
        raise KeyServiceError("tracked recipients are malformed")
    return restore, founder


class AgeKeyService:
    """contract.KeyService. `url` is the engine database; `restore_identity` is the path of
    the scoped VM restore identity on the control VM (installed by WP8 with the founder)."""

    def __init__(self, url: str, *, restore_recipient: str, founder_recipient: str, restore_identity):
        for r in (restore_recipient, founder_recipient):
            if not (type(r) is str and RECIPIENT.fullmatch(r)):
                raise KeyServiceError("recipients must be age X25519 recipients")
        self._recipients = (restore_recipient, founder_recipient)
        self._identity = Path(restore_identity)
        _check_identity_file(self._identity)
        public = _age(["age-keygen", "-y", str(self._identity)], b"", "restore identity is unreadable")
        if public.decode("ascii", "replace").strip() != restore_recipient:
            raise KeyServiceError("restore identity does not match the restore recipient")
        self._engine = _make_engine(url)
        _META.create_all(self._engine)
        self._keys: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        self._engine.dispose()

    def __repr__(self) -> str:
        return f"AgeKeyService({self._engine.url.render_as_string(hide_password=True)!r})"

    # ---- the protocol ------------------------------------------------------------------------

    def scope_key(self, scope: str) -> bytes:
        _scope(scope)
        with self._lock:
            key = self._keys.get(scope)
            if key is None:
                wrapped = self._stored(scope)
                if wrapped is None:
                    wrapped = self._create(scope)
                key = self._unwrap(scope, wrapped)
                self._keys[scope] = key
            return key

    def wrapped_key(self, scope: str) -> bytes:
        """The stored age ciphertext of the scope's key (safe to publish next to its archive)."""
        _scope(scope)
        wrapped = self._stored(scope)
        if wrapped is None:
            raise KeyServiceError(f"no key for scope {scope}")
        return wrapped

    # ---- internals ---------------------------------------------------------------------------

    def _stored(self, scope: str):
        try:
            with self._engine.connect() as conn:
                found = conn.execute(sa.select(SCOPE_KEYS.c.wrapped)
                                     .where(SCOPE_KEYS.c.scope == scope)).scalar_one_or_none()
        except sa.exc.SQLAlchemyError:
            raise KeyServiceError(f"could not read the key for scope {scope}") from None
        return None if found is None else bytes(found)

    def _create(self, scope: str) -> bytes:
        line = b" ".join((FORMAT, scope.encode(), base64.b64encode(secrets.token_bytes(32)))) + b"\n"
        args = ["age"]
        for r in self._recipients:
            args += ["-r", r]
        wrapped = _age(args, line, f"could not wrap the key for scope {scope}")
        try:
            with self._engine.begin() as conn:
                conn.execute(SCOPE_KEYS.insert().values(scope=scope, wrapped=wrapped))
        except sa.exc.IntegrityError:
            pass   # another process stored this scope first: its key wins, ours is dropped
        except sa.exc.SQLAlchemyError:
            raise KeyServiceError(f"could not store the key for scope {scope}") from None
        wrapped = self._stored(scope)
        if wrapped is None:
            raise KeyServiceError(f"could not store the key for scope {scope}")
        return wrapped

    def _unwrap(self, scope: str, wrapped: bytes) -> bytes:
        line = _age(["age", "-d", "-i", str(self._identity)], wrapped,
                    f"the key for scope {scope} does not open with the restore identity")
        parts = line.rstrip(b"\n").split(b" ")
        try:
            key = base64.b64decode(parts[2], validate=True) if len(parts) == 3 else b""
        except ValueError:
            key = b""
        if parts[:2] != [FORMAT, scope.encode()] or len(key) != 32:
            raise KeyServiceError(f"the stored key for scope {scope} is not a key of this scope")
        return key
