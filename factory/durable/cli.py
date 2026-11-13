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
import logging
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
from durable.runtime import Runtime, RuntimeErrorCode, check_role_swap, load_config, private_bytes


def dispatch(runtime, request):
    op = request["op"]
    if op == "prepare":
        kind = ArtifactKind(request["kind"])
        if kind is ArtifactKind.CASE_SNAPSHOT:
            # A rewrapped legacy checkpoint is too large for one socket line: read it on this host.
            # Its bytes stay age ciphertext to the worker statement key; the controller cannot open them.
            content = private_bytes(request["content_path"])
            if not content.startswith(b"age-encryption.org/v1\n"):
                raise RuntimeErrorCode("import_invalid")
            return to_record(runtime.prepare(request["scope"], kind, content))
        if kind not in (ArtifactKind.INPUTS, ArtifactKind.STATEMENT_REGISTRY, ArtifactKind.FOUNDER_RULING):
            raise RuntimeErrorCode("unsupported_preparation")
        return to_record(runtime.prepare(request["scope"], kind, base64.b64decode(request["content"], validate=True)))
    if op == "start":
        return runtime.start(request["spec"], request["registry"], request.get("import"), request.get("resume"),
                             request.get("override_reason"), request.get("roles"),
                             request.get("extra_case_money"), request.get("case_money_reason"))
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
        # A resumed case runs as "<case>@<batch>" (engine.resume_point).
        case, _, batch = request["destination"].partition("@")
        if not CASE_ID.fullmatch(case) or (batch and not BATCH_ID.fullmatch(batch)):
            raise RuntimeErrorCode("invalid_case")
        payload = dict(request["payload"])
        if payload.get("ruling") is not None:
            payload["ruling"] = Ref(**payload["ruling"])
        runtime.engine.reply(request["destination"], FounderReply(**payload))
        return {"sent": True}
    if op == "resume_held":
        case, _, batch = request["destination"].partition("@")
        if not CASE_ID.fullmatch(case) or (batch and not BATCH_ID.fullmatch(batch)):
            raise RuntimeErrorCode("invalid_case")
        return {"sent": runtime.engine.resume_held(request["destination"])}
    if op == "publish":
        from durable.classify import PUBLISHED_REASONS
        from durable.report import load_cards, publish
        if not BATCH_ID.fullmatch(request["batch"]):
            raise RuntimeErrorCode("invalid_batch")
        return publish(runtime.store.objects, request["batch"], load_cards(request["batch"]), PUBLISHED_REASONS)
    if op == "in_flight":
        return runtime.engine.in_flight()
    if op == "budget":
        if not BATCH_ID.fullmatch(request["batch"]):
            raise RuntimeErrorCode("invalid_batch")
        return runtime.ledger.balance(request["batch"])
    if op in ("status", "report"):
        from durable.classify import PUBLISHED_REASONS
        from durable.report import load_cards, scorecard
        if not BATCH_ID.fullmatch(request["batch"]):
            raise RuntimeErrorCode("invalid_batch")
        return scorecard(request["batch"], load_cards(request["batch"]), allowlist=PUBLISHED_REASONS)
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


def parse_roles(text):
    """`--roles stress_tester=<model>[,strong_calibrator=<model>]` as {role: model}, checked as far as
    it can be without the case card (runtime.check_role_swap; Runtime.start checks it again)."""
    roles = {}
    for item in text.split(","):
        role, sep, model = item.partition("=")
        if not sep or role in roles:
            raise RuntimeErrorCode("roles_invalid")
        roles[role] = model
    return check_role_swap(roles)


def stop_on_signal(drain, cleanup=lambda: None):
    """The first SIGTERM or SIGINT drains and ends the process. Nothing else is waited for: the
    socket loop may be held by a client, and a stuck thread must not outlive the stop."""
    stopping = threading.Lock()
    def finish():
        try:
            try:
                cleanup()   # first, so no new operator request arrives during the drain
            finally:
                drain()
            logging.shutdown()
        finally:
            os._exit(0)
    def stop(_signum, _frame):
        if stopping.acquire(blocking=False):
            threading.Thread(target=finish, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)


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
            stop_on_signal(runtime.drain, lambda: path.unlink(missing_ok=True))
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
    prepare.add_argument("kind", choices=[k.value for k in (ArtifactKind.INPUTS, ArtifactKind.STATEMENT_REGISTRY, ArtifactKind.FOUNDER_RULING, ArtifactKind.CASE_SNAPSHOT)])
    prepare.add_argument("content_file")
    start = commands.add_parser("start")
    start.add_argument("spec_file")
    start.add_argument("registry_file")
    start.add_argument("--import-file", help="ref printed by `prepare <first case id> case <rewrapped checkpoint>`")
    start.add_argument("--resume-case", help="a case stopped by an infrastructure failure (held or retired), or held "
                       "by a factory_bug diagnosis of an unchanged repair: continue it as this "
                       "one-case batch's case, where it stopped")
    start.add_argument("--override-reason", help="operator override (founder 2026-11-11): resume --resume-case once "
                       "more where the normal rules refuse it (a factory_bug hold whose stops are not all rerunnable "
                       "or that used its resumes, or a case whose last attempt was not an infra stop); never a "
                       "scientific stop or a sealed case. Recorded on the case card and the board")
    start.add_argument("--roles", help="founder 2026-11-12: resume --resume-case with another model for "
                       "stress_tester and/or strong_calibrator, as role=model[,role=model]; later resumes of "
                       "the lineage keep it; undo one by naming the role's earlier model. The worker refuses a swap "
                       "that breaks the family rules or changes the strong calibrator once a GATES step ran")
    start.add_argument("--extra-case-money", type=int, help="founder 2026-11-13: raise --resume-case's lineage "
                       "case-money ceiling (the $50 default its earlier spend plus this batch's case_money_usd_micros "
                       "must fit) by this many micro-USD; later resumes of the lineage keep it, a further "
                       "grant adds to it, $200 in all. Needs --case-money-reason. Recorded on the case card and the board")
    start.add_argument("--case-money-reason", help="why --extra-case-money was granted (printable, at most 200 characters)")
    install = commands.add_parser("install")
    install.add_argument("content_file", help="existing worker release bundle")
    install.add_argument("bench_version")
    install.add_argument("image")
    for name in ("status", "report", "publish"):
        commands.add_parser(name).add_argument("batch")
    commands.add_parser("board", help="read-only Sealing Board: every case in every batch, as JSON").add_argument(
        "--live", action="store_true", help="only cases still running in a live batch")
    for name in ("bench_release", "plumbing_release", "bound_raised", "founder_reply"):
        p = commands.add_parser(name)
        p.add_argument("destination")
        p.add_argument("payload_file")
    commands.add_parser("resume_held", help="rerun a case held for a factory release (held_for_release) "
                        "without waiting for one; counts as a factory_bug resume").add_argument("destination")
    args = vars(parser.parse_args(argv))
    try:
        config = load_config(args.pop("config"))
        if args["op"] == "run":
            serve(config)
            return 0
        if args['op'] in ('status', 'report'):
            from durable.observation import read_status
            result = read_status(config, args['batch'])
        elif args['op'] == 'board':
            from durable.board import read_board
            result = read_board(config, live_only=args['live'])
        elif args["op"] == "backup":
            result = backup(config, resume_after=args["resume_after"])
        elif args["op"] == "restore":
            result = restore(config, args["archive_file"], args["source_state"], quarantine=args["quarantine"])
        elif args["op"] == "reconcile":
            result = reconcile(config, ownership=args["ownership_reconciled"], spending=args["spending_reconciled"], cleared=args["cleared_record"])
        elif args["op"] == "resume":
            result = resume(config)
        else:
            if args.get("override_reason") is not None and args.get("resume_case") is None:
                raise RuntimeErrorCode("override_needs_resume_case")
            money = [args.pop(k, None) for k in ("extra_case_money", "case_money_reason")]
            if money != [None, None]:
                if args.get("resume_case") is None:
                    raise RuntimeErrorCode("case_money_needs_resume_case")
                if None in money:
                    raise RuntimeErrorCode("case_money_extra_invalid")
                args["extra_case_money"], args["case_money_reason"] = money
            if args.get("roles") is not None:
                if args.get("resume_case") is None:
                    raise RuntimeErrorCode("roles_need_resume_case")
                args["roles"] = parse_roles(args["roles"])
            elif "roles" in args:
                args.pop("roles")
            for field in ("spec", "registry", "payload", "import"):
                if args.get(field + "_file") is not None:
                    args[field] = json.loads(private_bytes(args.pop(field + "_file")))
            args.pop("import_file", None)
            if args.get("override_reason") is None:
                args.pop("override_reason", None)
            if args.get("resume_case") is not None:
                args["resume"] = args.pop("resume_case")
            args.pop("resume_case", None)
            if args.get("kind") == ArtifactKind.CASE_SNAPSHOT.value:
                args["content_path"] = str(Path(args.pop("content_file")).resolve())
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
