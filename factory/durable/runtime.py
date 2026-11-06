"""Control-side composition. Local storage/SQLite are for offline exercises only.

Configuration is a private JSON file: state_dir, pool_id, restore_identity,
restore_recipient, founder_recipient, application_version, and either local_objects
or r2 (account/access_key/secret_key/bucket). database_url comes from UNBUG_DURABLE_DSN
or database_url_file. output_retry_s defaults to 60; image defaults to bench-env.
Use application_version=durable.engine.APP_VERSION, pinned for this database lifetime.
For the supplied units state_dir must be /home/user/.unbug-durable. The configuration,
DSN file, restore identity and operator payload files must be owned regular 0600 files.
Worker model credentials must already exist on the chosen image.
"""
from __future__ import annotations

import fcntl
from contextlib import contextmanager
import json
import logging
import math
import os
from pathlib import Path
import stat
import threading

from durable.artifacts import AgeSealer, LocalObjects, R2Objects, SealedStore, check_scope
from durable.contract import ArtifactKind, Ref, assert_no_conductor, batch_spec_from_record
from durable.keys import AgeKeyService
from durable.ledger import SqlLedger
from durable.workers import BoatPool, PoolError, ReleaseStore, LABEL_CASE, LABEL_INTENT, _atomic_json, ownership_hash


LOG = logging.getLogger("durable.runtime")
SWEEP_INTERVAL_S = 300.0   # a stray sandbox is deleted within one interval of the pass that sees it


class RuntimeErrorCode(ValueError):
    pass


def private_bytes(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o600:
            raise RuntimeErrorCode("private_file_permissions")
        return stream.read()


@contextmanager
def runtime_lock(state):
    state = Path(state)
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = state.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
        raise RuntimeErrorCode("state_permissions")
    fd = os.open(state / "runtime.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeErrorCode("runtime_already_owned") from None
        yield lock


@contextmanager
def database_lock(config):
    import sqlalchemy as sa
    from durable.ledger import _make_engine
    if sa.engine.make_url(config["database_url"]).get_backend_name() != "postgresql":
        yield
        return
    engine = _make_engine(config["database_url"])
    try:
        with engine.connect() as conn:
            if not conn.execute(sa.text("SELECT pg_try_advisory_lock(719235184003)")).scalar():
                raise RuntimeErrorCode("database_already_owned")
            try:
                yield
            finally:
                conn.execute(sa.text("SELECT pg_advisory_unlock(719235184003)"))
    finally:
        engine.dispose()


def load_config(path):
    config = json.loads(private_bytes(path))
    config["database_url"] = os.environ.get("UNBUG_DURABLE_DSN") or private_bytes(config["database_url_file"]).decode().strip()
    return config


def objects_for(config):
    if ("local_objects" in config) == ("r2" in config):
        raise RuntimeErrorCode("choose_one_object_backend")
    return LocalObjects(config["local_objects"]) if "local_objects" in config else R2Objects(**config["r2"])


class PublishingStore(SealedStore):
    """Publish the dual-recipient wrapped key before acknowledging any ciphertext.

    A failed export fails publication; it never acknowledges an unrecoverable blob.
    The immutable key object is independent of nightly database backups.
    """
    def __init__(self, objects, keys):
        super().__init__(objects)
        self.keys = keys

    def put_sealed(self, scope, ref, ciphertext):
        check_scope(scope, ref)
        wrapped = self.keys.wrapped_key(scope)
        name = f"{self.prefix}/{scope}/scope-key.age"
        self.objects.put(name, wrapped)
        if self.objects.get(name) != wrapped:
            raise RuntimeErrorCode("wrapped_key_publication_failed")
        super().put_sealed(scope, ref, ciphertext)


class Runtime:
    def __init__(self, config):
        from durable.channel import BoatChannel
        from durable.executor import Executor
        from durable.engine import APP_VERSION, Engine
        assert_no_conductor(os.environ, {})
        if config["application_version"] != APP_VERSION:
            raise RuntimeErrorCode("application_version_mismatch")
        retry = config.get("output_retry_s", 60.0)
        if type(retry) not in (int, float) or not math.isfinite(retry) or retry < 0:
            raise RuntimeErrorCode("invalid_output_retry")
        self.config = config
        self.state = Path(config["state_dir"])
        self._ownership = runtime_lock(self.state)
        self.lock = self._ownership.__enter__()
        if (self.state / "cold-backup.json").exists():
            self._ownership.__exit__(None, None, None)
            raise RuntimeErrorCode("source_fenced_resume_or_restore_required")
        self.keys = self.ledger = self._database_ownership = None
        self.launched = False
        self._sweep_stop = threading.Event()
        try:
            ownership = database_lock(config)
            ownership.__enter__()
            self._database_ownership = ownership
            self.keys = AgeKeyService(config["database_url"], restore_recipient=config["restore_recipient"],
                                      founder_recipient=config["founder_recipient"], restore_identity=config["restore_identity"])
            self.ledger = SqlLedger(config["database_url"])
            self.sealer = AgeSealer()
            self.store = PublishingStore(objects_for(config), self.keys)
            self.releases = ReleaseStore(self.state / "releases")
            self.pool = BoatPool(self.state / "pool", self.releases, config["pool_id"], image=config.get("image", "bench-env"))
            self.channel = BoatChannel(self.store, keys=self.keys, sealer=self.sealer, output_retry_s=retry)
            self.executor = Executor(self.pool, self.channel, self.ledger, self.store, self.sealer, self.keys)
            self.engine = Engine(system_database_url=config["database_url"], executor=self.executor)
        except Exception:
            self.close()
            raise

    def launch(self):
        # No cleanup/release on reconciliation failure: journals retain ownership.
        if (self.state / "restored.json").exists():
            # Restored ownership is conservative: retain missing/uncertain records. Strays are
            # deleted only after a normal restore (the source stopped at the backup); a quarantined
            # one refuses them until its first clean launch, because its source may still own them.
            restored = json.loads((self.state / "restored.json").read_text())
            records = self.pool._records()
            ownership = {ownership_hash(case_id): record for case_id, record in records.items()}
            rows = self.pool._inventory()
            for row in rows:
                labels = self.pool._ours(row)
                if labels is None:
                    continue
                record = ownership.get(labels.get(LABEL_CASE))
                if record is None or not (record["worker"] == row["id"] or (
                        record["worker"] is None and record["intent"] is not None
                        and record["intent"] == labels.get(LABEL_INTENT))):
                    # A quarantined restore may hold sandboxes this archive cannot account for (the
                    # source may still run): refuse, even after reconcile, until one launch is clean.
                    # Otherwise this is a late create of ours: delete it.
                    if restored.get("quarantined") and not restored.get("launched"):
                        raise RuntimeErrorCode("restore_unclaimed_worker")
                    self.pool._delete_raw(row["id"])
            for case_id, record in records.items():
                worker = self.pool._find(rows, case_id, worker=record["worker"], intent=record["intent"])
                if worker is not None and record["worker"] != worker:
                    self.pool._write(case_id, {**record, "worker": worker})
            if restored.get("quarantined") and not restored.get("launched"):
                _atomic_json(self.state / "restored.json", {**restored, "launched": True})
            # Normal acquire/release reconciles each retained record before work. restored.json stays:
            # it holds the operator's reconcile attestation, and every start repeats this conservative check.
        else:
            self.pool.recover()
        self.launched = True  # destroy even if DBOS launch fails halfway through
        self.engine.launch()
        threading.Thread(target=self._sweep_pool, daemon=True).start()

    def _sweep_pool(self):
        while not self._sweep_stop.wait(SWEEP_INTERVAL_S):
            try:
                self.pool.sweep()
            except Exception as error:   # the next pass retries; log a fixed code, never the text
                LOG.warning("pool sweep failed: %s", error.reason if isinstance(error, PoolError) else "infra:sweep_failed")

    def prepare(self, scope, kind, plaintext):
        check_scope(scope, Ref("0" * 64, ArtifactKind(kind)))
        ref, ciphertext = self.sealer.seal(self.keys.scope_key(scope), ArtifactKind(kind), plaintext)
        self.store.put_sealed(scope, ref, ciphertext)
        return ref

    def start(self, spec_record, registry_record):
        spec = batch_spec_from_record(spec_record)
        registry = Ref(**registry_record)
        if registry.kind is not ArtifactKind.STATEMENT_REGISTRY:
            raise RuntimeErrorCode("registry_required")
        # Authenticate opaque inputs without coupling to the admission payload schema.
        for ref in (spec.inputs, registry):
            self.sealer.open(self.keys.scope_key(spec.batch_id), ref, self.store.get_sealed(spec.batch_id, ref))
        self.releases.bundle(spec.plumbing_version)
        self.engine.start_batch(spec, registry)
        return {"batch_id": spec.batch_id}

    def close(self):
        self._sweep_stop.set()
        try:
            if self.launched:
                self.engine.shutdown()
        finally:
            try:
                for component in (self.keys, self.ledger):
                    if component is not None:
                        component.close()
            finally:
                try:
                    if self._database_ownership is not None:
                        self._database_ownership.__exit__(None, None, None)
                finally:
                    self._ownership.__exit__(None, None, None)
