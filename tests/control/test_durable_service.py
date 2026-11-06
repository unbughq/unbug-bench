"""Offline unit configuration checks; no systemd activation."""
import configparser
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "factory"))


class ServiceTests(unittest.TestCase):
    def test_units(self):
        for name in ("unbug-durable.service", "unbug-durable-backup.service"):
            unit = configparser.ConfigParser(interpolation=None, strict=False)
            unit.read(ROOT / "control" / name)
            service = unit["Service"]
            self.assertEqual(service["User"], "root" if "backup" in name else "user")
            self.assertEqual(service["UMask"], "0077")
            if "backup" in name:
                self.assertEqual(service["ExecStart"], "/bin/sh /usr/local/libexec/unbug-durable-backup")
            else:
                self.assertIn("--config /home/user/.unbug-durable/config.json", service["ExecStart"])
            self.assertNotIn("postgresql://", service["ExecStart"])
        unit.read(ROOT / "control/unbug-durable.service")
        self.assertEqual(unit["Service"]["Restart"], "always")
        timer = configparser.ConfigParser()
        timer.read(ROOT / "control/unbug-durable-backup.timer")
        self.assertEqual(timer["Timer"]["Persistent"], "true")

    def test_a_stop_can_drain_and_a_restart_never_gives_up(self):
        from durable.runtime import DRAIN_S
        for path in (ROOT / "control/unbug-durable.service", ROOT / "control/campaign/unbug-durable-case-campaign.service"):
            unit = configparser.ConfigParser(interpolation=None, strict=False)
            unit.read(path)
            self.assertEqual(unit["Service"]["Restart"], "always")
            self.assertEqual(unit["Service"]["KillMode"], "control-group")
            self.assertGreater(int(unit["Service"]["TimeoutStopSec"]), DRAIN_S)
            self.assertEqual(unit["Unit"]["StartLimitIntervalSec"], "0")

    def test_nothing_turns_a_small_failure_into_a_stop(self):
        guard = (ROOT / "control/campaign/unbug-case-campaign-guard.service").read_text()
        self.assertNotIn("OnFailure", guard)
        campaign = (ROOT / "control/campaign/unbug-durable-case-campaign.service").read_text()
        self.assertNotIn("Requires=", campaign)   # a router restart must not stop the controller
        self.assertIn("Wants=unbug-model-router.service", campaign)

    def test_the_deadline_holds_even_if_the_guard_cannot_run(self):
        cleanup = (ROOT / "control/campaign/unbug-case-campaign-cleanup.service").read_text()
        self.assertIn('$SERVICE_RESULT" = success', cleanup)
        self.assertNotIn("ExecStartPre", cleanup)

    def test_setup_syntax_and_no_activation(self):
        path = ROOT / "control/setup-durable.sh"
        subprocess.run(["sh", "-n", str(path)], check=True)
        text = path.read_text()
        self.assertIn("dbos==3.4.0", text)
        self.assertIn("pg_restore", text)
        backup = (ROOT / "control/unbug-durable-backup.service").read_text()
        self.assertIn("controlled pause and resume", backup)
        self.assertIn("-o root -g root", text)
        subprocess.run(["sh", "-n", str(ROOT / "control/durable-backup.sh")], check=True)
        self.assertNotIn("systemctl enable", text)
        self.assertNotIn("age-keygen -o", text)


if __name__ == "__main__":
    unittest.main()
