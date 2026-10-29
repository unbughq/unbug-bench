## Goldfish diff review 2: `t3/isolation-timeouts` (E, first increment)

**Mode:** REVIEW, using the zoom_out and implementation_readiness personas. I read both agent docs first.

**Scope:**
- Base is `8c5de61`, head is `7847387`.
- I read the full diff review 1 with its dispositions.
- I read the `c04f5ff..7847387` fix delta in full.
- I read the design, the register rows, the public fixtures, and the canonical control-home `launch.json`, `list.json` and `new.1` listings, read-only.

**What I ran:** I made no edits and did no cloud calls or decryption. I ran these scripts with `-B`:
- `tests/factory/test_isolation_timeouts.py`: 20/20 pass.
- `tests/bench/test-launch-guards.py`: all checks pass (376 s).
- `tests/bench/test_gate_setup.py`: 15 pass.
- `tests/tools/test_gate_smoke.py`: 7 pass.
- `tests/factory/test_parallel.py`: all PASS lines, but only with `BENCH=$PWD`. Run bare it fails on a `~/unbug-bench` path. `tests/run.py` sets `BENCH`, so this is a harness artifact and not a defect.

`git status` was clean before and after. `~/.unbug-control/boat-reservations.json` is still `reservations: {}`, so `test_gate_smoke` no longer touches the real control home.

## Verdict: PASS

All six prior findings are fixed and I found no new blockers. The four closures (31/44/46/52) are proven, each with a nit-level caveat noted below.

## Prior findings

| Finding | Status | Evidence |
|---|---|---|
| **B1** wipe child calls an undefined `processes` | **Fixed** | `run_artifacts.py:130` now has `import bench, processes`. `test_parallel_wipe_executes_real_child_and_removes_slot_guard` copies the real `bench.py`, `bench_judging.py`, `processes.py`, `case_permissions.py` and `compose.yaml`. It runs the actual `python -c` snippet against a fake `docker` executable only. It asserts `factory_cleanup_ok` and a recorded `image rm -f unbug-bench-medusa:guard-1` with `slot=1`. No process call is mocked. |
| **B2** accidental 120 s cap on standalone `bench.command` | **Fixed** | `bench.command(timeout=3600)` still takes the minimum with the inherited deadline. The test advances `processes.time.monotonic` by 121 s only after the real child signals ready. The standalone call completes. A countercase with an inherited deadline of `now+60` raises `TimeoutExpired`. The general helper's 120 s default is unchanged. |
| **M1** no real `run.py` supervisor proof | **Fixed** | `test_real_runner_early_import_and_ready_boundary` copies all `factory/*.py` and asserts the copied `run.py` is byte-identical to the real one. It poisons one dependency per case and runs the real `runner_supervisor.py` with saved argv (resume args stripped) plus `--dry-run`. The numbers match the design. |
| **M2** default Boat discovery and caveat | **Fixed** | `test_default_home_discovery_pins_without_an_interactive_shell` uses a temp `HOME` with `.ascii/bin/boat` and no `BOAT_CMD`. A match returns the list fixture, a mismatch exits nonzero with empty stdout. Register row 31 now says "mismatch refused. VM install pin remains a deployment prerequisite". |
| **M3** `unset identity` | **Fixed** | `launch.sh:687` is `[ -z "$restore" ] || unset identity` after `set -e` and `setup_status`. When `restore` is empty, `launch.sh:235` already unset it. |
| **M4** test control-home leak | **Fixed and committed** | `test_gate_smoke.py:186` sets `UNBUG_CONTROL_HOME` to a temp dir. I grepped the other tests that reach `boat-spend`: `test-launch-guards`, `test_codex_login_rotation`, `test_control_resume`, `test_isolation_timeouts` and `test_control_key_holder` all set it. The rest stub it or never run `--check` or `--finish`. |

The extra delta is sound:
- **`kill_tree` PGID snapshot:** `killed_groups` stops duplicate signals to one group. A reaped leader's group is signalled only if the snapshot shows a member with `pgid == pid`. Shared or diagnostic children still go through `os.kill`, never the caller's group or session.
- **`run()` and `shell()`:** direct children are joined and streams closed even if `kill_tree` raises.
- **`gate_pipeline.py`:** `contextlib` is now a normal import. `processes` stays function-local, which is correct. `run.py:12` imports `GatePipeline` before `run.py:117` installs `BENCH/bin` on `sys.path`.

## Row closures

| Row | Verdict | Basis |
|---|---|---|
| **31** | **Proven** | The fixtures match the canonical copies: `list.json` and the launch argv. The saved `boat-version.json` records `1.0.85`. Real-billing, default-discovery, mismatch-refusal and `BOAT_NO_UPDATE` cases are covered. The register states the residual deploy prerequisite (`control/setup.sh:39` stays unpinned), which matches design lines 267–277. |
| **44** | **Proven** | Unchanged from review 1, and B1 no longer undermines the slot cleanup. |
| **46** | **Proven** | The real runner under the real supervisor shows pre-ready failure retrying exactly 3 times with no marker and no work. Post-ready failure is not retried: marker present, one attempt, `reason=finished`, work preserved. Neither case writes DONE. The receipt fields match the design. |
| **52** | **Proven** | The concurrent-503 test holds a real model call open, gets a 503 on the second ask, and the first still completes with 200. The body-trickle test sends activity past `REQUEST_SECONDS=.2`. The subsequent `recv` must return `b''`, a reset or `HTTP`. If the timer were refreshed by activity, `recv` would raise a timeout and fail the test. Total elapsed time is under 2 s. |

Row 49 carries an honest "Progress" note and stays open. Rows 17/18/29/30/32/37/42/43/45/50 are untouched or open. Row 28 is not touched.

## Scope and rules

- There are no `budget.py` or gate-evaluator changes. `git diff` over those paths is empty.
- `run.py` is limited to `sh()` plus the ready marker.
- Parent D/status/interface documentation changes are excluded from this review.
- The `test_restore_failover_bundle.py` deletion is parent-authorized.

## New findings (no blockers)

- **Nit, full-suite proof:** the full suite on `7847387` was still running when I finished. `/tmp/isolation-reviewed-tests.log` was being rewritten at the time. I confirmed only the focused scripts above, so please attach the final `130/0` line before merge. Design lines 336–348 still quote the older run and say "Re-run the final full suite".
- **Nit, `kill_tree` ps probe:** `subprocess.Popen(['ps', …])` sits outside the `try`. A missing `ps` raises `FileNotFoundError` out of cleanup. If `ps` times out, `group_present` stays at its `True` default. The killpg of a recycled pid is theoretical, and both come from code already reviewed.
- **Nit, `run()` finally block:** if `kill_tree` succeeds but `process.wait(timeout=2)` raises `TimeoutExpired`, that can mask the original exception. This is only reachable when SIGKILL fails.
- **Nit, trickle assertion:** `assertIn(reply[:4], (b'', b'HTTP'))` is loose. The test is still meaningful because the `recv` timeout exception fails it if the connection stays open.
- **Process note:** the 60 s harness budget in `test-launch-guards.py` is a test-only change, and production deadlines are unchanged. The suite took 376 s here, with the host loaded by the concurrent run.

## To merge

Nothing blocks merge from this review. Attach the clean full-suite result on `7847387` as a condition, and keep the deployment prerequisites in the design: a newly qualified release, and the `boat 1.0.85` check on the control VM. I did not merge.


---

Elephant disposition and final validation

PASS accepted; no blocking findings were rejected. The mandatory full suite
on reviewed source commit 78473870ec2acb6672e9a2a24c97ac1f24114751 completed:

```text
uv run --with numpy --with scipy python -B tests/run.py
130 test scripts run; 0 failed.
```

All 20 focused fault tests pass as independently confirmed by the goldfish.
No implementation changed after this review; the final commit only records
review/validation evidence. Optional nits remain optional; remaining E rows
and deployment prerequisites stay as recorded in the design. No merge or
Boat worker launch was performed.
