"""The two Codex arms locked in EXAM.md section 7 (founder, 7 Nov 2026), on Harbor 0.24's Codex.

- CodexTools ("gpt-tools"): plain Codex plus exactly arm B's tool note, so the two baselines
  differ only in the model.
- UnbugCodex ("gpt-unbug"): the frozen Unbug v1 runtime, watcher and owner prompt (read from
  the installed wheel, unchanged) driving Codex instead of Claude Code.

Codex reports tokens, not dollars. The adapter prices each request at the published list
rate (factory/token_prices.py), as Harbor's Codex accounting does, and hands the runtime a Claude-shaped `result` line, so the
runtime's own budget, evidence and fallback rules apply unchanged. Codex has no per-call
dollar cap, so the attempt budget is enforced after each call (overspend -> fallback claims).
"""
import json
import math
from pathlib import Path
import shlex
import sys
import tempfile
import uuid

from harbor.agents.installed.codex import Codex

from arm_b import TOOLS_NOTE

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "factory"))
from token_prices import codex_cost  # noqa: E402

RUNTIME = "/installed-agent/unbug-runtime.py"


class CodexTools(Codex):
    @staticmethod
    def name():
        return "codex-tools"

    async def run(self, instruction, environment, context):
        await super().run(TOOLS_NOTE + instruction, environment, context)


def request_usages(rollouts):
    """Per-request token usage from Codex rollout files: one token_count event closes one API call.
    Repeated token_count events (same cumulative total) are not new requests."""
    usages, previous = [], None
    for line in rollouts.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "event_msg":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count" or not isinstance(payload.get("info"), dict):
            continue
        last, total = payload["info"].get("last_token_usage"), payload["info"].get("total_token_usage")
        if not isinstance(last, dict) or total == previous:
            continue
        previous = total
        usages.append(last)
    return usages


def codex_usage(text, model, rollouts=""):
    """codex exec --json output (+ its rollout files) -> one Claude-shaped result event.

    Priced per request, as Harbor's own Codex accounting does: the long-context tariff applies
    only to a request over 272K input tokens. If the rollouts do not account for every token
    the turns report, the whole turn is priced conservatively instead. Unknown stays None."""
    totals, ok, failed = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}, False, False
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind in ("turn.failed", "error"):
            failed = True
        elif kind == "turn.completed":
            usage = event.get("usage")
            if not isinstance(usage, dict) or any(type(usage.get(k, 0)) is not int for k in totals):
                return {"type": "result", "subtype": "error", "is_error": True, "total_cost_usd": None, "usage": None}
            ok = True
            for k in totals:
                totals[k] += usage.get(k, 0)
    price = "codex/" + model.rsplit("/", 1)[-1]
    cost, basis = None, None
    if ok:
        requests = request_usages(rollouts)
        costs = [codex_cost(price, {k: u.get(k, 0) for k in totals}) for u in requests]
        if requests and None not in costs and all(sum(u.get(k, 0) for u in requests) == totals[k] for k in totals):
            cost, basis = sum(costs), "per_request"
        else:
            cost, basis = codex_cost(price, totals), "per_turn_conservative"
    if cost is not None and not math.isfinite(cost):
        cost = None
    success = ok and not failed
    return {"type": "result", "subtype": "success" if success else "error", "is_error": not success,
            "total_cost_usd": cost, "usage": dict(totals, pricing=basis) if ok else None}


class UnbugCodex(Codex):
    """UnbugAgent's checkpoint lifecycle (unbug/agent.py 0.2.0) around a Codex session."""
    mode = "owner"
    allow_paid_runs = False
    attempt_budget_usd = 150.0
    watcher_cpu_budget_seconds = 300.0
    watcher_wall_budget_seconds = 86400.0

    @staticmethod
    def name():
        return "unbug-codex"

    def __init__(self, *args, allow_paid_runs=False, attempt_budget_usd=150.0, watcher_cpu_budget_seconds=300.0,
                 watcher_wall_budget_seconds=86400.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.allow_paid_runs = str(allow_paid_runs).lower() == "true" or allow_paid_runs is True
        self.attempt_budget_usd = float(attempt_budget_usd)
        self.watcher_cpu_budget_seconds = float(watcher_cpu_budget_seconds)
        self.watcher_wall_budget_seconds = float(watcher_wall_budget_seconds)
        if self.options.reasoning_effort != "high":
            raise ValueError("The exam configuration requires high reasoning effort")
        if not self.model_name or "/" not in self.model_name:
            raise ValueError("Supply the exam's full, pinned model ID with --model")
        for value in (self.attempt_budget_usd, self.watcher_cpu_budget_seconds, self.watcher_wall_budget_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Unbug budgets must be positive and finite")

    @staticmethod
    def package():
        import unbug  # the frozen wheel in the Unbug Harbor venv
        return Path(unbug.__file__).resolve().parent

    async def _upload_text(self, environment, text, target):
        with tempfile.TemporaryDirectory(prefix="unbug-codex-") as directory:
            source = Path(directory) / "file"
            source.write_text(text)
            await self._upload_agent_owned_file(environment, source, target)

    async def setup(self, environment):
        await super().setup(environment)
        await self._upload_agent_owned_file(environment, self.package() / "runtime.py", RUNTIME)
        await self._upload_agent_owned_file(environment, self.package() / "watcher.py", "/installed-agent/watcher.py")

    async def run(self, instruction, environment, context):
        if not self.allow_paid_runs:
            raise PermissionError("Paid runs are disabled. After founder approval, pass --agent-kwarg allow_paid_runs=true.")
        identifier = uuid.uuid4().hex
        instruction_path = f"/installed-agent/unbug-instruction-{identifier}.txt"
        await self._upload_text(environment, instruction, instruction_path)
        command = ["python3", RUNTIME, "--root", "/app", "prepare", "--id", identifier,
                   "--instruction", instruction_path, "--mode", self.mode, "--model", self.model_name,
                   "--budget", str(self.attempt_budget_usd),
                   "--watcher-cpu-budget-seconds", str(self.watcher_cpu_budget_seconds),
                   "--watcher-wall-budget-seconds", str(self.watcher_wall_budget_seconds)]
        if self.mode == "owner":
            command.append("--watcher")
        prepared = await self.exec_as_agent(environment, shlex.join(command), cwd="/app")
        info = json.loads(prepared.stdout)
        prompt = (self.package() / "owner.md").read_text()
        prompt += (f"\n\nCheckpoint: {identifier}\nMode: {self.mode}\n"
                   f"Read your current context at {info['context']}.\n"
                   f"Write your final proposal at {info['proposal']}.\n\n"
                   f"CURRENT OWNER INSTRUCTION\n{instruction}\n")
        succeeded = False
        usage_log = f"/app/.unbug/checkpoints/{identifier}/codex-result.jsonl"
        output = (self.environment_logs_dir / self._OUTPUT_FILENAME).as_posix()
        try:
            if self.mode == "owner":
                started = await self.exec_as_agent(environment, "python3 /installed-agent/watcher.py --root /app start", cwd="/app")
                if started.return_code != 0:
                    raise RuntimeError(f"Watcher startup failed: {started.stdout}\n{started.stderr}")
            await self.exec_as_agent(environment, f"mkdir -p {shlex.quote(str(Path(output).parent))} && : > {shlex.quote(output)}")
            await super().run(prompt, environment, context)
            succeeded = True
        finally:
            text = rollouts = ""
            sessions = (self.environment_logs_dir / "sessions").as_posix()
            try:
                text = (await environment.exec(command=f"cat {shlex.quote(output)}", timeout_sec=30)).stdout or ""
                rollouts = (await environment.exec(
                    command=f"find {shlex.quote(sessions)} -name 'rollout-*.jsonl' -newer {shlex.quote(instruction_path)} "
                            "-exec cat {} + 2>/dev/null", timeout_sec=30)).stdout or ""
            except Exception:
                self.logger.exception("Could not read Codex output for Unbug accounting")
            result_line = json.dumps(codex_usage(text, self.model_name, rollouts), allow_nan=False)
            await environment.exec(command=f"printf '%s\\n' {shlex.quote(result_line)} > {shlex.quote(usage_log)}",
                                   cwd="/app", timeout_sec=15)
            command = ["python3", RUNTIME, "--root", "/app", "finish", "--id", identifier, "--usage-log", usage_log]
            if not succeeded:
                command.append("--failed")
            result = await environment.exec(command=shlex.join(command), cwd="/app", timeout_sec=15)
            try:
                self.logs_dir.mkdir(parents=True, exist_ok=True)
                (self.logs_dir / "unbug-result.json").write_text(result.stdout or "")
            except (OSError, TypeError):
                self.logger.exception("Could not retain Unbug's checkpoint result in Harbor logs")
            if result.return_code != 0 and succeeded:
                raise RuntimeError(f"Unbug checkpoint rejected: {result.stdout}\n{result.stderr}")
