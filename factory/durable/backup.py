"""Fenced cold restore points with non-activating lost-source data recovery.

Stop the controller, backup, then either resume (invalidates the restore point)
or hand over using the original fenced source-state directory. Quarantine mode
can recover data without that directory; it cannot resume cases or spend money.
A restored database must be pre-created and empty; activation remains a separate
operator run command. Workers can keep using their already-reserved grants.
"""
from __future__ import annotations

from functools import wraps
from contextlib import ExitStack
import datetime
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import uuid
import urllib.parse
import xml.etree.ElementTree as ET

import sqlalchemy as sa

from durable.engine import APP_VERSION
from durable.ledger import _make_engine
from durable.runtime import RuntimeErrorCode, objects_for, private_bytes, runtime_lock, database_lock
from durable.workers import _atomic_json


def _operator(fn):
    @wraps(fn)
    def checked(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except RuntimeErrorCode:
            raise
        except Exception:
            raise RuntimeErrorCode("backup_operation_failed") from None
    return checked


def _pg(config, command, data=None):
    url = sa.engine.make_url(config["database_url"])
    if url.get_backend_name() != "postgresql":
        raise RuntimeErrorCode("backup_requires_postgresql")
    if set(url.query) - {"sslmode", "host"}:
        raise RuntimeErrorCode("unsupported_backup_dsn_options")
    # Do not inherit libpq service/options that could change the target database.
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    for key, value in {"PGHOST": url.query.get("host", url.host), "PGPORT": url.port, "PGUSER": url.username,
                       "PGPASSWORD": url.password, "PGDATABASE": url.database,
                       "PGSSLMODE": url.query.get("sslmode")}.items():
        if value is not None:
            env[key] = str(value)
    result = subprocess.run(command, input=data, env=env, capture_output=True)
    if result.returncode:
        raise RuntimeErrorCode("backup_database_command_failed")
    return result.stdout


def _age(config, data, decrypt=False):
    private_bytes(config["restore_identity"])
    public = subprocess.run(["age-keygen", "-y", config["restore_identity"]], capture_output=True)
    if public.returncode or public.stdout.decode().strip() != config["restore_recipient"]:
        raise RuntimeErrorCode("backup_identity_mismatch")
    args = (["age", "-d", "-i", config["restore_identity"]] if decrypt else
            ["age", "-r", config["restore_recipient"], "-r", config["founder_recipient"]])
    done = subprocess.run(args, input=data, capture_output=True)
    if done.returncode:
        raise RuntimeErrorCode("backup_crypto_failed")
    return done.stdout


def _identity(config):
    if config["application_version"] != APP_VERSION:
        raise RuntimeErrorCode("application_version_mismatch")
    # Local objects are archived; remote objects must remain in their original bucket.
    backend = ({"local": True} if "local_objects" in config else
               {k: config["r2"].get(k) for k in ("account", "bucket", "endpoint", "region")})
    return {"version": APP_VERSION, "pool": config["pool_id"], "objects": backend,
            "recipients": [config["restore_recipient"], config["founder_recipient"]]}


def _files(root):
    if not root.exists():
        return {}
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise RuntimeErrorCode("backup_unsafe_file")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def _objects(config):
    if "local_objects" in config:
        return _files(Path(config["local_objects"]) / "durable")
    from durable.artifacts import sigv4_headers, EMPTY_SHA256
    objects = objects_for(config)
    token, seen, files = None, set(), {}
    tokens = set()
    while True:
        query = {"list-type": "2", "prefix": "durable/"}
        if token:
            query["continuation-token"] = token
        encoded = urllib.parse.urlencode(sorted(query.items()), quote_via=urllib.parse.quote)
        path = "/" + urllib.parse.quote(objects.bucket, safe="")
        headers = sigv4_headers("GET", objects.host, path, {}, EMPTY_SHA256,
                                access_key=objects._access, secret_key=objects._secret,
                                now=objects._clock(), region=objects.region, query=encoded)
        status, _, body = objects._transport("GET", objects.endpoint + path + "?" + encoded, headers, None)
        if status != 200:
            raise RuntimeErrorCode("backup_object_inventory_failed")
        root = ET.fromstring(body)
        if root.tag != "{http://s3.amazonaws.com/doc/2006-03-01/}ListBucketResult":
            raise RuntimeErrorCode("backup_object_inventory_failed")
        ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
        for row in root.findall("s:Contents", ns):
            key = row.findtext("s:Key", namespaces=ns)
            if not key or not key.startswith("durable/") or key in seen:
                raise RuntimeErrorCode("backup_object_inventory_failed")
            seen.add(key)
            # Immutable R2 objects already have off-host durability. Archive the
            # inventory, not a RAM-sized copy of every case/checkpoint ciphertext.
            files[key.removeprefix("durable/")] = None
        truncated = root.findtext("s:IsTruncated", namespaces=ns)
        if truncated == "false":
            return files
        next_token = root.findtext("s:NextContinuationToken", namespaces=ns)
        if truncated != "true" or not next_token or next_token in tokens:
            raise RuntimeErrorCode("backup_object_inventory_failed")
        tokens.add(next_token)
        token = next_token


@_operator
def backup(config, *, resume_after=False):
    identity = _identity(config)
    state = Path(config["state_dir"]).resolve()
    with runtime_lock(state), database_lock(config):
        fence = state / "cold-backup.json"
        if fence.exists():
            raise RuntimeErrorCode("source_already_fenced")
        token = uuid.uuid4().hex
        # Fence before taking the dump: even failed backup requires explicit resume.
        _atomic_json(fence, {"token": token, "retired": False})
        try:
            files = {"database.dump": _pg(config, ["pg_dump", "--format=custom"])}
            for name in ("pool", "releases"):
                files.update({name + "/" + k: v for k, v in _files(state / name).items()})
            objects_snapshot = _objects(config)
            files.update({"objects/" + k: v for k, v in objects_snapshot.items() if v is not None})
            manifest = {"format": 2, "remote_objects": [k for k, v in objects_snapshot.items() if v is None], "identity": identity, "source": str(state), "token": token,
                        "files": {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}}
            files["manifest.json"] = json.dumps(manifest, sort_keys=True).encode()
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as archive:
                for name, data in files.items():
                    info = tarfile.TarInfo(name)
                    info.mode, info.size = 0o600, len(data)
                    archive.addfile(info, io.BytesIO(data))
            encrypted = _age(config, buf.getvalue())
            key = f"backups/{token}.tar.age"
            objects = objects_for(config)
            objects.put(key, encrypted)
            if objects.get(key) != encrypted:
                raise RuntimeErrorCode("backup_publication_failed")
            return {"backup": key, "source_fenced": not resume_after}
        finally:
            # Only this invocation's fence may be invalidated, under the same lock.
            # A failed or killed handover backup still stays fenced by default.
            if resume_after and json.loads(private_bytes(fence)) == {"token": token, "retired": False}:
                fence.unlink()



@_operator
def resume(config):
    with runtime_lock(config["state_dir"]):
        fence = Path(config["state_dir"]) / "cold-backup.json"
        if json.loads(private_bytes(fence))["retired"]:
            raise RuntimeErrorCode("source_retired")
        fence.unlink()
    return {"source_resumable": True, "restore_point_invalidated": True}


@_operator
def reconcile(config, *, ownership=False, spending=False, cleared=()):
    """The founder's explicit exit from a quarantined restore, never automatic.

    Only a destination that restore(quarantine=True) completed qualifies: a source fence,
    a handed-over source and a normal restore have no such restored.json. It runs under
    the state and database locks, so no controller holds either. It cannot see a stale
    source elsewhere; that is what the attestation covers. The attestation is saved first
    and the fence removed second, so a crash between the two is finished by a repeat.
    An uncertain pool record (unresolved create or delete) refuses and is listed. The
    operator who checked it in Boat names it in `cleared`; only listed records qualify,
    and the names are saved in the attestation before any record is removed."""
    if ownership is not True or spending is not True:
        raise RuntimeErrorCode("reconcile_requires_ownership_and_spending_attestation")
    state = Path(config["state_dir"])
    with runtime_lock(state), database_lock(config):
        fence, saved = state / "cold-backup.json", state / "restored.json"
        if not saved.exists():
            raise RuntimeErrorCode("reconcile_requires_quarantined_restore")
        restored = json.loads(private_bytes(saved))
        if restored.get("quarantined") is not True or (
                fence.exists() and json.loads(private_bytes(fence)) != {"retired": True}):
            raise RuntimeErrorCode("reconcile_requires_quarantined_restore")
        if "reconciled" in restored and not fence.exists():
            return {"reconciled": True, "quarantine_released": True}
        from durable.workers import BoatPool, ReleaseStore
        pool = BoatPool(state / "pool", ReleaseStore(state / "releases"), config["pool_id"])
        uncertain = sorted(c for c, r in pool._records().items()
                           if r["deleting"] is not None or (r["worker"] is None and r["intent"] is not None))
        attested = restored.get("reconciled")
        cleared = attested["cleared"] if attested else sorted(set(cleared))   # a repeat finishes the saved list
        if not attested and not set(cleared) <= set(uncertain):
            raise RuntimeErrorCode("reconcile_cleared_record_not_uncertain")
        if remaining := [c for c in uncertain if c not in cleared]:
            raise RuntimeErrorCode("reconcile_pool_records_uncertain:" + ",".join(remaining))
        if not attested:
            _atomic_json(saved, {**restored, "reconciled": {
                "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "ownership": True, "spending": True, "cleared": cleared}})
        for case_id in cleared:
            pool._record_path(case_id).unlink(missing_ok=True)
        fence.unlink(missing_ok=True)
    return {"reconciled": True, "quarantine_released": True}


def _unpack(data):
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for member in archive:
            name = member.name
            parts = PurePosixPath(name).parts
            if (not member.isfile() or not parts or name != PurePosixPath(name).as_posix()
                    or name.startswith("/") or ".." in parts or name in files
                    or (name not in ("database.dump", "manifest.json")
                        and parts[0] not in ("pool", "releases", "objects"))):
                raise RuntimeErrorCode("backup_unsafe_archive")
            files[name] = archive.extractfile(member).read()
    manifest = json.loads(files.pop("manifest.json"))
    remote = manifest.get("remote_objects", [])
    if (not isinstance(remote, list) or not all(isinstance(n, str) and n == PurePosixPath(n).as_posix()
            and len(PurePosixPath(n).parts) == 2 and ".." not in PurePosixPath(n).parts and not n.startswith("/") for n in remote)
            or len(set(remote)) != len(remote)):
        raise RuntimeErrorCode("backup_unsafe_object_inventory")
    if (manifest["format"] not in (1, 2) or "database.dump" not in files or
            manifest["files"] != {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}):
        raise RuntimeErrorCode("backup_incomplete_or_corrupt")
    return manifest, files


def _private_directory(path):
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise RuntimeErrorCode("restore_unsafe_directory")
        return
    _private_directory(path.parent)
    path.mkdir(mode=0o700)


@_operator
def restore(config, archive_file, source_state=None, *, quarantine=False):
    identity = _identity(config)
    data = private_bytes(archive_file)
    manifest, files = _unpack(_age(config, data, decrypt=True))
    if manifest["identity"] != identity:
        raise RuntimeErrorCode("backup_identity_mismatch")
    source = Path(source_state or manifest["source"]).resolve()
    destination = Path(config["state_dir"]).absolute()
    if (not quarantine and (source_state is None or str(source) != manifest["source"])) or source == destination.resolve():
        raise RuntimeErrorCode("restore_requires_original_source_and_fresh_destination")
    if destination.exists() or destination.is_symlink():
        raise RuntimeErrorCode("restore_destination_exists")
    object_root = Path(config["local_objects"]).absolute() if "local_objects" in config else None
    if object_root and (object_root.exists() or object_root.is_symlink()):
        raise RuntimeErrorCode("restore_objects_destination_exists")
    with ExitStack() as stack:
        if not quarantine:
            stack.enter_context(runtime_lock(source))
        stack.enter_context(runtime_lock(destination))
        stack.enter_context(database_lock(config))
        _atomic_json(destination / "cold-backup.json", {"retired": True})
        fence = source / "cold-backup.json"
        if not quarantine and (not fence.exists() or json.loads(private_bytes(fence)) != {"token": manifest["token"], "retired": False}):
            raise RuntimeErrorCode("restore_point_invalidated")
        engine = _make_engine(config["database_url"])
        try:
            with engine.begin() as conn:
                # Keep the empty destination exclusive until transactional pg_restore.
                if conn.execute(sa.text("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE :system AND n.nspname <> :info"), {"system": "pg_%", "info": "information_schema"}).scalar():
                    raise RuntimeErrorCode("restore_database_not_empty")
            # A failed restore is rolled back, never cleaned with destructive DROP.
            _pg(config, ["pg_restore", "--exit-on-error", "--single-transaction", "--no-owner", "--no-privileges", "--dbname", sa.engine.make_url(config["database_url"]).database], files.pop("database.dump"))
        finally:
            engine.dispose()
        for name, content in files.items():
            parts = PurePosixPath(name).parts
            if parts[0] == "objects" and object_root is None:
                object_key = "durable/" + "/".join(parts[1:])
                objects_for(config).put(object_key, content)
                if objects_for(config).get(object_key) != content:
                    raise RuntimeErrorCode("restore_object_conflict")
                continue
            path = (object_root / "durable" / Path(*parts[1:]) if parts[0] == "objects"
                    else destination / name)
            _private_directory(path.parent)
            with path.open("xb") as stream:
                os.chmod(path, 0o600)
                stream.write(content)
        for directory in ("pool", "releases"):
            _private_directory(destination / directory)
        _validate(config, [n.removeprefix("objects/") for n in files if n.startswith("objects/")] + manifest.get("remote_objects", []))
        # Lost-host/stale archives can recover data, but never authorize spending.
        # Their destination remains fenced for external ownership/spend reconciliation.
        if not quarantine:
            _atomic_json(fence, {"token": manifest["token"], "retired": True})
        _atomic_json(destination / "restored.json", {"token": manifest["token"], "quarantined": quarantine})
        if not quarantine:
            (destination / "cold-backup.json").unlink()
    return {"restored": True, "activation_required": True, "quarantined": quarantine}


def _validate(config, object_names):
    from durable.keys import AgeKeyService, SCOPE_KEYS
    from durable.artifacts import AgeSealer
    from durable.contract import Ref, ArtifactKind
    from durable.workers import ReleaseStore, BoatPool, check_bundle
    engine = _make_engine(config["database_url"])
    try:
        inspector = sa.inspect(engine)
        if not all(inspector.has_table(name) for name in (
                "durable_scope_key", "durable_ledger_batch", "durable_ledger_attempt")):
            raise RuntimeErrorCode("restore_database_incomplete")
    finally:
        engine.dispose()
    keys = AgeKeyService(config["database_url"], restore_recipient=config["restore_recipient"],
                         founder_recipient=config["founder_recipient"], restore_identity=config["restore_identity"])
    try:
        with keys._engine.connect() as conn:
            scopes = conn.execute(sa.select(SCOPE_KEYS.c.scope)).scalars().all()
        published = {n.split("/", 1)[0] for n in object_names}
        for scope in scopes:
            keys.scope_key(scope)  # authenticate every restored wrapped key
            wrapped = objects_for(config).get(f"durable/{scope}/scope-key.age")
            if (wrapped is not None or scope in published) and wrapped != keys.wrapped_key(scope):
                raise RuntimeErrorCode("restore_wrapped_key_missing")
        for name in object_names:
            scope, filename = name.split("/")
            if scope not in scopes:
                raise RuntimeErrorCode("restore_unknown_scope")
            if filename == "scope-key.age":
                continue
            digest, kind, suffix = filename.split(".")
            if suffix != "age":
                raise RuntimeErrorCode("restore_invalid_object")
            AgeSealer().open(keys.scope_key(scope), Ref(digest, ArtifactKind(kind)),
                             objects_for(config).get("durable/" + name))
        releases = ReleaseStore(Path(config["state_dir"]) / "releases")
        for path in (releases.root / "bundles").glob("*.tgz"):
            check_bundle(releases.bundle(path.stem))
        for path in (releases.root / "benches").glob("*.json"):
            releases.register_bench(path.stem, releases.image_for(path.stem, "bench-env"))
        BoatPool(Path(config["state_dir"]) / "pool", releases, config["pool_id"])._records()
    finally:
        keys.close()
