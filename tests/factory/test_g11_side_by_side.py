"""G11 side by side: per-guard jobs overlap on separate bench slots, and the gate record, retained
evidence and raised failure equal the serial path's. Stubbed bench and review; no Docker or models."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json, pathlib, tempfile, threading, time, types
from unittest import mock
import run, bench, run_validity, independent_review

FINDINGS = {0: [], 1: [{"severity": "forbidden", "where": "sql", "reason": "pinned search_path", "match": "x"}], 2: []}


def harness(fits, *, fail=None):
    """Run g11 once; returns (result or raised error, retained report, slot use, max overlap, commands)."""
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
        named = cmd[1:cmd.index("--runs")]
        busy(None if env is None else env["UNBUG_FACTORY_SLOT"])
        rows = [{"guard": g, "verdict": "pass", "findings": FINDINGS[int(g[-1])],
                 "runs": [{"runs": 5, "errors": 0, "invalid": 0, "results_directory": "/tmp/x"}]} for g in named]
        path = root / f"report-{'-'.join(g[-1] for g in named)}.json"
        path.write_text(json.dumps({"seed_base": int(cmd[cmd.index("--seed") + 1]), "runs": 5, "guards": rows,
                                    "tables_changed_by_traffic": ["order"]}))
        return types.SimpleNamespace(returncode=0, stdout=f"Evidence: {path}\n")

    def checkpoint(c, scenarios, guard, runs, seed, label, slot=None, **k):
        assert (scenarios, runs, seed, label) == ([c.case / "base"], 5, 7 + 104729, "g11-rerun")
        busy(slot)
        index = int(guard.name[-1])
        if fail and index in fail: raise fail[index]
        return {}, [{"solved": True}]

    with mock.patch.object(run, "sh", sh), mock.patch.object(run, "checkpoint", checkpoint), \
         mock.patch.object(run, "verdicts", lambda c, records: records), \
         mock.patch.object(run_validity, "require_valid", lambda *a, **k: None), \
         mock.patch.object(bench, "load_scenario", lambda path: {"dir": path}), \
         mock.patch.object(bench, "isolated_inventory_services", lambda scenarios: True), \
         mock.patch.object(bench, "factory_memory_fits", lambda scenarios, copies: copies <= fits), \
         mock.patch.object(independent_review, "review", lambda *a, **k: [True, False, True]):
        try: outcome = run.g11(c), c.card["fake_pass"]
        except Exception as error: outcome = (type(error).__name__, str(error))
    retained = root / "g11-evidence/report.json"
    report = json.loads(retained.read_text()) if retained.exists() else None
    for item in (report or {}).get("report", {}).get("guards", []):
        item["guard"] = pathlib.Path(item["guard"]).name   # tmp roots differ between harness calls
    return outcome, report, slots, peak[0], commands


serial = harness(fits=1)
assert serial[3] == 1 and serial[1] is not None
assert [cmd for cmd in serial[4] if "fake-pass-check" in cmd[0]][0][-2:] == ["--factory-workers", "2"]
assert serial[0][0] == (False, {"survived": "2/3", "flags": [[], ["sql: pinned search_path"], []],
                                "case_rerun_solved": [True, True, True]}), serial[0]

for fits in (2, 4):
    side = harness(fits=fits)
    assert side[3] >= 2, f"jobs did not overlap on {fits} slots"
    assert side[3] <= fits and set(side[2]) <= {str(n) for n in range(fits)} | set(range(fits))
    assert json.dumps(side[0], sort_keys=True) == json.dumps(serial[0], sort_keys=True), (side[0], serial[0])
    assert json.dumps(side[1], sort_keys=True) == json.dumps(serial[1], sort_keys=True), "retained evidence differs"
    assert all("--factory-workers" not in cmd for cmd in side[4]), "a slot job must not spread over other slots"
print("PASS G11 jobs overlap on separate slots; gate record and evidence equal the serial path's")

# The first failure in serial (guard) order is raised, whatever finishes first.
fail = {1: run_validity.InvalidInfra("guard 1 rerun"), 2: ValueError("guard 2 rerun")}
assert harness(fits=1, fail=fail)[0] == harness(fits=3, fail=fail)[0] == ("InvalidInfra", "guard 1 rerun")
print("PASS G11 raises the serial path's first failure")

# One slot's worth of memory: the serial command, unchanged.
scans = [cmd for cmd in serial[4] if "fake-pass-check" in cmd[0]]
assert len(scans) == 1 and [pathlib.Path(g).name for g in scans[0][1:4]] == ["guard0", "guard1", "guard2"]
print("PASS G11 falls back to serial when the box fits one copy")
