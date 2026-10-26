# Local validation — 2026-10-16

Mac Docker Desktop, existing seeded Medusa 2.19.0 volume; default stress traffic,
seed 1000004 (base 1, run 1). No remote model/paid-service calls in these tests.

```sh
bin/checkpoint --scenario scenarios/dev/S13-marketplace --guard none --runs 1
bin/checkpoint --scenario scenarios/dev/S13-marketplace --guard "$PWD/scenarios/dev/S13-marketplace/examples/tables-only" --runs 1
bin/checkpoint --scenario scenarios/dev/S13-marketplace --guard "$PWD/scenarios/dev/S13-marketplace/examples/cross-service" --runs 1
python3 tests/bench/test_inventory.py
```

The checkpoint script was invoked through `runpy` with only its flock changed from
nonblocking to blocking, to queue behind other workers using the same Docker stack.
All judge/traffic/checkpoint code and options were unchanged.

- **none:** pass_runs 0/1; error_runs 0; invalid_runs 0; key_consistent true.
  Violated: cancel-resale, draft-order, order-edit, store-checkout, service:marketplace.
  S promises: Medusa 12 + marketplace 10 = **22 / 10**.
  Channel HTTP statuses: 200, 200, 409, 200. Legit completion 0.88.
  Checkpoint: `results/runs/20261016T213128462582Z-s13-verified-none/checkpoint.json`.
- **tables-only:** pass_runs 0/1; error_runs 0; invalid_runs 0; key_consistent true.
  Violated: **service:marketplace only**. All Medusa-only checks pass.
  S promises: Medusa 5 + marketplace 10 = **15 / 10**.
  Channel HTTP statuses: 200, 200, 409, 200. Legit completion 0.9696969697.
  Checkpoint: `results/runs/20261016T213159806864Z-s13-verified-tables-only/checkpoint.json`.
- **cross-service:** pass_runs 1/1; error_runs 0; invalid_runs 0; key_consistent true.
  Violated: none. S promises: Medusa 5 + marketplace 5 = **10 / 10**.
  Channel HTTP statuses: 200, 409, 200, 409. Legit completion **1.0**.
  Checkpoint: `results/runs/20261016T213242976033Z-s13-verified-cross-service/checkpoint.json`.
- Read-only monitor check passes for every guard: authenticated GET succeeds,
  unauthenticated GET is 401, POST to the monitor is 404, reset view is empty.
- **12 focused regressions pass:** aggregate promises across multiple writers;
  exact-fit stock; missing/silently canceled/rewritten orders; acknowledged cancellation;
  pre-cancel windows; invalid quantities; frozen external/relative projects; shared
  declarations across scenarios; binary service fixtures preserved and hashed.
- Python compilation, Node hook syntax, and `git diff --check` pass.

Initial container-hardening attempts produced invalid reset runs (tmpfs ownership and
Docker Desktop `docker cp` visibility). Those are not calibration verdicts. The corrected
runs above use an owned tmpfs and trusted `/bin/cat` byte transport to host SQLite.
Fresh-volume `bin/setup` was not repeated against the existing seeded volume.

Frozen-source replay also passed:

```sh
bin/replay results/runs/20261016T213242976033Z-s13-verified-cross-service --runs 1
```

Output: `stored pass=True replayed pass=True MATCH; other differing fields: none`.
Report: `results/replays/20261016T213432Z-cross-service.json`.
A following plain `bench.reset()` removed the marketplace container and active service
state and restored the exact Medusa seed baseline.
