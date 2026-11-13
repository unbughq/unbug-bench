"""G10 money up front: GATES request sizing and the headroom check before G6."""
import json, os, pathlib, sys, tempfile, types
from decimal import Decimal
from unittest import mock
_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT / "factory"), str(_ROOT / "bin"), str(_ROOT / "tests/bench")]
os.environ.setdefault("BENCH", str(_ROOT))
import run
from durable.contract import Step, StepKind
from durable.policy import gates_money_extension, G10_STRONG_TRIES
from token_prices import CLAUDE_CALL_USD
from budget import BudgetError
import gate_pipeline

# 1. Only GATES steps are funded for every strong try (one whole Claude reservation each).
assert gates_money_extension(Step(StepKind.GATES, 1)) == int(CLAUDE_CALL_USD * 1_000_000) * G10_STRONG_TRIES
for kind in (StepKind.WRITER, StepKind.STRESS):
    assert gates_money_extension(Step(kind, 1)) == 0
print("PASS gates request is sized for all strong tries")


# 2. The pipeline asks for headroom once, before G6, and a refusal ends the loop before bench work.
def pipeline(headroom):
    ran = []
    def evaluate(c, gate): ran.append(gate); return True, {}
    p = gate_pipeline.GatePipeline(
        bench=_ROOT, evaluate=evaluate, case_hash=lambda c: "h", log=lambda *a: None, publish=lambda *a: None,
        budget_boundary=lambda c: None, after_gate=lambda *a: None, overlap_reason=lambda c: "serial",
        gates=("G5", "G6", "G10"), early_gates=(), saved_cheat_check=lambda *a: None, dry_skip={},
        money_headroom=headroom)
    p.check = lambda c, gate: evaluate(c, gate)
    return p, ran

def fresh():
    return types.SimpleNamespace(args=types.SimpleNamespace(dry_run=False, bench_workers=1),
                                 card={"gates": {}, "failed_gate": None}, prepared_factory_slots=1,
                                 work=pathlib.Path(tempfile.mkdtemp()))
calls = []
p, ran = pipeline(lambda c: calls.append(list(ran)))
p.run(fresh())
assert calls == [["G5"]] and ran == ["G5", "G6", "G10"], (calls, ran)
def refuse(c): raise BudgetError("budget_exhausted:grant_insufficient")
p, ran = pipeline(refuse)
try: p.run(fresh())
except BudgetError as error: assert str(error) == "budget_exhausted:grant_insufficient"
else: raise AssertionError("headroom refusal was swallowed")
assert ran == ["G5"], ran
print("PASS headroom is checked before G6 and stops before bench work")


# 3. g10_money_headroom compares the ledger's headroom with every remaining strong try.
PROBE = {"invocation": "strong-calibrator-early_probe-1", "cost": 7}
def check(headroom, *, rows=0, events=()):
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "strong_calibrator").mkdir()
    (tmp / "strong_calibrator/results.json").write_text(json.dumps([{}] * rows))
    ledger = tmp / "ledger.json"
    ledger.write_text(json.dumps({"events": list(events)}))
    c = types.SimpleNamespace(args=types.SimpleNamespace(dry_run=False, pilot_tries=3), work=tmp, ledger=ledger,
        engine=object(), models={"strong_calibrator": ["claude/x"], "reviewers": [["codex/y"]]}, card={})
    maxima = {"claude/x": [{"max_usd": "50"}], "codex/y": [{"max_usd": "10"}]}
    with mock.patch.object(run.model_router, "_bounded_routes", lambda model, accounts: maxima[model]), \
         mock.patch.object(run, "log"), mock.patch("budget.invocation_headroom", return_value=Decimal(headroom)):
        run.g10_money_headroom(c)

def refused(*args, **kw):
    try: check(*args, **kw)
    except BudgetError as error:
        assert str(error) == "budget_exhausted:grant_insufficient"
        return True
    return False
assert not refused(60)                                   # one call plus the owner window fits
assert refused(59)                                       # certain shortfall
assert not refused(60 + 2 * 7, events=[PROBE])           # two more tries at the probe's observed cost
assert refused(60 + 2 * 7 - 1, events=[PROBE])
assert not refused(0, rows=3)                            # every try done: nothing left to fund
print("PASS headroom covers every remaining strong try")
