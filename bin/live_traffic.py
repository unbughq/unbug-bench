#!/usr/bin/env python3
"""Ordinary API traffic for an entire live observation period; never a probe.

One standard stress schedule plus continuing fitting customer orders. No reset,
stock writes, judge reads, or failure knowledge. The controller bounds lifetime.
"""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(os.environ.get('BENCH_ROOT', Path(__file__).resolve().parents[1]))


def main():
    value, options = float(sys.argv[1]), json.loads(sys.argv[2])
    deadline = value if '--deadline' in sys.argv[3:] else time.monotonic() + value
    if deadline <= time.monotonic():
        print(json.dumps({'error': 'traffic start missed the observation deadline'}))
        return
    loader = importlib.machinery.SourceFileLoader('ordinary_shoppers', str(ROOT / 'bin/shoppers'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    shoppers = importlib.util.module_from_spec(spec); loader.exec_module(shoppers)
    stop = threading.Event()
    records, lock = [], threading.Lock()
    def customers():
        index = 0
        while not stop.is_set():
            index += 1
            attempt_start = time.monotonic()
            try: record = shoppers.shop(index)
            except Exception as error: record = {'error': type(error).__name__}
            record['started_at_monotonic'] = attempt_start
            with lock: records.append(record)
            stop.wait(2)
    thread = threading.Thread(target=customers, daemon=True); thread.start()
    node = subprocess.Popen(['node', str(ROOT / 'cases/medusa-oversell/traffic/run.mjs'),
        str(ROOT / 'projects/medusa/seed-ids.json'), '1', json.dumps(options)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    schedule_start = time.monotonic()
    try:
        out, err = node.communicate(timeout=max(0, deadline - time.monotonic()))
        result = json.loads(out)
        if node.returncode: result['error'] = 'traffic exited nonzero: ' + err[-300:]
        result['standard_schedule_seconds'] = time.monotonic() - schedule_start
        stop.wait(max(0, deadline - time.monotonic()))
    except (subprocess.TimeoutExpired, ValueError):
        node.kill(); out, err = node.communicate()
        result = {'error': 'traffic did not produce a complete schedule before deadline',
                  'standard_schedule_seconds': time.monotonic() - schedule_start,
                  'traffic_stderr_tail': err[-2000:], 'traffic_stdout_tail': out[-2000:]}
    finally:
        stop.set()
    with lock:
        attempts = [r for r in records if not r.get('skipped')]
        result['ordinary_customers'] = {'attempted': len(attempts),
            'placed': sum(bool(r.get('order_id')) for r in attempts),
            'first_attempt_monotonic': records[0]['started_at_monotonic'] if records else None,
            'last_attempt_monotonic': records[-1]['started_at_monotonic'] if records else None}
    print(json.dumps(result), flush=True)


if __name__ == '__main__': main()
