#!/usr/bin/env python3
"""Private local operator socket; only contract records cross into DBOS.

Run --help for commands. All content/message/spec arguments are private file paths.
The service is the sole Engine owner; operator clients never launch recovery.
Backups are full PostgreSQL dumps plus local pool/release state, encrypted in RAM.
Cold backup fences the stopped source until explicit resume or restore.
Restore requires the fenced source state and a fresh destination configuration.
A quarantined restore starts only after `reconcile` records the operator's attestation.
`publish` writes the allowlisted scorecard to the object store; nothing else is published.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import signal
import socket
import socketserver
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from durable.contract import (ArtifactKind, BenchRelease, BoundRaised, FounderReply, PlumbingRelease,
                              Ref, Topic, to_record, BATCH_ID, CASE_ID)
from durable.runtime import Runtime, RuntimeErrorCode, load_config, private_bytes


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
    if op == "publish":
        from durable.classify import PUBLISHED_REASONS
        from durable.report import load_cards, publish
        if not BATCH_ID.fullmatch(request["batch"]):
            raise RuntimeErrorCode("invalid_batch")
        return publish(runtime.store.objects, request["batch"], load_cards(request["batch"]), PUBLISHED_REASONS)
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
        except Exception as error:
            code = "batch_already_finished" if isinstance(error, RuntimeErrorCode) and str(error) == "batch_already_finished" else "operator_request_failed"
            response = {"ok": False, "error": code}
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


from durable.backup import backup, reconcile, restore, resume


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="owned regular 0600 JSON configuration file")
    commands = parser.add_subparsers(dest="op", required=True)
    commands.add_parser("run")
    commands.add_parser("backup").add_argument("--resume-after", action="store_true", help="invalidate this restore point and resume the source after a scheduled backup")
    commands.add_parser("resume", help="invalidate the cold restore point and allow source startup")
    restore_parser = commands.add_parser("restore", help="restore into the fresh config destination; source remains retired")
    restore_parser.add_argument("archive_file", help="owned 0600 encrypted archive downloaded from backup storage")
    restore_parser.add_argument("--source-state")
    restore_parser.add_argument("--quarantine", action="store_true", help="recover data only; destination stays fenced for reconciliation")
    reconcile_parser = commands.add_parser("reconcile", help="release a quarantined restore after external ownership and spending were reconciled")
    reconcile_parser.add_argument("--ownership-reconciled", action="store_true", required=True, help="attest every external worker and the source controller were reconciled")
    reconcile_parser.add_argument("--spending-reconciled", action="store_true", required=True, help="attest all spending since the archive was reconciled")
    reconcile_parser.add_argument("--cleared-record", action="append", default=[], help="case id of an uncertain pool record already checked in Boat; repeat per record")
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
    for name in ("status", "report", "publish"):
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
            result = backup(config, resume_after=args["resume_after"])
        elif args["op"] == "restore":
            result = restore(config, args["archive_file"], args["source_state"], quarantine=args["quarantine"])
        elif args["op"] == "reconcile":
            result = reconcile(config, ownership=args["ownership_reconciled"], spending=args["spending_reconciled"], cleared=args["cleared_record"])
        elif args["op"] == "resume":
            result = resume(config)
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
                    raise RuntimeErrorCode("batch_already_finished" if response.get("error") == "batch_already_finished" else "operator_request_failed")
                result = response["result"]
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        print(str(error) if isinstance(error, RuntimeErrorCode) else "durable_operator_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
