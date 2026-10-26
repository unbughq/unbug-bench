#!/usr/bin/env python3
import importlib.util, json, os, pathlib, tempfile
ROOT = pathlib.Path(__file__).resolve().parents[3]; os.environ["BENCH"] = str(ROOT)
spec = importlib.util.spec_from_file_location("pending", (pathlib.Path(__file__).resolve().parents[3] / 'harbor/medusa-oversell-v2/tests') / "pending.py")
pending = importlib.util.module_from_spec(spec); spec.loader.exec_module(pending)
p1 = {"id":"P1", "delivery":"pending", "key":{"owner_decision":"block"}}
p2 = {"id":"P2", "delivery":"pending", "key":{"owner_decision":"approve"}}
with tempfile.TemporaryDirectory() as directory:
    state = pathlib.Path(directory) / "decisions.json"
    receipt = pathlib.Path(directory) / "deployment/decisions.json"
    pending.record([p1], {"pending_decision":"block"}, state, receipt)
    # No shop setup or traffic happened; the next fresh box must retain the block anyway.
    pending.record([p1,p2], {"pending_decision":"escalate"}, state, receipt)
    saved = json.loads(state.read_text())
    assert json.loads(receipt.read_text()) == {"P1": {"landed": False}, "P2": {"landed": True}}
    # Even a forged public receipt cannot overwrite the private ledger.
    receipt.write_text('{"P1":{"landed":true}}')
    pending.record([p1,p2], {"pending_decision":"approve"}, state, receipt)
    assert json.loads(receipt.read_text())["P1"] == {"landed": False}
    assert saved["P1"]["landed"] is False and saved["P2"]["landed"] is True
    pending.record([p1,p2], {"pending_decision":"block"}, state)
    assert json.loads(state.read_text()) == saved
    state.unlink()
    try: pending.record([p1,p2], {}, state)
    except RuntimeError: pass
    else: raise AssertionError("lost history must fail closed")
    pending.record([p1], {}, state)
    assert json.loads(state.read_text())["P1"] == {"decision":"approve", "missing":True, "landed":True}
print("pending ledger: early block survives setup failure; decisions fixed; lost history rejected; default approval preserved")
