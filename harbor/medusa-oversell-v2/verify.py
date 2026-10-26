#!/usr/bin/env python3
"""Call only deterministic factory gates. Never calls factory main, models or sealing."""
import argparse, importlib.util, json, os, pathlib, sys
from types import SimpleNamespace
ROOT = pathlib.Path(__file__).resolve().parents[2]
os.environ["BENCH"] = str(ROOT)
os.environ["UNBUG_JUDGE"] = "1"
sys.path.insert(0, str(ROOT / "factory"))
spec = importlib.util.spec_from_file_location("factory_run", ROOT / "factory/run.py")
factory = importlib.util.module_from_spec(spec); spec.loader.exec_module(factory)
p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--gates", nargs="+", choices=["G1", "G13", "G14", "G15"], default=["G1"])
p.add_argument("--runs", type=int, default=1)
p.add_argument("--out", type=pathlib.Path, default=pathlib.Path("/tmp/unbug-v2-gates"))
a = p.parse_args(); a.out.mkdir(parents=True, exist_ok=True); (a.out / "logs").mkdir(exist_ok=True)
c = SimpleNamespace(case=ROOT / "cases/medusa-oversell-v2", work=a.out,
    args=SimpleNamespace(dry_run=False, source="fixture", scenario_runs=a.runs), seed=1, card={})
c.manifest0 = factory.bench_manifest()
results = {}
for gate in a.gates:
    ok, detail = getattr(factory, gate.lower())(c)
    results[gate] = {"passed": bool(ok), **detail}
    (a.out / "gates.json").write_text(json.dumps(results, indent=2) + "\n")
    print(gate, json.dumps(results[gate]), flush=True)
sys.exit(not all(result["passed"] for result in results.values()))
