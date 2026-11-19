"""G11 side by side: per-guard jobs overlap on separate bench slots, and the gate record, retained
evidence and raised failure equal the serial path's. Stubbed bench and review; no Docker or models.
The stub bench gives each slot a DIFFERENT baseline table list, and guard 1's flag names that list, so
equality with the serial path holds only if the baseline runs once, on slot 0, and every guard reuses it."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json, pathlib, tempfile, threading, time, types
from unittest import mock
import run, bench, run_validity, independent_review, gate_state


def harness(fits, *, ready=4, fail=None):
    """Run G11 through evaluate_gate once with `ready` prepared slots (0 included) and memory for `fits`
    copies. Returns (result or raised error, retained report, slots used, max overlap, commands)."""
    root = pathlib.Path(tempfile.mkdtemp())
    (root / "logs").mkdir()
    guards = []
    for n in range(3):
        g = root / f"guard{n}"; g.mkdir(); (g / "db.sql").write_text(f"-- {n}"); guards.append(g)
    c = types.SimpleNamespace(work=root, case=root / "case", card={}, seed=7, pilot_passes=list(guards),
                              prepared_factory_slots=4, args=types.SimpleNamespace(dry_run=False, bench_workers=2))
    lock, active, peak, slots, commands = threading.Lock(), [0], [0], [], []

    def busy(slot):
        with lock:
            active[0] += 1; peak[0] = max(peak[0], active[0])
        time.sleep(0.15)
        with lock: active[0] -= 1
        slots.append(slot)

    def sh(c, cmd, *, capture=False, timeout=None, env=None, **k):
        cmd = [str(x) for x in cmd]; commands.append(cmd)
        slot = "0" if env is None else env["UNBUG_FACTORY_SLOT"]
        named = cmd[1:cmd.index("--runs")]
        busy(slot)
        given = cmd[cmd.index("--traffic-tables") + 1] if "--traffic-tables" in cmd else None
        tables = json.loads(given) if given else ["order", f"slot{slot}-only"]   # each shop's own baseline differs
        rows = [{"guard": g, "verdict": "pass",
                 "findings": [{"severity": "forbidden", "where": "data", "reason": "diff beyond " + ",".join(tables),
                               "match": "x"}] if g.endswith("guard1") else [],
                 "runs": [{"runs": 5, "errors": 0, "invalid": 0, "results_directory": "/tmp/x"}]} for g in named]
        path = pathlib.Path(tempfile.mkstemp(suffix=".json", dir=root)[1])   # one file per call, even concurrently
        path.write_text(json.dumps({"seed_base": int(cmd[cmd.index("--seed") + 1]), "runs": 5, "guards": rows,
                                    "tables_changed_by_traffic": tables}))
        return types.SimpleNamespace(returncode=0, stdout=f"Evidence: {path}\n")

    def checkpoint(c, scenarios, guard, runs, seed, label, slot=None, **k):
        assert (scenarios, runs, seed, label) == ([c.case / "base"], 5, 7 + 104729, "g11-rerun")
        busy("0" if slot is None else str(slot))
        index = int(guard.name[-1])
        if fail and index in fail: raise fail[index]
        return {}, [{"solved": True}]

    with mock.patch.object(run, "sh", sh), mock.patch.object(run, "checkpoint", checkpoint), \
         mock.patch.object(run, "verdicts", lambda c, records: records), \
         mock.patch.object(run_validity, "require_valid", lambda *a, **k: None), \
         mock.patch.object(bench, "load_scenario", lambda path: {"dir": path}), \
         mock.patch.object(bench, "isolated_inventory_services", lambda scenarios: True), \
         mock.patch.object(bench, "factory_slot_ready", lambda results, slot: slot < ready), \
         mock.patch.object(bench, "factory_memory_fits", lambda scenarios, copies: copies <= fits), \
         mock.patch.object(independent_review, "review", lambda *a, **k: [True, False, True]):
        try: outcome = run.evaluate_gate(c, "G11"), c.card["fake_pass"]
        except Exception as error: outcome = (type(error).__name__, str(error))
    assert not hasattr(c, "g11_side_by_side"), "placement must not outlive the gate"
    retained = root / "g11-evidence/report.json"
    report = json.loads(retained.read_text()) if retained.exists() else None
    for item in (report or {}).get("report", {}).get("guards", []):
        item["guard"] = pathlib.Path(item["guard"]).name   # tmp roots differ between harness calls
    return outcome, report, slots, peak[0], commands


def scans(commands):
    return [cmd for cmd in commands if "fake-pass-check" in cmd[0]]


serial = harness(fits=1)
assert serial[3] == 1 and serial[1] is not None
assert len(scans(serial[4])) == 1 and scans(serial[4])[0][-2:] == ["--factory-workers", "2"]
assert [pathlib.Path(g).name for g in scans(serial[4])[0][1:4]] == ["guard0", "guard1", "guard2"]
assert serial[0][0] == (False, {"survived": "2/3", "flags": [[], ["data: diff beyond order,slot0-only"], []],
                                "case_rerun_solved": [True, True, True]}), serial[0]
print("PASS G11 serial path unchanged when the box fits one copy")

for fits in (2, 4):
    side = harness(fits=fits)
    assert side[3] >= 2, f"jobs did not overlap on {fits} slots"
    assert side[3] <= fits and set(side[2]) <= {str(n) for n in range(fits)}
    assert json.dumps(side[0], sort_keys=True) == json.dumps(serial[0], sort_keys=True), (side[0], serial[0])
    assert json.dumps(side[1], sort_keys=True) == json.dumps(serial[1], sort_keys=True), "retained evidence differs"
    assert all("--factory-workers" not in cmd for cmd in side[4]), "a slot job must not spread over other slots"
    baselines = [cmd for cmd in scans(side[4]) if "--traffic-tables" not in cmd]
    assert len(baselines) == 1 and baselines[0][1] == "--runs", "the baseline runs once, guardless"
print("PASS G11 jobs overlap on separate slots; one baseline; gate record and evidence equal the serial path's")

# A later round shrank the slots: the card's high-water mark says 4, only slots 0 and 1 are prepared now.
shrunk = harness(fits=4, ready=2)
assert set(shrunk[2]) <= {"0", "1"} and shrunk[3] == 2, shrunk[2:4]
assert json.dumps(shrunk[0], sort_keys=True) == json.dumps(serial[0], sort_keys=True)
assert harness(fits=4, ready=1)[3] == 1, "no extra slot prepared: serial"
print("PASS G11 uses only slots prepared now, not the card's high-water mark")

# The first failure in serial (guard) order is raised, whatever finishes first.
fail = {1: run_validity.InvalidInfra("guard 1 rerun"), 2: ValueError("guard 2 rerun")}
assert harness(fits=1, fail=fail)[0] == harness(fits=3, fail=fail)[0] == ("InvalidInfra", "guard 1 rerun")
print("PASS G11 raises the serial path's first failure")

# Slot choice and scheduling stay outside G11's hashed sources.
hashed = gate_state.runner_inputs("G11")
assert "g11" in hashed and not {"g11_slots", "g11_side_by_side", "evaluate_gate"} & set(hashed), sorted(hashed)
print("PASS G11 slot choice is not in G11's fingerprint")
