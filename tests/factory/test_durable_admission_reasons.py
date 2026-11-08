"""Admission rejection codes and the read-only VM backfill (durable/admission_reasons.py).

The codes come from structured fields only: no URL, statement or reviewer sentence may reach
them. The backfill opens a real sealed snapshot with a fake key service and DBOS client.
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

from durable import admission_reasons as ar
from durable.artifacts import AgeSealer, LocalObjects, SealedStore
from durable.contract import ArtifactKind, Step, StepKind, to_record

SECRET = "private-sentinel"
PIN = "2.19.0"
MODELS = {"easy_calibrator": ["openrouter/z-ai/glm-5.3-flash"], "reviewers": [["openrouter/xiaomi/mimo-v2.6-pro"]]}


def hit(url, same=True, **more):
    return {"url": url, "resolved": True, "same_bug": same, "retrieved": True, "retrieved_from": "live",
            "app_version": PIN, "version_scope": SECRET, "why": SECRET, **more}


def snapshot(members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, value in members.items():
            data = value if isinstance(value, bytes) else json.dumps(value).encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class Codes(unittest.TestCase):
    def test_source_classes_never_echo_the_url(self):
        repo = "medusajs/medusa"
        cases = {"https://github.com/medusajs/medusa/pull/9": "upstream_pull",
                 "https://github.com/medusajs/medusa/commit/abc": "upstream_commit",
                 "https://github.com/medusajs/medusa/issues/1": "upstream_issue",
                 "https://github.com/medusajs/medusa/releases/tag/v2.19.4": "upstream_release",
                 "https://github.com/medusajs/medusa": "upstream_repo",
                 "https://github.com/someone/fork/issues/2": "github_issue",
                 "https://docs.medusajs.com/resources/" + SECRET: "app_docs",
                 "https://www.npmjs.com/package/@medusajs/medusa": "package_registry",
                 "https://stackoverflow.com/q/1": "forum",
                 "https://blog.example/" + SECRET: "web",
                 None: "unknown"}
        for url, expected in cases.items():
            self.assertEqual(ar.source_class(url, repo), expected, url)

    def test_freshness_evidence_strength_and_release_versions(self):
        repo = "medusajs/medusa"
        def details(*hits):
            return ar.freshness_details({"hits": list(hits)}, repo)
        self.assertEqual(details(hit("https://github.com/medusajs/medusa/issues/1"))["evidence"], "upstream_report")
        self.assertEqual(details(hit("https://docs.medusajs.com/x"))["evidence"], "app_docs")
        self.assertEqual(details(hit("https://blog.example/x"))["evidence"], "third_party")
        # Only confirmed, retrieved matches count; an excluded row is not evidence.
        self.assertEqual(details(hit("https://github.com/medusajs/medusa/pull/9", same=False))["evidence"], "unrecorded")
        self.assertEqual(ar.freshness_details(None, repo), {"evidence": "unrecorded"})
        found = details(hit("https://github.com/medusajs/medusa/releases/tag/%40medusajs%2Fmedusa%402.18.2"),
                        hit("https://github.com/medusajs/medusa/releases/tag/v2.19.0"),
                        hit("https://github.com/medusajs/medusa/releases/tag/v2.20.1"))
        self.assertEqual(found["evidence"], "upstream_fix")
        self.assertEqual(found["pin_version"], PIN)
        self.assertEqual(found["fix_releases"], [{"version": "2.18.2", "relation": "before_pin"},
                                                 {"version": "2.19.0", "relation": "at_pin"},
                                                 {"version": "2.20.1", "relation": "after_pin"}])
        # A monorepo tag spelt literally parses too, and a fix older than the pin says so.
        older = details(hit("https://github.com/medusajs/medusa/releases/tag/@medusajs/medusa@2.18.2"))
        self.assertEqual(older.get("fix_releases"), None)   # five path parts only: an unescaped "/" is not a tag
        older = details(hit("https://github.com/medusajs/medusa/releases/tag/v2.18.2"))
        self.assertEqual(older["fix_releases"], [{"version": "2.18.2", "relation": "before_pin"}])
        self.assertNotIn(SECRET, json.dumps(found))

    def test_reason_code_prefers_a_judged_screen(self):
        dedup = {"screen": "dedup", "evidence": "board_duplicate"}
        repeat = {"screen": "other", "evidence": "repeat_candidate"}
        fix = {"screen": "freshness", "evidence": "upstream_fix"}
        docs = {"screen": "freshness", "evidence": "app_docs"}
        self.assertEqual(ar.reason_code([dedup, repeat, {"codes": repeat}]), "dedup_board_duplicate")
        self.assertEqual(ar.reason_code([fix, {"codes": docs}]), "freshness_mixed")
        self.assertEqual(ar.reason_code([fix, dedup]), "rejected_mixed")
        self.assertEqual(ar.reason_code([repeat]), "other_repeat_candidate")
        self.assertEqual(ar.reason_code([]), "other_unknown")
        self.assertEqual(ar.reason_code([{"screen": "freshness", "evidence": SECRET}]), "other_unknown")
        self.assertTrue(set(ar.REJECTION_CODES) >= {ar.reason_code([r]) for r in (dedup, repeat, fix, docs)})

    def test_candidate_rows_for_each_screen(self):
        card = {"models": MODELS, "dedup": {"duplicate_of": "case-old-1", "reason": SECRET},
                "admission": {"status": "rejected", "screen": "internal_duplicate"}}
        self.assertEqual(ar.candidate_row(card, statuses={"case-old-1": "completed"}),
                         {"screen": "dedup", "evidence": "board_duplicate", "judge_family": "z-ai",
                          "duplicate_of": "case-old-1", "duplicate_status": "completed"})
        card = {"models": MODELS, "admission": {"screen": "idea_realism"}, "idea_realism": {"approve": False}}
        self.assertEqual(ar.candidate_row(card), {"screen": "realism", "evidence": "rejected", "judge_family": "xiaomi"})
        self.assertEqual(ar.candidate_row({}, problems=["missing statement.md"]),
                         {"screen": "other", "evidence": "missing_statement"})
        self.assertEqual(ar.candidate_row({}, problems=[SECRET]), {"screen": "other", "evidence": "unknown"})

    def test_snapshot_of_an_old_card_reads_only_its_codes(self):
        # A card written before ADMIT recorded codes: rows carry the screen; the last row's
        # details come from the card's own fields and the reviewer verdict.
        card = {"case": "case-imp-1", "models": MODELS, "imported_from": {"case": "case-old"},
                "admission": {"status": "exhausted", "candidates": 1},
                "rejected_candidates": [{"statement_sha256": "a" * 64, "screen": "public_freshness",
                                         "problems": ["candidate public freshness screen failed"]}]}
        raw = snapshot({"scorecard.json": card,
                        "freshness-verdict.json": {"hits": [hit("https://github.com/medusajs/medusa/pull/77")]},
                        "case/case.json": {"app": {"repo": "https://github.com/medusajs/medusa", "commit": "v2.19.0"}},
                        "case/statement.md": SECRET.encode(), "statements/case-x.md": SECRET.encode()})
        out = ar.inspect_snapshot(raw)
        self.assertEqual(out["reason"], "admit:freshness_upstream_fix")
        self.assertEqual(out["candidates"][0]["sources"], ["upstream_pull"])
        self.assertTrue(out["imported"])
        # A receipt bound to another candidate's statement is not this candidate's evidence.
        stale = {"binding": {"statement_sha256": "f" * 64}, "hits": [hit("https://github.com/medusajs/medusa/pull/77")]}
        self.assertEqual(ar.inspect_snapshot(snapshot({"scorecard.json": card, "freshness-verdict.json": stale}))["reason"],
                         "admit:freshness_unrecorded")
        self.assertNotIn(SECRET, json.dumps(out))
        self.assertNotIn("github.com", json.dumps(out))
        # Several old candidates: earlier rows keep only their screen.
        card["rejected_candidates"] = [{"statement_sha256": "b" * 64, "screen": "idea_realism"},
                                       {"statement_sha256": "c" * 64, "screen": "selection_failed"},
                                       *card["rejected_candidates"]]
        out = ar.inspect_snapshot(snapshot({"scorecard.json": card}))
        self.assertEqual([(r["screen"], r["evidence"]) for r in out["candidates"]],
                         [("realism", "rejected"), ("other", "unknown"), ("freshness", "unrecorded")])
        self.assertEqual(out["reason"], "admit:rejected_mixed")
        self.assertEqual(ar.inspect_snapshot(snapshot({"case/case.json": {}})), {"error": "card_unreadable"})


class FakeKeys:
    def __init__(self, keys):
        self.keys, self.opened = keys, []

    def wrapped_key(self, scope):
        if scope not in self.keys:
            raise KeyError(scope)
        return b"wrapped"

    def scope_key(self, scope):
        self.opened.append(scope)
        return self.keys.setdefault(scope, os.urandom(32))   # a real service would create it


class FakeClient:
    def __init__(self, rows, events):
        self.rows, self.events = rows, events

    def list_workflows(self, *, workflow_id_prefix, **_):
        return [r for r in self.rows if r.workflow_id.startswith(workflow_id_prefix)]

    def get_event(self, workflow_id, key, timeout_seconds=None):
        return self.events.get((workflow_id, key))


class Backfill(unittest.TestCase):
    def test_backfill_prints_codes_for_the_last_admit_snapshot_only(self):
        sealer, case, other = AgeSealer(), "case-imp-b5521c-5-1", "case-imp-nokey-1"
        keys = FakeKeys({case: os.urandom(32)})
        with tempfile.TemporaryDirectory() as tmp:
            store = SealedStore(LocalObjects(tmp))
            def sealed(card):
                ref, ciphertext = sealer.seal(keys.keys[case], ArtifactKind.CASE_SNAPSHOT, snapshot({"scorecard.json": card}))
                store.put_sealed(case, ref, ciphertext)
                return to_record(ref)
            old = sealed({"admission": {"status": "waiting"}})
            last = sealed({"admission": {"status": "exhausted"}, "models": MODELS,
                           "rejected_candidates": [{"statement_sha256": "a" * 64, "screen": "internal_duplicate",
                                                    "codes": {"screen": "dedup", "evidence": "board_duplicate",
                                                              "duplicate_of": "case-old-1"}}]})
            def row(seq, attempt, kind, result):
                return SimpleNamespace(workflow_id=f"{case}/{seq}/x/{attempt}",
                    input={"args": [{"input": {"case_id": case, "seq": seq, "attempt": attempt,
                                               "step": to_record(Step(kind))}}]},
                    output={"result": result})
            rows = [row(1, 1, StepKind.ADMIT, {"outcome": "infra_error", "reason": "admit:processing_failed", "snapshot": old}),
                    row(1, 2, StepKind.ADMIT, {"outcome": "exhausted", "reason": "admit:exhausted", "snapshot": last}),
                    row(1, 3, StepKind.ADMIT, {"outcome": "infra_error", "reason": "infra:deadline"})]
            client = FakeClient(rows, {("b-imp-b5521c-5", "cases"): [case]})
            results = ar.backfill({}, ["b-imp-b5521c-5", other, "not a case"], client=client, keys=keys, store=store)
        self.assertEqual(results[0]["case"], case)
        self.assertEqual((results[0]["seq"], results[0]["attempt"]), (1, 2))
        self.assertEqual(results[0]["recorded_reason"], None)   # "admit:exhausted" was never published
        self.assertEqual(results[0]["reason"], "admit:dedup_board_duplicate")
        self.assertEqual(results[0]["candidates"][0]["duplicate_of"], "case-old-1")
        self.assertEqual(results[1], {"case": other, "error": "no_admit_snapshot"})
        self.assertEqual(results[2], {"target": None, "error": "invalid_target"})
        # Only the case that already had a key was opened; nothing was created.
        self.assertEqual(keys.opened, [case])

    def test_a_missing_key_is_never_created(self):
        case = "case-imp-x-1"
        keys = FakeKeys({})
        rows = [SimpleNamespace(workflow_id=case + "/1/x/1",
                                input={"args": [{"input": {"case_id": case, "seq": 1, "attempt": 1,
                                                           "step": to_record(Step(StepKind.ADMIT))}}]},
                                output={"result": {"outcome": "exhausted", "snapshot": {"digest": "0" * 64, "kind": "case"}}})]
        with tempfile.TemporaryDirectory() as tmp:
            results = ar.backfill({}, [case], client=FakeClient(rows, {}), keys=keys, store=SealedStore(LocalObjects(tmp)))
        self.assertEqual(results[0]["error"], "snapshot_unavailable")
        self.assertEqual(keys.opened, [])


if __name__ == "__main__":
    unittest.main()
