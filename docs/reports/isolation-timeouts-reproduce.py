"""Reproduce the old test assertions offline, under three CPU burners.

Run from the repo root: python3 docs/reports/isolation-timeouts-reproduce.py phase
or replace phase with signal. Uses the unchanged production code in this branch
and the old test at 15e16b5; the only fault is in the in-memory fake transport.
An expected assertion failure returns zero; any other result fails the repro.
"""
import ast
from pathlib import Path
import subprocess
import sys

kind = sys.argv[1]
assert kind in ('phase', 'signal')
source = Path.cwd() / 'tests/bench/test-launch-guards.py'
text = subprocess.check_output(['git', 'show', '15e16b5:tests/bench/test-launch-guards.py'], text=True)
if kind == 'phase':
    old = '        # Run the real snapshot extraction'
    new = '        time.sleep(1.5)\n' + old
    scenario = "run(mode='unreachable', BOAT_COMMAND_TIMEOUT_SECONDS='1')"
    symptom = 'AssertionError: launch '
else:
    old = '    if "factory/run.py" in args[-1]:'
    new = ('    if mode == "stall": sys.stderr.write("setup diagnostics\\n" * 16384); sys.stderr.flush()\n' + old)
    scenario = "run('factory', 'stall', sig=signal.SIGTERM, BOAT_STALL_MINUTES='20', BOAT_COMMAND_TIMEOUT_SECONDS='120')"
    symptom = 'AssertionError: launcher never polled'
assert text.count(old) == 1
tree = ast.parse(text.replace(old, new))
main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
body = main.body[1].body  # main's TemporaryDirectory context
cut = next(i for i, n in enumerate(body) if isinstance(n, ast.Assign)
           and any(isinstance(t, ast.Name) and t.id == 'exam_card' for t in n.targets))
body[cut:] = ast.parse(scenario).body
ast.fix_missing_locations(tree)
burners = [subprocess.Popen([sys.executable, '-c', 'while True: pass']) for _ in range(3)]
try:
    loader = ("import sys; exec(compile(sys.stdin.read(), sys.argv[1], 'exec'), "
              "{'__name__':'__main__','__file__':sys.argv[1]})")
    result = subprocess.run(['nice', '-n', '10', sys.executable, '-u', '-c', loader, str(source)],
                            input=ast.unparse(tree), capture_output=True, text=True)
    print(result.stdout, end='')
    print(result.stderr, end='')
    assert all(p.poll() is None for p in burners)
    assert result.returncode != 0 and symptom in result.stderr, 'expected symptom not reproduced'
    if kind == 'phase':
        assert 'setup failed' in result.stderr and 'deleted vm-1' in result.stderr
        assert 'boat-call: command timed out' in result.stderr
    print('Reproduced old', kind, 'assertion under three CPU burners; no real Boat calls.')
finally:
    for p in burners: p.terminate()
    for p in burners: p.wait()
