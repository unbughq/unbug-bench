"""G10 overlap and cancellation; synthetic gates, no models or bench instances."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import pathlib, sys, threading, types, tempfile
from contextlib import ExitStack
from unittest import mock
sys.path.insert(0, str((pathlib.Path(__file__).resolve().parents[2] / "factory")))
import run


def exercise(mode, *, reason=None):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    seen = []
    temporary = tempfile.TemporaryDirectory()
    c = types.SimpleNamespace(args=types.SimpleNamespace(dry_run=False, resume=None, bench_workers=2, no_early_probe=True),
                              card={'gates': {}, 'failed_gate': None}, prepared_factory_slots=4, work=pathlib.Path(temporary.name))
    c.case = c.work / 'case'; c.case.mkdir()
    def tester(c):
        seen.append('G10-start'); started.set()
        try:
            if mode == 'cancel':
                assert c.role_cancel.wait(3), 'foreground failure did not cancel G10'
                raise run.BudgetError('cancelled')
            assert release.wait(3), 'foreground gate did not overlap G10'
            if mode == 'budget': raise run.BudgetError('provider_limit')
            if mode == 'pause': raise run.PauseRequested()
            if mode in ('infra', 'dual-infra'):
                from run_validity import InvalidInfra
                raise InvalidInfra('saved reset failure')
            c.card['calibrators'] = {'synthetic': True}; c.card['difficulty'] = 'hard'
            return mode != 'reject', {'synthetic': True}
        finally:
            seen.append('G10-end'); finished.set()
    def bench(c):
        if reason:
            assert not started.is_set()
        else:
            assert started.wait(3), 'G10 did not start before G6 finished'
            assert c.calibrator_slot_offset == c.args.bench_workers
        seen.append('G6'); release.set()
        if mode == 'dual-infra':
            from run_validity import InfrastructureExhausted
            raise InfrastructureExhausted('foreground invalid')
        return mode != 'cancel', {'bench': True}
    def final(c):
        assert finished.is_set(), 'G11 ran before G10 joined'
        seen.append('G11'); return True, {}
    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(run, 'GATES', ['G5', 'G8', 'G9', 'G6', 'G13', 'G14', 'G15', 'G7', 'G10', 'G11']))
        stack.enter_context(mock.patch.object(run, 'log'))
        stack.enter_context(mock.patch.object(run, 'g10_overlap_reason', return_value=reason))
        for gate in ('g5', 'g8', 'g9', 'g13', 'g14', 'g15', 'g7'):
            stack.enter_context(mock.patch.object(run, gate, return_value=(True, {})))
        for gate, fn in [('g6', bench), ('g10', tester), ('g11', final)]:
            stack.enter_context(mock.patch.object(run, gate, fn))
        try:
            run.run_gates(c)
        except run.BudgetError as error:
            assert mode == 'budget' and str(error) == 'provider_limit'
        except run.PauseRequested:
            assert mode == 'pause'
        else:
            assert mode not in ('budget', 'pause'), 'background stop was swallowed'
    assert finished.is_set(), 'G10 thread outlived the gate loop'
    if mode == 'cancel':
        assert c.card['failed_gate'] == 'G6' and 'G11' not in seen
    elif mode == 'reject':
        assert c.card['failed_gate'] == 'G10' and 'G11' not in seen
        assert c.card['gates']['G10'] == 'fail'
    elif mode == 'dual-infra':
        assert c.card['infrastructure_gate']['gate'] == 'G6'
        assert c.card['gates'].get('G10') != 'invalid-infra'
        assert c.card['gates']['G6'] == 'invalid-infra'
    elif mode == 'infra':
        assert not c.card.get('failed_gate') and 'G11' not in seen
        assert c.card['gates']['G10'] == 'invalid-infra'
        assert c.card['terminal_stop'] == 'infrastructure_exhausted'
    elif mode == 'pass':
        assert c.card['failed_gate'] is None and seen[-1] == 'G11'
        assert c.card['gates']['G10'] == 'pass'
        assert 'G10' in c.card['gate_minutes']
    if reason: assert seen.index('G6') < seen.index('G10-start')
    temporary.cleanup()


for mode in ('pass', 'cancel', 'reject', 'budget', 'pause', 'infra', 'dual-infra'):
    exercise(mode)
    print('PASS G10 overlap ' + mode)
exercise('pass', reason='memory allowance')
print('PASS G10 serial fallback')

# G10's two contexts retain their own slots, including checkpoint calls (no fan-out).
c = types.SimpleNamespace(args=types.SimpleNamespace(resume=None, bench_workers=2), card={}, calibrator_slot_offset=2,
                          role_cancel=threading.Event())
slots = []
def calibrate(child, role):
    assert child.args.bench_workers == 1 and child.role_cancel is c.role_cancel
    slots.append(child.factory_slot)
    return {'solved': 0, 'tries': 1}
with mock.patch.object(run, 'parallel_calibrators', return_value=False), mock.patch.object(run, 'make_pilots') as pilots, \
     mock.patch.object(run, 'calibrate', calibrate):
    assert run.g10(c)[0]
assert sorted(slots) == [2, 3]
assert pilots.call_args.args[1] == [('pilot-strong', 2), ('pilot-easy', 3)]
print('PASS G10 tester slots stay beyond foreground pool')

# Capacity admission is fail-closed and counts both testers plus every foreground worker.
import tempfile
with tempfile.TemporaryDirectory() as tmp:
    c.case = pathlib.Path(tmp); (c.case / 'scenarios').mkdir()
    c.args.dry_run = False
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "bin"))
    import bench
    with mock.patch.object(run, 'parallel_calibrators', return_value=False):
        assert 'parallel calibrators unavailable' in run.g10_overlap_reason(c)
    with mock.patch.object(run, 'parallel_calibrators', return_value=True), \
         mock.patch.object(bench, 'load_scenario', return_value={}), \
         mock.patch.object(bench, 'isolated_inventory_services', return_value=True), \
         mock.patch.object(bench, 'factory_memory_fits', return_value=False) as fits:
        assert 'memory allowance' in run.g10_overlap_reason(c)
        assert fits.call_args.args[1] == 4
        fits.return_value = True
        assert run.factory_slots(c) == 4
print('PASS G10 admission requires isolation and combined memory capacity')
