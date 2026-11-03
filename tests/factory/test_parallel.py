"""Factory scheduling checks; no Docker or model calls."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json
import os
import pathlib
import sys
import threading
import argparse
import subprocess
import tempfile
import time
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "bin"))
import bench
import factory_pool

for count in (1, 2, 3, 5, 10):
    seen = {}
    barrier = threading.Barrier(min(count, 2))
    def child(argv, *, env, check):
        job = json.loads(pathlib.Path(argv[2]).read_text())
        slot = int(env["UNBUG_FACTORY_SLOT"])
        seen[slot] = job
        barrier.wait(timeout=5)  # fails if supposedly independent jobs are serialized
        pathlib.Path(argv[3]).write_text(json.dumps([{"run": i} for i in job["numbers"]]))
    # Scheduling starts after preparation; lifecycle ordering has its own regressions.
    with mock.patch.object(factory_pool, "prepare", return_value=True) as prepared, \
         mock.patch.object(factory_pool.subprocess, "run", child):
        records = factory_pool.run_records(pathlib.Path("/guard"), list(range(1, count + 1)),
                                           {"mode": "stress", "seed_base": 17}, [{"dir": pathlib.Path("/base")}], 2,
                                           {1: {"mode": "stress", "seed": 42}})
    prepared.assert_called_once_with(min(2, count))
    assert sorted(records) == list(range(1, count + 1))
    assert sorted(i for job in seen.values() for i in job["numbers"]) == list(range(1, count + 1)), "each run executes exactly once"
    assert seen[0]["numbers"][-1] == count, "fake-pass must inspect the final run on slot zero"
    assert all(j["options"] == {"mode": "stress", "seed_base": 17} and j["scenarios"] == ["/base"] for j in seen.values())
    assert all(j["per_run_options"] == {"1": {"mode": "stress", "seed": 42}} for j in seen.values())
    for i in records:
        assert bench.traffic_options(seen[next(s for s, j in seen.items() if i in j["numbers"])]["options"], i)["seed"] == (17 * 1_000_003 + i) % 2**31

# Default paths, ports and Docker command remain exactly the exam's single instance.
assert bench.RESULTS == bench.ROOT / "results"
assert bench.PORTS == (9000, 9001)
assert bench.GUARD_IMAGE == "unbug-bench-medusa:guard"
assert bench.COMPOSE == ["docker", "compose", "-f", str(bench.APP / "compose.yaml")]
assert "UNBUG_FACTORY_SLOT" not in os.environ

# A gate timeout stops a grandchild that ignores TERM before wipe can begin.
sys.path.insert(0, str((pathlib.Path(__file__).resolve().parents[2] / "factory")))
import run
with tempfile.TemporaryDirectory() as tmp:
    c = run.Ctx(); c.work = pathlib.Path(tmp); (c.work / "logs").mkdir()
    c.args = argparse.Namespace(bench_workers=2)
    heartbeat = c.work / "heartbeat"
    child = "import signal,time,pathlib; signal.signal(signal.SIGTERM, signal.SIG_IGN); p=pathlib.Path(" + repr(str(heartbeat)) + ")\nwhile True:\n p.write_text(str(time.time_ns())); time.sleep(.01)"
    parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); time.sleep(60)"
    popen = subprocess.Popen
    def ready(*args, **kwargs):
        process = popen(*args, **kwargs)
        deadline = time.monotonic() + 10
        while not heartbeat.exists() and time.monotonic() < deadline: time.sleep(.01)
        if not heartbeat.exists():
            os.killpg(process.pid, run.signal.SIGKILL); process.wait()
            raise AssertionError("test grandchild did not start")
        return process
    with mock.patch.object(run.subprocess, "Popen", ready):
        try: run.sh(c, [sys.executable, "-c", parent], capture=True, timeout=.1)
        except subprocess.TimeoutExpired: pass
        else: raise AssertionError("gate should time out")
    before = heartbeat.read_text(); time.sleep(.1)
    assert heartbeat.read_text() == before, "grandchild survived the gate timeout"
print("PASS concurrent scheduling, exact run coverage/seeds, final database ownership, serial defaults, timeout cleanup")

# Model scheduling: separate Unix homes AND live bench instances, with serial attempts.
with tempfile.TemporaryDirectory() as tmp:
    c = run.Ctx(); c.work = pathlib.Path(tmp); c.case = c.work / 'case'
    c.card = {}; c.args = argparse.Namespace(concurrent_roles=True, bench_workers=4)
    barrier = threading.Barrier(2)
    seen = []
    def calibrator(child, role):
        seen.append((role, child.pilot_user, run.pilot_home(child.pilot_user), child.factory_slot, child.args.bench_workers))
        barrier.wait(timeout=3)
        child.pilot_passes.append(pathlib.Path('/' + role))
        return {'model': role, 'tries': 3, 'solved': 1}
    commands = []
    with mock.patch.object(run, 'parallel_calibrators', return_value=True), \
         mock.patch.object(run, 'sh', side_effect=lambda c, args, **kw: commands.append(args)), \
         mock.patch.object(run, 'pilot_wall') as wall, mock.patch.object(run, 'shred_tree'), \
         mock.patch.object(run, 'calibrate', calibrator):
        assert run.g10(c)[0]
    assert len({entry[1] for entry in seen}) == len({entry[2] for entry in seen}) == 2
    assert {entry[3] for entry in seen} == {0, 1}
    assert all(entry[4] == 1 for entry in seen), 'checkpoint fan-out must not reset the other live app'
    assert [p.name for p in c.pilot_passes] == ['strong_calibrator', 'easy_calibrator']
    assert wall.call_args_list == [mock.call(c, 'pilot-strong', 0, remove=True), mock.call(c, 'pilot-strong', 0),
                                   mock.call(c, 'pilot-easy', 1, remove=True), mock.call(c, 'pilot-easy', 1)]
    assert len([cmd for cmd in commands if cmd[:2] == ['sudo', 'useradd']]) == 2
    # Flag off preserves the original role order, shared pilot, and bench parallelism.
    c.args.concurrent_roles = False
    order = []
    def serial(child, role):
        assert child is c and not hasattr(child, 'factory_slot')
        order.append(role)
        return {'model': role, 'tries': 3, 'solved': 1}
    with mock.patch.object(run, 'sh'), mock.patch.object(run, 'pilot_wall') as wall, mock.patch.object(run, 'shred_tree'), \
         mock.patch.object(run, 'calibrate', serial):
        assert run.g10(c)[0]
    assert order == ['strong_calibrator', 'easy_calibrator']
    # Zero strong solves needs diagnosis before it can be labelled hard.
    for strong_solved, easy_solved, ok, label in ((0, 0, True, 'undetermined'), (1, 3, False, 'normal')):
        results = {'strong_calibrator': strong_solved, 'easy_calibrator': easy_solved}
        with mock.patch.object(run, 'sh'), mock.patch.object(run, 'pilot_wall'), mock.patch.object(run, 'shred_tree'), \
             mock.patch.object(run, 'calibrate', lambda child, role: {'model': role, 'tries': 3, 'solved': results[role]}):
            assert run.g10(c)[0] is ok and c.card['difficulty'] == label
    c.pilot_passes = []; c.card['difficulty'] = 'hard'; c.args.dry_run = False
    assert run.g11(c)[0]
    assert wall.call_args_list == [mock.call(c, 'pilot', 0, remove=True), mock.call(c, 'pilot', 0)]
    # Early probe: one strong try, a label only; its own failure (e.g. a provider limit) never stops the case.
    def probe(child, role, tries=None, name=None):
        assert (role, tries, name) == ('strong_calibrator', 1, 'early_probe')
        return {'model': role, 'tries': 1, 'solved': 0}
    def limited(*a, **k): raise run.BudgetError('provider_limit:codex')
    (c.work / 'logs').mkdir(exist_ok=True)
    for fake, want in ((probe, 'likely_hard'), (limited, None)):
        with mock.patch.object(run, 'sh'), mock.patch.object(run, 'pilot_wall'), mock.patch.object(run, 'shred_tree'), \
             mock.patch.object(run, 'calibrate', fake):
            run.early_probe(c)
        assert c.card['early_probe'].get('label') == want and (want or c.card['early_probe']['skipped'] == 'BudgetError')
    assert run.GATES == ['G1', 'G2', 'G3', 'G4', 'G5', 'G16', 'G8', 'G9', 'G6', 'G13', 'G14', 'G15', 'G7', 'G10', 'G17', 'G11']
    # Early review: findings go back to the writer; a pass is reused; a changed case is reviewed again.
    verdicts = iter([{'fairness': {'approve': False, 'findings': ['unstated rule']}, 'realism': {'approve': True}},
                     {'fairness': {'approve': True}, 'realism': {'approve': True}}])
    def reviewer(c, chain, text, d, label): (d / 'verdict.json').write_text(json.dumps(next(verdicts)))
    c.models = {'reviewers': [['r']]}; c.case.mkdir(exist_ok=True); (c.case / 'case.json').write_text('{}')
    for k in ('early', 'early_hash', 'votes'): c.__dict__.pop(k, None)
    with mock.patch.object(run, 'opencode', reviewer), mock.patch.object(run, 'prompt', lambda *a: ''), \
         mock.patch.object(run, 'run_context', lambda *a, **k: ''):
        problems = run.early_review(c)
        assert 'unstated rule' in problems[0] and 'G9' in c.early and 'G8' not in c.early
        assert run.early_review(c) == problems  # unchanged case: cached votes, no second reviewer call
        (c.case / 'case.json').write_text('{"fixed": true}')
        assert run.early_review(c) is None and run.g8(c)[0]  # changed case: fresh review, which passes
    # Hardcoded inventory-service ports must stay on the old path.
    c.args.concurrent_roles = True
    with mock.patch.object(bench, 'load_scenario', return_value={}), \
         mock.patch.object(bench, 'inventory_services', return_value=[{'name': 'other-writer'}]):
        assert not run.parallel_calibrators(c)
    with mock.patch.object(bench, 'load_scenario', return_value={}), \
         mock.patch.object(bench, 'inventory_services', return_value=[{'name': 'other-writer', 'host_ports': [9010]}]), \
         mock.patch.object(bench, 'factory_memory_fits', return_value=True):
        assert run.parallel_calibrators(c)
        c.args.bench_workers = 1
        assert run.factory_slots(c) == 2, 'concurrent testers must not reserve a third shop on 8 GB'
    assert {user for user, _ in run.pilot_homes()} == {'pilot', 'pilot-strong', 'pilot-easy'}
print('PASS concurrent role identities/homes/bench slots, serial fallback and original order')

# Each tester can reach only its own app and declared service publications.
commands = []
c = run.Ctx(); c.case = pathlib.Path('/synthetic/case')
with mock.patch.object(bench, 'load_scenario', return_value={}), \
     mock.patch.object(bench, 'inventory_services', return_value=[{'name': 'channel', 'host_ports': [9010, 9011]}]), \
     mock.patch.object(run, 'sh', side_effect=lambda c, args, **kw: commands.append(args)):
    run.pilot_wall(c, 'pilot-easy', 1)
accepts = [cmd for cmd in commands if cmd[-1] == 'ACCEPT']
assert {cmd[cmd.index('--dport') + 1] for cmd in accepts if '--dport' in cmd} == {'9100', '9101', '9110', '9111'}
assert all(cmd[1] == 'iptables' for cmd in accepts), 'IPv6 must not open peer endpoints'
assert any(cmd[-3:] == ['LOCAL', '-j', 'REJECT'] for cmd in commands)
print('PASS pilot UID wall includes own service ports and rejects other local APIs')

# Every new home is archived and wiped, including when the flag changes on resume.
import shlex
import shutil
with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    c = run.Ctx(); c.work = root / 'work'; c.work.mkdir()
    c.case = c.work / 'case'; c.card = {}; c.case_id = 'synthetic'
    c.args = argparse.Namespace(bench_workers=1, dry_run=False, concurrent_roles=False)
    c.prepared_factory_slots = 3  # a repair lowered its active count after preparing these slots
    c.recipient = 'synthetic-public-recipient'; c.t0 = 0
    homes = [(user, root / user) for user in ('pilot', 'pilot-strong', 'pilot-easy')]
    for _, home in homes:
        home.mkdir(); (home / 'fixture').write_text('synthetic session')
    cleaned = []
    def command(argv, **kwargs):
        if kwargs.get('env', {}).get('UNBUG_FACTORY_SLOT'):
            cleaned.append(int(kwargs['env']['UNBUG_FACTORY_SLOT']))
        if isinstance(argv, str):
            pathlib.Path(shlex.split(argv)[-1]).write_bytes(b'synthetic ciphertext')
        elif argv[:3] == ['sudo', 'cp', '-a']:
            shutil.copytree(argv[3], argv[4])
        return subprocess.CompletedProcess(argv, 0, stdout='')
    walls = []
    def wall(c, user, slot, remove=False):
        assert c.work.exists(), 'firewall removal must happen before shredding the command logs'
        walls.append((user, remove))
    def shred(path, sudo=False):
        if path.is_dir(): shutil.rmtree(path)
    with mock.patch.object(run, 'pilot_homes', return_value=homes), \
         mock.patch.object(run, 'SEALED', root / 'sealed'), mock.patch.object(run, 'AGENT_STATE', []), \
         mock.patch.object(run, 'HOME', root / 'runner'), \
         mock.patch.object(run.RunArtifacts, 'results_since', return_value=[]), \
         mock.patch.object(run.RunArtifacts, 'result_dirs_since', return_value=[]), \
         mock.patch('run_artifacts.processes.run', command):
        run.seal(c)
        for user, _ in homes:
            assert (c.work / f'agent-state/{user}-home/fixture').is_file()
        with mock.patch.object(run, 'pilot_wall', wall), mock.patch.object(run, 'shred_tree', shred):
            run.wipe(c)
    assert walls == [(user, True) for user, _ in homes]
    assert not any(home.exists() for _, home in homes)
    assert c.card['wipe']['plaintext_files_left'] == 0
    assert cleaned == [1, 2] and c.card['wipe']['factory_cleanup_ok'], 'wipe lost previously prepared slot data'
print('PASS seal/wipe covers every pilot home and removes firewall rules before logs')
