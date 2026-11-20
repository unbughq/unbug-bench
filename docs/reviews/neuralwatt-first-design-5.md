# Design review 5: neuralwatt-first (goldfish)

**Scope:** the "## Neuralwatt first (2026-11-20)" section of `docs/designs/neuralwatt-routes.md` (lines 329-707) at 25f6946b, checked against `git diff 3dfdde3c -- factory tests`. I used the zoom_out, design_critic and implementation_readiness lenses. I checked the Deploy section against `control/release.py` (`build_plumbing`, `switch`, `drained`), `control/check-drained.py`, `control/campaign/*.service` and the rest of the doc. I took the VM facts in the doc (the `zzz-approved-ceiling.conf` `ExecStart`, the paths) as given. I also looked at `fix/router-retry` (83c659f8) only to check how it merges with this change.

**Tests run** (all pass, with `uv run -q --with numpy --with scipy --with dbos==3.4.0`):
- `test_neuralwatt_routes.py`: 10 tests.
- `test_neuralwatt_runtime.py`: 8 tests.
- `test_model_router.py`: 49 tests.
- `test_free_routes.py`: 9 tests.
- `test_model_runtime.py`: 11 tests.
- **Deploy step 1:** `test_neuralwatt_routes.py` also passes under a bare interpreter with no extra packages, so it runs as written.
- **Deploy step 2:** the assert passes on this tree.
- **Mutations, on copies in the scratchpad:**
  - Dropping `'chain'` from the acquire allowed-fields set gives 1 failure and 5 errors. So step 1 does catch a bad merge.
  - Removing the `knows` filter in `choices` gives 1 failure and 1 error.
  - Removing the `knows` filter in the queue-ahead check gives 2 failures.

## Earlier blocking findings, re-checked against current text and code

- **R1 B1 (the off switch loops new workers): resolved.**
  - `_admit` sends `chain=chain(model)` (`factory/model_router.py:889`).
  - The router filters by `knows` in `choices` (`:540`) and in the queue-ahead check (`:567`).
  - `_admit` is the only acquire caller in `factory/`, `control/` and `bin/`, so no new-release caller sends a request without a chain.
  - A chain can only narrow `_routes()`. `excluded_lanes`, `ungated_lanes` and `enforce` are unchanged, so the wall holds, and the walled GLM and DeepSeek test passes.
  - No `disabled_routes` entry is used.
- **R1 B2 (list price is also what each step books): resolved.**
  - The doc text matches `budget.py:1410-1413`.
  - `runtime_prices` and `nw_request_worst` both read `_nw_profile` (`token_prices.py:81-84`).
  - The tests pin $1.572865, $0.786432 and the `own=` price source.
  - MiMo and GLM `nw_maximum` values are pinned byte-identical to 3dfdde3c.
- **R2 B1 (rollback hard-stops cases): resolved.** Lines 691-707 forbid moving a batch back to 3dfdde3c and forbid downgrading the router. Withdrawing the key is the loop-free rollback, and `disabled_routes` is for emergencies only.
- **R3 B1 (router checkout): resolved, given the operator's evidence.**
  - Step 3 reads the loaded unit (`systemctl show -p ExecStart`).
  - The router and controller units both run from `source-current` (`control/campaign/unbug-durable-case-campaign.service` `ExecStart`).
  - `production_database` is a fixed path (`model_router.py:327-334`), so `--router-db` in step 4 names the ledger the router really uses.
- **R4 B1 (switch without a drain check): resolved.**
  - Step 4 uses `release.py switch`. It calls `drained()` before printing anything (`release.py:398-403`).
  - It then prints `ln -sfn <build-plumbing source> <source-current>` and the restarts in `--unit` order, router first (`:405-409`).
  - The symlink no longer moves before the drain. `unbug install` and launches come after the check in step 4.
- **Merge with the router-retry change:** it adds no `CHAINS` entry, so `LATE_ROUTES` stays complete. Its `no_route` reason is only sent to callers with `capacity_protocol == 2`, so 3dfdde3c callers still get `outage`. The `capacity_protocol=2, chain=chain(model)` line will conflict, and step 1 catches a merge that drops `chain`.

## Findings

1. **NIT: the step 4 check of the router process cannot tell the old process from the new one.**
   - **Where:** `neuralwatt-routes.md:679`. The check is that `/proc/<MainPID>/cmdline` names `source-current`.
   - **Why it is weak:** the old router's command line also names `source-current`, because it was started through the symlink.
   - **How it can fail:** if the restart is skipped or run before the `ln`, this check and the `status` check both pass. Step 5 then installs workers that send `chain`, the old router refuses them (`invalid admission fields`), and every new-release acquire parks `router_unavailable`.
   - **Fix:** record `systemctl show -p MainPID,ExecMainStartTimestamp unbug-model-router.service` before the switch. Afterwards, require a new MainPID and a start time later than the `ln`.
2. **NIT: step 2 calls the 11-19 hand form "equivalent", but step 4 refuses it.**
   - **Where:** `:654`.
   - **Why:** `switch` calls `recorded(args, "plumbing", ...)`, which needs `~/.unbug-release/plumbing-<12>/state.json` (`release.py:357-358`). It also links only `plumbing['source']`, never a hand-built `source-<short>` tree.
   - **Effect:** the switch fails closed, which is a delay, not a hazard. The tree checked in step 2 could also differ from the tree linked in step 4.
   - **Fix:** drop the "equivalent" sentence and make `build-plumbing` the only path.
3. **NIT: step 2 does not say which interpreter or checkout runs `release.py`.**
   - **Interpreter:** the docstring says to use the controller's venv python (`release.py:4`). `switch` runs `check-drained.py` with `sys.executable`, and that script imports `dbos`. Under `/usr/bin/python3` the drain check exits 2, so the switch is always refused.
   - **Checkout:** `--repo` defaults to the parent of the script. If run from the `source-current` tree, which is an extracted archive with no `.git`, the command fails with "not a commit".
   - **Fix:** write the full command: `/home/user/durable-qualification-20261105/venv/bin/python -B <git checkout that holds the merge>/control/release.py ...`. Use the same form in step 4.
4. **NIT: "wait until the router has no pending paid request" (`:669-670`) cannot be acted on.**
   - **Why:** it names no field. Paid holds live in the sqlite ledger and survive a restart (`_paid_counts`, `status.paid`). An `unknown_requests` count that never clears would block the deploy forever.
   - **Fix:** name the field, `status.paid.outstanding_usd`, or drop the sentence, because `check-drained`'s lease check already covers calls in flight.
5. **NIT: no test pins `LATE_ROUTES` as complete across all chains.**
   - **Where:** `test_neuralwatt_routes.py` compares only the DeepSeek chain minus `LATE_ROUTES` to 3dfdde3c.
   - **Risk:** a later change, or a later merge, that adds a lane to any other chain and forgets `LATE_ROUTES` would hand 3dfdde3c workers a lease they reject. That is the `new-neuralwatt-3` loop again.
   - **Fix:** pin 3dfdde3c's whole `CHAINS` as a literal and assert `tuple(tuple(r for r in c if r not in router.LATE_ROUTES) for c in router.CHAINS) == CHAINS_3DFDDE3C`.
6. **NIT: the drain may take a long time to reach, and the doc does not say how to get there.**
   - **Where:** step 4, "Rerun it until it passes", at `:669`.
   - **Why:** with live cases stepping, a moment with no step in flight may be rare. Between a passing check and the printed restarts, the controller can still start a step, which this repo has seen cost `worker_lost`.
   - **Fix:** say how to reach the drain, for example by holding new step leases or waiting for a quiet moment, and run the printed commands in the same shell straight after the check passes.
7. **NIT, carried from round 3: still open, not blocking.**
   - The founder has not yet confirmed booking case money at 1.8× ($4.91 against $2.73 over 7 days, `:354-357`).
   - The Murphy rows are recorded only in the design until the register lands (`:631-642`).

**Verdict: PASS**

## Elephant response (2026-11-20)

PASS. Every nit is taken except where noted.

- **N1.** Step 4 records `MainPID,ExecMainStartTimestamp` before the switch. Afterwards it requires a new `MainPID` started after the `ln`, and says why the cmdline alone proves nothing.
- **N2.** `build-plumbing` is now the only path. The doc says the 11-19 hand form does not work with `switch`.
- **N3.** Steps 2 and 4 name the controller venv python (`/home/user/durable-qualification-20261105/venv/bin/python`, as in `control/campaign/*.service`), a git checkout holding the merge, and the controller's `config.json`.
- **N4.** The vague "no pending paid request" sentence is dropped. `check-drained`'s lease check covers calls in flight.
- **N5.** `test_neuralwatt_routes.py` now pins 3dfdde3c's whole `CHAINS` as a literal, and asserts that every current chain minus `LATE_ROUTES` equals it.
- **N6.** Step 4 says to pause launches and wait for a quiet moment, and to run the printed commands in the same shell straight after the check passes.
- **N7.** Still open, as before: the founder confirmation goes in the hand-back report, and the Murphy rows wait for the register on `main`.
