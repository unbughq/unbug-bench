#!/usr/bin/env python3
"""Local read-only board of every factory case: where it is, and what blocks it. Stdlib only.

Reads scorecards (metadata), key-holder status, the machine list and, for each live
factory machine, the same numeric-only progress query as factory_dashboard.py.
Never reads case content, transcripts, guards or keys.
"""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
from pathlib import Path
import re
import shlex
import threading
import time

from factory_dashboard import REMOTE, number, public_remote, run_json, text

ROOT = Path(__file__).resolve().parents[1]
TARGET = 24
LABELS = {'write': 'Writing', 'G1': 'Parts', 'G2': 'Not public', 'G3': 'Builds', 'G4': 'Bug shows',
          'G5': 'Fix works', 'G16': 'Judge breadth', 'G8': 'Fairness', 'G9': 'Realism', 'G6': 'Cheats fail',
          'G13': 'Later step', 'G14': 'Intent', 'G15': 'Beats shortcuts', 'G7': 'New seed',
          'G10': 'Testers', 'G17': 'Diagnosis', 'G11': 'Fake passes', 'G12': 'Sealed'}
MODELS = {'muse': 'Muse', 'mimo': 'MiMo', 'claude': 'Claude', 'gpt': 'GPT', 'glm': 'GLM', 'deepseek': 'DeepSeek',
          'minimax': 'MiniMax', 'qwen': 'Qwen', 'grok': 'Grok', 'kimi': 'Kimi'}
ROUTES = {'opencode-go': 'OpenCode Go', 'opencode': 'OpenCode', 'openrouter': 'OpenRouter',
          'claude': 'Claude plan', 'codex': 'Codex plan'}
ROLES = {'role:writer': 'writer', 'role:stress_tester': 'stress tester', 'role:reviewer': 'reviewer',
         'role:strong_tester': 'strong tester', 'role:easy_tester': 'easy tester',
         'role:second_writer': 'second writer', 'role:diagnoser': 'diagnoser'}


def gate_order():
    found = re.search(r'^GATES = (\[[^\]]*\])', (ROOT/'factory/run.py').read_text(), re.M)
    return ['write'] + ast.literal_eval(found[1]) + ['G12']


def model_name(model):
    """'openrouter/xiaomi/mimo-v2.6-pro' -> 'MiMo on OpenRouter'."""
    if not isinstance(model, str) or '/' not in model:
        return None
    route, name = model.split('/', 1)[0], model.rsplit('/', 1)[-1]
    word = re.split(r'[-.\d]', name)[0]
    if route == 'claude': return 'Claude plan'
    return MODELS.get(word, word.capitalize()) + ' on ' + ROUTES.get(route, route)


def stop_label(stop):
    if stop.startswith('provider_limit:'):
        return (model_name(stop.split(':', 1)[1]) or 'a provider') + ' hit its limit'
    return {'codex_error': 'Codex crashed', 'call_limit': 'Hit the call limit', 'stalled': 'Stalled',
            'Budget ledger stopped: codex_error': 'Codex crashed (ledger stop)'}.get(stop, stop.replace('_', ' '))


def next_step(label):
    if 'OpenRouter' in label: return 'Top up OpenRouter, then resume.'
    if 'Claude plan' in label: return 'Resumes after the Claude plan resets.'
    if 'OpenCode' in label: return 'Resumes after the OpenCode limit resets.'
    if 'Codex crashed' in label: return 'Auto-resume refuses; needs a repair decision.'
    if 'call limit' in label: return 'Needs a budget decision.'
    return 'Needs a look before resuming.'


def ago(seconds):
    seconds = max(0, seconds)
    if seconds < 3600: return '%d min' % (seconds // 60)
    if seconds < 86400: return '%dh %02dm' % (seconds // 3600, seconds % 3600 // 60)
    return '%d d' % (seconds // 86400)


def case_row(card, mtime, order, live, now):
    gates = card.get('gates') if isinstance(card.get('gates'), dict) else {}
    cells = {g: {'pass': 'pass', 'fail': 'fail'}.get(gates.get(g), 'skip' if gates.get(g) else None) for g in order[1:]}
    failed = text(card.get('failed_gate'))
    stop = text(card.get('terminal_stop')) if card.get('status') == 'stopped' else None
    roles = card.get('roles') if isinstance(card.get('roles'), dict) else {}
    writer = (roles.get('writer') or {}).get('model') or ((card.get('models') or {}).get('builder') or [None])[0]
    row = {'case': card['case'], 'short': card['case'][-6:], 'since': mtime, 'live': None,
           'hours': round(number(card.get('wall_minutes')) / 60, 1) if number(card.get('wall_minutes')) else None,
           'writer': model_name(writer)}
    sealed = not failed and not stop and gates.get('G11') == 'pass' and gates.get('G12') == 'pass'
    if not sealed: cells['G12'] = None  # G12 also archives failed cases; only a clean pass is a seal
    if live:
        progress = (live.get('remote') or {}).get('progress') or {}
        for g, r in progress.get('completed', {}).items():
            if g in cells: cells[g] = 'pass'
        stages = sorted(progress.get('stages', {}).items(), key=lambda kv: kv[1]['updated_at'])
        running = [(g, r) for g, r in stages if r['status'] == 'running']
        current = (running or stages or [(None, None)])[-1]
        name, info = current
        gate = name if name in cells else None
        what = LABELS[gate] if gate else ROLES.get(name, 'writing')
        stop = ((live.get('remote') or {}).get('usage') or {}).get('terminal_stop')
        if info and info['status'] == 'running':
            label = 'Running: ' + what
        else:
            label = ('Pausing' if stop in ('PauseRequested', 'paused') else 'Stopped') + (': ' + what + ' ' + info['status'] if info else '')
        started = dt.datetime.fromisoformat(info['updated_at'].replace('Z', '+00:00')).timestamp() if info and info['status'] == 'running' else None
        row.update(state='running', position=gate or 'write', live=live, label=label, stage_started=started,
                   stage_seconds=info.get('elapsed_seconds') if info and not started else None)
    elif card.get('dry_run'):
        row.update(state='test', position=None, label='Dry run')
    elif failed:
        row.update(state='failed', position=failed, label='Failed: ' + LABELS.get(failed, failed))
    elif stop and stop != 'paused':
        row.update(state='blocked', label=stop_label(stop), stop=stop)
    elif stop:
        row.update(state='paused', label='Paused')
    elif sealed:
        row.update(state='sealed', position=None, label='Sealed' + (' · hard' if card.get('difficulty') == 'hard' else ''),
                   missing=[g for g in order[1:-1] if cells.get(g) is None])
    else:
        row.update(state='other', position=None, label='Incomplete record')
    if 'position' not in row:
        row['position'] = next((g for g in order[1:] if cells.get(g) != 'pass'), 'G12') if any(v == 'pass' for v in cells.values()) else 'write'
    cells['write'] = 'pass' if row['state'] == 'failed' or any(v == 'pass' for v in cells.values()) else None
    if row['position'] in cells and row['state'] not in ('failed',):
        cells[row['position']] = 'run' if row['state'] == 'running' else 'here'
    if row['state'] == 'failed': cells[failed] = 'fail'
    row['cells'] = cells
    return row


def live_probe(machine):
    """Numeric-only progress for whichever case lives on this machine."""
    suffix = machine['suffix'] or ''
    lookup = "(lambda m:m[-1] if m else 'case-none')(sorted(x.name for x in (h/'work').glob('case-*%s')))" % suffix
    code = (REMOTE.replace("h=pathlib.Path.home();", "", 1)
            .replace('case=CASE', "h=pathlib.Path.home();case=" + lookup, 1)
            .replace("out={'observed_at'", "out={'case':case,'observed_at'", 1)
            .replace('LAUNCH_SECONDS', str(machine['created']), 1))
    raw = run_json([str(ROOT/'bin/boat-call'), 'ssh', machine['id'], 'python3 -c ' + shlex.quote(code)])
    case = raw.get('case') if isinstance(raw.get('case'), str) and re.fullmatch(r'case-[A-Za-z0-9-]+', raw['case']) else None
    return case, public_remote(raw)


def collect():
    now, errors = time.time(), []
    order = gate_order()
    cards = {}
    for path in (ROOT/'sealed').glob('case-*.scorecard.json'):
        try:
            card = json.loads(path.read_text())
            if re.fullmatch(r'case-[A-Za-z0-9-]+', card.get('case', '')): cards[card['case']] = (card, path.stat().st_mtime)
        except (OSError, ValueError):
            errors.append('Unreadable scorecard: ' + path.name[:40])
    try:
        holder = run_json(['python3', str(ROOT/'factory/key_holder.py'), 'status'])
    except Exception:
        holder = None; errors.append('Key holder status unavailable')
    try:
        boxes = run_json([str(ROOT/'bin/boat-call'), 'list', '--json'])['sandboxes']
    except Exception:
        boxes = []; errors.append('Machine list unavailable')
    try:
        balance = float(run_json([str(ROOT/'bin/boat-spend')]))
    except Exception:
        balance = None; errors.append('Boat balance unavailable')
    machines = []
    for box in boxes:
        name = re.sub(r'[^A-Za-z0-9_:/+. -]+', '-', box.get('name') or '')[:120]
        if not name.startswith('factory') or not re.fullmatch(r'bx_[a-z0-9]+', box.get('id', '')): continue
        tail = name.rsplit(' ', 1)[-1]
        created = dt.datetime.fromisoformat(box['createdAt'].replace('Z', '+00:00')).timestamp()
        machines.append({'id': box['id'], 'name': name, 'state': text(box.get('state')), 'health': text(box.get('health')),
                         'created': created, 'suffix': tail if re.fullmatch(r'[0-9a-f]{6}', tail) else None,
                         'expires': dt.datetime.fromisoformat(box['archiveAfter'].replace('Z', '+00:00')).timestamp()
                         if box.get('archiveAfter') else None})

    def probe(machine):
        try:
            machine['case'], machine['remote'] = live_probe(machine)
        except Exception:
            machine['case'], machine['remote'] = None, None
            errors.append('No progress from machine ' + machine['id'])
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(probe, machines))
    live = {m['case']: m for m in machines if m.get('case')}
    rows = [case_row(card, mtime, order, live.get(case), now) for case, (card, mtime) in cards.items()]
    rows += [case_row({'case': case, 'gates': {}}, now, order, m, now) for case, m in live.items() if case not in cards]
    for row in rows:
        m = row['live']
        if not m: continue
        r = m.get('remote') or {}
        dur = r.get('durability') or {}
        saved = max([m['created']] + ([dur['at']] if dur.get('remote_durable') and dur.get('at') else []))
        row['live'] = {'machine': m['id'], 'expires': m['expires'], 'saved': saved,
                       'runner': r.get('runner_present'), 'stop': (r.get('usage') or {}).get('terminal_stop'), 'last_call': (r.get('usage') or {}).get('updated_at'),
                       'calls': (r.get('usage') or {}).get('calls'), 'cost': (r.get('usage') or {}).get('cost'),
                       'model': model_name((r.get('usage') or {}).get('configured_model')),
                       'context': (r.get('timing') or {}).get('latest_context_tokens')}
    rows.sort(key=lambda r: (['running', 'blocked', 'failed', 'paused', 'sealed', 'other', 'test'].index(r['state']), -r['since']))
    orphans = [m for m in machines if not m.get('case')]
    return {'observed_at': now, 'target': TARGET, 'order': order, 'labels': LABELS, 'rows': rows, 'errors': errors,
            'blockers': blockers(rows, holder, balance, orphans, now), 'balance': balance,
            'holder': holder and {'unlocked': holder.get('unlocked') is True,
                                  'seconds_remaining': number(holder.get('seconds_remaining'))}}


def blockers(rows, holder, balance, orphans, now):
    """Most urgent first: 'stop' = work or money at risk now, 'warn' = needs a decision, 'info' = backlog."""
    out = []
    add = lambda level, title, detail='', cases=(): out.append({'level': level, 'title': title, 'detail': detail, 'cases': list(cases)})
    if holder is None:
        add('stop', 'Key holder status is unavailable', 'No case can launch or resume until it answers.')
    elif not holder.get('unlocked'):
        add('stop', 'Key holder is locked', 'Nothing can launch or resume until you unlock it.')
    elif (holder.get('seconds_remaining') or 0) < 2 * 3600:
        add('warn', 'Key holder locks in ' + ago(holder['seconds_remaining']), 'Running cases keep going; new launches will stop.')
    if balance is not None and balance < 5:
        add('stop' if balance < 2 else 'warn', 'Boat balance is $%.2f' % balance, 'Machines stop when it runs out. Auto-refill is off.')
    for row in rows:
        lv = row['live']
        if not lv: continue
        unsaved = now - lv['saved']
        pausing = lv['stop'] in ('PauseRequested', 'paused')
        if lv['expires'] and lv['expires'] - now < 3600:
            add('stop' if unsaved > 900 else 'warn', '%s: machine expires in %s' % (row['short'], ago(lv['expires'] - now)),
                ('The factory asked to pause; confirm the checkpoint is collected before then. ' if pausing else 'Collect or extend before then. ')
                + 'Unsaved work: %s.' % ago(unsaved), [row['short']])
        if pausing:
            pass
        elif lv['runner'] is False:
            add('stop', '%s: machine is up but the factory is not running' % row['short'], 'Idle machine, still billing.', [row['short']])
        elif lv['last_call'] and now - lv['last_call'] > 1200:
            add('stop', '%s: no model call for %s' % (row['short'], ago(now - lv['last_call'])), 'Likely stalled. ' + row['label'] + '.', [row['short']])
        if row.get('stage_started') and now - row['stage_started'] > 2 * 3600:
            add('warn', '%s: %s for %s' % (row['short'], row['label'][9:].lower() or 'one stage', ago(now - row['stage_started'])),
                'No gate finished in that time. Last model call %s ago.' % ago(now - lv['last_call']) if lv['last_call'] else '', [row['short']])
    for m in orphans:
        add('warn', 'Machine %s has no case on it' % m['id'], 'Still billing. ' + (m['name'] or ''))
    groups = {}
    for row in rows:
        if row['state'] == 'blocked': groups.setdefault(row['label'], []).append(row['short'])
    for label, cases in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        add('warn', '%d %s: %s' % (len(cases), 'cases stopped' if len(cases) > 1 else 'case stopped', label), next_step(label), cases)
    failed = {}
    for row in rows:
        if row['state'] == 'failed': failed.setdefault(row['position'], []).append(row['short'])
    for gate, cases in sorted(failed.items(), key=lambda kv: -len(kv[1])):
        add('info', '%d failed at %s (%s)' % (len(cases), LABELS.get(gate, gate), gate), 'Waiting for repair.', cases)
    paused = [r['short'] for r in rows if r['state'] == 'paused']
    if paused: add('info', '%d paused' % len(paused), 'Checkpointed and collected; waiting for a relaunch.', paused)
    unchecked = [r['short'] for r in rows if r['state'] == 'sealed' and r.get('missing')]
    if unchecked: add('info', '%d sealed before the newest checks' % len(unchecked), 'Not yet run: ' + ', '.join(LABELS[g] for g in sorted({g for r in rows for g in r.get('missing', [])})) + '.', unchecked)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    state, lock = {'observed_at': None, 'rows': [], 'blockers': [], 'errors': ['First look in progress']}, threading.Lock()

    def poll():
        while True:
            try:
                latest = collect()
            except Exception as error:
                with lock: state['errors'] = ['Refresh failed: ' + type(error).__name__]
            else:
                with lock: state.clear(); state.update(latest)
            time.sleep(60)

    report = ROOT/'report/index.html'  # reuse the report's embedded Source Sans 3; offline, no CDN
    fonts = ''.join(re.findall(r'@font-face\{font-family:"Source Sans 3"[^}]*\}', report.read_text())) if report.exists() else ''
    page = lambda: Path(__file__).with_name('factory_board.html').read_text().replace('/*FONTS*/', fonts, 1).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get('Host') not in ('127.0.0.1:%d' % args.port, 'localhost:%d' % args.port):
                return self.send_error(403)
            if self.path == '/':
                body, kind = page(), 'text/html; charset=utf-8'
            elif self.path == '/api/board':
                with lock: body = json.dumps(state).encode()
                kind = 'application/json'
            else:
                return self.send_error(404)
            self.send_response(200); self.send_header('Content-Type', kind)
            self.send_header('Cache-Control', 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

        def log_message(self, *_): pass

    threading.Thread(target=poll, daemon=True).start()
    print('Board: http://127.0.0.1:%d' % args.port, flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
