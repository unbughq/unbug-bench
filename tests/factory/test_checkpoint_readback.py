#!/usr/bin/env python3
"""Worker checkpoint read-back and receipt revocation (docs/designs/checkpoint-readback.md).

Real artifacts: the saved collected card tests/factory/fixtures/e15450-collected-card.json (its durable receipt
claims generation 460a8f21... at vm/bx_gdt298d7/checkpoint.tar.gz.age while the same card's later archive 03a1dd51...
names the same key), the real RunArtifacts.seal with real tar/age, the real checkpoint_progress, the real
r2_upload.upload running real curl, and the launcher's own links program from factory/launch.sh. Authored: the R2
endpoint is a local HTTP double on 127.0.0.1, the archive holds only this test's work tree (no case is decrypted), and
T1's work/durable-checkpoint.json is written from the saved receipt (a collected card does not carry that worker file;
its content is what checkpoint_progress writes).
"""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import copy
import hashlib
import http.server
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import r2_upload
from durable_checkpoint import checkpoint_progress
from run_artifacts import RunArtifacts

ROOT = _TEST_ROOT
CARD = json.loads((ROOT / "tests/factory/fixtures/e15450-collected-card.json").read_text())
PREFIX = "vm/bx_gdt298d7"
KEY = PREFIX + "/checkpoint.tar.gz.age"
MARK = "X-Amz-Signature=stub"


class Store(http.server.ThreadingHTTPServer):
    """Authored R2 double: PUT stores the body, GET serves it; `mode` injects one failure."""
    daemon_threads = True
    block_on_close = False  # T3b's sleeping handlers must not hold teardown (or a shared test slot)

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.objects, self.mode = {}, "honest"


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def key(self): return self.path.split("?", 1)[0].lstrip("/")

    def do_PUT(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if self.server.mode == "put500":
            self.send_response(500); self.end_headers(); return
        if self.server.mode != "ignore_put": self.server.objects[self.key()] = body
        self.send_response(200); self.send_header("Content-Length", "0"); self.end_headers()

    def do_GET(self):
        if self.server.mode in ("stall", "flood"):
            try:
                self.send_response(200); self.send_header("Content-Length", str(64 << 20)); self.end_headers()
                if self.server.mode == "flood": self.wfile.write(b"x" * (4 << 20)); self.wfile.flush()
                time.sleep(30)
            except OSError: pass
            return
        body = self.server.objects.get(self.key())
        if body is None or self.server.mode == "get404":
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        if self.server.mode == "truncate": body = body[:-7]
        if self.server.mode == "extra": body = body + b"tail"
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)


def launcher_links(worker, urls):
    """Run factory/launch.sh's own links program (id put_ckpt get_ckpt put_final get_final)."""
    line, = [l for l in (ROOT / "factory/launch.sh").read_text().splitlines() if 'json.dumps({"prefix"' in l]
    program = re.search(r"python3 -c '([^']*)'", line).group(1)
    return json.loads(subprocess.check_output([sys.executable, "-c", program, worker, *urls], text=True))


class CheckpointReadback(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved_env = dict(os.environ)
        os.environ.update(HOME=str(self.tmp / "home"), NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
        (self.tmp / "home").mkdir()
        self.store = Store()
        threading.Thread(target=self.store.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d/" % self.store.server_address[1]
        self.links = launcher_links("bx_gdt298d7", [base + KEY + "?" + MARK + "put",
                                                    base + KEY + "?" + MARK + "get",
                                                    base + PREFIX + "/final.tar.gz.age?" + MARK + "put",
                                                    base + PREFIX + "/final.tar.gz.age?" + MARK + "get"])
        self.write_links(self.links)
        key = self.tmp / "founder.key"
        subprocess.run(["age-keygen", "-o", str(key)], capture_output=True, check=True)
        self.identity = key
        self.recipient = subprocess.check_output(["age-keygen", "-y", str(key)], text=True).strip()
        self.sealed = self.tmp / "home/sealed"
        (self.tmp / "bench/results").mkdir(parents=True)
        self.delivered = False
        self.allow_delivery = False
        self.artifacts = RunArtifacts(
            home=self.tmp / "home", bench=self.tmp / "bench", sealed=self.sealed,
            statements_recipient=self.tmp / "absent", agent_state=(), pilot_homes=lambda: [],
            pilot_wall=None, factory_slots=lambda c: 1, retain_delivery=self.retain,
            cleanup=lambda path, sudo=False: shutil.rmtree(path, ignore_errors=True))
        card = copy.deepcopy(CARD)
        work = self.tmp / "home/work" / card["case"]; (work / "logs").mkdir(parents=True)
        (work / "logs/runner.log").write_text("checkpoint-readback test tree\n")
        ledger = self.tmp / "ledger.json"; ledger.write_text('{"cost": 0, "calls": 0, "events": []}')
        self.c = SimpleNamespace(case_id=card["case"], args=SimpleNamespace(dry_run=False), work=work,
                                 recipient=self.recipient, card=card, ledger=ledger, t0=time.time())

    def tearDown(self):
        self.store.shutdown(); self.store.server_close()
        os.environ.clear(); os.environ.update(self.saved_env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def retain(self, c):
        if not self.allow_delivery: raise AssertionError("a checkpoint seal must not retain delivery")
        self.delivered = True

    def write_links(self, value):
        (self.tmp / "home/.factory-r2").write_text(json.dumps(value))

    def seal(self, c, *, checkpoint=False):
        self.artifacts.seal(c, checkpoint=checkpoint)

    def inner(self, archive, name):
        """A member of the sealed test work tree, decrypted with this test's throwaway key."""
        plain = subprocess.run(["age", "-d", "-i", str(self.identity), str(archive)], capture_output=True, check=True).stdout
        return json.loads(subprocess.run(["tar", "-xzO", f"{self.c.case_id}/{name}"], input=plain,
                                         capture_output=True, check=True).stdout)

    # T1: the real card's stale receipt is revoked before its copies are replaced.
    def test_t1_real_stale_receipt_revoked_on_checkpoint_seal(self):
        saved = CARD["durable_checkpoint"]
        self.assertEqual((saved["sha256"][:8], saved["r2_object"], saved["remote_durable"], saved["local_durable"]),
                         ("460a8f21", KEY, True, True))
        self.assertEqual((CARD["sha256"][:8], CARD["r2_object"]), ("03a1dd51", KEY))  # same key, later bytes
        (self.c.work / "durable-checkpoint.json").write_text(json.dumps(saved))
        self.seal(self.c, checkpoint=True)
        receipt = self.c.card["durable_checkpoint"]
        self.assertEqual({k: receipt[k] for k in ("local_durable", "remote_durable", "pending", "superseded")},
                         dict(local_durable=False, remote_durable=False, pending=True, superseded="checkpoint_replaced"))
        self.assertEqual((receipt["sha256"], receipt["r2_object"]), (saved["sha256"], saved["r2_object"]))
        self.assertEqual(json.loads((self.c.work / "durable-checkpoint.json").read_text()), receipt)
        archive = Path(self.c.card["archive"])
        self.assertEqual(self.inner(archive, "scorecard.json")["durable_checkpoint"], receipt)
        self.assertEqual(self.inner(archive, "durable-checkpoint.json"), receipt)
        self.assertEqual(self.c.card["r2_object"], KEY)
        self.assertEqual(hashlib.sha256(self.store.objects[KEY]).hexdigest(), self.c.card["sha256"])
        self.assertEqual(self.c.card["sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())

    def test_t1b_final_seal_does_not_revoke(self):
        self.allow_delivery = True
        self.seal(self.c, checkpoint=False)
        self.assertEqual(self.c.card["durable_checkpoint"], CARD["durable_checkpoint"])
        self.assertEqual(self.c.card["r2_object"], PREFIX + "/final.tar.gz.age")
        self.assertNotIn(KEY, self.store.objects)

    def test_t1c_local_path_revokes_without_links(self):
        (self.tmp / "home/.factory-r2").unlink()
        receipt = self.c.card["durable_checkpoint"]
        receipt["archive"] = str(self.sealed / f"{self.c.case_id}.checkpoint.tar.gz.age")  # saved /home/user path
        self.seal(self.c, checkpoint=True)
        self.assertEqual((receipt["local_durable"], receipt["remote_durable"], receipt["superseded"]),
                         (False, False, "checkpoint_replaced"))
        self.assertNotIn("r2_object", self.c.card)
        self.assertEqual(self.store.objects, {})

    # T2 / T4: the honest store, through the launcher's own links program.
    def test_t2_t4_verified_receipt_through_launcher_links(self):
        self.assertEqual(set(self.links), {"prefix", "checkpoint", "checkpoint_get", "final", "final_get"})
        self.assertEqual(self.links["prefix"], PREFIX)
        text = (ROOT / "factory/launch.sh").read_text()
        for key in ("checkpoint", "final"):
            self.assertIn(f'r2_sign PUT "vm/$id/{key}.tar.gz.age" 604800', text)
            self.assertIn(f'r2_sign GET "vm/$id/{key}.tar.gz.age" 604800', text)
        self.assertTrue(checkpoint_progress(self.c, self.seal, quiescent=True, interval=0))
        receipt = self.c.card["durable_checkpoint"]
        self.assertEqual((receipt["version"], receipt["local_durable"], receipt["remote_durable"], receipt["pending"]),
                         (2, True, True, False))
        self.assertEqual(receipt["r2_object"], KEY)
        self.assertEqual(receipt["sha256"], hashlib.sha256(self.store.objects[KEY]).hexdigest())
        self.assertEqual({k: self.c.card[k] for k in ("sha256", "archive", "r2_object")},
                         {k: CARD[k] for k in ("sha256", "archive", "r2_object")})

    # T3 / T5: every read-back failure fails closed, and no link leaks.
    def test_t3_t5_readback_failures_fail_closed(self):
        for mode in ("ignore_put", "truncate", "extra", "get404", "missing_get", "put500"):
            with self.subTest(mode=mode):
                self.c.card = copy.deepcopy(CARD); self.c.durable_checkpoint_at = None
                self.store.objects = {KEY: b"previous object bytes"} if mode == "ignore_put" else {}
                self.store.mode = "honest" if mode == "missing_get" else mode
                links = dict(self.links)
                if mode == "missing_get": del links["checkpoint_get"]
                self.write_links(links)
                captured = self.tmp / f"fd-{mode}.txt"
                with captured.open("w+") as sink:
                    saved = os.dup(1), os.dup(2)
                    os.dup2(sink.fileno(), 1); os.dup2(sink.fileno(), 2)
                    try: self.assertTrue(checkpoint_progress(self.c, self.seal, quiescent=True, interval=0))
                    finally:
                        os.dup2(saved[0], 1); os.dup2(saved[1], 2); os.close(saved[0]); os.close(saved[1])
                receipt = self.c.card["durable_checkpoint"]
                self.assertEqual((receipt["local_durable"], receipt["remote_durable"], receipt["pending"]),
                                 (True, False, True))
                self.assertNotIn("r2_object", receipt)
                self.assertEqual(receipt["reason"], "remote_upload_unavailable_or_failed")
                self.assertEqual({k: self.c.card[k] for k in ("sha256", "archive", "r2_object")},
                                 {k: CARD[k] for k in ("sha256", "archive", "r2_object")})
                for text in (json.dumps(self.c.card), (self.c.work / "durable-checkpoint.json").read_text(),
                             captured.read_text()):
                    self.assertNotIn("X-Amz-Signature", text)

    # T3b: a stalled GET times out, and an oversized GET is cut off early; both fail closed (design-1 diff NB).
    def test_t3b_readback_stall_and_oversize_cut_off(self):
        url = self.links["checkpoint_get"]
        # stall: only the 2 s bound can end it. flood: the bound is 25 s, so returning within 10 s proves the
        # per-block size cut-off ended the read, not the timeout. (Whether the explicit kill or EPIPE ends curl
        # afterwards is not distinguished; both fail closed.)
        for mode, timeout in (("stall", 2), ("flood", 25)):
            with self.subTest(mode=mode):
                self.store.mode = mode
                start = time.monotonic()
                self.assertIsNone(r2_upload._readback(url, 1024, timeout=timeout))
                self.assertLess(time.monotonic() - start, 10)

    # T6: resume-in-place refuses a VM whose links predate read-back, before replacing its code.
    def test_t6_resume_in_place_refuses_put_only_links(self):
        lines = (ROOT / "factory/resume-in-place.sh").read_text().splitlines()
        guard, = [l for l in lines if l.startswith("! test -f ~/.factory-r2 ")]
        self.assertLess(lines.index(guard), [i for i, l in enumerate(lines) if l.startswith("rm -rf ~/factory && tar ")][0])
        guard = guard.replace('\\$', '$').replace('\\"', '"')
        home = self.tmp / "vm"; home.mkdir()
        def run():
            return subprocess.run(["/bin/sh", "-c", "set -eu\n" + guard + "\necho passed"],
                                  env={**os.environ, "HOME": str(home)}, capture_output=True, text=True)
        self.assertEqual(run().stdout.strip(), "passed")  # absent: host-collected only, nothing claimed
        (home / ".factory-r2").write_text(json.dumps({"prefix": "vm/x", "checkpoint": "p", "final": "f"}))
        refused = run()
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("predate checkpoint read-back", refused.stderr)
        (home / ".factory-r2").write_text(json.dumps(self.links))
        self.assertEqual(run().stdout.strip(), "passed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
