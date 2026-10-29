"""The host adapter is bound to its explicit release fingerprint."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'factory'))
import key_holder


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


class AdapterPinTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)

    def test_host_only_adapter_pin_is_holder_bound_and_enforced(self):
        self.assertIn('factory/launcher-sha256.json', key_holder.PINNED)
        code = (ROOT / 'factory/launch.sh').read_text().split('qualified_adapter() {', 1)[1]
        code = code.split("<<'PYCODE'\n", 1)[1].split('\nPYCODE', 1)[0]
        root = self.home / 'host'; (root / 'bin').mkdir(parents=True); (root / 'factory').mkdir()
        adapter = root / 'bin/qualified-release.py'; adapter.write_text('raise SystemExit(17)\n')
        pin = root / 'factory/launcher-sha256.json'; pin.write_text(json.dumps({'bin/qualified-release.py': sha(adapter)}))
        for content, expected in ((adapter.read_bytes(), 17), (b'raise SystemExit(19)\n', None)):
            adapter.write_bytes(content)
            with patch.object(sys, 'argv', ['-', str(adapter)]), self.assertRaises(SystemExit) as stopped:
                exec(compile(code, 'qualified_adapter', 'exec'), {})
            if expected is None:
                self.assertEqual(str(stopped.exception), 'qualified release adapter changed; review launcher fingerprint')
            else: self.assertEqual(stopped.exception.code, expected)


if __name__ == '__main__': unittest.main()
