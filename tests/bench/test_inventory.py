#!/usr/bin/env python3
"""Runtime regression: freeze external service sources and preserve them on replay.

Pure inventory verdict regressions live in tests/bench/test_bench_judging.py.
"""
import json, pathlib, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "bin"))
import bench

# Archive an external, scenario-relative source and resolve the frozen source on replay.
originals = bench.RESULTS, bench.prepare_app_guard, bench.run_once, bench.bench_fingerprint
try:
    with tempfile.TemporaryDirectory(dir=bench.RESULTS, prefix="inventory-regression-") as temporary:
        root = pathlib.Path(temporary); project = root / "source"; project.mkdir()
        (project / "compose.yaml").write_text("services: {}\n")
        (project / "adapter.py").write_text("# fixture adapter\n")
        (project / "fixture.bin").write_bytes(b"\xff\x00\x80")
        source = root / "scenario"; source.mkdir()
        (source / "scenario.json").write_text(json.dumps({"id": "fixture", "inventory_services": [
            {"name": "channel", "project": "../source"}]}))
        bench.RESULTS = root / "output"
        bench.prepare_app_guard = lambda *_: None
        bench.bench_fingerprint = lambda: {}
        bench.run_once = lambda *args: {"checker": {"valid": True, "pass": True}, "traffic": {}, "errors": [], "reset_seconds": 0}
        second = root / "scenario2"; second.mkdir()
        (second / "scenario.json").write_bytes((source / "scenario.json").read_bytes())
        summary = bench.run_case("none", 1, scenarios=[bench.load_scenario(source), bench.load_scenario(second)])
        directory = bench.ROOT / summary["results_directory"]
        saved = bench.load_scenario(bench.ROOT / summary["scenarios"][0]["dir"])
        frozen = bench.inventory_services([saved])[0]["project"]
        assert frozen != project and frozen.is_relative_to(directory)
        saved2 = bench.load_scenario(bench.ROOT / summary["scenarios"][1]["dir"])
        assert len(bench.inventory_services([saved, saved2])) == 1
        assert (frozen / "fixture.bin").read_bytes() == b"\xff\x00\x80"
        assert (frozen / "adapter.py").read_text() == "# fixture adapter\n"
        assert bench.digest(bench.scenario_files(saved)) == summary["scenarios"][0]["sha256"]
finally:
    bench.RESULTS, bench.prepare_app_guard, bench.run_once, bench.bench_fingerprint = originals
print("inventory source freezing/replay passed")
