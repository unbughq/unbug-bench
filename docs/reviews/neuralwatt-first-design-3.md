# Design review 3: neuralwatt-first (goldfish)

**Scope:** the "Neuralwatt first (2026-11-20)" section of `docs/designs/neuralwatt-routes.md` (lines 327-661), checked against `git diff 3dfdde3c -- factory tests` at 5ba15c89. Lenses: zoom_out, design_critic, implementation_readiness.

**Tests run:** `test_neuralwatt_routes.py` (10), `test_neuralwatt_runtime.py` (8) and `test_model_router.py` (49) all pass. I also mutated a scratch copy: removing either `knows` filter (`model_router.py:540` or `:567`) makes two tests fail each time. So the design's claim that each filter is tested holds.

**Earlier blocking findings, re-checked in the current text and code**

- **R1 B1 (off-switch loop): still resolved.**
  - `_admit` sends `chain=chain(model)` (`model_router.py:889`). `chain()` and `routes()` share one source (`:71`, `:175`).
  - The router narrows by `knows()` in `choices` (`:540`) and in the queue-ahead check (`:567`).
  - `chain` can only narrow the router's own `_routes()`, never widen it. `excluded_lanes`, `ungated_lanes`, `bounded_route` and `enforce` are unchanged, so the isolation wall holds. The walled GLM and DeepSeek test passes.
  - `LATE_ROUTES` is complete. `CHAINS` did not change between dafec806, where `neuralwatt-key` was added, and 3dfdde3c.
- **R1 B2 (list price is also what each step books): still resolved.**
  - The text at `:355-367` matches `budget.py:1410-1413`.
  - `runtime_prices` and `nw_request_worst` read `_nw_profile`.
  - The maximum is $1.572865, one request's bound is $0.786432, and the `own=` price source is pinned in a test. MiMo and GLM `nw_maximum` stay byte-identical to 3dfdde3c, pinned as literals.
- **R2 B1 (rollback hard-stops cases): resolved.** Step 5 (`:642-661`) now says:
  - never move a batch back to 3dfdde3c, with the `spent_routes` and `open_steps` reasons;
  - never downgrade the router while a worker on this release is live;
  - withdrawing the key is the loop-free rollback, and `disabled_routes` is for emergencies only.
- **R2 nits 2-5: done.** The comments are updated, deploy step 1 runs the tests on the merged tree, the step 2 check includes `knows`, and the router test helper sends the chain by default.

**Findings**

1. **BLOCKING: the deploy restarts the router on old code, because the design names the wrong checkout.**
   - **The contradiction:**
     - `:434` says "The router runs from `source-current` (`router-approved-config.json`)".
     - Deploy step 2 (`:635`) says "Point `source-current` at the release", then check, then restart.
     - But the checked-in unit runs `/home/user/unbug-bench/factory/model_router.py --config /run/unbug-bench/router.json` (`control/unbug-model-router.service:14`).
     - This doc's own rollout runbook says that checkout is one "which neither `unbug install` nor `source-current` moves" (`:193-197`).
     - `router-approved-config.json` appears nowhere else in the repo.
   - **What goes wrong:**
     - The step 2 assert names no working directory. Run in `source-current`, it passes.
     - The drained restart then reloads the same old router code.
     - Step 3 resumes launches. Every new-release worker sends `chain`, and the old router refuses it with `invalid admission fields` (old allowed-fields line, `3dfdde3c:factory/model_router.py:~507`).
     - Every acquire on those batches then parks as `router_unavailable`. That is the pit stop the deploy order exists to prevent.
     - Separately, re-pointing `source-current` under a running controller (which lazily imports `model_router`, `guard.py:679`) is an unannounced mixed-version change.
   - **Fix (text only):**
     - Correct `:434`.
     - Rewrite step 2:
       - record `git -C /home/user/unbug-bench rev-parse HEAD`;
       - fast-forward that checkout to the release (it also carries `unbug-durable.service`, as `:198-199` notes);
       - run the assert with `cwd=/home/user/unbug-bench`, after confirming the path with `systemctl cat unbug-model-router.service`;
       - then do the drained restart.
     - Drop the `source-current` move, or keep it only with an explicit controller restart.
     - Have rollback step 5 name the same checkout.

2. **NIT: 3dfdde3c is not the only key-offering release that sends no chain.**
   - Release 6ed7c545 (PR #197, dafec806) also offers `neuralwatt-key` and has the same `CHAINS`. So `:457` ("older than 3dfdde3c never offer the key") is wrong.
   - The `LATE_ROUTES` removal rule at `:473` should read "no batch on 6ed7c545 or 3dfdde3c live or held".
   - The behaviour is already safe: `knows` treats every caller without a chain alike.
   - Add any 6ed7c545 batches to the "Who is exposed" list.

3. **NIT: moving a batch to this release reruns its model-stage gates, and step 3 should say so.**
   - The model `verdict_code` digest changes from 60be464f… at 3dfdde3c to 56902128… at HEAD. Neither is pinned: `verdict_code_pins.model.to` is 898b3f9d….
   - So a `plumbing_release` restarts model-stage receipts. `:217` records that cost for the first rollout, but `:640` presents step 3 as free.
   - State the cost per batch. Alternatively, argue for a pin in the diff review. The edit to `model_call_gate.py` is comment-only, but `model_runtime.py` and `model_router.py` change model effects.

4. **NIT: the case-money over-count is not yet a founder decision.**
   - `:367` says the founder's "Neuralwatt anyway" is "taken to cover" booking case money at 1.8× ($4.91 against $2.73 over 7 days). That is the author's reading.
   - Put it to the founder as an explicit line in the next check-in, rather than leaving it as an assumption.

5. **NIT: the Murphy rows are missing from the register.**
   - `new-neuralwatt-2` and `new-neuralwatt-3` (`:317`, `:610-617`) are not in `docs/murphy-register.md`. The main checkout's copy has no neuralwatt rows, and this branch does not track the file.
   - Add them, with the closing tests, when the change lands.

**Verdict: FAIL** (1 blocking)

## Elephant response (2026-11-20)

**B1 is fixed in the text, using live evidence instead of the checked-in unit.**
- On the control VM, `systemctl cat unbug-model-router.service` shows three `ExecStart` lines, and the last one wins:
  - `/etc/systemd/system/unbug-model-router.service`: `/home/user/unbug-bench/...`;
  - `99-qualified-runtime.conf`: `source-324b00f3/...`;
  - `zzz-approved-ceiling.conf`: `.../source-current/factory/model_router.py --config .../router-approved-config.json`.
- So the router really does run from `source-current` today. The campaign controller does too: its `ExecStart` is `source-current/control/campaign/campaign_controller.py`.
- The design now:
  - cites that evidence, and notes that the 11-19 runbook's step 3 path is outdated;
  - has deploy step 2 begin by confirming the last `ExecStart` with `systemctl cat`, and say that the steps apply to whatever checkout it names;
  - runs the assert inside `source-current`;
  - restarts the controller right after the drained router restart, so the controller does not run old code against replaced files;
  - has the rollback name the same checkout and note that re-pointing `source-current` moves both.

**Nits:**
- **N2.** The text now covers 6ed7c545, and the removal rule names both releases. No `source-6ed7c545` is installed on the VM: a scan of every `source-*` directory found `neuralwatt-key` only in `source-3dfdde3c` and in a `.tmp` staging directory.
- **N3.** Deploy step 3 states that `plumbing_release` reruns model-stage gates, as the operator's choice per batch. New launches are unaffected.
- **N4.** The design marks the over-count as for the founder to confirm. The hand-back report raises it.
- **N5.** The rows stay recorded in the design until the register lands on `main`, as `new-neuralwatt-1` was. The design says so.
