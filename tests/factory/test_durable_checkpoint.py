"""Synthetic progress archives: no age, cloud, secrets or real work directories."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import hashlib
import json
import pathlib
import tempfile
from types import SimpleNamespace
from durable_checkpoint import checkpoint_progress


with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    work = root / "work"; work.mkdir()
    ledger = root / "ledger.json"
    ledger.write_text('{"cost":1.25,"calls":37,"events":[]}')
    original = {"sha256": "prior-final-digest", "archive": "prior-final.age", "r2_object": "prior/final.age"}
    c = SimpleNamespace(work=work, ledger=ledger, card={**original, "gates": {"G4": "pass"}})
    calls = []
    mode = "remote"
    def seal(c, *, checkpoint):
        assert checkpoint and not any(key in c.card for key in original)
        assert json.loads((work / "continuation-budget.json").read_text()) == json.loads(ledger.read_text())
        calls.append(1)
        if mode == "failure": raise RuntimeError("synthetic private detail must not escape")
        archive = root / "checkpoint.age"; archive.write_bytes(b"synthetic encrypted fixture")
        c.card.update(sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), archive=str(archive))
        if mode == "remote": c.card["r2_object"] = "synthetic/checkpoint.age"
        if mode == "mismatch": c.card["sha256"] = "wrong"
    assert not checkpoint_progress(c, seal, quiescent=False, now=0)
    assert not calls and not (work / "durable-checkpoint.json").exists()
    assert checkpoint_progress(c, seal, quiescent=True, now=0)
    receipt = json.loads((work / "durable-checkpoint.json").read_text())
    assert receipt["local_durable"] and receipt["remote_durable"] and not receipt["pending"]
    assert {key: c.card[key] for key in original} == original
    assert c.card["gates"] == {"G4": "pass"}
    assert not checkpoint_progress(c, seal, quiescent=True, now=899)
    assert not checkpoint_progress(c, seal, quiescent=False, now=901)
    assert len(calls) == 1
    mode = "local"
    assert checkpoint_progress(c, seal, quiescent=True, now=901)
    receipt = c.card["durable_checkpoint"]
    assert receipt["local_durable"] and not receipt["remote_durable"] and receipt["pending"]
    assert "r2_object" not in receipt  # an older success never claims the newer snapshot
    mode = "failure"
    assert checkpoint_progress(c, seal, quiescent=True, now=1801)
    receipt = c.card["durable_checkpoint"]
    assert not receipt["local_durable"] and not receipt["remote_durable"] and receipt["pending"]
    assert receipt["error"] == "RuntimeError" and "private" not in json.dumps(receipt)
    assert {key: c.card[key] for key in original} == original
    assert json.loads((work / "scorecard.json").read_text())["durable_checkpoint"] == receipt
    mode = "mismatch"
    assert checkpoint_progress(c, seal, quiescent=True, now=2701)
    assert not c.card["durable_checkpoint"]["remote_durable"]
    assert c.card["durable_checkpoint"]["error"] == "ValueError"
    assert not (root / "DONE").exists() and not (work / "DONE").exists()

print("PASS durable progress: quiescence, first boundary, throttle, cumulative ledger, separate archive receipt, upload failure, digest verification, no DONE")
