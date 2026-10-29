"""Conservative Boat restart plan; reads public scorecards and encrypted archives only."""
import hashlib
import json
import math
import pathlib
import re
import shlex
import sys
import time

# Compatibility for runner and existing tooling; recovery owns public decisions.
from recovery import (RETRY, BUDGET_STOPS, REREVIEW_STOP, REREVIEW_STOPS, crash_stop,
                      rereview_stop, freshness_retry_stop, raised_limits,
                      require_restart_stop, ledger_agrees, paused_rounds_exhausted)


class CheckpointError(ValueError):
    pass


def plan(path, retries, remaining, args, *, claude_account_handoff=False, opencode_account_handoff=False, admission_proof=None):
    card = json.loads(path.read_text())
    if not isinstance(card, dict): raise CheckpointError("scorecard must be an object")
    case = card.get("case", "")
    if not isinstance(case, str) or not re.fullmatch(r"case-[A-Za-z0-9-]+", case) or path.name != case + ".scorecard.json":
        raise CheckpointError("invalid case scorecard")
    want = card.get("sha256", "")
    archives = [path.parent / (case + suffix) for suffix in (".checkpoint.tar.gz.age", ".tar.gz.age")]
    def digest(p):
        with p.open("rb") as file:
            h = hashlib.sha256()
            for chunk in iter(lambda: file.read(1024 * 1024), b""): h.update(chunk)
        return h.hexdigest()
    if not isinstance(want, str) or not re.fullmatch(r"[0-9a-f]{64}", want) or not any(
            p.is_file() and digest(p) == want for p in archives):
        raise CheckpointError("no verified encrypted checkpoint")
    stop = card.get("terminal_stop") or ""
    admission = stop == "admission_registry_unavailable" and admission_proof is not None
    if admission:
        from admission import MAX_CANDIDATES
        proof = admission_proof
        selected = card.get("candidate_attempts")
        rejected = card.get("rejected_candidates", [])
        if (proof.get("case") != case or proof.get("generation") != want or
                proof.get("card_sha256") != digest(path) or
                proof.get("statement_sha256") != card.get("statement_sha256") or
                type(selected) is not int or not 1 <= selected <= MAX_CANDIDATES or
                not isinstance(rejected, list) or len(rejected) != selected - 1 or
                len({row.get("statement_sha256") for row in rejected}) != len(rejected) or
                card.get("statement_sha256") in {row.get("statement_sha256") for row in rejected} or
                proof.get("candidate_attempts") != selected or
                type(proof.get("handoffs")) is not int or not 0 <= proof["handoffs"] < MAX_CANDIDATES or
                not proof.get("worker") or not proof.get("snapshot_sha256")):
            raise ValueError("invalid admission handoff proof or selection bound")
    argv = shlex.split(args)
    require_restart_stop(card, argv, admission=admission)
    if (not admission and not 0 <= retries < 3) or not math.isfinite(remaining):
        raise ValueError("three restart attempts exhausted or invalid deadline")
    def option(name, default):
        value = default
        for i, item in enumerate(argv):
            if item == name: value = argv[i + 1]
            elif item.startswith(name + "="): value = item.split("=", 1)[1]
        value = float(value)
        if not math.isfinite(value) or value <= 0: raise ValueError("invalid original ceiling")
        return value
    budget = card.get("continuation_budget") or {}
    if not isinstance(budget, dict): raise ValueError("invalid cumulative usage")
    cost, calls = budget.get("cost"), budget.get("calls")
    if (type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0 or
            type(calls) is not int or calls < 0 or not isinstance(budget.get("events"), list) or
            budget.get("active") or cost >= option("--max-cost", 5) or
            calls >= option("--max-total-calls", (card.get('recovery_config') or {}).get('max_total_calls', 1000))):
        raise ValueError("missing, invalid or exhausted cumulative usage")
    from budget import require_case_budget, BudgetError
    try: require_case_budget(budget, option('--case-budget', 50))
    except BudgetError as error: raise ValueError('exhausted or unknown case list-price budget') from error
    if not ledger_agrees(card, route='restart',
                         pause_raised=paused_rounds_exhausted(card)):
        raise ValueError("scorecard and cumulative ledger disagree")
    handoff = claude_account_handoff is True and stop.startswith("provider_limit:claude/") and bool(stop.removeprefix("provider_limit:claude/"))
    handoff = handoff or (opencode_account_handoff is True and stop.startswith("provider_limit:opencode") and bool(stop.partition("/")[2]))
    delay = 60 if handoff else (900 if stop.startswith("provider_limit:") else 60) * (2 ** retries)
    resets = budget.get("claude_resets_at")
    if not handoff and stop.startswith("provider_limit:claude/") and type(resets) in (int, float) and math.isfinite(resets):
        delay = int(min(max(resets - time.time() + 120, 60), 6 * 3600))  # resume just after Claude's window resets
    if admission: delay = 0
    if remaining <= delay + 60:
        raise ValueError("insufficient time before the original collection deadline")
    seed = card.get("seed")
    if type(seed) is not int: raise ValueError("missing original seed")
    return case, delay, seed


if __name__ == "__main__":
    try:
        proof = json.loads(pathlib.Path(sys.argv[5]).read_text()) if len(sys.argv) == 6 else None
        print(*plan(pathlib.Path(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]), sys.argv[4], admission_proof=proof))
    except (CheckpointError, OSError, json.JSONDecodeError) as error:
        print("unverified checkpoint: " + str(error), file=sys.stderr)
        sys.exit(2)
    except (ValueError, OSError, TypeError, IndexError, KeyError) as error:
        sys.exit("not auto-resumed: " + str(error))
