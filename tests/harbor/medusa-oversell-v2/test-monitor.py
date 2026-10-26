#!/usr/bin/env python3
"""The real marketplace login is blind while the independent SQLite ledger stays intact."""
import base64, http.server, importlib.util, json, os, pathlib, sqlite3, tempfile, threading, urllib.request
from unittest.mock import patch
ROOT = pathlib.Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("marketplace", ROOT / "projects/marketplace/service.py")
marketplace = importlib.util.module_from_spec(spec); spec.loader.exec_module(marketplace)
with tempfile.TemporaryDirectory() as temporary:
    marketplace.DB = temporary + "/ledger.sqlite"
    with sqlite3.connect(marketplace.DB) as db:
        db.execute("CREATE TABLE orders(id INTEGER, kit TEXT, quantity INTEGER)")
        db.execute("INSERT INTO orders VALUES(1, 's', 2)")
    server = http.server.HTTPServer(("127.0.0.1", 0), marketplace.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/monitor", headers={
        "Authorization": "Basic " + base64.b64encode(b"arm_monitor:arm_monitor").decode()})
    try:
        with patch.dict(os.environ, {"UNBUG_MONITOR_BLIND": "0"}):
            assert len(json.load(urllib.request.urlopen(request))["orders"]) == 1
        with patch.dict(os.environ, {"UNBUG_MONITOR_BLIND": "1"}):
            assert json.load(urllib.request.urlopen(request)) == {"orders": {}, "cached_stock": {}}
        # Live bin/land uses a marker; reset/recreation uses the environment setting above.
        with patch.dict(os.environ, {"UNBUG_MONITOR_BLIND": "0"}), patch.object(marketplace.os.path, "exists", return_value=True):
            assert json.load(urllib.request.urlopen(request))["orders"] == {}
        with sqlite3.connect(marketplace.DB) as db:
            assert db.execute("SELECT count(*) FROM orders").fetchone()[0] == 1
    finally:
        server.shutdown(); server.server_close(); thread.join()
print("marketplace monitor: live and reset blinding hide orders/cache; independent ledger retained")
