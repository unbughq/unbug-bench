"""Offline unit configuration checks; no systemd activation."""
import configparser
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


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
        self.assertEqual(unit["Service"]["Restart"], "on-failure")
        timer = configparser.ConfigParser()
        timer.read(ROOT / "control/unbug-durable-backup.timer")
        self.assertEqual(timer["Timer"]["Persistent"], "true")

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
