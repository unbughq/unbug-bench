"""The read-only free-route error read (durable/free_route_errors.py), on a fake sealed snapshot.

Only receipt fields and OpenCode error events' name, status and 200-character message may leave it.
"""
import sys
from pathlib import Path as _TestPath

_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT / "factory"), str(_TestPath(__file__).resolve().parent)]

import io
import json
import os
import tarfile
import tempfile
from types import SimpleNamespace
import unittest

from durable import free_route_errors as fre
from durable.artifacts import AgeSealer, LocalObjects, SealedStore
from durable.contract import ArtifactKind, Step, StepKind, to_record

SECRET = "private-sentinel"
LEASE, OTHER = "2575841a" + "0" * 24, "42aa2c2e" + "1" * 24


def snapshot(members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, value in members.items():
            data = value if isinstance(value, bytes) else json.dumps(value).encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def receipt(lease, invocation, **more):
    return {"lease_id": lease, "invocation": invocation, "outcome": "interrupted", "failure_reason": "outage",
            "source_stop": None, "final_usage_known": False, "events": [{"text": SECRET}], **more}


def transcript(*events):
    return "\n".join(json.dumps(e) for e in events).encode()


MEMBERS = {
    "usage-receipts/" + LEASE + ".json": receipt(LEASE, "attacker-1"),
    "usage-receipts/" + OTHER + ".json": receipt(OTHER, "writer-2", outcome="denied", failure_reason=SECRET),
    "usage-receipts/" + "f" * 32 + ".json": receipt("f" * 32, "reviewer-1"),
    "transcripts/attacker-1.100.jsonl": transcript(
        {"type": "text", "part": {"text": SECRET}},
        {"type": "error", "error": {"name": "APIError", "data": {"statusCode": 429, "message": "x" * 300, "body": SECRET}}},
        {"type": "step_finish", "part": {"tokens": {"input": 1}}}),
    "transcripts/attacker-1.50.jsonl": transcript({"type": "error", "error": {"name": "bad name " + SECRET, "data": {}}}),
    "transcripts/reviewer-1.1.jsonl": transcript({"type": "error", "error": {"name": "ShouldNotAppear", "data": {}}}),
    "scorecard.json": {"statement": SECRET},
}


class Inspect(unittest.TestCase):
    def test_reads_only_receipt_fields_and_error_events(self):
        rows = fre.inspect_snapshot(snapshot(MEMBERS), ["2575841a", "42aa2c2e", "deadbeef"])
        first, second, missing = rows
        self.assertEqual(first["lease"], LEASE)
        self.assertEqual((first["outcome"], first["failure_reason"], first["source_stop"], first["final_usage_known"]),
                         ("interrupted", "outage", None, False))
        self.assertEqual([t["started_ns"] for t in first["transcripts"]], [50, 100])   # oldest first
        self.assertEqual(first["transcripts"][0]["errors"], [{"name": None, "status": None, "message": None}])
        self.assertEqual(first["transcripts"][1]["errors"], [{"name": "APIError", "status": 429, "message": "x" * 200}])
        self.assertEqual((second["outcome"], second["failure_reason"], second["transcripts"]), ("denied", None, []))
        self.assertEqual(missing, {"lease": "deadbeef", "error": "no_receipt"})
        text = json.dumps(rows)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("ShouldNotAppear", text)   # another lease's invocation is never read


class FakeKeys:
    def __init__(self, keys):
        self.keys, self.opened = keys, []

    def wrapped_key(self, scope):
        if scope not in self.keys:
            raise KeyError(scope)
        return b"wrapped"

    def scope_key(self, scope):
        self.opened.append(scope)
        return self.keys.setdefault(scope, os.urandom(32))


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def list_workflows(self, *, workflow_id_prefix, **_):
        return [r for r in self.rows if r.workflow_id.startswith(workflow_id_prefix)]


class Read(unittest.TestCase):
    def test_opens_the_latest_snapshot_with_an_existing_key_only(self):
        sealer, case, nokey = AgeSealer(), "case-fresh-1108a-1", "case-fresh-1108b-1"
        keys = FakeKeys({case: os.urandom(32)})
        with tempfile.TemporaryDirectory() as tmp:
            store = SealedStore(LocalObjects(tmp))
            def sealed(members):
                ref, ciphertext = sealer.seal(keys.keys[case], ArtifactKind.CASE_SNAPSHOT, snapshot(members))
                store.put_sealed(case, ref, ciphertext)
                return to_record(ref)
            old = sealed({"scorecard.json": {}})
            last = sealed(MEMBERS)
            def row(case_id, seq, attempt, kind, result):
                return SimpleNamespace(workflow_id=f"{case_id}/{seq}/x/{attempt}",
                    input={"args": [{"input": {"case_id": case_id, "seq": seq, "attempt": attempt,
                                               "step": to_record(Step(kind))}}]},
                    output={"result": result})
            rows = [row(case, 1, 1, StepKind.ADMIT, {"snapshot": old}),
                    row(case, 2, 1, StepKind.ADMIT, {"snapshot": last}),
                    row(case, 2, 2, StepKind.ADMIT, {"outcome": "infra_error"}),
                    row(nokey, 1, 1, StepKind.ADMIT, {"snapshot": old})]
            results = fre.read({}, [case, nokey, "not a case"], ["2575841a"], client=FakeClient(rows), keys=keys, store=store)
        self.assertEqual((results[0]["seq"], results[0]["attempt"]), (2, 1))
        self.assertEqual([r["lease"] for r in results[0]["leases"]], [LEASE])
        self.assertEqual(results[1], {"case": nokey, "seq": 1, "attempt": 1, "error": "snapshot_unavailable"})
        self.assertEqual(results[2], {"case": None, "error": "invalid_case"})
        self.assertEqual(keys.opened, [case])   # the key-less case was never given one
        self.assertNotIn(SECRET, json.dumps(results))
        with self.assertRaises(ValueError):
            fre.read({}, [case], ["not-hex"], client=FakeClient(rows), keys=keys, store=store)


if __name__ == "__main__":
    unittest.main()
