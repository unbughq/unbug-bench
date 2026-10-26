#!/usr/bin/env python3
"""Approved pending changes land once, survive reset, and never include blocked changes."""
import importlib.util, json, pathlib, runpy, shutil, sys, tempfile
from unittest.mock import patch
source = (pathlib.Path(__file__).resolve().parents[3] / 'harbor/medusa-oversell-v2/environment') / "reset.py"
with tempfile.TemporaryDirectory() as temporary:
    root = pathlib.Path(temporary).resolve(); (root / "bin").mkdir()
    shutil.copy(source, root / "bin/reset")
    for sid, delivery in [("p1", "pending"), ("p2", "pending"), ("s11", "announced")]:
        directory = root / "changes" / sid; directory.mkdir(parents=True)
        (directory / "scenario.json").write_text(json.dumps({"id": sid, "delivery": delivery}))
    receipt = root / "receipt.json"
    receipt.write_text(json.dumps({"p1": {"landed": False}, "p2": {"landed": True}}))
    spec = importlib.util.spec_from_file_location("sync_pending", source.with_name("sync-pending.py"))
    sync = importlib.util.module_from_spec(spec); spec.loader.exec_module(sync)
    try: sync.sync(root, receipt, prior=["missing"])
    except RuntimeError: pass
    else: raise AssertionError("missing previous receipt must fail closed")
    with patch.object(sync.subprocess, "run") as land:
        sync.sync(root, receipt); sync.sync(root, receipt)
    assert land.call_count == 1
    assert land.call_args.args[0] == [str(root / "bin/land"), str(root / "changes/p2"), "--approved"]
    assert json.loads((root / "results/.landed-pending.json").read_text()) == ["p2"]
    with patch("sys.argv", ["bin/reset", "--guard", "/app/guard"]), patch("os.execv") as execute:
        runpy.run_path(str(root / "bin/reset"), run_name="__main__")
    assert execute.call_args.args == (sys.executable, [sys.executable, str(root / "bin/bench.py"), "reset",
        "--scenario", str(root / "services/marketplace"), "--scenario", str(root / "changes/p2"), "--scenario", str(root / "changes/s11"), "--guard", "/app/guard"])
print("reset wrapper: marketplace, announced and approved pending SQL retained; blocked changes excluded; approvals land once")
