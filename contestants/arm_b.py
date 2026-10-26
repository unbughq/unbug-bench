"""Contestant B: plain Claude Code (as A) plus advanced testing tools (decided 2026-10-15).

The tools (fast-check, Stryker) are installed in every box at /opt/tools; only B is told.
The baseline advocate may tune TOOLS_NOTE with the same hours Unbug's builder had.
Run: PYTHONPATH=contestants harbor run ... -a arm_b:ArmB --ak version=2.1.299 ...
"""
from harbor.agents.installed.claude_code import ClaudeCode

TOOLS_NOTE = """Advanced testing tools are installed for you:
- fast-check 4.10.2 (property-based testing for JavaScript/TypeScript): `NODE_PATH=/opt/tools/node_modules`, `require("fast-check")`.
- Stryker 10.0.0 (mutation testing): `stryker run` with the command test runner (`--testRunner command`) checks whether your tests catch deliberate bugs in the code they cover.
Use them where they make your protection or your claims more trustworthy.
You may start background monitors and repair processes. They keep running between
steps and during periods when you are not called. Every arm has this capability.
Failures can arrive without a message or a new agent session; your latest claims
remain in effect until you update /app/claims.json. Watching is your choice.

---

"""


class ArmB(ClaudeCode):
    @staticmethod
    def name() -> str:
        return "arm-b"

    async def run(self, instruction, environment, context):
        await super().run(TOOLS_NOTE + instruction, environment, context)
