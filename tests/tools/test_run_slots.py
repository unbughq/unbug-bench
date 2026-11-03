#!/usr/bin/env python3
"""tests/run.py machine slots cap concurrency across suites and free on exit."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

RUN = Path(__file__).resolve().parents[1] / "run.py"


def load(slot_dir, count):
    os.environ.update(TEST_SLOT_DIR=slot_dir, TEST_SLOTS=str(count))
    spec = importlib.util.spec_from_file_location(f"run_{count}_{time.monotonic_ns()}", RUN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SlotTests(unittest.TestCase):
    def test_two_suites_share_one_cap(self):
        with tempfile.TemporaryDirectory() as slots:
            suites = [load(slots, 2), load(slots, 2)]  # two runners, one host-wide pool
            live, peak, guard = [0], [0], threading.Lock()

            def work(module):
                with module.machine_slot():
                    with guard:
                        live[0] += 1; peak[0] = max(peak[0], live[0])
                    time.sleep(0.2)
                    with guard:
                        live[0] -= 1

            threads = [threading.Thread(target=work, args=(suites[i % 2],)) for i in range(8)]
            for t in threads: t.start()
            for t in threads: t.join()
            self.assertEqual(peak[0], 2)

    def test_killed_holder_releases_slot(self):
        with tempfile.TemporaryDirectory() as slots:
            holder = subprocess.Popen([sys.executable, "-c",
                f"import importlib.util,os,time;os.environ.update(TEST_SLOT_DIR={slots!r},TEST_SLOTS='1');"
                f"s=importlib.util.spec_from_file_location('r',{str(RUN)!r});m=importlib.util.module_from_spec(s);"
                "s.loader.exec_module(m)\nwith m.machine_slot(): print('held',flush=True); time.sleep(60)"],
                stdout=subprocess.PIPE, text=True)
            self.assertEqual(holder.stdout.readline().strip(), "held")
            module = load(slots, 1)
            holder.kill(); holder.wait()
            start = time.monotonic()
            with module.machine_slot():
                pass
            self.assertLess(time.monotonic() - start, 5)


if __name__ == "__main__":
    unittest.main()
