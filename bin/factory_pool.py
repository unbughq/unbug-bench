"""Factory-only subprocess workers. No global env or bench state is changed in the parent."""
import concurrent.futures
import contextlib
import fcntl
import json
import os
import pathlib
import subprocess
import sys
import tempfile


def worker_env(slot):
    return {**os.environ, "UNBUG_FACTORY_SLOT": str(slot)}


def prepare_slot(slot):
    """Capture setup diagnostics instead of losing them outside the crash receipt."""
    p = subprocess.run([sys.executable, "-c", "import bench; bench.prepare_factory_slot()"],
                       cwd=pathlib.Path(__file__).resolve().parent, env=worker_env(slot),
                       capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"Factory slot {slot} preparation failed:\n{p.stdout}\n{p.stderr}")


def prepare(slots, *, previous_slots=1, fresh=False, execute=None):
    """Own extra-shop retirement, readiness and serial preparation before trials.

    execute is the logged factory command adapter. Without it, the pool uses
    subprocesses. Explicit fresh=True (startup and G3) discards and seeds slot zero.
    A failed main setup returns False; extra-shop failures raise, as in G3.
    """
    import bench
    if type(slots) is not int or slots < 1 or type(previous_slots) is not int or previous_slots < 1:
        raise ValueError("factory slot counts must be positive integers")
    if bench.FACTORY_SLOT:
        raise ValueError("factory pool preparation requires slot zero")
    # The checkpoint path already holds this lock for ordinary pool preparation.
    # G3 owns it across retirement, main setup and all extra-shop setup; taking it
    # only in the main child leaves destructive phases open to another checkpoint.
    lock_context = (bench.RESULTS / bench.LOCK).open("w") if fresh else contextlib.nullcontext()
    with lock_context as lock:
        if fresh: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _prepare(slots, previous_slots=previous_slots, fresh=fresh, execute=execute)


def _prepare(slots, *, previous_slots, fresh, execute):
    import bench
    def invoke(slot, code):
        args = [sys.executable, "-c", code]
        kwargs = dict(cwd=pathlib.Path(__file__).resolve().parent, env=worker_env(slot))
        if execute is not None:
            execute(args, **kwargs, timeout=3600, check=True)
        else:
            p = subprocess.run(args, **kwargs, capture_output=True, text=True)
            if p.returncode:
                raise RuntimeError(f"Factory slot {slot} preparation failed:\n{p.stdout}\n{p.stderr}")
    for slot in range(slots, previous_slots):
        invoke(slot, "import bench; bench.retire_factory_slot()")
    if fresh:
        args = [sys.executable, "-c", "import bench; bench.prepare_factory_main()"]
        kwargs = dict(cwd=pathlib.Path(__file__).resolve().parent, timeout=3600)
        result = execute(args, **kwargs) if execute is not None else subprocess.run(args, **kwargs)
        status = result if isinstance(result, int) else result.returncode
        if status:
            return False
    missing = [slot for slot in range(1, slots)
               if fresh or not bench.factory_slot_ready(bench.RESULTS, slot)]
    if missing:
        # Preparation must finish before any trial starts; shared image builds
        # and seeding must not compete with the main application's live shop.
        if execute is None:
            bench.stop_inventory_services()
            bench.dc("stop", *bench.APP_SERVICES)
        else:
            execute([sys.executable, "-c",
                     "import bench; bench.stop_inventory_services(); bench.dc('stop', *bench.APP_SERVICES)"],
                    cwd=pathlib.Path(__file__).resolve().parent, timeout=3600, check=True)
        for slot in missing:
            if execute is None:
                prepare_slot(slot)
            else:
                invoke(slot, "import bench; bench.prepare_factory_slot()")
    return True


def run_records(guard, numbers, options, scenarios, workers, per_run_options=None):
    """Prepare once per worker, keep original run numbers (and therefore traffic seeds)."""
    prepare(min(workers, len(numbers)))
    def chunk(slot):
        # Slot zero retains the final run's database for fake-pass's post-traffic diff.
        selected = [n for i, n in enumerate(numbers) if (len(numbers) - 1 - i) % workers == slot]
        if not selected:
            return {}
        # A killed worker can leave records behind: keep them inside seal/wipe's scope.
        with tempfile.TemporaryDirectory(prefix=".factory-runs-", dir=pathlib.Path(__file__).resolve().parents[1] / "results") as tmp:
            job = pathlib.Path(tmp) / "job.json"
            output = pathlib.Path(tmp) / "records.json"
            job.write_text(json.dumps({"guard": str(guard), "numbers": selected, "options": options,
                                       "per_run_options": per_run_options or {},
                                       "scenarios": [str(s["dir"]) for s in scenarios]}))
            subprocess.run([sys.executable, __file__, str(job), str(output)], env=worker_env(slot), check=True)
            return {r["run"]: r for r in json.loads(output.read_text())}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        records = {}
        for result in pool.map(chunk, range(workers)):
            records.update(result)
    return records


if __name__ == "__main__":
    import bench
    job = json.loads(pathlib.Path(sys.argv[1]).read_text())
    try:
        if not bench.IDS.is_file() or (bench.FACTORY_SLOT and not bench.factory_slot_ready(bench.ROOT / "results", bench.FACTORY_SLOT)):
            raise RuntimeError(f"Factory slot {bench.FACTORY_SLOT} is not prepared; run bin/setup or prepare the pool first")
        summary = bench.run_case(job["guard"], len(job["numbers"]), run_numbers=job["numbers"],
                                 options=job["options"], per_run_options={int(k): v for k, v in job.get("per_run_options", {}).items()},
                                 scenarios=[bench.load_scenario(s) for s in job["scenarios"]], frozen_inputs=True)
        directory = bench.ROOT / summary["results_directory"]
        pathlib.Path(sys.argv[2]).write_text(json.dumps([
            json.loads((directory / f"{i:02}.json").read_text()) for i in job["numbers"]]))
    finally:
        bench.stop_inventory_services()
        bench.dc("stop", *bench.APP_SERVICES)  # idle workers must leave RAM for the next build
