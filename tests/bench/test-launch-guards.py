#!/usr/bin/env python3
"""Offline launch guard checks: python3 tests/bench/test-launch-guards.py (about two minutes).
Use --restore-only for the archive transfer and recovery checks.
Copies only launch scripts into a temp bench. Never invokes real boat or paid services.
"""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import json
import os
import pathlib
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = _BENCH_ROOT
FAKE = r'''#!/usr/bin/env python3
import json, os, pathlib, shlex, subprocess, sys, time
root = pathlib.Path(os.environ["FAKE_STATE"])
mode = os.environ.get("FAKE_MODE", "finish")
args = sys.argv[1:]
with (root / "calls").open("a") as f: f.write(json.dumps(args) + "\n")
cmd = args[0]
def vmdir(id): return root / id
if cmd == "billing":
    if mode == "bad-billing": print('{}'); sys.exit(0)
    balance = int(os.environ.get("FAKE_BALANCE", "1000000"))
    balance -= len(list(root.glob("vm-*/deleted"))) * 100
    print(json.dumps({"limits": {"creditBalanceSeconds": balance}}))
elif cmd == "new":
    id = "vm-" + str(len(list(root.glob("vm-*"))) + 1)
    vmdir(id).mkdir()
    print(json.dumps({"event": "creating"}))
    print(json.dumps({"event": "created", "id": id}), flush=True)
    if mode == "new-fail": sys.exit(1)
elif cmd == "exec":
    if os.environ.get("EXAM_CLAUDE_SECRET") == "claude-token-2":
        assert (vmdir(args[1]) / "shm-secrets/claude-token").read_text() == "fake-claude-token-2\n"
    vm = vmdir(args[1]); (vm / "sealed").mkdir(exist_ok=True); (vm / "exam-out").mkdir(exist_ok=True)
    if "factory/run.py" in args[-1]:
        import hashlib
        statement = vm / "statements/case-old.statement.age"
        assert hashlib.sha256(statement.read_bytes()).hexdigest() == os.environ['FAKE_STATEMENT_SHA']
        board = vm / "statements/selection-board.json"
        if "--resume" not in args[-1]:
            assert board.is_file(), "new factory launches need the advisory selection board"
        if board.exists():
            assert json.loads(board.read_text()) == {
                'version': 1, 'scope': 'selection_only', 'complete': True,
                'registry_revision': 1, 'statements': {'case-old': os.environ['FAKE_STATEMENT_SHA']}}
            assert not (vm / "statements/admission.json").exists(), 'selection history grants no reservation'
        assert (vm / "shm-secrets/statements-key").read_text() == "fake-statements-key\n"
        assert "export OPENCODE_DISABLE_AUTOUPDATE=1" in args[-1]
        assert (vm / "opencode-version").read_text() == "1.19.0"
        if "'--continue-g11-review'" in args[-1]:
            assert "--resume 'case-synthetic'" in args[-1]
            assert (vm / "work/case-synthetic/g11-audit/case/promise.md").read_text() == "synthetic case"
            assert (vm / "work/case-synthetic/g11-audit/notes.txt").read_text() == "saved review notes"
            assert json.loads((vm / "sealed/case-synthetic.continuation-budget.json").read_text())["calls"] == 49
    (vm / "work").mkdir(exist_ok=True); (vm / "jobs").mkdir(exist_ok=True)
    if "bin/run-exam" in args[-1]:
        (vm / "exam").touch()
        (vm / "exam-private/trial/jobs").mkdir(parents=True)
    (vm / ".boat-launch-start").touch()
    for dest in ("sealed", "exam-out"):
        (vm / dest / "result.scorecard.txt").write_text("fake scorecard\n")
        (vm / dest / "result.jobs.tar.gz.age").write_text("fake sealed bytes")
        (vm / dest / "result.statement.age").write_text("fake statement ciphertext")
    (vm / "exam-stdout").write_text("fake exam scorecard\n")
    if mode in ("finish", "collect-fail", "delete-fail", "reuse-review") or (mode == "mixed" and args[1] == "vm-2"):
        (vm / "sealed/DONE").touch(); (vm / "exam-out/DONE").touch()
    if mode == "stale": os.utime(vm / ".boat-launch-start", (1, 1))
    if mode.startswith("autoretry"):
        import hashlib
        case = "case-synthetic"
        folder = vm / "sealed"
        count = vm / "exec-count"
        attempt = int(count.read_text()) + 1 if count.exists() else 1
        count.write_text(str(attempt))
        # Each completed retry publishes a new checkpoint generation and retains
        # cumulative work. Repeating identical old cards is correctly not retried.
        payload = ("synthetic ciphertext generation " + str(attempt)).encode()
        (folder / (case + ".checkpoint.tar.gz.age")).write_bytes(payload)
        card = {"case":case, "seed":42, "status":"stopped", "terminal_stop":"stalled",
                "sha256":hashlib.sha256(payload).hexdigest(),
                "continuation_budget":{"cost":0.25 * attempt,"calls":2 * attempt,"events":[],"terminal_stop":"stalled"}}
        if mode == "autoretry-gate": card["failed_gate"] = "G8"
        if mode == "autoretry-cap": card["terminal_stop"] = "call_limit"
        if mode == "autoretry-corrupt": card["sha256"] = "0" * 64
        if mode == "autoretry-nohash": card.pop("sha256")
        (folder / (case + ".scorecard.json")).write_text(json.dumps(card))
        (folder / "DONE").write_text(case)
        if "--resume case-synthetic" in args[-1]:
            assert "--resume-bench-sha " + "a"*64 in args[-1]
            assert "--seed 42" in args[-1]
            assert "'--max-total-calls' '700'" in args[-1]
            assert "'--max-cost' '2'" in args[-1]
            assert "test -f ~/sealed/case-synthetic.continuation-budget.json" in args[-1]
            assert "factory-restart.lock" in args[-1]
            if mode == "autoretry-uncertain":
                (folder / (case + ".checkpoint.tar.gz.age")).write_bytes(b"new uncertain checkpoint")
                card["sha256"] = hashlib.sha256(b"new uncertain checkpoint").hexdigest()
                (folder / (case + ".scorecard.json")).write_text(json.dumps(card))
                sys.exit(1)  # remote mutation succeeded; its transport acknowledgement was lost
elif cmd == "ssh":
    vm = vmdir(args[1]); command = args[2]
    if "cat > ~/factory.tgz" in command:
        # Exercise the real streamed bytes and checksum; fake only the transport.
        sys.exit(subprocess.run(["/bin/sh", "-c", command],
            input=sys.stdin.buffer.read(), env={**os.environ, "HOME":str(vm)}).returncode)
    elif "mkdir /home/user/.statements-stage-" in command and "tar -xzf -" in command:
        # Run the real snapshot extraction in this synthetic VM; the following
        # Python swap still checks every transferred digest before installation.
        sys.exit(subprocess.run(["/bin/sh", "-c", command.replace("/home/user/", str(vm) + "/")],
            input=sys.stdin.buffer.read(), env={**os.environ, "HOME": str(vm)}).returncode)
    elif "print(run.bench_manifest())" in command:
        print("a" * 64)
    elif 'factory/worker_release.py' in command:
        assert not (vm / 'secrets-ok').exists(), 'qualification must precede credentials'
        if mode == 'qualification-fail': sys.exit(1)
        print(json.dumps({'schema':1,'verified_drivers':['opencode','codex']}))
    elif command == 'if test -d ~/sealed/.factory-restart.lock; then echo locked; else echo unlocked; fi':
        print('unlocked')
    elif command == "cat ~/sealed/DONE":
        print((vm / "sealed/DONE").read_text())
    elif 'factory/case_permissions.py --extract-to' in command:
        assert float(os.environ.get('BOAT_COMMAND_TIMEOUT_SECONDS','120')) == float(os.environ.get('FAKE_EXPECT_RESTORE_TIMEOUT','1200')), 'restore inherited ordinary SSH timeout'
        time.sleep(float(os.environ.get('FAKE_RESTORE_SLEEP','0')))
        args = [str(vm / a[2:]) if a.startswith('~/') else a for a in shlex.split(command)]
        args[2] = os.environ['FAKE_PERMISSION_HELPER']
        sys.exit(subprocess.run(args, stdin=sys.stdin.buffer, umask=0o077).returncode)
    elif "cat > ~/sealed/case-synthetic.continuation-budget.json" in command:
        folder = vm / "sealed"; folder.mkdir(exist_ok=True)
        (folder / "case-synthetic.continuation-budget.json").write_bytes(sys.stdin.buffer.read())
    elif command == "test -d ~/work/case-synthetic/g11-audit/case":
        sys.exit(0 if (vm / "work/case-synthetic/g11-audit/case").is_dir() else 1)
    elif "cat > /dev/shm/exam-key" in command:
        assert sys.stdin.read() == pathlib.Path(os.environ["FAKE_IDENTITY"]).read_text()
    elif "base64 -d | tar" in command:
        import base64, io, tarfile, re
        shm = vm / "shm-secrets"; shm.mkdir(exist_ok=True)
        tarfile.open(fileobj=io.BytesIO(base64.b64decode(sys.stdin.read()))).extractall(shm, filter="data")
        names = re.search(r"for n in (.*?); do", command).group(1).split()
        if not all((shm / n).read_text() == "fake-" + n + "\n" for n in names): sys.exit(1)
        (vm / "secrets-ok").touch()
    elif command == "cp /dev/shm/secrets/claude-token-2 /dev/shm/secrets/claude-token":
        (vm / "shm-secrets/claude-token").write_text((vm / "shm-secrets/claude-token-2").read_text())
    elif "opencode" in command and "--version" in command:
        assert "/usr/local/bin/opencode" in command, "preflight must inspect the runner's absolute CLI"
        tools = vm / "tools"; tools.mkdir()
        prefix = vm / "usr/local"; (prefix / "bin").mkdir(parents=True)
        (vm / "opencode-version").write_text(os.environ.get("FAKE_OPENCODE_VERSION", "1.19.0"))
        cli = prefix / "bin/opencode"
        cli.write_text('#!/usr/bin/env python3\nimport os,pathlib,sys\nassert os.environ.get("OPENCODE_DISABLE_AUTOUPDATE")=="1"\nassert sys.argv[1:]==["--version"]\nprint((pathlib.Path(os.environ["FAKE_VM"])/"opencode-version").read_text())\n')
        cli.chmod(0o755)
        (vm / "codex-version").write_text(os.environ.get("FAKE_CODEX_VERSION", "0.162.1"))
        codex = prefix / "bin/codex"
        codex.write_text('#!/usr/bin/env python3\nimport os,pathlib\nprint("codex-cli " + (pathlib.Path(os.environ["FAKE_VM"])/"codex-version").read_text())\n')
        codex.chmod(0o755)
        # Poison PATH: only the absolute binary above is the version used by the runner.
        (tools / "opencode").write_text("#!/bin/sh\nexit 98\n"); (tools / "opencode").chmod(0o755)
        (tools / "sudo").write_text('#!/bin/sh\nexec "$@"\n'); (tools / "sudo").chmod(0o755)
        npm = tools / "npm"
        npm.write_text('#!/usr/bin/env python3\nimport os,pathlib,sys\np=pathlib.Path(os.environ["FAKE_VM"])\nassert os.environ.get("OPENCODE_DISABLE_AUTOUPDATE")=="1"\nassert "opencode-ai@1.19.0" in sys.argv or "@openai/codex@0.162.1" in sys.argv\nif "@openai/codex@0.162.1" in sys.argv:\n (p/"codex-installed").touch()\n if os.environ["FAKE_MODE"]=="codex-pin-install-fail": sys.exit(1)\n if os.environ["FAKE_MODE"]!="codex-pin-wrong-version": (p/"codex-version").write_text("0.162.1")\n sys.exit(0)\nassert sys.argv[sys.argv.index("--prefix")+1]==str(p/"usr/local")\n(p/"opencode-installed").touch()\nif os.environ["FAKE_MODE"]=="pin-install-fail": sys.exit(1)\nif os.environ["FAKE_MODE"]!="pin-wrong-version": (p/"opencode-version").write_text("1.19.0")\n')
        npm.chmod(0o755)
        env = dict(os.environ, FAKE_VM=str(vm), PATH=str(tools)+os.pathsep+os.environ["PATH"])
        sys.exit(subprocess.run(["/bin/sh", "-c", command.replace("/usr/local", str(prefix))], env=env).returncode)
    elif command.startswith("python3 -c ") and "snapshot transfer digest mismatch" in command:
        # Statement installation precedes the runner; it is not a watchdog poll.
        sys.exit(subprocess.run(["/bin/sh", "-c", command.replace("/home/user", str(vm))],
                                env=dict(os.environ, HOME=str(vm))).returncode)
    elif command.startswith(("python3 -c ", "OPENCODE_DISABLE_AUTOUPDATE=1 python3 -c ")):
        (vm / "polled").touch()
        if mode == "collect-fail" and "pathlib.Path.home()" in command and "sealed" in command: sys.exit(1)
        if mode == "unreachable": sys.exit(1)
        if mode == "hang": time.sleep(10)
        command = command.replace("/home/user", str(vm))
        if mode == "progress":
            count = vm / "poll-count"
            n = int(count.read_text()) + 1 if count.exists() else 1
            count.write_text(str(n))
            # Match run-exam's real private job directory, which is absent from ~/jobs.
            if (vm / "exam").exists(): (vm / "exam-private/trial/jobs/progress").touch()
            else: (vm / "sealed/case.continuation-budget.json").touch()
            if n >= 5:
                (vm / "sealed/DONE").touch(); (vm / "exam-out/DONE").touch()
        env = dict(os.environ, HOME=str(vm))
        sys.exit(subprocess.run(["/bin/sh", "-c", command], env=env).returncode)
    elif "ls *." in command:
        folder = "exam-out" if "exam-out" in command else "sealed"
        if not (vm / folder).exists():  # both collectors: no output folder = nothing to collect
            if folder == "exam-out": print("NOTHING")
            sys.exit(0)
        if mode.startswith("autoretry"):
            print("case-synthetic.scorecard.json\ncase-synthetic.checkpoint.tar.gz.age")
        else:
            print("result.scorecard.txt\nresult.jobs.tar.gz.age" + ("\nresult.statement.age" if folder == "sealed" else ""))
    elif command.startswith("sha256sum ") and mode.startswith("autoretry"):
        import hashlib
        print(hashlib.sha256((vm / "sealed" / command.rsplit("/",1)[-1]).read_bytes()).hexdigest())
    elif command == "cat ~/exam-stdout":
        if not (vm / "exam-stdout").exists(): sys.exit(1)
        print((vm / "exam-stdout").read_text(), end="")
    elif command.startswith('if [ ! -f ~/sealed/DONE ]'):
        sys.exit(0)  # Setup failure is not a failed collector pause/transport.
    elif mode == "setup-fail": sys.exit(1)
elif cmd == "scp":
    if args[1].endswith(".statement.age") and not args[1].startswith("vm-"):
        import shutil
        id = args[2].split(":")[0]
        dest = vmdir(id) / "statements"
        dest.mkdir(exist_ok=True)
        shutil.copyfile(args[1], dest / pathlib.Path(args[1]).name)
    if args[1].startswith("vm-"):
        if mode == "collect-fail": sys.exit(1)
        if mode.startswith("autoretry"):
            import shutil
            source = vmdir(args[1].split(":")[0]) / "sealed" / args[1].rsplit("/", 1)[-1]
            shutil.copyfile(source, args[2])
        else: pathlib.Path(args[2]).write_text("fake sealed result\n")
elif cmd == "delete":
    if mode == "delete-fail": sys.exit(1)
    (vmdir(args[1]) / "deleted").touch()
    print(json.dumps({'operation': {'id': 'op-' + args[1], 'targetId': args[1],
          'kind': 'sandbox', 'status': 'pending', 'stage': 'queued', 'completedAt': None,
          'privateDiagnostic': 'must not persist'}}))
elif cmd == "deletion":
    assert args[1] == 'status' and args[3] == '--json'
    if mode == 'deletion-unavailable': sys.exit(1)
    operation = dict(id=args[2], targetId=args[2].removeprefix('op-'), kind='sandbox',
                     status='completed', stage='completed', completedAt='2026-10-22T22:00:00Z',
                     privateDiagnostic='must not persist')
    if mode == 'deletion-wrong-worker': operation['targetId'] = 'other-worker'
    if mode == 'deletion-wrong-operation': operation['id'] = 'other-operation'
    if mode == 'deletion-wrong-kind': operation['kind'] = 'volume'
    if mode == 'deletion-incomplete': operation.update(status='processing', stage='deleting', completedAt=None)
    if mode == 'deletion-wrong-stage': operation['stage'] = 'deleting'
    if mode == 'deletion-no-timestamp': operation['completedAt'] = None
    print(json.dumps({'operation': operation}))
elif cmd == "list":
    import datetime
    expiry = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)
    print(json.dumps({"sandboxes": [{"id": vm.name, "status": "running", "type": "default",
          "name": "factory: G11 review — synthetic", "archiveAfter": expiry.isoformat()}
          for vm in root.glob("vm-*") if not (vm / "deleted").exists()]}))
else: sys.exit("unexpected fake boat command " + cmd)
'''


def main():
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="launch-guards-test-") as directory:
        base = pathlib.Path(directory)
        bench = base / "bench"
        for f in ("factory/run.py", "factory/calibration.py", "factory/prompts/pilot.md", "factory/launch.sh", "factory/control_resume.py", "factory/collect.sh", "factory/restart.py", "factory/transfer.py", "factory/sealed_audit.py", "factory/exam_responder.py", "harbor/responder/responder.py", "harbor/responder/ask-human",
                  "factory/worker_release.py", "factory/free_models.py", "factory/worker-release.json", "factory/statements-recipient.txt", "factory/rotation.json", "factory/rotation-3writers.json",
                  "bin/bench.py", "bin/bench_judging.py", "bin/setup", "bin/reset", "bin/check", "bin/verify-negative",
                  "projects/medusa/package.json", "projects/medusa/package-lock.json", "projects/medusa/compose.yaml",
                  "projects/medusa/verify-lock.mjs", "projects/medusa/Dockerfile", "projects/medusa/Dockerfile.deps",
                  "projects/medusa/medusa-config.ts", "bin/exam-launch", "bin/boat-call",
                  "bin/boat-spend", "bin/boat-launch-guards.sh", "bin/push-secrets"):
            dest = bench / f
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / f, dest)
        # Exercise the current runtime dependency closure, not a stale hand-copy.
        for source in (ROOT / "factory").glob("*.py"):
            if not source.name.startswith("test_"):
                shutil.copy2(source, bench / "factory" / source.name)
        for name in ("checkpoint", "checkpoint_evidence.py", "factory_pool.py", "strategy"):
            shutil.copy2(ROOT / "bin" / name, bench / "bin" / name)
        (bench / "sealed").mkdir()
        # A throwaway age key and an encrypted fake bundle, shaped like bin/setup-secrets output.
        identity = base / "identity.txt"
        subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)
        recipient = subprocess.check_output(["age-keygen", "-y", str(identity)], text=True).strip()
        # This isolated bench belongs to the throwaway identity. Keep the real
        # founder-identity check active, with its public recipient set to our key.
        import re
        runner = bench / "factory/run.py"
        runner_source, replacements = re.subn(r'^FOUNDER_RECIPIENT = "age1[a-z0-9]+"',
            'FOUNDER_RECIPIENT = "' + recipient + '"', runner.read_text(), flags=re.M)
        assert replacements == 1
        runner.write_text(runner_source)
        plain = base / "plain"; plain.mkdir()
        for name in ("claude-token", "claude-token-2", "codex-auth.json", "openrouter-key", "opencode-go-key", "statements-key"):
            (plain / name).write_text("fake-" + name + "\n")
        bundle_file = base / "secrets.age"
        tar = subprocess.run(["tar", "-C", str(plain), "-cf", "-", "claude-token", "claude-token-2", "codex-auth.json", "openrouter-key", "opencode-go-key", "statements-key"],
                             check=True, capture_output=True).stdout
        subprocess.run(["age", "-r", recipient, "-o", str(bundle_file)], input=tar, check=True)
        IDENTITY = identity.read_text()
        (bench / "sealed/test.tar.gz.age").write_text("encrypted fixture")
        sys.path.insert(0, str(bench / "factory"))
        from exam_responder import contract
        from sealed_audit import delivery_contract
        reviewer = {"model": "synthetic/reviewer", "effort": "high"}
        (bench / "sealed/test.scorecard.json").write_text(json.dumps(
            {"case": "test", "sha256": "a" * 64, "roles": {"reviewer": reviewer}, "owner_contract": contract(bench, reviewer),
             "delivery_provenance": {"contract": delivery_contract(), "sha256": "b" * 64}, "gates": {f"G{i}": "pass" for i in range(1, 18)}}))
        # Use the real registry and age format for the advisory selection board.
        from registry import Registry
        statement = bench / "sealed/case-old.statement.age"
        subprocess.run(["age", "-r", recipient, "-o", str(statement)],
                       input=b"synthetic old statement", check=True)
        Registry(bench / "sealed/statement-registry").import_historical("case-old", statement)
        import hashlib
        statement_sha = hashlib.sha256(statement.read_bytes()).hexdigest()
        fake = base / "fake-boat"
        fake.write_text(FAKE); fake.chmod(0o755)
        # Advance only the retry test's host clock. No production retry/backoff is shortened.
        clockbin = base / "clockbin"; clockbin.mkdir()
        clock = clockbin / "date"
        clock.write_text('#!/usr/bin/env python3\nimport os,pathlib,subprocess,sys,time\n'
                         'if sys.argv[1:]==["+%s"]:\n'
                         ' p=pathlib.Path(os.environ["FAKE_STATE"])/"clock"\n'
                         ' n=int(p.read_text())+75 if p.exists() else int(time.time())\n'
                         ' p.write_text(str(n)); print(n)\n'
                         'else: sys.exit(subprocess.run(["/bin/date",*sys.argv[1:]]).returncode)\n')
        clock.chmod(0o755)
        # Any accidental call to naming is a hard failure, even though BOAT_CMD should skip it.
        (bench / "bin/boat-name").write_text("#!/bin/sh\necho UNEXPECTED_NAMING_CALL >&2\nexit 99\n")
        (bench / "bin/boat-name").chmod(0o755)
        # Isolated retirement seam: no launcher, case or credentials; receipts survive cleanup.
        for mode in ('finish', 'deletion-wrong-worker', 'deletion-wrong-operation',
                     'deletion-wrong-kind', 'deletion-incomplete', 'deletion-wrong-stage',
                     'deletion-no-timestamp', 'deletion-unavailable'):
            cloud = base / ('receipt-' + mode); (cloud / 'vm-1').mkdir(parents=True)
            temporary = cloud / 'temporary'; temporary.mkdir()
            (temporary / 'ids').write_text('vm-1\n')
            spend = cloud / 'spend.json'; spend.write_text('{}')
            script = r'''root=$1; state=$2; spend_file=$3; label=exam
. "$root/bin/boat-launch-guards.sh"
collect_vm() { touch "$state/$1.collected"; }
guard_retire vm-1
status=$?
# A second retirement (as from guard_exit) must not issue another deletion.
guard_retire vm-1 >/dev/null 2>&1
rm -rf "$state"
exit "$status"
'''
            result = subprocess.run(['/bin/sh', '-c', script, 'sh', str(bench),
                                     str(temporary), str(spend)], capture_output=True, text=True,
                                    timeout=10, env=dict(os.environ, UNBUG_CLOUD='boat',
                                    BOAT_CMD=str(fake), FAKE_STATE=str(cloud), FAKE_MODE=mode,
                                    BOAT_DELETION_TIMEOUT_SECONDS='3'))
            evidence = spend.with_suffix('.deletions') / 'vm-1'
            assert not temporary.exists()
            assert (evidence / 'deletion-request.json').exists(), (mode, result.returncode, result.stderr)
            request = json.loads((evidence / 'deletion-request.json').read_text())
            assert request['id'] == 'op-vm-1' and request['targetId'] == 'vm-1'
            assert 'must not persist' not in (evidence / 'deletion-request.json').read_text()
            completion = evidence / 'deletion-completion.json'
            assert completion.exists() == (mode == 'finish'), (mode, result.stderr)
            if mode == 'finish':
                verified = json.loads(completion.read_text())
                assert result.returncode == 0 and verified == dict(id='op-vm-1', targetId='vm-1',
                    kind='sandbox', status='completed', stage='completed', completedAt='2026-10-22T22:00:00Z')
            else:
                assert result.returncode != 0 and 'verification FAILED' in result.stderr
            calls = [json.loads(line) for line in (cloud / 'calls').read_text().splitlines()]
            assert len([c for c in calls if c[0] == 'delete']) == 1
            assert calls[0] == ['delete', 'vm-1', '--yes', '--json']
            assert all(c == ['deletion', 'status', 'op-vm-1', '--json'] for c in calls[1:])
        print('PASS durable deletion receipts; exact identity/completion, bounded polling, no deletion resubmission')
        counter = 0

        def code_ok(proc): return proc.returncode == 0

        def run(kind="factory", mode="finish", extra=(), count=1, sig=None, **overrides):
            nonlocal counter
            counter += 1
            state = base / f"state-{counter}"
            state.mkdir()
            env = dict(os.environ, BOAT_CMD=str(fake), FAKE_STATE=str(state), FAKE_MODE=mode, FAKE_STATEMENT_SHA=statement_sha, UNBUG_CONTROL_HOME=str(base / "control"),
                       BOAT_POLL_SECONDS="0.1", BOAT_STALL_MINUTES="0.02",
                       BOAT_UNREACHABLE_SECONDS="1", BOAT_COMMAND_TIMEOUT_SECONDS="2", BOAT_COLLECT_RETRY_SECONDS="0", UNBUG_SECRETS_FILE=str(bundle_file), FAKE_IDENTITY=str(identity), FAKE_PERMISSION_HELPER=str(bench / "factory/case_permissions.py"))
            env.update(overrides)
            if mode.startswith("reuse-"):
                env['UNBUG_CLOUD'] = 'boat'
                vm = state / 'vm-existing'; (vm / 'factory').mkdir(parents=True)
                (vm / 'sealed').mkdir(); (vm / 'work/case-synthetic/case').mkdir(parents=True)
                sha = 'b' * 64 if mode == 'reuse-bench-changed' else 'a' * 64
                (vm / 'factory/run.py').write_text(f'def bench_manifest(): return {sha!r}\n')
                if mode == 'reuse-advanced-ledger':
                    (vm / 'sealed/case-synthetic.continuation-budget.json').write_text(json.dumps({'cost': .33, 'calls': 50}))
                if mode == 'reuse-locked': (vm / 'sealed/.factory-review-restore.lock').mkdir()
                if mode == 'reuse-audit-present':
                    audit = vm / 'work/case-synthetic/g11-audit'; audit.mkdir()
                    (audit / 'notes.txt').write_text('newer notes that must survive')
                # The fake VM must not see the host's real Codex agent process.
                processbin = vm / 'processbin'; processbin.mkdir()
                (processbin / 'pgrep').write_text('#!/bin/sh\nexit '+('0' if mode == 'reuse-runner' else '1')+'\n')
                if mode in ('reuse-tar', 'reuse-model'):
                    pattern = 'tar -x' if mode == 'reuse-tar' else 'opencode'
                    (processbin / 'pgrep').write_text('#!/bin/sh\ncase "$*" in *"'+pattern+'"*) exit 0;; *) exit 1;; esac\n')
                (processbin / 'pgrep').chmod(0o755)
                env['PATH'] = str(processbin) + os.pathsep + env['PATH']
            if mode.startswith("autoretry"):
                env.update(UNBUG_CLOUD="boat", PATH=str(clockbin)+os.pathsep+env["PATH"])
            cmd = ["/bin/sh", str(bench / "factory/launch.sh"), str(count), "--source", "port"] if kind == "factory" else [
                "/bin/sh", str(bench / "bin/exam-launch"), str(bench / "sealed/test.tar.gz.age"), "--arm", "A"]
            before = set((bench / "results/spend").glob("*.json"))
            proc = subprocess.Popen(cmd + list(extra), env=env, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    start_new_session=True)
            if sig:
                proc.stdin.write(IDENTITY); proc.stdin.flush(); proc.stdin.close(); proc.stdin = None
                deadline = time.monotonic() + 5
                while not list(state.glob("vm-*/polled")):
                    assert proc.poll() is None, "launcher exited before signal test"
                    assert time.monotonic() < deadline, "launcher never polled"
                    time.sleep(0.02)
                os.kill(proc.pid, sig)
                out, err = proc.communicate(timeout=30)
            else:
                try:
                    out, err = proc.communicate(IDENTITY, timeout=30)
                except subprocess.TimeoutExpired:
                    # Never leave a failed synthetic controller running after
                    # its temporary fixture is removed.
                    os.killpg(proc.pid, signal.SIGKILL)
                    out, err = proc.communicate()
                    raise AssertionError("synthetic launcher timed out: " + err)
            calls = [json.loads(line) for line in (state / "calls").read_text().splitlines()] if (state / "calls").exists() else []
            records = set((bench / "results/spend").glob("*.json")) - before
            record = json.loads(next(iter(records)).read_text()) if records else None
            assert "UNEXPECTED_NAMING_CALL" not in err, err
            ids = [vm.name for vm in state.glob("vm-*")]
            rejected_reuse = mode.startswith('reuse-') and not any(c[0] == 'exec' for c in calls)
            if mode != "delete-fail":
                assert rejected_reuse or mode in ("collect-fail", "autoretry-corrupt", "autoretry-nohash", "autoretry-uncertain", "unreachable", "hang") or all((state / id / "deleted").exists() for id in ids), (cmd, err)
            for id in ids:
                if rejected_reuse or mode in ("collect-fail", "autoretry-corrupt", "autoretry-nohash", "autoretry-uncertain", "unreachable", "hang"):  # uncertain artifacts never permit deletion
                    assert not any(call[:2] == ["delete", id] for call in calls), err; continue
                deletion = next(i for i, call in enumerate(calls) if call[:2] == ["delete", id])
                assert any(call[:2] == ["ssh", id] and "ls *." in call[2] for call in calls[:deletion]), err
            if mode == "finish" and code_ok(proc):
                assert ids and all((state / id / "secrets-ok").exists() for id in ids), err
            if record:
                retained = any(not (state / id / "deleted").exists() for id in ids)
                if retained and not rejected_reuse:
                    assert mode in ("collect-fail", "autoretry-corrupt", "autoretry-nohash", "autoretry-uncertain", "unreachable", "hang", "delete-fail"), (mode, err)
                    assert "!!! ORPHAN:" in err, err
                if kind == "factory" and retained and not rejected_reuse:
                    # Durable factory launches remain open until retirement;
                    # legacy exam launches report the observed balance delta.
                    assert record["balance_after_usd"] is None and record["actual_spend_usd"] is None, (record, err)
                    assert "Actual spend" not in err
                else:
                    assert record["balance_after_usd"] is not None, (record, err)
                    assert "Actual spend" in err
            return proc.returncode, out, err, calls, record

        exam_card = bench / "sealed/test.scorecard.json"
        qualified = exam_card.read_text()
        legacy = json.loads(qualified); legacy["gates"].pop("G16")
        exam_card.write_text(json.dumps(legacy))
        code, _, _, calls, _ = run("exam")
        assert code != 0 and not calls, "unqualified cases must fail before any cloud action"
        exam_card.write_text(qualified)
        for kind, hours in (("factory", 8), ("exam", 2.5)):
            code, out, err, calls, rec = run(kind)
            assert code == 0, err
            if kind == "factory": assert (bench / "sealed/result.statement.age").is_file()
            assert rec["ttl_seconds"] == hours * 3600
            assert abs(rec["actual_spend_usd"] - 0.001) < 1e-9
            assert "TTL:" in err
        code, _, err, _, rec = run("exam", extra=("--arm", "C", "--tries", "2"))
        assert code == 0 and rec["ttl_seconds"] == 7 * 3600, err
        code, _, err, _, rec = run("exam", extra=("--ttl-hours", "0.5"))
        assert code == 0 and rec["ttl_seconds"] == 1800, err
        print("PASS TTL defaults, arm/try sizing, override, collection and spend records")

        # Real age/tar streaming through the actual launcher, with a fake cloud only.
        import hashlib
        audit = base / "audit/g11-audit"; (audit / "case").mkdir(parents=True)
        (audit / "case/promise.md").write_text("synthetic case")
        (audit / "notes.txt").write_text("saved review notes")
        archive = bench / "sealed/g11-review-case-synthetic.tar.gz.age"
        tar = subprocess.run(["tar", "-C", str(audit.parent), "-czf", "-", audit.name], check=True, capture_output=True).stdout
        subprocess.run(["age", "-r", recipient, "-o", str(archive)], input=tar, check=True)
        card = {"case": "case-synthetic", "kind": "g11-independent-review", "status": "stopped", "inputs_unchanged": True, "digest_version": 2,
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "continuation_budget": {"cost": .32, "calls": 49},
                "review_bench_sha256": 'a' * 64}
        public = bench / "sealed/g11-review-case-synthetic.scorecard.json"; public.write_text(json.dumps(card))
        code, out, err, calls, rec = run(extra=("--restore-review", "case-synthetic"))
        assert code == 0, err
        assert any(c[0] == "exec" and "'--continue-g11-review'" in c[-1] for c in calls), err
        assert not list((bench / "sealed").glob("g11-audit")), "restore must not decrypt into host sealed/"
        original = base / "original/case-synthetic"; (original / "case").mkdir(parents=True)
        (original / "case/promise.md").write_text("synthetic original baseline")
        source_archive = bench / "sealed/case-synthetic.tar.gz.age"
        source_tar = subprocess.run(["tar", "-C", str(original.parent), "-czf", "-", original.name], check=True, capture_output=True).stdout
        subprocess.run(["age", "-r", recipient, "-o", str(source_archive)], input=source_tar, check=True)
        source_card = {"case": "case-synthetic", "failed_gate": "G11", "sha256": hashlib.sha256(source_archive.read_bytes()).hexdigest()}
        source_public = bench / "sealed/case-synthetic.scorecard.json"; source_public.write_text(json.dumps(source_card))
        card["digest_version"] = 1; public.write_text(json.dumps(card))
        code, _, err, calls, _ = run(extra=("--restore-review", "case-synthetic"))
        assert code == 0, err
        assert sum(c[0] == "ssh" and "case_permissions.py --extract-to ~/work" in c[-1] for c in calls) == 2
        code, _, err, calls, _ = run(extra=("--restore-review", "case-synthetic"),
            BOAT_COMMAND_TIMEOUT_SECONDS='0.5', BOAT_RESTORE_TIMEOUT_SECONDS='3',
            FAKE_EXPECT_RESTORE_TIMEOUT='3', FAKE_RESTORE_SLEEP='1')
        assert code == 0, err
        reuse = ('--restore-review', 'case-synthetic', '--reuse-review-worker', 'vm-existing')
        code, _, err, calls, rec = run(mode='reuse-review', extra=reuse)
        assert code == 0, err
        assert not any(c[0] in ('new', 'ttl') for c in calls), 'recovery must preserve the existing VM and provider expiry'
        assert 3600 < rec['ttl_seconds'] <= 7200
        assert len([c for c in calls if c[0] == 'exec']) == 1
        for mode in ('reuse-advanced-ledger', 'reuse-bench-changed', 'reuse-locked', 'reuse-runner', 'reuse-audit-present', 'reuse-tar', 'reuse-model'):
            code, _, err, calls, _ = run(mode=mode, extra=reuse)
            assert code != 0, (mode, err)
            assert not any(c[0] in ('new', 'exec', 'scp', 'delete') for c in calls), (mode, err)
        print('PASS slow archive streams use their own timeout; same-VM recovery keeps expiry and rejects active, locked or changed work without taking ownership')
        source_card["sha256"] = "0" * 64; source_public.write_text(json.dumps(source_card))
        code, _, _, calls, _ = run(extra=("--restore-review", "case-synthetic"))
        assert code != 0 and not calls, "legacy baseline must also be authenticated before VM creation"
        card["sha256"] = "0" * 64; public.write_text(json.dumps(card))
        code, _, err, calls, rec = run(extra=("--restore-review", "case-synthetic"))
        assert code != 0 and not calls, "corrupt audit must stop before creating or billing a VM"
        print("PASS review continuation streams prior notes to the right VM path, preserves usage and rejects corrupt archives before VM creation")
        if '--restore-only' in sys.argv[1:]:
            print('All restore checks passed; no real boat calls.')
            return

        code, _, err, _, _ = run("exam", EXAM_CLAUDE_SECRET="claude-token-2")
        assert code == 0, err
        print("PASS account 2 reaches canonical claude-token in VM RAM")

        code, _, err, calls, _ = run(mode='qualification-fail')
        assert code != 0 and 'worker release qualification failed' in err
        assert not any(c[0] == 'exec' or (c[0] == 'ssh' and 'base64 -d | tar' in c[2]) for c in calls)
        print('PASS worker release qualification failure precedes secrets and model work')

        for version in ("1.19.0", "1.19.3"):
            code, _, err, calls, _ = run(FAKE_OPENCODE_VERSION=version)
            assert code == 0, err
            vm = base / f"state-{counter}/vm-1"
            assert (vm / "opencode-installed").exists() == (version != "1.19.0")
            preflight = next(i for i,c in enumerate(calls) if c[0] == "ssh" and "--version" in c[2])
            secret = next(i for i,c in enumerate(calls) if c[0] == "ssh" and "base64 -d | tar" in c[2])
            assert preflight < secret
        for mode in ("pin-install-fail", "pin-wrong-version"):
            code, _, err, calls, _ = run(mode=mode, FAKE_OPENCODE_VERSION="1.19.3")
            assert code != 0, err
            assert not any(c[0] == "exec" or c[0] == "ssh" and "base64 -d | tar" in c[2] for c in calls)
        print("PASS absolute OpenCode pin repairs drift before secrets, disables updates and fails closed")
        code, _, err, calls, _ = run(FAKE_CODEX_VERSION="0.163.0")
        assert code == 0, err
        assert (base / f"state-{counter}/vm-1/codex-installed").exists()
        for mode in ("codex-pin-install-fail", "codex-pin-wrong-version"):
            code, _, err, calls, _ = run(mode=mode, FAKE_CODEX_VERSION="0.163.0")
            assert code != 0, err
            assert not any(c[0] == "exec" or c[0] == "ssh" and "base64 -d | tar" in c[2] for c in calls)
        print("PASS Codex drift is repaired before secrets; wrong or failed pins stop before work")

        for mode, expected in (("autoretry", 4), ("autoretry-gate", 1), ("autoretry-cap", 1), ("autoretry-corrupt", 1), ("autoretry-nohash", 1), ("autoretry-uncertain", 2)):
            code, _, err, calls, _ = run(mode=mode, extra=("--max-total-calls", "700", "--max-cost", "2"), BOAT_COLLECT_RETRY_SECONDS="0")
            starts = [c for c in calls if c[0] == "exec"]
            assert len(starts) == expected, (mode, err, starts)
            assert len([c for c in calls if c[0] == "new"]) == 1
            assert not any(c[0] == "ttl" for c in calls)
            assert code == (1 if mode in ("autoretry-corrupt", "autoretry-nohash", "autoretry-uncertain") else 0), (mode, err)
            if mode == "autoretry-uncertain":
                assert "detached restart outcome is uncertain" in err
                assert (bench / "sealed/case-synthetic.checkpoint.tar.gz.age").read_bytes() == b"new uncertain checkpoint"
            if expected == 4:
                assert "retry 3/3" in err and "three restart attempts exhausted" in err, err
                for start in starts[1:]:
                    idx = calls.index(start)
                    assert any(c[0] == "ssh" and "case-synthetic.checkpoint" in c[2] and "hashlib.sha256()" in c[2] for c in calls[:idx])
        print("PASS Boat retries: three attempts, checkpoint verification, preserved ceilings and seed, no gate/cap/corruption retry")

        wrong = base / "wrong.txt"
        subprocess.run(["age-keygen", "-o", str(wrong)], check=True, capture_output=True)
        for kind in ("factory", "exam"):
            saved, IDENTITY = IDENTITY, wrong.read_text()
            code, _, err, calls, _ = run(kind)
            IDENTITY = saved
            assert code != 0 and "could not decrypt" in err and not any(c[0] == "new" for c in calls), err
        print("PASS keys decrypt in memory, reach every VM; a wrong identity stops before any VM")

        for options in ({"extra": ("--max-spend", "0.01")}, {"FAKE_BALANCE": "1"}, {"count": 21}):
            code, _, err, calls, rec = run(**options)
            assert code != 0 and not any(c[0] == "new" for c in calls), err
            assert rec and not rec["allowed"]
        for options in ({"mode": "bad-billing"}, {"extra": ("--ttl-hours", "NaN")},
                        {"extra": ("--max-spend", "-1")}, {"BOAT_STALL_MINUTES": "0"}):
            code, _, err, calls, _ = run(**options)
            assert code != 0 and not any(c[0] == "new" for c in calls), err
        print("PASS spend cap, balance, malformed billing and invalid options fail closed")

        for kind in ("factory", "exam"):
            code, _, err, _, _ = run(kind, "stale")
            assert code != 0 and "STALLED: no progress for 0.02 min" in err, err
            extra = ("--out", "~/exam-out", "--private=~/exam-private") if kind == "exam" else ()
            code, _, err, calls, _ = run(kind, "progress", extra=extra, BOAT_POLL_SECONDS="0.4", BOAT_STALL_MINUTES="0.016")
            assert code == 0 and "STALLED" not in err, err
            if kind == "exam":
                assert any(c[0] == "exec" and "'--out' '/home/user/exam-out'" in c[-1]
                           and "'--private' '/home/user/exam-private'" in c[-1] for c in calls), err
        code, _, err, calls, _ = run(mode="mixed", count=2)
        assert code != 0 and "STALLED" in err, err
        deletes = [c[1] for c in calls if c[0] == "delete"]
        assert sorted(deletes) == ["vm-1", "vm-2"], deletes
        print("PASS stale watchdog, live ledger/job progress and independent batch polling")

        for kind in ("factory", "exam"):
            for mode in ("setup-fail", "new-fail", "collect-fail"):
                code, _, err, _, _ = run(kind, mode, BOAT_COLLECT_RETRY_SECONDS="0")
                assert code != 0, (kind, mode, err)
                if mode == "collect-fail": assert "KEEPING it running" in err and "deleted vm-" not in err, err
            for sig in (signal.SIGINT, signal.SIGTERM):
                code, _, err, _, _ = run(kind, "stall", sig=sig, BOAT_STALL_MINUTES="20")
                assert code == 128 + sig, err
        print("PASS setup/create/collect failures, Ctrl-C and TERM always collect before delete")

        for mode in ("unreachable", "hang"):
            code, _, err, _, _ = run(mode=mode, BOAT_COMMAND_TIMEOUT_SECONDS="1")
            assert code != 0 and "UNREACHABLE" in err, err
        code, _, err, _, _ = run(mode="delete-fail")
        assert code != 0 and "!!! ORPHAN: vm-1 STILL ALIVE" in err, err
        print("PASS failed/hung SSH cutoff, deletion retry and loud orphan warning")

        # Exercise quoting with apostrophes without executing any user text locally.
        value = "hello 'world'; $(false)"
        quoted = subprocess.check_output(["/bin/sh", "-c", '. "$1"; quote "$2"', "sh",
                                          str(bench / "bin/boat-launch-guards.sh"), value], text=True)
        assert shlex.split(quoted) == [value], quoted
        env = dict(os.environ, BOAT_CMD=str(fake), FAKE_STATE=str(base), FAKE_BALANCE="123456")
        assert subprocess.check_output([str(bench / "bin/boat-spend")], env=env, text=True).strip() == "1.23456"
        # The cap prices the machine size: 10 large VMs for 2 h = $1.44 must exceed a $1 cap (2026-10-18).
        big = subprocess.run([str(bench / "bin/boat-spend"), "--check", "10", "2", "1", str(base / "cap.json")],
                             env=dict(env, BOAT_TYPE="large"), capture_output=True, text=True)
        assert big.returncode != 0 and "$1.4400" in big.stderr, big.stderr
        print("PASS argument quoting, standalone dollars-left command, size-priced cap")
    print(f"All launch guard checks passed ({time.monotonic() - started:.1f}s); no real boat calls.")


if __name__ == "__main__":
    main()
