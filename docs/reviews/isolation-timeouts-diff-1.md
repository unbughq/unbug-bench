## Goldfish diff review 1: `t3/isolation-timeouts` against `docs/designs/isolation-timeouts.md`

**Mode:** REVIEW, with the zoom_out and implementation_readiness personas. `git merge-base 4a10966 HEAD` is `4a10966`, and the head is `e26fb55`.

I read the design, ENGINEERING.md, design reviews 1–3, the full diff, and the public fixtures. I compared the fixtures with the canonical `control-home/launches/653390…` directory read-only. I made no edits, ran no cloud commands and decrypted nothing. The only commands I ran were:
- `tests/factory/test_isolation_timeouts.py`, which passed (15 tests).
- `boat --version`.
- `boat list --help`, with `BOAT_NO_UPDATE=1`.

I did not write `docs/reviews/isolation-timeouts-diff-1.md`, because I am read-only. Please save this text there verbatim.

## Verdict: FAIL

There are two blockers. Both are regressions in code that no test executes, and the suite cannot see them. Row 44 is proven. Row 52 is proven with minor gaps. Row 31 needs a test and a wording fix. Row 46 is not yet proven.

Scope fit is good:
- There are no `budget.py` or provider-classifier changes.
- The only `run.py` changes are `sh()` and the ready marker.
- No gate evaluator is edited.
- The `test_restore_failover_bundle.py` deletion is ignored, as you instructed.
- Rows 17/18/29/30/32/37/42/43/45/49/50 stay open, and row 28 is untouched.

## Blockers

**B1. The `wipe` child script calls an undefined name, so slot cleanup silently fails.**
- **Scope:** `factory/run_artifacts.py:130`.
- **Defect:** The diff replaced `subprocess.run` with `processes.run` inside a `python3 -c "import bench, subprocess; …"` string. That child process never imports `processes`. `bench.py` imports it only inside `command()`.
- **Check:** `python3 -c "import subprocess; processes.run(['x'])"` gives `NameError: name 'processes' is not defined`.
- **Effect:** The child runs `stop_inventory_services` and `dc('down')`, then dies with a `NameError`. The slot's `docker image rm` and the `assert not command(['docker','images','-q', GUARD_IMAGE])` never execute. The result is `factory_cleanup_ok=False` on every parallel run (slots > 1), which is the normal `nproc/2` case.
- **Residue:** The tagged `unbug-bench-medusa:guard-<slot>` images keep patched case source. The later cleanup only removes the unsuffixed tag, and `guard_image_left` only checks that tag.
- **Why no test caught it:** `tests/factory/test_parallel.py:218` mocks `run_artifacts.processes.run`, so the `-c` string never runs. This is the "fixture proves nothing" pattern from ENGINEERING §4.
- **Guidance:** Fix the string, either by importing `processes` with a `sys.path` entry for `bin`, or by restoring `subprocess` inside it. Add a test that actually executes or compiles that snippet with `bench` stubbed.

**B2. Every `bench.command()` now has an implicit 120-second cap when no deadline is inherited.**
- **Scope:** `bin/bench.py:90` and `bin/processes.py` `envelope()`. `limit == inf` becomes `monotonic() + 120`.
- **Where the deadline exists:** Inside the supervised runner it is inherited, so `UNBUG_PROCESS_DEADLINE` is set by the supervisor or `sh()`.
- **Where it breaks:** Unsupervised callers get the 120-second default, including long Docker work:
  - `bin/bake-image.sh:17` runs `bin/setup`, which calls `dc("build","medusa")`, `up --wait`, `npm run migrate` and `seed`. This path was unbounded before.
  - `factory/public_fixture_smoke.py:86` calls `bench.setup`.
  - Manual `bin/setup` runs and an unsupervised `run.py` also hit it.
- **Why it matters:** The design's "default 120" was written for `run()` in general. It never says bench Docker builds are capped at 2 minutes. This changes behaviour outside the stated boundary, and nothing tests it.
- **Guidance:** Make `bench.command` bounded only by an inherited or explicit deadline. Alternatively, pass an explicit long timeout from `bench.command`, and add a test that a command longer than 120 seconds with no env deadline is not killed.

## Majors

**M1. Row 46 is not proven with the real runner.**
- **Scope:** `SupervisorTests` and the `startup-crash` mode in `tests/bench/test-launch-guards.py`.
- **What is tested:** The supervisor runs `python -c <injected code>` and ignores the real worker args. The controller-side `STARTUP_FAILED` test uses a `runner-status.json` that the fake VM writes by hand.
- **What is not tested:** No test runs the real `factory/run.py` under the supervisor. So `run.py`'s placement of the `FACTORY_RUNNER_READY` touch (after signal setup, `run.py:2473`) is unproven. A real early crash is also unproven, which is the headline of row 46. Both retry safety (`untouched` plus the ready marker) and the "finished" classification depend on that marker.
- **Guidance:** Add one test that runs the real `run.py` through `runner_supervisor.py`, in dry-run or with a poisoned import. Assert the marker, the retry bound, and the receipt fields. Otherwise mark row 46 partial rather than closed.

**M2. Row 31's closure has a coverage gap and an unstated caveat.**
- **Coverage gap:** The Mac holder case is the one the row's text names: no `BOAT_CMD`, so discovery of `~/.ascii/bin/boat` or `which boat`. That path is untested.
  - All `BoatTests` set `BOAT_CMD` to a fake file named `boat`.
  - Deleting the zsh discovery is therefore unproven.
  - A temp `HOME` with `.ascii/bin/boat` would cover it.
- **Fixture check:** The `1.0.85` fixture matches the local binary (`boat 1.0.85` confirmed). `list.json` is byte-identical to the canonical `control-home` copy. `billing.json` is a one-field reduction. I found no canonical billing capture to compare it with.
- **Wording:** `control/setup.sh:39` still downloads Boat unpinned, which is the register's cited location. The "Closed by" cell should say that the code refuses on mismatch and that the VM install pin remains a deploy prerequisite (design lines 267–277). Without that, the cell overclaims "pin the executable".

**M3. `unset identity` no longer reaches the launcher shell.**
- **Scope:** `factory/launch.sh:671`, now inside the `( … )` setup subshell.
- **Defect:** The parent keeps the founder age identity in memory for the entire monitoring phase. Before, the main shell unset it after restore. The subshell also swallows `unset` for any other per-worker secret.
- **Guidance:** Run `unset identity` in the parent after capturing `setup_status` when `restore` is set, or whenever n=1. This is one line.

**M4. Uncommitted test fix needs committing.**
- **Scope:** `tests/tools/test_gate_smoke.py`.
- **Defect:** The working tree has an uncommitted line, not mine, that sets `UNBUG_CONTROL_HOME`. HEAD lacks it, so that test runs `boat-spend` against the real `~/.unbug-control`. I found that ledger on this machine, created at 22:08. It is empty now.
- **Risk:** A reserved hold left there would block real launches until it expires. The branch must carry this fix.

## Row closures (31/44/46/52)

| Row | Verdict | Basis |
|---|---|---|
| 44 | **Proven** | `ProcessesTests` run the real `run.sh` with `bench_workers=1` and the real `strategy.silent_checkpoint`. They kill a SIGTERM-ignoring child in a new session and assert that its heartbeat stops. They cover timeout, role_cancel, `pause_on_term`, async cancellation, successful-exit cleanup, nested deadlines and the shared-owner survival case. The command is synthetic, which is expected for fault injection. The saved launch argv drives `argument_parser` only. |
| 52 | **Proven, minor gaps** | The test uses the real `harbor` `protocol.Handler` over real sockets. It covers 413, missing length and non-object bodies, a partial body with the timer expiring, `/healthz` staying healthy, and bounded close. Gaps: there is no 503 concurrent-ask test, though the design lists it. The "trickle" test sends one partial write and not a trickle. |
| 31 | **Conditional** | See M2. |
| 46 | **Not yet proven** | See M1. |

## Check-by-check notes (no action unless stated)

- **Wallet:**
  - The locking and idempotency of the ledger look right.
  - A refused check reserves nothing.
  - Expired holds reconcile only when `list --all --json` returns `hasMore=false` and every sandbox is in an inactive state.
  - `--all` is a valid flag (confirmed with `boat list --help`). It includes the stopped, pending and error states, so an `error` sandbox keeps the hold. This is fail-closed.
  - The fixture `list.json` has `sandboxes: []`, so the non-empty-fleet branch is only fake-driven. That is acceptable for now.
- **Spend accounting:**
  - `actual_spend_usd` is null, and the delta is `account_balance_delta_usd` with `account_observation`.
  - `public-qualification/finish.py` is the only live consumer and it refuses null, as the design says.
- **Unknown creation:**
  - `new.N.pending` survives `guard_exit` and holds the reservation. Tested.
  - The loop then moves to the next serial without retrying that creation, which is as designed.
- **Frozen-runtime guard:**
  - It runs before allocation.
  - The real `candidate-vm-canary` manifest lacks the supervisor and `processes.py` (confirmed), so the guard refuses it.
  - This branch therefore cannot launch from the current qualified release until a new release is cut and the `qualified-release.py` pins and `launcher-sha256.json` are regenerated. That is the parent's rollout item, not a defect.
  - An unqualified upload cannot install `bin/*` (`worker_upload` ships only `factory/*`). The guard passes, and the worker's own `worker_release` check then fails against the old baked image. This is the open row 32.
- **Supervisor:**
  - The final `child = None` adjustment is correct.
  - `collect.sh`'s `pkill -f '^python3 .*factory/run.py'` also matches the supervisor command line. The double TERM is safe under `pause_on_term`'s `SIG_IGN`, as the design states.
- **Murphy register:**
  - Closed rows 31/44/46/52 cite existing tests and classes.
  - Rows 17/18/42/43/49 stay open with no progress notes. That is honest.
  - Row 49's description still says "Actual spend is an account balance delta", which is no longer true for Boat. Add a progress note (nit).

## Nits

- `GatePipeline.check` uses `__import__('contextlib')` and a function-local import (`gate_pipeline.py:48–51`). Use a module-level import for consistency.
- `kill_tree` forks `ps -axo` on every `processes.run` call. This is acceptable, but note the cost across thousands of `sh()` calls.
- The `STARTUP_FAILED` probe also fires for `phase='finished'` or `'stopped'` without DONE. That correctly detects a runner that died after the ready marker, but the message says "startup". Fine operationally.

## To reach PASS

1. Fix B1 and B2, each with a test that executes the real path.
2. Add the real-`run.py` supervisor test for M1, or demote row 46 to partial.
3. Add the default-discovery `BoatTests` case and the row 31 caveat for M2.
4. Make the `unset identity` change for M3.
5. Commit the `test_gate_smoke.py` fix for M4.
6. Resubmit for a goldfish round.


---

Elephant disposition

B1 and B2 fixed with executable real-path regressions. M1 uses the real runner at pre/post-ready import boundaries; M2 covers default executable discovery and narrows the register wording; M3 clears the parent identity; M4 commits an isolated test control home. Additional focused cleanup guarantees and the bounded integration harness budget are documented in the design. No blocking finding was rejected. Pending fresh round 2.

Focused fix validation: 20 fault tests pass; gate setup, parallel cleanup and
owner protocol regressions pass. Added actual concurrent-ask and body-trickle
cases for the row-52 nits. contextlib imports normally; the processes import
intentionally remains local because the runner initializes its bin path after
importing GatePipeline. This retains the real runner import boundary.
