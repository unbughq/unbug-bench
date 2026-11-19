# Diff review 4: neuralwatt-routes confirm on 429773f0 (goldfish)

**Prior B1: RESOLVED for the forward rollout. New BLOCKING: the step 6 rollback reopens the same window.**

**(1) Key-on-box window**
- **How a box gets keys.** The controller filters keys by `worker_credentials.accounts`, not by what is in the bundle:
  - `factory/durable/runtime.py:244-255` (`worker_credentials`) decrypts `bundle_file` and passes `names = config["accounts"]` to `pack`.
  - `factory/router_delivery.py:63-64` skips every bundle member not in `names`.
  - `names` comes from the controller config loaded at startup (`runtime.py:222-227`), so a changed accounts list only counts after a controller restart.
  - `factory/durable/workers.py:572` delivers on every acquire, fresh or reused, and the script at 586 runs `rm -rf /dev/shm/secrets` first. A box's key set therefore changes only at its next acquire.
- **Forward direction: no window.** Before step 6 the key is in neither the bundle nor `accounts`, a double guard. Step 6.4 turns the lane on at the router first. Only then does 6.5 install the bundle, add the account and restart the controller. Boxes still on old secrets don't offer the key (`model_runtime.py:70-75`), and old accounts see no NW lane at all.
- **Rollback: there is a window** (`docs/designs/neuralwatt-routes.md:208-210`). It says to put `neuralwatt/` back in `disabled_routes` first, then restore the backups and restart the controller.
  - Every in-flight step already holds the key in `/dev/shm/secrets`.
  - `c.router_accounts` is fixed at `Ctx` init (`factory/run.py:170`), so those steps keep offering `neuralwatt-key`.
  - Redelivery only happens at a new acquire, and a "drained" router restart doesn't end a running step.
  - That is the exact B1 shape: `ordinary_retry.py:136-140` counts the NW route, `exhausted()` never comes true, and a malformed answer loops on outage waits until the deadline.

**(2) Does the new test fail if `disabled_routes` were ignored? Yes.**
- I patched `Store._routes` in memory to drop the `disabled_routes` filter (no files changed). `test_the_off_switch_keeps_an_offered_key_on_the_openrouter_twin` then fails: MiMo gets a lease on `neuralwatt/mimo-v2.6-pro` instead of the credit wait, and the test errors with `KeyError: 'reason'`. Unmodified, all 6 tests pass (run with unittest, since pytest isn't installed).
- NIT: the test sets `self.store.disabled_routes` after construction (`tests/factory/test_neuralwatt_routes.py:73`). It never exercises the constructor/config path (`model_router.py:418-419, 1162`). Passing `disabled_routes=('neuralwatt/',)` to `router.Store(...)` would cover that too.

**(3) New findings**
- **BLOCKING: rollback order** (`docs/designs/neuralwatt-routes.md:208-210`). Disabling the lane while boxes hold the key recreates the B1 loop for in-flight steps, and the loop doesn't end by itself.
  - Fix: restore the bundle, remove `neuralwatt-key` from `worker_credentials.accounts` and restart the controller *first*.
  - Then wait until no in-flight step was delivered the key (every live case has re-acquired), or pause/restart those steps.
  - Only then put `neuralwatt/` back in `disabled_routes`. If an emergency needs the lane off immediately, the runbook must say the affected in-flight steps have to be stopped too.
- **BLOCKING (same rollback; NIT if rollback is deliberately out of scope): stored retry state** (`factory/ordinary_retry.py:128-130`). Once the key is removed, any case whose `ordinary-retries/*/state.json` lists an NW route in `spent_routes` fails the check `spent_routes ⊆ routes(models[0], accounts)`. It raises `infra:ordinary_retry_state_invalid` (`durable/classify.py:112`) every time it re-enters. The runbook protects against moving such cases to a lower release, but not against removing the key while they stay on this one. The rollback needs to say how those cases are handled, for example "cases that ran an NW call keep the key" or "clear/reset their retry state".
- **NIT: "step 4 again" is not enough to bring item 8 live** (`docs/designs/neuralwatt-routes.md:197-198`). Item 8 changes `budget.classify_provider_failure`, which runs on the worker. Cases moved in step 5 stay on the first release until they get another `plumbing_release`. The gate should read "steps 2, 4 and 5 again for the follow-up release". If that release also touches `model_router.py`, step 3 is needed again too.

**Verdict: FAIL.** The forward rollout is fixed, but the step 6 rollback disables the lane while boxes still carry the key.

## Elephant response (2026-11-19)

- **Rollback order (BLOCKING):** fixed. The runbook rollback now runs key first and lane last: restore the bundle, remove the key and restart the controller; wait until every live case starts a new step (or SIGTERM `worker_step`, booking `infra:step_crashed`); only then disable the lane.
- **Stored retry state (BLOCKING):** fixed. The rollback deletes the `ordinary-retries/*/state.json` of a call that lists an NW route in `spent_routes`; that resets one call's retry count.
- **Step 6 gate (NIT):** taken: steps 2, 4 and 5 again for the follow-up release, and step 3 if it touches `model_router.py`.
- **Off-switch test (NIT):** taken: the store is built with `disabled_routes=('neuralwatt/',)`, the router config path.
