"""Read-only real ciphertext inventory; no identities, decryption or cloud calls."""
import json
import math
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
LAUNCH = (ROOT / 'factory/launch.sh').read_text()


def function(name):
    return name + '() {' + LAUNCH.split(name + '() {', 1)[1].split('\n}', 1)[0] + '\n}\n'


class RestoreInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archives = sorted((ROOT / 'sealed').glob('*.checkpoint.tar.gz.age'))
        if not cls.archives:
            raise RuntimeError('real sealed checkpoint inventory required for qualification')

    def test_every_real_checkpoint_is_batch_keyed_or_legacy_restorable(self):
        legacy_without_key = 0
        for archive in self.archives:
            prefix = archive.name.removesuffix('.checkpoint.tar.gz.age')
            card = json.loads((archive.parent / (prefix + '.scorecard.json')).read_text())
            key = archive.parent / (prefix + '.casekey.age')
            batch = card.get('batch_release_sha256') or ''
            result = subprocess.run(['sh', '-c', function('restore_casekey') +
                'restore_casekey "$1" "$2"', 'sh', str(key), batch], capture_output=True, text=True, check=True)
            if batch:
                self.assertEqual(result.stdout.strip(), str(key), archive.name)
            elif not key.is_file():
                self.assertEqual(result.stdout, '', archive.name)  # Select the retained legacy stream.
                legacy_without_key += 1
        self.assertGreater(legacy_without_key, 0, 'qualification must cover real unwrapped legacy archives')
        print(f'Real inventory: {len(self.archives)} checkpoints restorable; {legacy_without_key} legacy without casekeys')

    def test_batch_without_wrapped_key_fails_before_allocation(self):
        # Use an actual legacy checkpoint's missing key, never manufacture the inventory.
        archive = next(p for p in self.archives if not p.with_name(
            p.name.removesuffix('.checkpoint.tar.gz.age') + '.casekey.age').exists())
        key = archive.with_name(archive.name.removesuffix('.checkpoint.tar.gz.age') + '.casekey.age')
        result = subprocess.run(['sh', '-c', function('restore_casekey') +
            'restore_casekey "$1" batch', 'sh', str(key)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('wrapped case key required for batch restore; no VM created', result.stderr)

    def test_largest_real_checkpoint_uses_r2_or_size_scaled_upload_timeout(self):
        archive = max(self.archives, key=lambda p: p.stat().st_size)
        size = archive.stat().st_size
        self.assertGreater(size, 500_000_000, 'qualification requires the real approximately 528 MB checkpoint')
        expected = max(1200, 2 + math.ceil(size / 262144))
        script = function('restore_transfer_timeout') + function('restore_ciphertext') + '''
ckpt=$1; r2_object=$2; r2_sha=public-digest; id=public-worker; fail_r2=$3
restore_timeout=$(restore_transfer_timeout "$ckpt")
r2_sign() { printf 'https://public.invalid/ciphertext'; }
boat() {
  printf '%s\n' "$BOAT_COMMAND_TIMEOUT_SECONDS" "$*" >&2
  case "$*" in *curl*) [ "$fail_r2" != yes ] ;; esac
}
restore_ciphertext
'''
        for object_name, failed in (('vm/public/checkpoint.tar.gz.age', 'no'), ('', 'no'),
                                    ('vm/public/checkpoint.tar.gz.age', 'yes')):
            result = subprocess.run(['sh', '-c', script, 'sh', str(archive), object_name, failed],
                                    capture_output=True, text=True, check=True)
            lines = result.stderr.splitlines()
            self.assertTrue(all(int(v) == expected for v in lines[::2]))
            self.assertIn('curl -fsS' if object_name and failed == 'no' else 'cat > ~/restore.age', lines[-1])
            self.assertTrue(all('age -d' not in v for v in lines[1::2]),
                            'ciphertext transport must not decrypt on the host')
        print(f'Real checkpoint: {size} bytes; R2/local ciphertext timeout {expected}s (default boat timeout is 120s)')


if __name__ == '__main__': unittest.main()
