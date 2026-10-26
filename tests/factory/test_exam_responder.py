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


if __name__ == "__main__":
    unittest.main()
