"""Real ask-human HTTP exchange with a synthetic metered owner and no OS mutations."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json
import os
from unittest.mock import patch
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import urllib.error
import urllib.request

from exam_responder import owner_channel, owner_server, docker_owner_server, responder, contract


class OwnerTests(unittest.TestCase):
    def check_attempt_drain(self, *, timeout=False, body_error=False):
        import threading
        from run_validity import InvalidInfra
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        reasons = []
        scope = types.SimpleNamespace(mark_unpublishable=reasons.append)
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); case = root/'case'; case.mkdir()
            (case/'fact-sheet.md').write_text('authored owner facts')
            workspace = root/'attempt'; workspace.mkdir()
            c = types.SimpleNamespace(case=case, args=types.SimpleNamespace(), card={},
                                      models={'reviewers': [['existing-reviewer']]})
            def model(ctx, models, text, directory, name, **kw):
                started.set(); release.wait(5)
                (directory/'answer.json').write_text('{"answer":"authored answer"}')
                return 0
            runner = types.SimpleNamespace(BENCH=_TEST_ROOT, model_call=model, BudgetError=RuntimeError,
                jload=lambda p, default: json.loads(p.read_text()) if p.exists() else default)
            request = None
            def ask(url):
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, data=b'{"question":"authored"}'), timeout=5) as response:
                        response.read()
                finally: finished.set()
            try:
                with patch('exam_responder.OWNER_DRAIN_SECONDS', .02 if timeout else 2):
                    try:
                        with owner_server(c, runner, workspace) as url:
                            request = threading.Thread(target=ask, args=(url,)); request.start()
                            self.assertTrue(started.wait(2))
                            if not timeout: threading.Timer(.05, release.set).start()
                            if body_error: raise ValueError('authored body error')
                    except (InvalidInfra, ValueError) as error:
                        self.assertTrue(timeout)
                        self.assertIsInstance(error, ValueError if body_error else InvalidInfra)
                    else: self.assertFalse(timeout)
                if not timeout: self.assertTrue(finished.wait(1))
            finally:
                release.set()
                if request: request.join(5)
            self.assertTrue(finished.is_set())

    def test_factory_owner_drain_includes_call_finishing_after_calibrator(self):
        self.check_attempt_drain()

    def test_factory_owner_drain_timeout_marks_attempt_unpublishable(self):
        self.check_attempt_drain(timeout=True)

    def test_factory_owner_drain_does_not_mask_body_error(self):
        self.check_attempt_drain(timeout=True, body_error=True)

    def test_exam_overlay_adds_owner_network_only_to_responder(self):
        bench = pathlib.Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            fake = pathlib.Path(tmp) / 'harbor'
            fake.write_text('#!/bin/sh\nif [ "$1" = --version ]; then echo 0.24.0; fi\n')
            fake.chmod(0o700)
            env = {**os.environ, 'OWNER_URL':'http://172.25.0.1:12345/synthetic/ask',
                   'OWNER_RELAY_NETWORK':'owner-relay-'+'a'*16, 'OWNER_RELAY_ADDRESS':'172.25.0.2'}
            command = [sys.executable, str(bench/'harbor/run-audited.py'), '--agent','oracle',
                       '--job-name','synthetic','--answerer','reviewer','--harbor',str(fake),'--dry-run']
            result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            stage = pathlib.Path(json.loads(result.stdout)['staged_inputs'])
            try:
                joint = (stage/'joint.yaml').read_text()
                self.assertIn('owner-relay:\n        ipv4_address: 172.25.0.2', joint.split('  main:')[0])
                self.assertNotIn('owner-relay', joint.split('  main:')[1].split('\nnetworks:')[0])
                self.assertIn('external: true\n    name: owner-relay-'+'a'*16, joint)
                self.assertFalse((stage/'responder/fact-sheet.txt').exists())
            finally:
                shutil.rmtree(stage)

    def test_docker_owner_firewall_scoped_and_removed_on_error(self):
        from contextlib import contextmanager
        commands = []
        def command(args, **kw):
            commands.append(args)
            if args[:3] == ['docker', 'network', 'inspect']:
                return json.dumps([{'Id':'a'*64, 'IPAM':{'Config':[{'Gateway':'172.25.0.1'}]}, 'Containers':{'leftover':{}}}])
            return ''
        @contextmanager
        def server(*a, **kw):
            self.assertEqual(kw['host'], '172.25.0.1')
            yield 'http://172.25.0.1:12345/synthetic/ask'
        with patch('exam_responder.subprocess.check_output', command), patch('exam_responder.owner_server', server):
            with self.assertRaisesRegex(RuntimeError, 'trial failed'):
                with docker_owner_server(None, None, None) as relay:
                    self.assertEqual(relay['OWNER_RELAY_ADDRESS'], '172.25.0.2')
                    raise RuntimeError('trial failed')
        add = next(c for c in commands if c[:5] == ['sudo','iptables','-w','5','-I'])
        self.assertEqual(add[5:], ['INPUT','1','-i','br-aaaaaaaaaaaa','-s','172.25.0.2/32','-d','172.25.0.1/32','-p','tcp','--dport','12345','-j','ACCEPT'])
        self.assertIn(add[:4] + ['-D','INPUT'] + add[7:], commands)
        self.assertEqual(commands[-2][:4], ['docker','network','disconnect','-f'])
        self.assertEqual(commands[-1][:3], ['docker','network','rm'])

    def test_private_facts_client_protocol_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            case = root / "case"; case.mkdir()
            (case / "fact-sheet.md").write_text("SYNTHETIC_PRIVATE_FACT")
            workspace = root / "try-1"; workspace.mkdir()
            destination = root / "pilot"; destination.mkdir()
            c = types.SimpleNamespace(case=case, args=types.SimpleNamespace(),
                                      models={"reviewers": [["existing-reviewer"]]}, card={})
            rules = []
            def shell(ctx, argv, **kwargs):
                if argv[1] == "iptables":
                    rules.append(argv)
                else:
                    pathlib.Path(argv[-1]).write_bytes(pathlib.Path(argv[-2]).read_bytes())
            def model(ctx, models, text, directory, name, **kwargs):
                self.assertIn("SYNTHETIC_PRIVATE_FACT", text)
                self.assertEqual(models, ["existing-reviewer"])
                (directory / "answer.json").write_text('{"answer":"synthetic answer"}')
                return 0
            runner = types.SimpleNamespace(
                BENCH=pathlib.Path(__file__).resolve().parents[2],
                sh=shell, model_call=model, BudgetError=RuntimeError,
                jload=lambda p, default: json.loads(p.read_text()) if p.exists() else default)
            with owner_channel(c, runner, workspace, destination, "synthetic-pilot") as instruction:
                self.assertNotIn("SYNTHETIC_PRIVATE_FACT", instruction)
                client = destination / "ask-human"
                self.assertNotIn("SYNTHETIC_PRIVATE_FACT", client.read_text())
                result = subprocess.run([sys.executable, str(client), "What happened?"],
                                        text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "synthetic answer")
                # The exam sidecar relays to precisely the same factory owner.
                endpoint = re.search(r"http://127\.0\.0\.1:\d+/[a-f0-9]+/ask", client.read_text())[0]
                protocol = responder(runner.BENCH)
                with patch.dict(os.environ, ANSWERER="reviewer", OWNER_URL=endpoint):
                    self.assertEqual(protocol.answer("What happened?")[0], "synthetic answer")
                with patch.dict(os.environ, ANSWERER="reviewer", OWNER_URL=""):
                    with self.assertRaises(RuntimeError):
                        protocol.answer("What happened?")
                url = re.search(r"http://127\.0\.0\.1:\d+", client.read_text())[0]
                request = urllib.request.Request(url + "/wrong/ask", data=b'{"question":"x"}')
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(request)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
            self.assertEqual(rules[0][4:7], ["-I", "factory-synthetic-pilot", "1"])
            self.assertEqual(rules[1][4:6], ["-D", "factory-synthetic-pilot"])
            evidence = json.loads((workspace / "owner/questions.jsonl").read_text().splitlines()[0])
            self.assertEqual(evidence["minutes_charged"], 5)
            self.assertEqual(evidence["answer"], "synthetic answer")

    def test_invalid_owner_blocks_scoring_and_contract_pins_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "fact-sheet.md").write_text("synthetic fact")
            c = types.SimpleNamespace(case=root, args=types.SimpleNamespace(), card={},
                                      models={"reviewers": [["existing-reviewer"]]})
            runner = types.SimpleNamespace(BENCH=pathlib.Path(__file__).resolve().parents[2],
                BudgetError=RuntimeError, model_call=lambda *a, **k: 1, jload=lambda *a: {})
            protocol = responder(runner.BENCH)
            with self.assertRaisesRegex(RuntimeError, "owner_invalid_answer"):
                with owner_server(c, runner, root) as url:
                    with patch.dict(os.environ, ANSWERER="reviewer", OWNER_URL=url):
                        with self.assertRaises(RuntimeError):
                            protocol.answer("question")
                    # Even if a contestant ignores the HTTP error, exit fails closed.
            a = contract(runner.BENCH, {"model": "reviewer-a", "effort": "high"})
            b = contract(runner.BENCH, {"model": "reviewer-a", "effort": "low"})
            self.assertNotEqual(a, b)


class OwnerFailureTests(unittest.TestCase):
    """2026-11-21: 13 GATES attempts (~56 h, ~$122) stopped infra:cancelled. An owner answer with no free lane
    in 120 s cancelled the strong tester; the cancelled tester then skipped the owner port's cleanup and both
    finallys reported the derived "cancelled" instead of the owner's error."""

    def ask(self, model, *, body=None, on_cleanup=None):
        """One tester try that asks one question. Returns (raised error, iptables rules, tester cancel)."""
        import threading
        from budget import BudgetError
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            case = root / "case"; case.mkdir()
            (case / "fact-sheet.md").write_text("synthetic fact")
            workspace = root / "try-1"; workspace.mkdir()
            destination = root / "pilot"; destination.mkdir()
            c = types.SimpleNamespace(case=case, args=types.SimpleNamespace(), card={}, role_cancel=threading.Event(),
                                      models={"reviewers": [["existing-reviewer"]]})
            rules = []
            def shell(ctx, argv, **kwargs):   # run.sh: a set role_cancel stops it before the command runs
                if getattr(ctx, "role_cancel", None) is not None and ctx.role_cancel.is_set(): raise BudgetError("cancelled")
                if argv[1] == "iptables":
                    rules.append(argv[4])
                    if argv[4] == "-D" and on_cleanup: on_cleanup()
                else: pathlib.Path(argv[-1]).write_bytes(pathlib.Path(argv[-2]).read_bytes())
            runner = types.SimpleNamespace(BENCH=_TEST_ROOT, sh=shell, model_call=model, BudgetError=BudgetError,
                jload=lambda p, default: json.loads(p.read_text()) if p.exists() else default)
            try:
                with owner_channel(c, runner, workspace, destination, "synthetic-pilot"):
                    result = subprocess.run([sys.executable, str(destination / "ask-human"), "What happened?"],
                                            text=True, capture_output=True, timeout=20)
                    if body: body(c, result)
            except BaseException as error:
                return error, rules, c.role_cancel.is_set()
            return None, rules, c.role_cancel.is_set()

    @staticmethod
    def cancelled_tester(c, result):   # the tester's own model call, cancelled by the owner's failure
        from budget import BudgetError
        assert c.role_cancel.is_set() and result.returncode
        raise BudgetError("cancelled")

    def test_owner_failure_reports_its_own_error_and_still_closes_the_port(self):
        from budget import BudgetError
        from durable.classify import classify
        def broken(*a, **k): raise BudgetError("process_error")
        error, rules, cancelled = self.ask(broken, body=self.cancelled_tester)
        self.assertTrue(cancelled)
        self.assertEqual(str(error), "process_error")   # was "cancelled"
        self.assertEqual(rules, ["-I", "-D"])            # was ["-I"]: the cancel skipped the cleanup
        self.assertEqual(classify(str(error), step="gates", now=0).reason, "router:process_error")

    def test_a_lane_wait_within_the_ceiling_is_no_owner_failure(self):
        import model_router
        calls = []
        def lanes(ctx, models, text, directory, name, **kw):
            calls.append(kw["timeout"])
            if len(calls) < 3:   # Neuralwatt seats full, then both Go accounts on quota (2026-11-21)
                reason = "capacity" if len(calls) == 1 else "quota"
                raise model_router.ProviderWait("reviewer", model_router.Wait(reason, 0, evidence="interrupted"
                    if reason == "quota" else "denied_before_work", route="opencode-go/mimo-v2.6-pro"))
            (directory / "answer.json").write_text('{"answer":"synthetic answer"}')
            return 0
        answers = []
        error, rules, cancelled = self.ask(lanes, body=lambda c, result: answers.append(result.stdout.strip()))
        self.assertIsNone(error)
        self.assertFalse(cancelled)
        self.assertEqual(answers, ["synthetic answer"])
        self.assertEqual(calls, [120, 120, 120])
        self.assertEqual(rules, ["-I", "-D"])

    def test_an_owner_that_never_gets_a_lane_stops_as_a_provider_wait(self):
        import model_router
        from durable.classify import classify_wait
        from durable.contract import Outcome
        def full(*a, **k): raise model_router.ProviderWait("reviewer", model_router.Wait("capacity", 0))
        with patch("exam_responder.OWNER_LANE_WAIT_SECONDS", 0):
            error, rules, cancelled = self.ask(full, body=self.cancelled_tester)
        self.assertIsInstance(error, model_router.ProviderWait)
        self.assertEqual(rules, ["-I", "-D"])
        result, _ = classify_wait(error, step="gates", now=0)   # how the engine labels a ProviderWait
        self.assertEqual((result.outcome, result.reason), (Outcome.PROVIDER_LIMIT, "router:capacity"))

    def test_real_owner_errors_are_not_waited_out_or_scored(self):
        import model_router
        from budget import BudgetError
        # A spent credit is a financial refusal (no new CLI); an unsettled interrupted call settles first.
        for wait in (model_router.Wait("credit", 0), model_router.Wait("rate", 0, evidence="interrupted", route="claude/x")):
            calls = []
            def refused(*a, **k):
                calls.append(1); raise model_router.ProviderWait("reviewer", wait)
            error, _, _ = self.ask(refused, body=self.cancelled_tester)
            self.assertIsInstance(error, model_router.ProviderWait)
            self.assertEqual(len(calls), 1)
        # The owner's own run limit is no answer, never the tester's scored time limit (run._author_try).
        def slow(*a, **k): raise BudgetError("timeout")
        error, _, _ = self.ask(slow, body=self.cancelled_tester)
        self.assertEqual(str(error), "owner_invalid_answer")

    def test_a_try_that_ends_during_a_lane_wait_cancels_no_one(self):
        import threading, model_router
        from budget import BudgetError
        def own_timeout(c, result): raise BudgetError("timeout")   # the tester's own time limit
        # The tester gave up on ask-human (here its client timeout), then finished its try or hit its own limit.
        for body, stop in ((lambda c, result: self.assertTrue(result.returncode), "owner_closed_unanswered"),
                           (own_timeout, "timeout")):   # the tester's own cap, scored as before
            calls = []
            def lanes(ctx, *a, **k):
                calls.append(1)
                if len(calls) == 1: raise model_router.ProviderWait("reviewer", model_router.Wait("capacity", 0))
                if not ctx.role_cancel.wait(10): raise AssertionError("owner never cancelled")
                raise BudgetError("cancelled")   # await_lease, cancelled when the try's owner server closes
            with patch.dict(os.environ, ASK_TIMEOUT="1"):
                error, rules, cancelled = self.ask(lanes, body=body)
            self.assertEqual(str(error), stop)   # a clean end was "cancelled"
            # The ended try cancels no one: role_cancel is shared with the other G10 tester and the next try.
            self.assertFalse(cancelled)
            self.assertEqual(rules, ["-I", "-D"])

    def test_a_try_that_ends_during_the_first_wait_or_answer_is_a_counted_infra_stop(self):
        """The reviewer's probe (goldfish diff 2): the tester's CLI drops ask-human while the owner is still in its
        first await_lease, or still answering, and the try ends cleanly. The teardown's cancel was infra:cancelled.
        It stays an unscored INFRA_ERROR that counts against the step's infra retries (goldfish diff 3: as a
        PROVIDER_LIMIT it slept and reran paid tries forever), under its own name."""
        from budget import BudgetError
        from durable.classify import classify
        from durable.contract import Outcome
        def first(ctx, *a, **k):   # no ProviderWait yet: still in the first lane wait, or the model still running
            if not ctx.role_cancel.wait(10): raise AssertionError("owner never cancelled")
            raise BudgetError("cancelled")
        with patch.dict(os.environ, ASK_TIMEOUT="1"):
            error, rules, cancelled = self.ask(first, body=lambda c, result: self.assertTrue(result.returncode))
        self.assertEqual(str(error), "owner_closed_unanswered")   # was "cancelled"; still raised: unscored
        self.assertFalse(cancelled)
        self.assertEqual(rules, ["-I", "-D"])
        result = classify(str(error), step="gates", now=0)
        self.assertEqual((result.outcome, result.reason), (Outcome.INFRA_ERROR, "infra:owner_closed_unanswered"))
        self.assertIsNone(result.retry_at)   # no provider sleep: an ordinary, counted infra retry

    def test_an_owner_failure_during_the_port_cleanup_cancels_no_one(self):
        import threading, time
        from budget import BudgetError
        cleanup, failed = threading.Event(), threading.Event()
        def late(*a, **k):   # the owner fails only once the ended try is closing its port
            if not cleanup.wait(10): raise AssertionError("cleanup never ran")
            failed.set()
            raise BudgetError("process_error")
        def closing_port():
            cleanup.set()
            self.assertTrue(failed.wait(5))
            time.sleep(.1)   # answer() records the failure
        with patch.dict(os.environ, ASK_TIMEOUT="1"):
            error, rules, cancelled = self.ask(late, body=lambda c, result: None, on_cleanup=closing_port)
        self.assertFalse(cancelled)   # was True: the shared role_cancel stopped the other G10 tester
        self.assertEqual(str(error), "process_error")
        self.assertEqual(rules, ["-I", "-D"])

    def test_a_tester_cap_racing_an_owner_failure_stays_the_tester_cap(self):
        from budget import BudgetError
        def broken(*a, **k): raise BudgetError("process_error")
        def capped(c, result):   # the tester's call stopped on its own limit just as the owner failed
            self.assertTrue(c.role_cancel.is_set())
            raise BudgetError("timeout")
        error, rules, cancelled = self.ask(broken, body=capped)
        self.assertTrue(cancelled)
        self.assertEqual(str(error), "timeout")   # the tester's own cap: run._author_try scores it, no new rule
        self.assertEqual(rules, ["-I", "-D"])

    def test_g10_reports_the_tester_stop_that_cancelled_both(self):
        import argparse, threading, time
        import run
        c = run.Ctx(); c.card = {}; c.args = argparse.Namespace(concurrent_roles=True, bench_workers=4)
        def calibrator(child, role):
            if role == "strong_calibrator":
                child.role_cancel.set()   # exam_responder: its owner failed
                time.sleep(.3)            # cleanup and drain: the easy tester's cancel ends first
                raise run.BudgetError("process_error")
            child.role_cancel.wait(5)
            raise run.BudgetError("cancelled")
        with tempfile.TemporaryDirectory() as tmp:
            c.work = pathlib.Path(tmp); c.case = c.work / "case"
            with patch.object(run, "parallel_calibrators", return_value=True), patch.object(run, "sh"), \
                 patch.object(run, "pilot_wall"), patch.object(run, "shred_tree"), patch.object(run, "calibrate", calibrator):
                with self.assertRaisesRegex(run.BudgetError, "^process_error$"):   # was "cancelled"
                    run.g10(c)


if __name__ == "__main__":
    unittest.main()
