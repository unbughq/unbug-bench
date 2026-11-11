#!/usr/bin/env python3
"""Whether the controller is drained enough to restart it or send a release. Read-only.

  python3 control/check-drained.py --config <controller config.json> [--router-db <factory.sqlite3>]

Not drained (exit 1): an attempt has leased a worker and not recorded its attempt_step, or the
model router holds an unexpired lease. Exit 2: something could not be read. Restarting the
controller or sending a plumbing/bench release while a step runs mid-call cost 19 hours of
infra:worker_lost from 6 November.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import time

ATTEMPTS = ["attempt_workflow", "prepared_attempt_workflow"]
ROUTER_DB = Path.home() / ".unbug-control" / "router" / "factory.sqlite3"   # model_router.production_database


def _name(step) -> str:
    return str(step["function_name"]).rsplit(".", 1)[-1]


def steps_in_flight(client) -> list[str]:
    """Attempt workflow IDs that hold a worker and have not recorded attempt_step: the engine
    leased a worker (lease_step, or lease_alive_step for a prepared attempt) and is running it."""
    running = []
    for row in client.list_workflows(name=ATTEMPTS, status=["PENDING"], load_input=False, load_output=False):
        steps = client.list_workflow_steps(row.workflow_id)
        names = {_name(s) for s in steps}
        leased = any(_name(s) == "lease_step" and isinstance(s["output"], dict) and s["output"].get("worker_id")
                     or _name(s) == "lease_alive_step" and s["output"] is True for s in steps)
        if leased and "attempt_step" not in names:
            running.append(row.workflow_id)
    return sorted(running)


def router_leases(path, now: float) -> int:
    """Unfinished, unexpired model router leases (the router expires the rest on its next call)."""
    db = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    try:
        return db.execute("SELECT COUNT(*) FROM leases WHERE outcome IS NULL AND expires > ?", (now,)).fetchone()[0]
    finally:
        db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True, help="the controller's config.json")
    parser.add_argument("--router-db", type=Path, default=ROUTER_DB, help="the model router's ledger")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text())
        from dbos import DBOSClient
        client = DBOSClient(system_database_url=config["database_url"], retry_connection_errors=False,
                            observability_query_timeout_sec=10)
        try:
            running = steps_in_flight(client)
        finally:
            client.destroy()
        leases = router_leases(args.router_db, time.time())
    except Exception as error:   # noqa: BLE001 - unknown is never drained
        print(f"cannot tell whether drained: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    for key in running:
        print(f"step in flight: {key}")
    print(f"router leases active: {leases}")
    if running or leases:
        print("NOT DRAINED: wait for these to finish before a restart or release send", file=sys.stderr)
        return 1
    print("drained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
