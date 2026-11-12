"""Helper machines: independent seeded gate work (G6/G7 cheat checkpoints) on short-lived workers.

The case worker sends one job per checkpoint (case/guard/scenario digests, bench version, release
hash, runs, seed, label). A helper runs bin/checkpoint on its own bench copy and returns the
checkpoint directory's files, sealed with an HMAC over the exact job. The case worker verifies the
seal, rebuilds the directory and reads it with the same checkpoint_evidence.read_completed the serial
path uses, so the verdict code sees byte-identical (summary, records). Anything that goes wrong
with a helper (death, refused inputs, bad seal, invalid batch) requeues that job only; a job no
helper completes is left out of the result and the caller runs it locally, exactly as today.

The transport (how a helper is leased and a job reaches it) is a small interface, `HelperPool`:
    lease() -> handle            raises HelperUnavailable when no helper can be had now
    run(handle, job, key) -> sealed result (seal()); raises HelperDied when the helper is lost
    release(handle, dead)        deletes the helper
Trust: the seal authenticates the transport (the helper holds the per-dispatch key, so it proves the
result came from a helper that echoed this exact job), not that bin/checkpoint really ran; a
compromised helper could fabricate records. Helpers are our own short-lived workers, as snapshot
authors are. Structural checks narrow the gap: exactly the files a `runs`-run checkpoint writes, the
summary agreeing with its records (read_completed), and the helper's own machine class equal to the job's.
Design and the remaining build (Boat transport, G10 tries, G5/G15): ARCHITECTURE.md "Helper machines".
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import queue
import re
import secrets
import threading
import time
from pathlib import Path

JOB_VERSION = 1
MAX_ATTEMPTS = 2                      # per job: a helper fault retries once on another helper, then local
_NAME = re.compile(r"checkpoint\.json|[0-9]{2,}\.json")


class HelperDied(Exception):
    """The helper was lost while running a job."""


class HelperUnavailable(Exception):
    """No helper can be leased now."""


class HelperRefused(Exception):
    """The helper's own copy of the inputs differs from the job (stale case, bench or release)."""


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest_of(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def machine_class() -> dict:
    """Stress timing depends on the machine: a helper must be the size of the case worker."""
    try: gib = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30)
    except (ValueError, OSError, AttributeError): gib = None
    return {"cpus": os.cpu_count(), "mem_gib": gib}


def make_job(*, case, guard, scenarios, bench, release, runs, seed, label, machine=None, workers=1) -> dict:
    """Everything that decides what the checkpoint measures. Digests are of trees, not paths."""
    return {"version": JOB_VERSION, "kind": "checkpoint", "case": case, "guard": digest_of(guard),
            "scenarios": [digest_of(s) for s in scenarios], "bench": bench, "release": release,
            "runs": runs, "seed": seed, "label": label,
            "machine": machine_class() if machine is None else machine, "workers": workers}


def collect(directory) -> dict:
    """Helper side: the files bin/checkpoint left (summary and numbered records)."""
    return {p.name: p.read_text() for p in sorted(Path(directory).glob("*.json")) if _NAME.fullmatch(p.name)}


def seal(key: bytes, job: dict, files: dict, machine=None) -> dict:
    body = {"job": job, "files": files, "machine": machine_class() if machine is None else machine}
    return {"body": body, "mac": hmac.new(key, canonical(body), hashlib.sha256).hexdigest()}


def open_sealed(key: bytes, job: dict, sealed) -> dict:
    """Case side: the files, only if the seal verifies and answers exactly this job."""
    if not isinstance(sealed, dict) or not isinstance(sealed.get("body"), dict) or type(sealed.get("mac")) is not str:
        raise ValueError("malformed helper result")
    body = sealed["body"]
    if not hmac.compare_digest(sealed["mac"], hmac.new(key, canonical(body), hashlib.sha256).hexdigest()):
        raise ValueError("helper result seal does not verify")
    if body.get("job") != job:
        raise ValueError("helper result answers a different job")
    if job.get("machine") is not None and body.get("machine") != job["machine"]:
        raise ValueError("helper machine class differs from the job's")
    files = body.get("files")
    if not isinstance(files, dict) or any(type(t) is not str for t in files.values()):
        raise ValueError("helper result files malformed")
    if job.get("kind") == "checkpoint" and set(files) != {"checkpoint.json", *(f"{i:02}.json" for i in range(1, job["runs"] + 1))}:
        raise ValueError("helper result is not exactly one checkpoint batch")
    return files


def execute(job: dict, key: bytes, *, check, run, machine=machine_class) -> dict:
    """Helper side of one job. `check(job)` raises HelperRefused if local inputs differ; `run(job)`
    runs bin/checkpoint and returns the checkpoint directory. A helper of another machine class
    refuses, and the seal records the class it ran on."""
    check(job)
    mine = machine()
    if job.get("machine") is not None and mine != job["machine"]:
        raise HelperRefused(f"machine class {mine} differs from job's {job['machine']}")
    return seal(key, job, collect(run(job)), mine)


def run_jobs(pool, jobs: dict, *, cap: int, key: bytes, accept, boundary=lambda: None, ledger=None) -> dict:
    """{name: accept(job, files)} for every job a helper completed; others are omitted.

    At most `cap` helpers at once, at most cap + len(jobs) leases in all. `boundary()` runs before
    each dispatch; what it raises (a money or lease stop) stops dispatch and propagates.
    """
    todo, done, fatal = queue.Queue(), {}, []
    for name in jobs: todo.put((name, 1))
    lock, leases, limit = threading.Lock(), [0], cap + len(jobs)
    note = ledger or (lambda event: None)

    def worker():
        handle = began = None
        while not fatal:
            try: name, attempt = todo.get_nowait()
            except queue.Empty: break
            try: boundary()
            except BaseException as stop:
                fatal.append(stop); todo.put((name, attempt)); break
            try:
                if handle is None:
                    with lock:
                        if leases[0] >= limit: todo.put((name, attempt)); break
                        leases[0] += 1
                    handle, began = pool.lease(), time.monotonic()
                    note({"event": "lease", "helper": str(handle)})
                done[name] = accept(jobs[name], open_sealed(key, jobs[name], pool.run(handle, jobs[name], key)))
                note({"event": "job", "helper": str(handle), "job": name, "ok": True})
            except HelperUnavailable:
                todo.put((name, attempt)); break
            except Exception as error:   # helper fault of any kind: this job only goes round again
                note({"event": "job", "helper": str(handle), "job": name, "ok": False, "error": type(error).__name__})
                if attempt < MAX_ATTEMPTS: todo.put((name, attempt + 1))
                if handle is not None:
                    _release(pool, handle, True, began, note)
                    handle = None
        if handle is not None: _release(pool, handle, False, began, note)

    threads = [threading.Thread(target=worker) for _ in range(max(1, min(cap, len(jobs))))]
    for t in threads: t.start()
    for t in threads: t.join()
    if fatal: raise fatal[0]
    return done


def _release(pool, handle, dead, began, note):
    try: pool.release(handle, dead)
    finally: note({"event": "release", "helper": str(handle), "dead": dead, "seconds": round(time.monotonic() - began, 1)})


def checkpoint_shards(c, guards, runs, seed, label, *, case, scenarios, bench, boundary=lambda: None) -> dict:
    """{str(guard): (summary, records)} for the cheat checkpoints helpers completed (G6/G7).

    Needs c.helper_pool and c.args.helper_workers > 0. Results are rebuilt on disk and read by
    checkpoint_evidence.read_completed, the serial path's own reader.
    """
    import types
    import checkpoint_evidence
    from durable.checkpoints import verdict_code
    jobs = {str(g): make_job(case=case, guard=_tree(g), scenarios=scenarios, bench=bench, release=verdict_code(),
                             runs=runs, seed=seed, label=label,
                             workers=getattr(c.args, "bench_workers", 1)) for g in guards}
    root = c.work / "helper-results"

    def accept(job, files):
        out = root / digest_of(job)[:24]
        out.mkdir(parents=True, exist_ok=True)
        for name, text in files.items(): (out / name).write_text(text)
        receipt = checkpoint_evidence.RECEIPT_PREFIX + json.dumps(
            {"version": 1, "path": str(out / "checkpoint.json"), "requested_runs": runs})
        summary, records, _ = checkpoint_evidence.read_completed(
            types.SimpleNamespace(returncode=0, stdout=receipt, stderr=""), runs, label, require_valid=True)
        return summary, records

    def ledger(event):
        with _LEDGER_LOCK, (c.work / "helper-ledger.jsonl").open("a") as f:
            f.write(json.dumps({**event, "label": label, "at": round(time.time())}) + "\n")

    return run_jobs(c.helper_pool, jobs, cap=max(1, c.args.helper_workers), key=secrets.token_bytes(32),
                    accept=accept, boundary=boundary, ledger=ledger)


_LEDGER_LOCK = threading.Lock()


def _tree(path):
    from calibration import tree_digest
    return tree_digest(path)
