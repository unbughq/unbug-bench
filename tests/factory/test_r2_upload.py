#!/usr/bin/env python3
"""Synthetic: the case key is stable across seals, opens the archive alone, is sealed to the founder, and a missing or
failing upload link returns None (no network)."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json, pathlib, subprocess, sys, tempfile
sys.path.insert(0, str((pathlib.Path(__file__).resolve().parents[2] / "factory")))
import r2_upload
from unittest.mock import patch

with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d); work, sealed = d / "work", d / "sealed"; work.mkdir(); sealed.mkdir()
    founder = d / "founder"; subprocess.run(["age-keygen", "-o", str(founder)], capture_output=True, check=True)
    founder_pub = subprocess.run(["age-keygen", "-y", str(founder)], capture_output=True, text=True, check=True).stdout.strip()
    pub = r2_upload.case_recipient(work, sealed, "case-x", founder_pub)
    assert pub == r2_upload.case_recipient(work, sealed, "case-x", founder_pub), "a resume must reuse the case key"
    before = (sealed / "case-x.casekey.age").read_bytes()
    real_run = subprocess.run
    def failed_reseal(command, **kwargs):
        if command[0] == "age":
            kwargs["stdout"].write(b"incomplete synthetic ciphertext")
            raise subprocess.CalledProcessError(1, command)
        return real_run(command, **kwargs)
    with patch.object(r2_upload.subprocess, "run", failed_reseal):
        try:
            r2_upload.case_recipient(work, sealed, "case-x", founder_pub)
        except subprocess.CalledProcessError:
            pass
        else:
            raise AssertionError("failed case-key seal was accepted")
    assert (sealed / "case-x.casekey.age").read_bytes() == before
    assert not list(sealed.glob(".casekey-*")), "failed seal leaked a temporary file"
    archive = d / "a.age"
    subprocess.run(["age", "-r", founder_pub, "-r", pub, "-o", str(archive)], input=b"case bytes", check=True)
    case_key = subprocess.run(["age", "-d", "-i", str(founder), str(sealed / "case-x.casekey.age")], capture_output=True, check=True).stdout
    (d / "k").write_bytes(case_key)
    assert subprocess.run(["age", "-d", "-i", str(d / "k"), str(archive)], capture_output=True, check=True).stdout == b"case bytes"
    assert subprocess.run(["age", "-d", "-i", str(founder), str(archive)], capture_output=True, check=True).stdout == b"case bytes"
    vm = d / 'throwaway-vm'
    subprocess.run(['age-keygen', '-o', str(vm)], capture_output=True, check=True)
    vm_pub = subprocess.run(['age-keygen', '-y', str(vm)], capture_output=True, text=True, check=True).stdout.strip()
    assert r2_upload.case_recipient(work, sealed, 'case-x', founder_pub, vm_pub) == pub
    vm_key = subprocess.run(['age', '-d', '-i', str(vm), str(sealed/'case-x.casekey.age')],
                            capture_output=True, check=True).stdout
    assert vm_key == case_key, 'batch VM unwrap must recover the same case identity'
    founder_key = subprocess.run(['age', '-d', '-i', str(founder), str(sealed/'case-x.casekey.age')],
                                 capture_output=True, check=True).stdout
    assert founder_key == case_key, 'dual wrapping must preserve founder recovery'
    assert r2_upload.upload(archive, True, links=d / "absent") is None
    (d / "links").write_text(json.dumps({"prefix": "vm/x", "checkpoint": "http://127.0.0.1:9/nowhere", "final": "x"}))
    assert r2_upload.upload(archive, True, links=d / "links") is None  # PUT-only links: no read-back, no claim
    (d / "links").write_text(json.dumps({"prefix": "vm/x", "checkpoint": "http://127.0.0.1:9/nowhere",
                                         "checkpoint_get": "http://127.0.0.1:9/nowhere", "final": "x", "final_get": "x"}))
    assert r2_upload.upload(archive, True, links=d / "links") is None  # the PUT itself fails
print("PASS stable case key, archive roundtrip, optional founder+VM wrap; failed or absent uploads return None")
