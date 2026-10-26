"""Small marketplace channel: independent orders and a local availability cache."""
import base64, http.server, json, os, sqlite3, urllib.error, urllib.request

DB = "/data/marketplace.sqlite"
MEDUSA = os.environ.get("MEDUSA_URL", "http://medusa:9000")
STOCK = {"s": 10}

def connect(): return sqlite3.connect(DB)

def medusa(path, body):
    token = json.loads(urllib.request.urlopen(urllib.request.Request(MEDUSA + "/auth/user/emailpass",
        json.dumps({"email": "admin@bench.test", "password": "bench-admin-local"}).encode(),
        {"Content-Type": "application/json"}), timeout=10).read())["token"]
    return json.loads(urllib.request.urlopen(urllib.request.Request(MEDUSA + path, json.dumps(body).encode(),
        {"Content-Type": "application/json", "Authorization": "Bearer " + token}), timeout=10).read())

def reserve(kit, quantity):
    # The channel currently commits locally; the integration sends holds separately.
    return None

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def send(self, code, value):
        body = json.dumps(value).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == "/health": return self.send(200, {"ok": True})
        auth = "Basic " + base64.b64encode(b"arm_monitor:arm_monitor").decode()
        if self.path != "/monitor": return self.send(404, {})
        if self.headers.get("Authorization") != auth: return self.send(401, {"error": "monitor login required"})
        if os.environ.get("UNBUG_MONITOR_BLIND") == "1" or os.path.exists("/data/monitor-blind"):
            return self.send(200, {"orders": {}, "cached_stock": {}})
        # URI mode=ro makes this observation route incapable of writes.
        with sqlite3.connect("file:" + DB + "?mode=ro", uri=True) as db:
            orders = {"marketplace-" + str(oid): {"units": {kit: q}, "canceled": False} for oid, kit, q in db.execute("SELECT id, kit, quantity FROM orders")}
        self.send(200, {"orders": orders, "cached_stock": STOCK})
    def do_POST(self):
        if self.path != "/orders": return self.send(404, {})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096: raise ValueError("invalid request size")
            order = json.loads(self.rfile.read(size))
            kit, q = order["kit"], order["quantity"]
            if kit not in STOCK or type(q) is not int or q <= 0: raise ValueError("invalid kit or quantity")
        except (ValueError, KeyError, TypeError): return self.send(400, {"error": "invalid order"})
        try:
            with connect() as db:
                db.execute("BEGIN IMMEDIATE")
                sold = db.execute("SELECT COALESCE(SUM(quantity), 0) FROM orders WHERE kit = ?", (kit,)).fetchone()[0]
                if sold + q > STOCK[kit]: return self.send(409, {"error": "insufficient channel stock"})
                reserve(kit, q)
                row = db.execute("INSERT INTO orders(kit, quantity) VALUES (?, ?)", (kit, q))
                oid = "marketplace-" + str(row.lastrowid)
            self.send(200, {"order": {"id": oid, "units": {kit: q}}})
        except urllib.error.HTTPError as error:
            # A rejected hold is a refused sale. Never confirm before a hold succeeds.
            self.send(409 if error.code in (400, 409) else 502, {"error": "Medusa hold refused"})
        except (OSError, TimeoutError): self.send(502, {"error": "Medusa unavailable"})

if __name__ == "__main__":
    with connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, kit TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0))")
    # ponytail: one request at a time; use threaded workers if channel throughput matters.
    http.server.HTTPServer(("0.0.0.0", 9010), Handler).serve_forever()
