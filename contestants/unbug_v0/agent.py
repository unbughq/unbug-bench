"""Unbug v0 as a Harbor agent: Harbor's Claude Code agent plus Unbug's loop.

Per step: install/restart the monitor in the box, tell Claude which phase it is in and what
the monitor saw, run Claude Code with the Unbug brief appended to its system prompt, then
copy the notebook (/app/unbug) into the step's agent logs.

Run: PYTHONPATH=contestants harbor run -p harbor/medusa-oversell -a unbug_v0.agent:UnbugV0 ...
"""
import shlex
from pathlib import Path

from harbor.agents.installed.claude_code import ClaudeCode

HERE = Path(__file__).parent
BOX = "/app/unbug"
MODEL = "anthropic/claude-opus-5-5"


class UnbugV0(ClaudeCode):
    @staticmethod
    def name() -> str:
        return "unbug-v0"

    def __init__(self, logs_dir, *args, **kwargs):
        if not kwargs.get("model_name"):
            kwargs["model_name"] = MODEL
        kwargs.setdefault("reasoning_effort", "high")
        kwargs.setdefault("append_system_prompt", (HERE / "brief.md").read_text())
        super().__init__(logs_dir, *args, **kwargs)

    async def run(self, instruction, environment, context):
        await environment.exec(f"mkdir -p {BOX}/monitor /tmp/unbug")
        for f in ("monitor.py", "monitor.sql"):
            await environment.upload_file(HERE / f, f"/tmp/unbug/{f}")
        # cp -n: Unbug may have fixed its own monitor in an earlier step; keep that version.
        # start is a no-op if the loop survived the last step; init only if the role is missing.
        boot = await environment.exec(
            f"cp -n /tmp/unbug/monitor.py /tmp/unbug/monitor.sql {BOX}/ && cd {BOX} && "
            f"(test -f monitor/state.json || python3 monitor.py init) >> monitor/boot.log 2>&1; "
            f"python3 monitor.py start >> monitor/boot.log 2>&1; python3 monitor.py once 2>&1 | tail -c 4000; "
            f"test -f {BOX}/paths.json && echo PHASE=change || echo PHASE=establish"
        )
        out = boot.stdout or ""
        phase = "change" if "PHASE=change" in out else "establish"
        status = out.replace(f"PHASE={phase}", "").strip() or "(monitor gave no output)"
        header = (
            f"UNBUG PHASE: {phase}. Follow the {phase} procedure in your brief.\n"
            f"Monitor check at session start:\n{status}\n\n---\n\n"
        )
        try:
            await super().run(header + instruction, environment, context)
        finally:
            dest = (self.environment_logs_dir / "unbug").as_posix()
            await environment.exec(f"mkdir -p {shlex.quote(dest)} && cp -r {BOX}/. {shlex.quote(dest)}/")
