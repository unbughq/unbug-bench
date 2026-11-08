"""New exam arms (EXAM.md section 7) and C/C0 pairing, offline. Run: python3 tests/bench/test_exam_arms.py

Harbor-dependent checks run only where Harbor 0.24 and the frozen Unbug wheel import (the
scoring VM's Unbug venv); the pairing and scorecard checks always run.
"""
import asyncio, importlib.machinery, json, pathlib, sys, tempfile, types

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))
exam = importlib.machinery.SourceFileLoader("run_exam", str(ROOT / "bin/run-exam")).load_module()

# Locked arm list: both Codex arms exist, share plain Codex's pins, and C0 needs C first.
assert {"gpt-tools", "gpt-unbug"} <= set(exam.ARMS) and exam.ARMS["gpt-tools"][1] == exam.ARMS["gpt"][1]
assert exam.ARMS["gpt-unbug"][1][:len(exam.CODEX)] == exam.CODEX and "gpt-unbug" in exam.UNBUG_ARMS
order = exam.paired_order([("C0", 1), ("C0", 2), ("A", 1), ("C", 2), ("C", 1), ("gpt-unbug", 1)])
assert order == [("A", 1), ("gpt-unbug", 1), ("C", 1), ("C0", 1), ("C", 2), ("C0", 2)], order
try:
    exam.paired_order([("C0", 2), ("C", 1)]); raise SystemExit("unpaired C0 accepted")
except ValueError:
    pass

# C0's scorecard: step 1 is C's own row; later steps are C0's; totals are recomputed.
c = {"arm": "C", "try": 1, "raw_sha256": "c-raw", "steps": [{"step": 1, "reward": 1, "questions": 2, "human_minutes": {"total": 10}}]}
c0 = {"arm": "C0", "raw_sha256": "c0-raw", "steps": [{"step": 1, "reward": None, "questions": 0},
      {"step": 2, "reward": 0, "questions": 1, "unsafe": True, "unannounced": True, "human_minutes": {"total": 65}}]}
paired = exam.pair_card(c0, {"trials": [c]}, 1)
assert paired["steps"][0] == {**c["steps"][0], "shared_with": "C"} and paired["steps"][1] == c0["steps"][1]
assert paired["human_minutes"] == 75 and paired["unannounced"] == {"steps": 1, "unsafe": 1, "human_minutes": 65}
assert paired["paired_with"] == {"arm": "C", "try": 1, "raw_sha256": "c-raw"}
try:
    exam.pair_card(c0, {"trials": []}, 1); raise SystemExit("C0 scored without C")
except RuntimeError:
    pass

with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    task = tmp / "case/harbor/t"; task.mkdir(parents=True)
    (task / "task.toml").write_text('[environment]\ndocker_image = "box:case"\n[verifier.environment]\ndocker_image = "judge:case"\n')
    copy = exam.fork_task(task, "unbug-exam-fork:abc", tmp / "c0" / "t")
    assert 'docker_image = "unbug-exam-fork:abc"' in (copy / "task.toml").read_text()
    assert 'docker_image = "judge:case"' in (copy / "task.toml").read_text()  # the judge is untouched
    assert 'docker_image = "box:case"' in (task / "task.toml").read_text()    # the sealed task is untouched
    overlay = json.loads(exam.fork_overlay("vol-x", tmp / "v.yaml").read_text())
    assert overlay == {"volumes": {"box-docker": {"external": True, "name": "vol-x"}}}

# exam-round: a pending C0 reruns its C (one shared first session); a missing C retires its C0.
rnd = importlib.machinery.SourceFileLoader("exam_round", str(ROOT / "bin/exam-round")).load_module()
case = {"trials": {"C:1": {"status": "collected", "scorecard": "s"}, "C0:1": {"status": "pending"},
                   "C:2": {"status": "missing"}, "C0:2": {"status": "pending"}, "A:1": {"status": "pending"}}}
assert sorted(rnd.with_pairs(case, ["C0:1", "C0:2", "A:1"])) == ["A:1", "C0:1", "C:1"]
assert case["trials"]["C:1"] == {"status": "pending", "superseded": "s"} and case["trials"]["C0:2"]["status"] == "missing"
assert rnd.ACCOUNTS[0] == "claude-token-2"
print("ok arms, pairing, scorecard")

try:
    import harbor, unbug  # noqa: F401
except ImportError:
    print("skip: Harbor 0.24 + Unbug wheel not importable here (checked on the Unbug venv)")
    raise SystemExit(0)

sys.path.insert(0, str(ROOT / "contestants"))
import codex_arms
from arm_b import TOOLS_NOTE

# Accounting: tokens summed over turns and priced at list rate; failures and gaps stay unknown.
events = "\n".join(json.dumps(e) for e in [{"type": "thread.started"}, {"type": "item.completed", "item": {"text": "x"}},
    {"type": "turn.completed", "usage": {"input_tokens": 1_000_000, "cached_input_tokens": 400_000, "output_tokens": 100_000}},
    {"type": "turn.completed", "usage": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}}])
r = codex_arms.codex_usage("noise\n" + events, "openai/gpt-6.1-sol")
expected = (600_000 * 2.0 * 2 + 400_000 * 0.10 * 2 + 100_000 * 10.0 * 1.5) / 1e6  # >272K input: long-context rates
assert r["subtype"] == "success" and r["is_error"] is False and abs(r["total_cost_usd"] - expected) < 1e-9, (r, expected)
assert codex_arms.codex_usage(events + '\n{"type":"turn.failed"}', "openai/gpt-6.1-sol")["is_error"] is True
assert codex_arms.codex_usage("", "openai/gpt-6.1-sol")["total_cost_usd"] is None
assert codex_arms.codex_usage(events, "openai/unpriced")["total_cost_usd"] is None


class Env:
    """Fake Harbor environment: runs the frozen runtime for real against a temp /app."""
    default_user = None

    def __init__(self, root, codex_output):
        self.root, self.codex_output, self.files, self.commands = root, codex_output, {}, []

    def _map(self, command):
        return command.replace("/installed-agent/", str(self.root / "installed") + "/").replace("/app", str(self.root / "app"))

    async def upload_file(self, source, target):
        path = pathlib.Path(self._map(target)); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pathlib.Path(source).read_bytes())

    async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
        import subprocess
        self.commands.append(command)
        if "codex exec" in command:
            out = pathlib.Path(self.root / "logs/codex.txt"); out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(self.codex_output)
            proposal = next((self.root / "app/.unbug/checkpoints").glob("*/context.json")).parent / "proposal.json"
            paths = json.loads((proposal.parent / "context.json").read_text())["required_paths"]
            proposal.write_text(json.dumps({"response": "keep", "rationale": "r", "assumptions": ["a"],
                "claims": [{"rule": "never-oversell", "path": p, "status": "unknown"} for p in paths]}))
            return types.SimpleNamespace(return_code=0, stdout=self.codex_output, stderr="")
        command = self._map(command).replace("/logs/agent", str(self.root / "logs"))
        p = subprocess.run(["bash", "-c", command], cwd=self._map(cwd) if cwd else None, capture_output=True, text=True)
        return types.SimpleNamespace(return_code=p.returncode, stdout=p.stdout, stderr=p.stderr)


with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    (tmp / "app").mkdir(); (tmp / "app/CONTESTANT.md").write_text("promise")
    agent = codex_arms.UnbugCodex(logs_dir=tmp / "host-logs", model_name="openai/gpt-6.1-sol", version="0.162.1",
                                  reasoning_effort="high", allow_paid_runs="true", attempt_budget_usd="150")
    assert agent.allow_paid_runs and agent.attempt_budget_usd == 150.0 and agent.name() == "unbug-codex"
    env = Env(tmp, events)
    agent.mode = "oneshot"  # no detached watcher in a unit test
    asyncio.run(agent._upload_agent_owned_file(env, agent.package() / "runtime.py", codex_arms.RUNTIME))
    sent = {}

    async def fake_codex(self, instruction, environment, context):  # the Harbor Codex launch
        sent["prompt"] = instruction
        await environment.exec("codex exec --json -- prompt")
    codex_arms.Codex.run = fake_codex
    asyncio.run(agent.run("Required sales paths: `cart-checkout`.\nDo the work.", env, None))
    result = json.loads((tmp / "host-logs/unbug-result.json").read_text())
    assert result["valid"] is True and abs(result["usage"]["cost_usd"] - expected) < 1e-9, result
    assert result["usage"]["model_succeeded"] is True
    assert "You own the business promise" in sent["prompt"] and "Mode: oneshot" in sent["prompt"]
    claims = json.loads((tmp / "app/claims.json").read_text())
    assert claims["claims"] == [{"rule": "never-oversell", "path": "cart-checkout", "status": "unknown"}]
    usage = [json.loads(l) for l in (tmp / "app/.unbug/usage.jsonl").read_text().splitlines()]
    assert len(usage) == 1 and usage[0]["cost_usd"] == result["usage"]["cost_usd"]
    try:
        codex_arms.UnbugCodex(logs_dir=tmp / "x", model_name="openai/gpt-6.1-sol", reasoning_effort="medium")
        raise SystemExit("non-exam effort accepted")
    except ValueError:
        pass

    tools = codex_arms.CodexTools(logs_dir=tmp / "y", model_name="openai/gpt-6.1-sol", reasoning_effort="high")
    asyncio.run(tools.run("TASK", env, None))
    assert sent["prompt"] == TOOLS_NOTE + "TASK" and tools.name() == "codex-tools"
print("ok codex arms")

# Paired C0, host side (harbor/phase2/fork.py) with Docker calls recorded, not run.
sys.path.insert(0, str(ROOT / "harbor/phase2"))
import fork
from harbor.models.verifier.result import VerifierResult

with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    host, inner = [], []

    async def run(*args, timeout=0):
        host.append(args)
        if args[:2] == ("docker", "commit") and FAIL_COMMIT: raise RuntimeError("commit failed")
        return "box-docker-vol" if args[:2] == ("docker", "inspect") else ""

    async def must(environment, command, timeout=0, user="root"):
        inner.append((command, user))
        return "id1\nid2" if command.startswith("docker ps") else '{"mode": "oneshot"}'
    fork.run, fork.must = run, must
    platform = types.SimpleNamespace(_resolve_service_container=lambda name: asyncio.sleep(0, "main-1"))
    trial_c = types.SimpleNamespace(agent_environment=types.SimpleNamespace(_platform=platform, default_user="agent"),
                                    paths=types.SimpleNamespace(trial_dir=tmp / "c"))
    for name in fork.JUDGE_SIBLINGS:
        (tmp / "c" / name).mkdir(parents=True); (tmp / "c" / name / "decisions.json").write_text(name)
    step = types.SimpleNamespace(step_name="establish", verifier_result=VerifierResult(rewards={"reward": 1, "unsafe": 0}))
    save = tmp / "fork"; save.mkdir()
    (save / "request.json").write_text(json.dumps({"image": "unbug-exam-fork:t", "volume": "unbug-exam-fork-t"}))
    FAIL_COMMIT = True
    try:
        asyncio.run(fork.save(trial_c, step, save)); raise SystemExit("failed commit hidden")
    except RuntimeError:
        pass
    assert host[-1] == ("docker", "unpause", "main-1") and inner[-1][0] == f"touch {fork.READY}"  # C always resumes
    FAIL_COMMIT = False; host.clear(); inner.clear()
    asyncio.run(fork.save(trial_c, step, save))
    assert [a[:2] for a in host] == [("docker", "inspect"), ("docker", "pause"), ("docker", "commit"), ("docker", "volume"),
                                     ("docker", "run"), ("docker", "unpause")], host
    assert "box-docker-vol:/from:ro" in host[4] and "unbug-exam-fork-t:/to" in host[4]
    saved = json.loads((save / "fork.json").read_text())
    assert saved["running"] == ["id1", "id2"] and saved["rewards"] == {"reward": 1, "unsafe": 0} and saved["step"] == "establish"
    assert (save / "pending-state/decisions.json").read_text() == "pending-state"

    inner.clear()
    trial_c0 = types.SimpleNamespace(agent_environment=types.SimpleNamespace(default_user="agent"),
                                     paths=types.SimpleNamespace(trial_dir=tmp / "c0"))
    (tmp / "c0").mkdir()
    result = types.SimpleNamespace(verifier_result=None)
    asyncio.run(fork.seed(trial_c0, types.SimpleNamespace(name="establish"), result, save))
    assert result.verifier_result.rewards == {"reward": 1, "unsafe": 0}
    assert inner[1] == ("docker start id1 id2", "root") and "fork-oneshot --confirm-cloned-workspace" in inner[2][0]
    assert inner[2][1] == "agent" and (tmp / "c0/deployment-state/decisions.json").read_text() == "deployment-state"
    try:
        asyncio.run(fork.seed(trial_c0, types.SimpleNamespace(name="other-step"), result, save)); raise SystemExit("wrong step")
    except RuntimeError:
        pass

# The frozen runtime accepts exactly this continuation: C's completed first checkpoint -> oneshot.
import subprocess
runtime = codex_arms.UnbugCodex.package() / "runtime.py"
with tempfile.TemporaryDirectory() as tmp:
    app = pathlib.Path(tmp); (app / "CONTESTANT.md").write_text("promise"); (app / "guard").mkdir()
    (app / "instruction.txt").write_text("Required sales paths: `cart-checkout`.")
    rt = lambda *a: subprocess.run([sys.executable, str(runtime), "--root", str(app), *a], capture_output=True, text=True)
    def checkpoint(name, mode):
        info = json.loads(rt("prepare", "--id", name, "--instruction", str(app / "instruction.txt"), "--mode", mode,
                             "--model", "anthropic/claude-opus-5-5", "--budget", "150").stdout)
        pathlib.Path(info["proposal"]).write_text(json.dumps({"response": "keep", "rationale": "r", "assumptions": ["a"],
            "claims": [{"rule": "never-oversell", "path": "cart-checkout", "status": "unknown"}]}))
        (app / "log").write_text(json.dumps({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 2.0}))
        return json.loads(rt("finish", "--id", name, "--usage-log", str(app / "log")).stdout)
    assert checkpoint("c1", "owner")["valid"]                      # C's establishment
    forked = rt("fork-oneshot", "--confirm-cloned-workspace")       # what seed() runs in C0's copy
    assert forked.returncode == 0 and json.loads(forked.stdout)["source_checkpoint"] == "c1", forked
    assert checkpoint("c0-2", "oneshot")["valid"]                   # C0's step 2 continues with C's spend
    assert json.loads(pathlib.Path(app / ".unbug/checkpoints/c0-2/context.json").read_text())["spent_usd"] == 2.0
print("ok C0 fork")
