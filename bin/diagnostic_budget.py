"""One bounded model diagnostic shared by strategy and checkpoint CLI entry points.

This is a tool budget, not a sandbox against arbitrary shell commands.
"""
import json, os, pathlib, subprocess


def execute(command, budget_dir, seconds=300, workers=1):
    import signal, time
    if not 1 <= seconds <= 900 or workers < 1:
        raise ValueError('invalid diagnostic limits')
    budget_dir = pathlib.Path(budget_dir)
    budget_dir.mkdir(parents=True, exist_ok=True)
    try:
        (budget_dir / 'claimed').mkdir()
    except FileExistsError:
        raise RuntimeError('diagnostic allowance exhausted; unfinished validation belongs to factory gates')
    metadata = {'status': 'running', 'runs': 1, 'workers': workers, 'limit_seconds': seconds,
                'gate_evidence': False}
    path = budget_dir / 'status.json'
    path.write_text(json.dumps(metadata) + '\n')
    start = time.monotonic()
    environment = {k: v for k, v in os.environ.items() if not k.startswith('FACTORY_STRATEGY_')}
    environment['UNBUG_DIAGNOSTIC_PROCESS_GROUP'] = '1'
    process = None
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=environment, start_new_session=True)
        output, _ = process.communicate(timeout=seconds)
        if process.returncode:
            metadata['status'] = 'error'
            raise RuntimeError('diagnostic execution failed; not a gate verdict')
        metadata['status'] = 'completed'
        return output
    except subprocess.TimeoutExpired:
        metadata['status'] = 'timeout'
        raise RuntimeError('diagnostic time allowance exhausted; unfinished, not passed') from None
    except BaseException:
        if metadata['status'] == 'running': metadata['status'] = 'error'
        raise
    finally:
        if process is not None:
            # Also clean descendants after successful exit; diagnostics must not leave tool loops running.
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            try: process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                # An independently detached command may retain inherited pipes; never wait forever.
                for stream in (process.stdout, process.stderr):
                    if stream is not None: stream.close()
                process.wait(timeout=2)
        metadata['elapsed_seconds'] = round(time.monotonic() - start, 3)
        path.write_text(json.dumps(metadata) + '\n')

