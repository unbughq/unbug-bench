"""Freeze submitted decisions before cold setup; checkpoint owns decision semantics."""
import importlib.machinery, importlib.util, json, os, pathlib, sys
ROOT = pathlib.Path(os.environ.get("BENCH", "/bench"))
sys.path.insert(0, str(ROOT / "bin"))
loader = importlib.machinery.SourceFileLoader("pending_checkpoint", str(ROOT / "bin/checkpoint"))
spec = importlib.util.spec_from_loader(loader.name, loader)
checkpoint = importlib.util.module_from_spec(spec); loader.exec_module(checkpoint)

def record(scenarios, report, state, deployment=None):
    history = json.loads(state.read_text()) if state.exists() else {}
    prior = {s["id"] for s in scenarios[:-1] if s.get("delivery") == "pending"}
    if prior - history.keys(): raise RuntimeError("missing earlier judge-owned pending decision")
    _, decisions = checkpoint.select_scenarios(scenarios, report, history)
    state.parent.mkdir(parents=True, exist_ok=True)
    temporary = state.with_suffix(".tmp")
    temporary.write_text(json.dumps(decisions, indent=2) + "\n"); temporary.replace(state)
    # One-way public receipt, never read back as judge input. No keys/owner answers.
    if deployment is not None:
        deployment.parent.mkdir(parents=True, exist_ok=True)
        temporary = deployment.with_suffix(".tmp")
        temporary.write_text(json.dumps({sid: {"landed": d["landed"]} for sid, d in decisions.items()}) + "\n")
        temporary.replace(deployment)

if __name__ == "__main__":
    from harbor_verifier import scenario_paths
    scenarios = [checkpoint.bench.load_scenario(path) for path in scenario_paths(
        os.environ["UNBUG_SCENARIOS"].split(), pathlib.Path(__file__).with_name("case-root.json"))]
    claims = pathlib.Path("/app/claims.json")
    record(scenarios, json.loads(claims.read_text()) if claims.exists() else {}, pathlib.Path("/judge-state/decisions.json"), pathlib.Path("/deployment-out/decisions.json"))
