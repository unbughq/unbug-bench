"""Local check of the gate-1 prechecks on the dry-run fixture (no Docker, no models).
  python3 tests/factory/test_run.py"""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import argparse, pathlib, sys, tempfile, time
from unittest import mock
sys.path.insert(0, str((pathlib.Path(__file__).resolve().parents[2] / "factory")))
import run

# Fixture tests must not race other workers changing the shared bench. Test the
# fingerprint separately on a tiny private tree, then hold it fixed for G1 fixtures.
with tempfile.TemporaryDirectory() as tmp, mock.patch.object(run, 'BENCH', pathlib.Path(tmp)):
    sample = pathlib.Path(tmp) / 'sample'; sample.write_text('before')
    before = run.bench_manifest(); sample.write_text('after')
    assert run.bench_manifest() != before
    before = run.bench_manifest(); (pathlib.Path(tmp) / 'unbug').mkdir(); (pathlib.Path(tmp) / 'unbug/watcher.pid').write_text('1')
    assert run.bench_manifest() == before  # guard runtime state is not a bench change

with tempfile.TemporaryDirectory() as tmp, mock.patch.object(run, 'bench_manifest', return_value='fixture-bench'):
    c = run.Ctx()
    c.args = argparse.Namespace(dry_run=True, source=None)
    c.work = pathlib.Path(tmp); c.case = c.work / "case"; c.card = {}
    (c.work / "logs").mkdir()
    c.manifest0 = run.bench_manifest()
    run.build_fixture(c)
    ok, info = run.g1(c)
    assert ok, (info, (c.work / "logs/runner.log").read_text()[-2000:])
    assert c.card["counts"]["scenarios"] == len([d for d in (run.BENCH / 'scenarios/dev').glob('S*') if d.is_dir() and d.name != 'S0-null'])
    # A service-only reference satisfies the same shared artifact contract as pilots.
    reference = c.case / "guards/reference"
    saved = {p.name: p.read_bytes() for p in reference.iterdir() if p.is_file()}
    for name in ("db.sql", "app.patch"): (reference / name).unlink(missing_ok=True)
    (reference / "services.patch").write_text("synthetic service-only reference")
    assert run.g1(c)[0], "service-only reference guard must reach the normal G1 checks"
    (reference / "services.patch").unlink()
    for name, content in saved.items(): (reference / name).write_bytes(content)
    (c.case / "promise.md").write_text("word " * 301)
    assert not run.g1(c)[0], "301-word promise must fail"
    (c.case / "promise.md").write_text("Keep the promise.")
    (c.case / "contestant.md").write_text("The answer key says so.")
    assert not run.g1(c)[0], "leak word must fail"
    (c.case / "contestant.md").write_text("ok")
    (c.case / "base/app.patch").write_text("not a patch\n")
    assert not run.g1(c)[0], "broken patch must fail"

    # Real build loop and G1: invalid round 1 reaches the next builder, never an attacker.
    import json
    from test_admission import evidence
    rows = [evidence('builder', kind, i) for kind in ('web', 'github') for i in range(3)]
    rows += [evidence('attacker', 'web', i) for i in range(2)]
    (c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
    from unittest import mock
    for rounds in (1, 2):
        for repaired in (False, True):
            (c.work / 'attack-state.json').unlink(missing_ok=True)
            c.args = argparse.Namespace(dry_run=True, source=None, rounds=rounds, runs=10, scenario_runs=3, resume='case-test')
            c.models = {'builder': ['fake/builder'], 'attacker': ['fake/attacker']}
            calls = []
            def driver(ctx, models, text, cwd, name, user=None, **kwargs):
                extra = json.loads(text.split('## This run')[1].split('```json\n')[1].split('```')[0])
                calls.append((name, extra))
                if name.endswith('-freshness'): return  # G2 top-up, covered separately below
                if name.startswith('builder'):
                    if name == 'builder-1':
                        (c.case / 'base/app.patch').unlink(missing_ok=True)
                        (c.case / 'promise.md').write_text('word ' * 301)
                    else:
                        assert 'promise has 301 words' in extra['precheck_problems']
                        if repaired: (c.case / 'promise.md').write_text('Keep the promise.')
                else:
                    pathlib.Path(extra['report_path']).write_text('{"complete": true, "blocking": []}')
            with mock.patch.object(run, 'opencode', driver), mock.patch.object(run, 'bench_manifest', return_value=c.manifest0):
                try:
                    run.build(c)
                except run.BudgetError as error:
                    assert str(error).startswith('stress_review_unresolved:'), error
                prechecked = run.g1(c)[0]
            names = [name for name, _ in calls]
            assert names[:2] == ['builder-1', 'builder-precheck' if rounds == 1 else 'builder-2'], names
            assert 'attacker-1' not in names, names
            assert prechecked == repaired
            if not repaired: assert not any(name.startswith('attacker') for name in names), names

    import tempfile, types  # G5 resolves an example guard in its own scenario, not the first same-named one
    with tempfile.TemporaryDirectory() as t:
        case = pathlib.Path(t)
        for s in ("S11", "S7a"): (case / f"scenarios/{s}/examples/repaired").mkdir(parents=True)
        fc = types.SimpleNamespace(case=case)
        assert run.find_guard(fc, "repaired", case / "scenarios/S7a") == case / "scenarios/S7a/examples/repaired"
        (case / "scenarios/S7b").mkdir()  # no own example: two candidates elsewhere -> refuse to guess
        try: run.find_guard(fc, "repaired", case / "scenarios/S7b"); raise AssertionError("guessed")
        except LookupError as e: assert "ambiguous" in str(e)
        import shutil; shutil.rmtree(case / "scenarios/S11/examples/repaired")  # unique -> used
        assert run.find_guard(fc, "repaired", case / "scenarios/S7b") == case / "scenarios/S7a/examples/repaired"
    with tempfile.TemporaryDirectory() as t:  # G2 top-up: one call, only for the role that logged too few searches
        fc = types.SimpleNamespace(case=pathlib.Path(t) / "case", work=pathlib.Path(t), card={}, args=argparse.Namespace(source="port", runs=1, scenario_runs=1),
                                   models={"builder": ["claude/x"], "attacker": ["opencode-go/y"]})
        fc.case.mkdir()
        from test_admission import evidence
        serial = iter(range(100))
        log = lambda who, kind: json.dumps(evidence(who, kind, next(serial)))
        (fc.case / "freshness.jsonl").write_text("\n".join(log("builder", k) for k in ("web", "github") for _ in range(3)) + "\n")
        calls = []
        def fake(c, models, text, cwd, name, user=None, **kwargs):
            calls.append(name)
            with open(c.case / "freshness.jsonl", "a") as f: f.write(log("attacker", "web") + "\n" + log("attacker", "github") + "\n")
        with mock.patch.object(run, "opencode", fake): run.freshness_topup(fc)
        assert calls == ["attacker-freshness"], calls
        assert fc.card["freshness_topup"]["after"]["attacker"] == 2
        fc.args.resume, fc.args.dry_run = "case-x", False
        for gate in ("G2", "G3"):  # resumed for a non-content failure: no rewrite, no new attack; searches suffice -> no calls
            (fc.work / "scorecard.json").write_text(json.dumps({"failed_gate": gate})); calls.clear()
            with mock.patch.object(run, "opencode", fake), mock.patch.object(run, "g1", lambda c: (True, {"problems": []})):
                run.build(fc)
            assert calls == [], (gate, calls)
        # Resumed after a stop during the stress test on a valid case: round 1 starts with the stress tester.
        (fc.work / "scorecard.json").write_text(json.dumps({"models_used": {"builder-1": "x", "attacker-1": "y"}})); calls.clear()
        fc.args.rounds, fc.args.dry_run = 1, False
        def fake2(c, models, text, cwd, name, user=None):
            calls.append(name)
            if name.startswith("attacker-1"):
                pathlib.Path(json.loads(text.split("```json\n")[-1].split("```")[0])["report_path"]).write_text('{"complete": true, "blocking": []}')
        with mock.patch.object(run, "opencode", fake2), mock.patch.object(run, "g1", lambda c: (True, {"problems": []})), \
             mock.patch.object(run, "statement_precheck", lambda c: True), mock.patch.object(run, "early_review", lambda c: None):
            run.write_and_attack(fc, json.loads((fc.work / "scorecard.json").read_text()))
        assert calls and calls[0] == "attacker-1", calls
    with tempfile.TemporaryDirectory() as t:  # early G3-G5: failure -> writer problems; pass -> cached, search log ignored
        ec = types.SimpleNamespace(case=pathlib.Path(t) / "case", work=pathlib.Path(t), card={})
        ec.case.mkdir(); (ec.case / "promise.md").write_text("p")
        ok_gate = lambda c: (True, {"x": 1})
        with mock.patch.object(run, "g3", ok_gate), mock.patch.object(run, "g4", lambda c: (False, {"broke": "3/10"})), \
             mock.patch.object(run, "g5", ok_gate), mock.patch.object(run, "log", lambda *a: None):
            probs = run.early_checks(ec)
        assert probs and "G4" in probs[0] and ec.early == {}, probs
        with mock.patch.object(run, "g3", ok_gate), mock.patch.object(run, "g4", ok_gate), mock.patch.object(run, "g5", ok_gate), \
             mock.patch.object(run, "log", lambda *a: None):
            assert run.early_checks(ec) is None and set(ec.early) == {"G3", "G4", "G5"}
        h = ec.early_hash; (ec.case / "freshness.jsonl").write_text("{}\n")
        assert run.case_hash(ec) == h, "the stress tester's search log must not invalidate early results"
        (ec.case / "promise.md").write_text("changed"); assert run.case_hash(ec) != h
    import os, signal  # SIGTERM pauses: the step stops with BudgetError('paused'); a second request is ignored
    old = signal.signal(signal.SIGTERM, run.pause_on_term)
    try:
        try: os.kill(os.getpid(), signal.SIGTERM); time.sleep(1); raise AssertionError("no pause")
        except run.PauseRequested: pass
        assert not issubclass(run.PauseRequested, Exception), "broad except Exception must not swallow a pause"
        assert signal.getsignal(signal.SIGTERM) == signal.SIG_IGN
    finally: signal.signal(signal.SIGTERM, old)
    print("ok")

# Admission rejection/resume behavior lives in test_admission.py. Encryption remains synthetic here.
with tempfile.TemporaryDirectory() as tmp:
    import json, subprocess, types
    root = pathlib.Path(tmp)
    work = root / "work"; work.mkdir()
    c = types.SimpleNamespace(work=work, case=work / "case", case_id="case-2new", card={},
                              args=argparse.Namespace(dry_run=False), statement="Synthetic selected statement")
    # Sealing encrypts the selected text to the statements PUBLIC recipient.
    recipient = root / "recipient.txt"; recipient.write_text("synthetic-public-recipient")
    sealed = root / "sealed"; sealed.mkdir()
    c.recipient = "synthetic-founder-public-recipient"
    def encrypt(cmd, **kwargs):
        import shlex
        if isinstance(cmd, list):
            assert cmd[:3] == ["age", "-r", "synthetic-public-recipient"]
            assert kwargs["input"] == c.statement.encode()
            assert c.statement not in " ".join(cmd)
            output = pathlib.Path(cmd[-1])
        else: output = pathlib.Path(shlex.split(cmd)[-1])
        output.write_bytes(b"fake ciphertext")
        return subprocess.CompletedProcess(cmd, 0)
    with mock.patch.object(run, "SEALED", sealed), mock.patch.object(run, "STATEMENTS_RECIPIENT", recipient), \
         mock.patch.object(run, "AGENT_STATE", []), mock.patch.object(run, "PILOT_HOME", root / "no-pilot"), \
         mock.patch.object(run.RunArtifacts, "results_since", return_value=[]), mock.patch("run_artifacts.processes.run", encrypt), \
         mock.patch("r2_upload.case_recipient", return_value=None):  # the case key has its own test (test_r2_upload.py)
        run.seal(c)
    assert (sealed / "case-2new.statement.age").read_bytes() == b"fake ciphertext"
print("statement dedup passed")
