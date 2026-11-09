"""Advance warnings of known limits: they alert, never degrade or stop, and never crash a pass."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "factory"))
from durable import preflight
from test_durable_guard import NOW, REQUEST, Fake

ROTATION = Path(__file__).resolve().parents[2] / "factory" / "rotation-3writers.json"


def make_cert(directory, days):
    key, cert = Path(directory) / f"k{days}.pem", Path(directory) / f"c{days}.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=router",
                    "-days", str(days), "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
    return cert


class Checks(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)

    def warn(self, request=REQUEST, now=NOW, **kw):
        if "cert_path" not in kw:
            kw["cert_path"] = make_cert(self.work.name, 30)
        kw.setdefault("rotation_path", ROTATION)
        return preflight.warnings(request, now, **kw)

    def test_all_clear(self):
        self.assertEqual(self.warn(router=lambda: (1.0, 100.0, 50.0)), {})

    def test_cert_expiring_and_expired(self):
        import time
        cert = make_cert(self.work.name, 2)
        self.assertIn("preflight:router_cert", self.warn(now=time.time(), cert_path=cert))
        self.assertIn("expired", self.warn(now=time.time() + 3 * 86400, cert_path=cert)["preflight:router_cert"])
        self.assertNotIn("preflight:router_cert", self.warn(now=time.time(), cert_path=make_cert(self.work.name, 4)))

    def test_cert_path_from_env(self):
        with mock.patch.dict("os.environ", {"UNBUG_ROUTER_CERT": str(Path(self.work.name) / "missing.crt")}):
            out = preflight.warnings(REQUEST, NOW, rotation_path=ROTATION)
        self.assertIn("preflight:router_cert:unknown", out)

    def test_headroom(self):
        out = self.warn(router=lambda: (95.5, 100.0, None))
        self.assertIn("$4.50 left", out["preflight:router_headroom"])
        self.assertNotIn("preflight:router_headroom", self.warn(router=lambda: (5.0, float("inf"), None)))
        self.assertNotIn("preflight:router_headroom", self.warn(router=lambda: (90.0, 100.0, None)))

    def test_deadline(self):
        self.assertIn("preflight:deadline", self.warn(now=REQUEST["deadline_epoch"] - 3600))
        self.assertNotIn("preflight:deadline", self.warn(now=REQUEST["deadline_epoch"] - 7 * 3600))
        self.assertNotIn("preflight:deadline", self.warn(now=REQUEST["deadline_epoch"] + 1))

    def test_unbounded_route(self):
        # The default rotation is bounded; an explicit model with no maximum anywhere in its chain is not.
        request = {**REQUEST, "models": {"writer": ["openrouter/acme/no-such-model"],
                                         "reviewers": [["claude/claude-opus-5-5"]]}}
        message = self.warn(request=request)["preflight:routes"]
        self.assertIn("openrouter/acme/no-such-model", message)
        self.assertNotIn("claude", message)

    def test_each_check_fails_alone(self):
        def broken():
            raise OSError("db locked")
        out = self.warn(request={**REQUEST, "deadline_epoch": "soon"}, router=broken,
                        rotation_path=Path(self.work.name) / "none.json", cert_path=Path(self.work.name) / "none")
        self.assertEqual(set(out), {f"preflight:{n}:unknown" for n in ("router_cert", "deadline", "routes",
                                                                      "router_headroom")})
        self.assertFalse(any("/" in m for m in out.values()))


class InGuard(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.fake = Fake(self.work.name)

    def test_warning_alerts_without_degrading(self):
        result = self.fake.guard(preflight=lambda now: {"preflight:deadline": "soon"}).run()
        self.assertEqual(result["phase"], "healthy")
        self.assertEqual(result["warnings"], {"preflight:deadline": "soon"})
        self.assertEqual(self.fake.sent, ["soon"])
        self.assertEqual(self.fake.stopped, 0)
        self.assertFalse((self.fake.state_dir / "guard" / "degraded.json").exists())
        status = json.loads((self.fake.state_dir / "guard" / "status.json").read_text())
        self.assertEqual(status["warnings"], {"preflight:deadline": "soon"})
        self.fake.guard(preflight=lambda now: {"preflight:deadline": "soon"}).run()
        self.assertEqual(self.fake.sent, ["soon"])   # once while it lasts

    def test_crashing_preflight_is_a_warning(self):
        def crash(now):
            raise RuntimeError("bug")
        result = self.fake.guard(preflight=crash).run()
        self.assertEqual(result["phase"], "healthy")
        self.assertIn("preflight:unknown", result["warnings"])

    def test_real_preflight_in_guard(self):
        def real(now):
            return preflight.warnings(REQUEST, now, router=lambda: (99.0, 100.0, None),
                                      cert_path=make_cert(self.work.name, 30), rotation_path=ROTATION)
        result = self.fake.guard(preflight=real).run()
        self.assertEqual(result["phase"], "healthy")
        self.assertEqual(set(result["warnings"]), {"preflight:router_headroom"})


if __name__ == "__main__":
    unittest.main()
