
# Keep direct execution independent of the working directory.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))

import time

import factory_board as b

ORDER = ['write', 'G1', 'G2', 'G3', 'G4', 'G5', 'G16', 'G8', 'G10', 'G17', 'G11', 'G12']
NOW = time.time()


def row(card, live=None):
    return b.case_row({'case': 'case-20261022T000000Z-abc123', **card}, NOW - 60, ORDER, live, NOW)


def test_states_and_positions():
    sealed = row({'gates': {g: 'pass' for g in ORDER[1:] if g not in ('G16', 'G17')}})
    assert sealed['state'] == 'sealed' and sealed['missing'] == ['G16', 'G17']
    failed = row({'gates': {'G1': 'fail', 'G12': 'pass'}, 'failed_gate': 'G1'})
    assert failed['state'] == 'failed' and failed['cells']['G1'] == 'fail' and failed['cells']['G12'] is None
    assert failed['cells']['write'] == 'pass'
    blocked = row({'gates': {'G1': 'pass'}, 'status': 'stopped', 'terminal_stop': 'provider_limit:openrouter/xiaomi/mimo-v2.6-pro'})
    assert blocked['label'] == 'MiMo on OpenRouter hit its limit' and blocked['position'] == 'G2'
    paused = row({'gates': {}, 'status': 'stopped', 'terminal_stop': 'paused'})
    assert paused['state'] == 'paused' and paused['cells']['write'] == 'here'


def live(stage, status, stop='running', expires_in=1800, runner=True):
    stamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(NOW - 3 * 3600))
    return {'id': 'bx_test', 'created': NOW - 4 * 3600, 'expires': NOW + expires_in,
            'remote': {'runner_present': runner, 'durability': {},
                       'usage': {'terminal_stop': stop, 'updated_at': NOW - 30},
                       'progress': {'stages': {stage: {'status': status, 'updated_at': stamp, 'elapsed_seconds': 60}},
                                    'completed': {}}}}


def finish(r):
    m = r['live']; rem = m['remote']
    r['live'] = {'machine': m['id'], 'expires': m['expires'], 'saved': m['created'], 'runner': rem['runner_present'],
                 'stop': rem['usage']['terminal_stop'], 'last_call': rem['usage']['updated_at']}
    return r


def test_live_blockers():
    running = finish(row({'gates': {}}, live('role:stress_tester', 'running')))
    assert running['label'] == 'Running: stress tester'
    out = b.blockers([running], {'unlocked': True, 'seconds_remaining': 9e4}, 20.0, [], NOW)
    titles = [x['title'] for x in out]
    assert out[0]['level'] == 'stop' and 'expires' in titles[0]
    assert any('stress tester for 3h' in t for t in titles)
    pausing = finish(row({'gates': {}}, live('role:stress_tester', 'interrupted', 'PauseRequested', runner=False)))
    assert pausing['label'].startswith('Pausing')
    out = b.blockers([pausing], {'unlocked': True, 'seconds_remaining': 9e4}, 20.0, [], NOW)
    assert not any('not running' in x['title'] for x in out)
    idle = finish(row({'gates': {}}, live('G5', 'running', expires_in=9e4, runner=False)))
    out = b.blockers([idle], None, 1.0, [], NOW)
    assert [x['level'] for x in out[:3]] == ['stop'] * 3  # holder unknown, balance, idle machine


if __name__ == '__main__':
    test_states_and_positions(); test_live_blockers(); print('ok')
