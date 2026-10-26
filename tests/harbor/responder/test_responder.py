#!/usr/bin/env python3
"""Self-test: canned responder + ask-human end to end (stdlib only)."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from pathlib import Path
HERE = str(Path(__file__).resolve().parents[3] / "harbor/responder")
RESPONDER = os.path.join(HERE, "responder.py")
ASK = os.path.join(HERE, "ask-human")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_ready(port, proc, deadline=15):
    end = time.time() + deadline
    while time.time() < end:
        if proc.poll() is not None:
            raise AssertionError("responder exited early code=%s" % proc.poll())
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/healthz" % port, timeout=1) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise AssertionError("responder not ready in %ss" % deadline)


def ask(url, question):
    env = dict(os.environ, RESPONDER_URL=url)
    return subprocess.run([sys.executable, ASK, question],
                          capture_output=True, text=True, env=env, timeout=60)


def main():
    tmp = tempfile.mkdtemp(prefix="responder-test-")
    canned = os.path.join(tmp, "canned.json")
    log = os.path.join(tmp, "questions.jsonl")
    with open(canned, "w", encoding="utf-8") as f:
        json.dump({"refund": "Refunds take 3 days."}, f)
    port = free_port()
    url = "http://127.0.0.1:%d/ask" % port
    env = dict(os.environ, ANSWERER="canned", CANNED_MAP=canned,
               RESPONDER_LOG=log, MINUTES_PER_QUESTION="5",
               HOST="127.0.0.1", PORT=str(port))
    proc = subprocess.Popen([sys.executable, RESPONDER], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_ready(port, proc)
        assert os.path.isfile(log), "zero-question log must be collectible"
        assert open(log, encoding="utf-8").read() == "", "startup must not invent questions"
        r1 = ask(url, "What is the refund policy?")
        assert r1.returncode == 0, "known q exit=%s err=%s" % (r1.returncode, r1.stderr)
        assert "Refunds take 3 days." in r1.stdout, "known q answer=%r" % r1.stdout
        r2 = ask(url, "What is the meaning of life?")
        assert r2.returncode == 0, "unknown q exit=%s err=%s" % (r2.returncode, r2.stderr)
        assert r2.stdout.strip() == "I don't know.", "unknown q answer=%r" % r2.stdout
        with open(log, encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        assert len(lines) == 2, "log lines=%d" % len(lines)
        for e in lines:
            assert set(("ts", "step", "question", "answer", "minutes_charged")) <= set(e), e
            assert e["minutes_charged"] == 5, e
        assert "refund" in lines[0]["question"].lower()
        assert lines[1]["answer"] == "I don't know."
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    # unreachable responder -> non-zero, no answer on stdout
    dead = free_port()
    r3 = ask("http://127.0.0.1:%d/ask" % dead, "hello?")
    assert r3.returncode != 0, "unreachable must exit non-zero"
    assert r3.stdout.strip() == "", "unreachable must not print an answer"
    assert "ask-human: error:" in r3.stderr, "unreachable needs a clear error"
    print("PASS: 2 answers ok, 2 log lines w/ minutes_charged=5, "
          "unknown -> \"I don't know.\", unreachable -> exit %d" % r3.returncode)


if __name__ == "__main__":
    main()
