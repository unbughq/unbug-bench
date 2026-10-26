#!/usr/bin/env python3
"""Local read-only pane for one explicitly selected factory launch; stdlib only."""
import argparse
import datetime as dt
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import re
import shlex
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'factory'))
from public_progress import _row, _stage
REMOTE = r'''
import json,pathlib,sqlite3,time,os,re
case=CASE
launch_seconds=LAUNCH_SECONDS
h=pathlib.Path.home();s=h/'sealed';w=h/'work'/case
out={'observed_at':time.time(),'cpu_count':os.cpu_count(),'load_1m':os.getloadavg()[0]}
p=s/(case+'.progress.json')
out['progress']=json.loads(p.read_text()) if p.exists() else None
p=s/(case+'.continuation-budget.json')
if p.exists():
 j=json.loads(p.read_text());out['usage']={k:j.get(k) for k in ('calls','cost','terminal_stop','configured_model')};out['usage']['updated_at']=p.stat().st_mtime
 out['usage']['active_count']=len(j.get('active',[]))
p=w/'durable-checkpoint.json'
if p.exists():
 j=json.loads(p.read_text());out['durability']={k:j.get(k) for k in ('at','local_durable','remote_durable','pending','sha256','error')}
out['done']=(s/'DONE').exists()
out['runner_present']=False
runner_pids=set();model_processes=[]
for p in pathlib.Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:
  args=(p/'cmdline').read_bytes().split(b'\0')
  if any(a.endswith(b'/factory/run.py') for a in args[:3]) and b'--resume' in args and args[args.index(b'--resume')+1].decode()==case:
   out['runner_present']=True;runner_pids.add(int(p.name))
  if (p/'comm').read_text().strip()=='opencode' and b'--title' in args:
   title=args[args.index(b'--title')+1].decode();ppid=int((p/'stat').read_text().split()[3])
   if re.fullmatch(r'factory-[A-Za-z0-9_-]+',title):model_processes.append((ppid,title))
 except OSError:pass
out['timing']=None
db=h/'.local/share/factory-opencode/opencode/opencode.db'
titles=[title for ppid,title in model_processes if ppid in runner_pids]
if db.exists() and len(titles)==1:
 try:
  c=sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True,timeout=2);c.row_factory=sqlite3.Row
  # Only numeric usage/timing and fixed tool/role names are selected; never text,
  # reasoning content, tool input/output, credentials or prompt columns.
  row=c.execute("select id,time_created,time_compacting,tokens_reasoning from session where title=? and time_created>=? order by time_created desc limit 1",(titles[0],launch_seconds*1000)).fetchone()
  if row:
   sid=row['id'];t={'session_started_at':row['time_created']/1000,'reasoning_tokens':row['tokens_reasoning'],'compaction_recorded':row['time_compacting'] is not None}
   t['tools']=[dict(r) for r in c.execute("select json_extract(data,'$.tool') as tool,json_extract(data,'$.state.status') as status,count(*) as count,sum(max(0,coalesce(json_extract(data,'$.state.time.end'),?)-json_extract(data,'$.state.time.start'))) / 1000.0 as seconds from part where session_id=? and json_extract(data,'$.type')='tool' group by 1,2",(int(time.time()*1000),sid))]
   t['reasoning_seconds']=c.execute("select sum(json_extract(data,'$.time.end')-json_extract(data,'$.time.start'))/1000.0 from part where session_id=? and json_extract(data,'$.type')='reasoning'",(sid,)).fetchone()[0]
   t['latest_context_tokens']=c.execute("select json_extract(data,'$.tokens.total') from message where session_id=? and json_extract(data,'$.role')='assistant' and json_extract(data,'$.time.completed') is not null order by time_created desc limit 1",(sid,)).fetchone()
   t['latest_context_tokens']=t['latest_context_tokens'][0] if t['latest_context_tokens'] else None
   if t['latest_context_tokens'] is None:
    row2=c.execute("select json_extract(data,'$.tokens.input'),json_extract(data,'$.tokens.cache.read'),json_extract(data,'$.tokens.output'),json_extract(data,'$.tokens.reasoning') from message where session_id=? and json_extract(data,'$.role')='assistant' and json_extract(data,'$.time.completed') is not null order by time_created desc limit 1",(sid,)).fetchone()
    t['latest_context_tokens']=sum(x or 0 for x in row2) if row2 and any(x is not None for x in row2) else None
   out['timing']=t
  c.close()
 except Exception as e:out['timing_error']=type(e).__name__
print(json.dumps(out))
'''


def run_json(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError('Metadata query failed (exit %d)' % result.returncode)
    return json.loads(result.stdout)


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def text(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_:/+. -]{1,180}', value) else None


def public_remote(raw):
    """Explicit response projection: unexpected fields never reach the browser."""
    out = {k: number(raw.get(k)) for k in ('observed_at', 'cpu_count', 'load_1m')}
    out.update({k: raw.get(k) if type(raw.get(k)) is bool else None for k in ('runner_present', 'done')})
    usage = raw.get('usage') or {}
    out['usage'] = {k: number(usage.get(k)) for k in ('calls', 'cost', 'updated_at', 'active_count')}
    out['usage'].update({k: text(usage.get(k)) for k in ('terminal_stop', 'configured_model')})
    progress = raw.get('progress') or {}
    out['progress'] = {section: {k: clean for k, v in (progress.get(section) or {}).items()
                               if _stage(k) and (clean := _row(v))}
                       for section in ('stages', 'completed')}
    timing = raw.get('timing')
    if isinstance(timing, dict):
        out['timing'] = {k: number(timing.get(k)) for k in
                         ('session_started_at', 'reasoning_tokens', 'reasoning_seconds', 'latest_context_tokens')}
        out['timing']['compaction_recorded'] = timing.get('compaction_recorded') is True
        out['timing']['tools'] = [{k: number(row.get(k)) for k in ('count', 'seconds')} |
                                 {'tool': row['tool'], 'status': row['status']}
                                 for row in timing.get('tools', []) if row.get('tool') in
                                 ('bash', 'read', 'write', 'edit', 'glob', 'grep', 'websearch', 'webfetch', 'apply_patch')
                                 and row.get('status') in ('pending', 'running', 'completed', 'error')]
    else:
        out['timing'] = None
    d = raw.get('durability') or {}
    out['durability'] = {'at': number(d.get('at')), **{k: d.get(k) if type(d.get(k)) is bool else None
                                                  for k in ('local_durable', 'remote_durable', 'pending')}}
    return out


def collect(identity):
    now = time.time()
    out = {'observed_at': now, 'case': identity['case'], 'worker': identity['worker_id'],
           'controller_pid': identity['controller_pid'], 'baseline_calls': identity['calls'],
           'baseline_cost': identity['cost'], 'launch_started_at': identity['launched_at'], 'errors': []}
    try:
        holder = run_json(['python3', str(ROOT/'factory/key_holder.py'), 'status'])
        job = holder.get('jobs', {}).get(identity['job'])
        out['controller_running'] = bool(job and job.get('pid') == identity['controller_pid'] and job.get('exit') is None)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        out['controller_running'] = None
        out['errors'].append('Holder status unavailable')
    try:
        provider = run_json([str(ROOT/'bin/boat-call'), 'info', identity['worker_id'], '--json'])['sandbox']
        if provider['id'] != identity['worker_id']:
            raise ValueError('identity mismatch')
        out['provider'] = {k: text(provider.get(k)) for k in ('state', 'health', 'createdAt', 'archiveAfter')}
        out['provider']['hydrated'] = provider.get('hydrated') is True
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired):
        out['provider'] = None
        out['errors'].append('Exact worker status unavailable; this is not collection proof')
    if out['provider']:
        try:
            code = REMOTE.replace('CASE', repr(identity['case']), 1).replace('LAUNCH_SECONDS', str(dt.datetime.fromisoformat(identity['launched_at'].replace('Z', '+00:00')).timestamp()), 1)
            raw = run_json([str(ROOT/'bin/boat-call'), 'ssh', identity['worker_id'], 'python3 -c '+shlex.quote(code)])
            out['remote'] = public_remote(raw)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
            out['remote'] = None
            out['errors'].append('Worker progress unavailable')
    archive = ROOT/'sealed'/(identity['case']+'.checkpoint.tar.gz.age')
    card_path = ROOT/'sealed'/(identity['case']+'.scorecard.json')
    if archive.is_file() and card_path.is_file():
        card = json.loads(card_path.read_text())
        with archive.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        out['checkpoint'] = {'mtime': archive.stat().st_mtime,
                             'verified': digest == card.get('sha256') and card.get('case') == identity['case'],
                             'new_since_launch': digest != identity['generation'] and digest == card.get('sha256') and card.get('case') == identity['case']}
    else:
        out['checkpoint'] = None
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    identity = json.loads((args.evidence/'canary-live.json').read_text())
    if not re.fullmatch(r'case-[A-Za-z0-9-]+', identity['case']) or not re.fullmatch(r'bx_[a-z0-9]+', identity['worker_id']):
        raise ValueError('Invalid launch identity')
    state = {'observed_at': None, 'case': identity['case'], 'worker': identity['worker_id'], 'errors': ['First observation pending']}
    lock = threading.Lock()

    def poll():
        deadline = dt.datetime.fromisoformat(identity['monitor_stop_at'].replace('Z', '+00:00')).timestamp()
        while time.time() < deadline:
            try:
                latest = collect(identity)
            except Exception as error:
                # Keep the last observation with an explicit collection failure.
                with lock:
                    state['errors'] = ['Refresh failed: '+type(error).__name__]
            else:
                with lock:
                    state.clear(); state.update(latest)
                target = args.evidence/'dashboard-latest.json'
                temporary = target.with_suffix('.tmp')
                temporary.write_text(json.dumps(latest, indent=2)+'\n'); temporary.replace(target)
            time.sleep(60)
        with lock:
            state['polling_ended'] = True

    page = Path(__file__).with_name('factory_dashboard.html').read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get('Host') not in ('127.0.0.1:'+str(args.port), 'localhost:'+str(args.port)):
                self.send_error(403); return
            if self.path == '/':
                body, kind = page, 'text/html; charset=utf-8'
            elif self.path == '/api/status':
                with lock:
                    body = json.dumps(state).encode()
                kind = 'application/json'
            else:
                self.send_error(404); return
            self.send_response(200); self.send_header('Content-Type', kind)
            self.send_header('Cache-Control', 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    threading.Thread(target=poll, daemon=True).start()
    print('Dashboard: http://127.0.0.1:'+str(args.port), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
