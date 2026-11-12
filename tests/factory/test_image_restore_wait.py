"""The image step waits for Boat's lazy restore of the baked image instead of rebuilding it."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory")]
os.environ.setdefault("BENCH", str(ROOT))
from durable.workers import IMAGE_SCRIPT, image_script  # noqa: E402

# A docker that reports the image only after `ready_after` inspects; every other call is logged.
DOCKER = """#!/bin/sh
d="$(dirname "$0")"
if [ "$1 $2" = "image inspect" ]; then
  n=$(cat "$d/n" 2>/dev/null || echo 0); echo $((n+1)) > "$d/n"
  [ "$n" -ge "$(cat "$d/ready_after")" ]; exit $?
fi
echo "$@" >> "$d/calls"
"""


def run(ready_after, script):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / "home/unbug-bench").mkdir(parents=True)
        (t / "bin").mkdir()
        (t / "bin/docker").write_text(DOCKER)
        (t / "bin/docker").chmod(0o755)
        (t / "bin/ready_after").write_text(str(ready_after))
        env = {**os.environ, "HOME": str(t / "home"), "PATH": f"{t / 'bin'}:{os.environ['PATH']}"}
        code = subprocess.run(["sh", "-c", script], env=env, timeout=30).returncode
        calls = (t / "bin/calls").read_text() if (t / "bin/calls").exists() else ""
        return code, calls


class ImageRestoreWait(unittest.TestCase):
    def test_late_restore_is_not_rebuilt(self):
        code, calls = run(3, image_script(5, 1).replace("sleep 1", "sleep 0"))
        self.assertEqual((code, calls), (0, ""))

    def test_missing_image_still_builds_after_the_wait(self):
        code, calls = run(10**6, image_script(2, 1).replace("sleep 1", "sleep 0"))
        self.assertEqual(code, 0)
        self.assertIn("build medusa", calls)

    def test_default_script_waits_up_to_five_minutes(self):
        self.assertIn("-le 100 ]", IMAGE_SCRIPT)


if __name__ == "__main__":
    unittest.main()
