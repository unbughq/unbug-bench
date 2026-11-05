#!/usr/bin/env python3
"""Private local operator socket; only contract records cross into DBOS.

Run --help for commands. All content/message/spec arguments are private file paths.
The service is the sole Engine owner; operator clients never launch recovery.
Backups are full PostgreSQL dumps plus local pool/release state, encrypted in RAM.
Restore automation, credential provisioning and live qualification are unsupported.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
from pathlib import Path
import signal
import socket
import socketserver
import subprocess
import sys
import tarfile
import threading
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from durable.contract import (ArtifactKind, BenchRelease, BoundRaised, FounderReply, PlumbingRelease,
                              Ref, Topic, to_record, BATCH_ID, CASE_ID)
from durable.runtime import Runtime, RuntimeErrorCode, load_config, objects_for, private_bytes


def dispatch(runtime, request):
    op = request["op"]
    if op == "prepare":
        kind = ArtifactKind(request["kind"])
        if kind not in (ArtifactKind.INPUTS, ArtifactKind.STATEMENT_REGISTRY, ArtifactKind.FOUNDER_RULING):
            raise RuntimeErrorCode("unsupported_preparation")
        return to_record(runtime.prepare(request["scope"], kind, base64.b64decode(request["content"], validate=True)))
    if op == "start":
        return runtime.start(request["spec"], request["registry"])
    if op == "install":
        digest = runtime.releases.put_bundle(base64.b64decode(request["content"], validate=True))
        runtime.releases.register_bench(request["bench_version"], request["image"])
        return {"plumbing_version": digest}
    if op in ("bench_release", "plumbing_release", "bound_raised"):
        if not BATCH_ID.fullmatch(request["destination"]):
            raise RuntimeErrorCode("invalid_batch")
        cls = {"bench_release": BenchRelease, "plumbing_release": PlumbingRelease, "bound_raised": BoundRaised}[op]
        runtime.engine.send(request["destination"], Topic(op), cls(**request["payload"]))
        return {"sent": True}
    if op == "founder_reply":
        if not CASE_ID.fullmatch(request["destination"]):
            raise RuntimeErrorCode("invalid_case")
        payload = dict(request["payload"])
        if payload.get("ruling") is not None:
            payload["ruling"] = Ref(**payload["ruling"])
        runtime.engine.reply(request["destination"], FounderReply(**payload))
        return {"sent": True}
    if op in ("status", "report"):
        from durable.report import load_cards, scorecard
        if not BATCH_ID.fullmatch(request["batch"]):
            raise RuntimeErrorCode("invalid_batch")
        return scorecard(request["batch"], load_cards(request["batch"]))
    raise RuntimeErrorCode("unknown_operation")


# A private directory and socket restrict access to the service user. One request per
# connection; exceptions never serialize paths, credentials, plaintext or tracebacks.
class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            self.connection.settimeout(120)
            request = json.loads(self.rfile.readline(64 * 1024 * 1024))
            response = {"ok": True, "result": dispatch(self.server.runtime, request)}
        except Exception:
            response = {"ok": False, "error": "operator_request_failed"}
        self.wfile.write(json.dumps(response).encode() + b"\n")


def serve(config):
    from sqlalchemy.engine import make_url
    if make_url(config["database_url"]).get_backend_name() != "postgresql":
        raise RuntimeErrorCode("service_requires_postgresql")
    runtime = Runtime(config)
    path = runtime.state / "operator.sock"
    try:
        runtime.launch()  # real pool recovery completes before DBOS.launch
        path.unlink(missing_ok=True)
        with socketserver.UnixStreamServer(str(path), Handler) as server:
            os.chmod(path, 0o600)
            server.runtime = runtime
            def stop(_signum, _frame):
                threading.Thread(target=server.shutdown, daemon=True).start()
            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            server.serve_forever(poll_interval=0.25)
    finally:
        path.unlink(missing_ok=True)
        runtime.close()


def backup(config):
    from sqlalchemy.engine import make_url
    url = make_url(config["database_url"])
    if url.get_backend_name() != "postgresql":
        raise RuntimeErrorCode("backup_requires_postgresql")
    env = {**os.environ}
    for key, value in {"PGHOST": url.host, "PGPORT": url.port, "PGUSER": url.username,
                       "PGPASSWORD": url.password, "PGDATABASE": url.database}.items():
        if value is not None:
            env[key] = str(value)
    # Connection options that pg_dump cannot faithfully reproduce must fail closed.
    if set(url.query) - {"sslmode"}:
        raise RuntimeErrorCode("unsupported_backup_dsn_options")
    if "sslmode" in url.query:
        env["PGSSLMODE"] = url.query["sslmode"]
    dump = subprocess.run(["pg_dump", "--format=custom"], env=env, capture_output=True, check=True).stdout
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as archive:
        info = tarfile.TarInfo("database.dump")
        info.size = len(dump)
        archive.addfile(info, io.BytesIO(dump))
        # Journals are individually atomic, but DB and files are not a single snapshot.
        # Recovery must reconcile inventory after restore; wrapped keys are exported
        # separately on every artifact publication.
        for name in ("pool", "releases"):
            path = Path(config["state_dir"]) / name
            if path.exists():
                archive.add(path, arcname=name)
    encrypted = subprocess.run(["age", "-r", config["restore_recipient"], "-r", config["founder_recipient"]],
                               input=buf.getvalue(), capture_output=True, check=True).stdout
    key = f"backups/{uuid.uuid4().hex}.tar.age"
    objects = objects_for(config)
    objects.put(key, encrypted)
    if objects.get(key) != encrypted:
        raise RuntimeErrorCode("backup_publication_failed")
    return {"backup": key}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="owned regular 0600 JSON configuration file")
    commands = parser.add_subparsers(dest="op", required=True)
    for name in ("run", "backup"):
        commands.add_parser(name)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("scope")
    prepare.add_argument("kind", choices=[k.value for k in (ArtifactKind.INPUTS, ArtifactKind.STATEMENT_REGISTRY, ArtifactKind.FOUNDER_RULING)])
    prepare.add_argument("content_file")
    start = commands.add_parser("start")
    start.add_argument("spec_file")
    start.add_argument("registry_file")
    install = commands.add_parser("install")
    install.add_argument("content_file", help="existing worker release bundle")
    install.add_argument("bench_version")
    install.add_argument("image")
    for name in ("status", "report"):
        commands.add_parser(name).add_argument("batch")
    for name in ("bench_release", "plumbing_release", "bound_raised", "founder_reply"):
        p = commands.add_parser(name)
        p.add_argument("destination")
        p.add_argument("payload_file")
    args = vars(parser.parse_args(argv))
    try:
        config = load_config(args.pop("config"))
        if args["op"] == "run":
            serve(config)
            return 0
        if args["op"] == "backup":
            result = backup(config)
        else:
            for field in ("spec", "registry", "payload"):
                if field + "_file" in args:
                    args[field] = json.loads(private_bytes(args.pop(field + "_file")))
            if "content_file" in args:
                args["content"] = base64.b64encode(private_bytes(args.pop("content_file"))).decode()
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(120)
                client.connect(str(Path(config["state_dir"]) / "operator.sock"))
                client.sendall(json.dumps(args).encode() + b"\n")
                with client.makefile("rb") as stream:
                    response = json.loads(stream.readline(64 * 1024 * 1024))
                if not response["ok"]:
                    raise RuntimeErrorCode("operator_request_failed")
                result = response["result"]
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print("durable_operator_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
