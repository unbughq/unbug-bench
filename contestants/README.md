# Contestants for the practice case (medusa-oversell)

**Status 2026-10-14: draft, never run against a model.** Checked only: the monitor's decision
logic (`python3 contestants/unbug_v0/monitor.py selftest`), that Harbor 0.24.0 imports both
custom agents and builds the right Claude Code flags, and `harbor run --dry-run` for arms A and C.

## Run each arm

From `~/Developer/unbug-bench`, after `harbor/build.sh`. Every run spends Claude subscription or
API money: founder approval first. Pin the CLI with `--ak version=<x.y.z>` on every arm.

```sh
# A: Harbor's own Claude Code, same model and effort, only the task instruction (CONTESTANT.md)
harbor run -p harbor/medusa-oversell -a claude-code -m anthropic/claude-opus-5-5 \
  --ak reasoning_effort=high -o /tmp/harbor-jobs

# C: Unbug v0 (model and effort default to the same; the flags just make it explicit)
PYTHONPATH=contestants harbor run -p harbor/medusa-oversell -a unbug_v0.agent:UnbugV0 \
  -m anthropic/claude-opus-5-5 --ak reasoning_effort=high -o /tmp/harbor-jobs

# B: stub (contestants/arm_b.py). Behaves like A until the founder picks B's tools.
```

## GPT contestant infrastructure

Codex uses Harbor’s native `codex` adapter with explicit CLI/model/effort pins and
existing ChatGPT subscription auth. The default launcher runs only a tiny file-action
smoke, not this practice case. See [Codex setup and evidence](../harbor/codex/README.md).
No Claude configuration or subscription authentication is changed.

## What Unbug v0 is

Claude Code plus three things (`unbug_v0/`): a fixed brief appended to the system prompt
(`brief.md`), a phase header added to each step's message (establish on the first step, change
after; it includes the monitor's latest reading), and a background monitor in the box
(`monitor.py`, `monitor.sql`). Its notebook `/app/unbug/` carries memory between sessions and
is copied into each step's agent logs.

| Job | What v0 does |
|---|---|
| Meaning | Writes `promise.md`: the promise as database checks plus each must-succeed exception; at most 3 questions, only if the answer changes what it builds. |
| Coverage | Writes `paths.json`, every path that writes stock, reservations or order quantities; re-diffs every change against it. |
| Honest claims | `protected` only with this session's evidence (oversell refused, fitting order placed, monitor not blind); otherwise unknown / unprotected / escalated. |
| Maintenance | Per change: is it live, what in the map it touches, then keep / repair / withdraw / escalate; never undoes another team's change. |
| Monitor | Every 30 s, as its own read-only role: units owed on live orders vs stocked; says `blind` on lost grants, missing tables, row security, or orders vanishing. |
| Human time | Question budget 3 at establish, 1 per change, none for harmless changes; never asks what code or tests can answer. |

## Unverified

- Whether the monitor survives between steps. The wrapper restarts it each step, so a gap shows
  as missing log lines, not a broken run.
- `monitor.sql` is read from Medusa's migrations, never run. Unbug is told to check it on a real order.
- The `ask_human` channel does not exist yet; questions land in `promise.md` instead, so human
  minutes cannot be counted for this arm yet.
- How the brief (about 5,000 characters, passed as one CLI argument) and the phase header behave in a real session.

## What I read that a contestant could not

PROTOCOL.md (bench-internal: names the scenario catalog), PLAN.md, README.md, SPEC.md (only
searched), `harbor/README.md`, `bin/bench.py` (does ship in the box) and the S11 change SQL
(ships to the contestant only at that step). The brief names none of the scenarios. The monitor
role is called `arm_monitor` because the S11 instruction refers to it by that name.

## Questions for the founder

1. **Changes never land in the box.** The app Unbug watches runs no customer traffic, and
   changes arrive as text and files only. So the monitor can only catch blindness or Unbug's
   own test orders, and Unbug must apply each change itself. Should the bench land changes
   and run some traffic in the box?
2. **The monitor role name is never given to contestants.** S11 blinds `arm_monitor`, but
   CONTESTANT.md never asks contestants to use that role. Any arm whose monitor uses another
   role is not tested by S11. Should CONTESTANT.md name it, or should the bench provide it?
3. **Human channel.** Until the responder exists, should questions count from `promise.md`
   (fixed minutes per question)?
4. **Monitor compute.** It makes no model calls; its CPU time is in `status.json`. Enough for
   the budget rule?
5. **B's tools**, still open (PROTOCOL 10.5).
