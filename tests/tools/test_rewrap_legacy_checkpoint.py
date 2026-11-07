"""bin/rewrap-legacy-checkpoint: founder ciphertext in, statement-key ciphertext out, no plaintext on disk."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def keypair(path):
    subprocess.run(["age-keygen", "-o", str(path)], capture_output=True, check=True)
    return subprocess.run(["age-keygen", "-y", str(path)], capture_output=True, check=True, text=True).stdout.strip()


class Rewrap(unittest.TestCase):
    def test_latest_archive_is_rewrapped_and_failures_leave_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            (tmp / "bin").mkdir(); (tmp / "factory").mkdir(); (tmp / "sealed").mkdir()
            shutil.copy(ROOT / "bin/rewrap-legacy-checkpoint", tmp / "bin")
            founder, statements = keypair(tmp / "founder"), keypair(tmp / "statements")
            (tmp / "factory/statements-recipient.txt").write_text(statements + "\n")
            seal = lambda name, data: subprocess.run(["age", "-r", founder, "-o", str(tmp / "sealed" / name)],
                                                     input=data, check=True)
            seal("case-a.checkpoint.tar.gz.age", b"older checkpoint")
            seal("case-a.tar.gz.age", b"final archive")
            seal("case-b.checkpoint.tar.gz.age", b"only checkpoint")
            identity = (tmp / "founder").read_bytes()
            run = lambda *cases, key=identity: subprocess.run([str(tmp / "bin/rewrap-legacy-checkpoint"), str(tmp / "out"), *cases],
                                                              input=key, capture_output=True)
            done = run("case-a", "case-b")
            self.assertEqual(done.returncode, 0, done.stderr)
            opened = lambda case: subprocess.run(["age", "-d", "-i", str(tmp / "statements"), str(tmp / "out" / f"{case}.import.age")],
                                                 capture_output=True, check=True).stdout
            self.assertEqual((opened("case-a"), opened("case-b")), (b"final archive", b"only checkpoint"))
            # A wrong identity or a missing case fails and writes no partial output.
            keypair(tmp / "other")
            self.assertNotEqual(run("case-c").returncode, 0)
            bad = run("case-b", key=(tmp / "other").read_bytes())
            self.assertNotEqual(bad.returncode, 0)   # refuses to overwrite, before decrypting
            (tmp / "out/case-b.import.age").unlink()
            bad = run("case-b", key=(tmp / "other").read_bytes())
            self.assertNotEqual(bad.returncode, 0)
            self.assertEqual(sorted(p.name for p in (tmp / "out").iterdir()), ["case-a.import.age"])


if __name__ == "__main__":
    unittest.main()
