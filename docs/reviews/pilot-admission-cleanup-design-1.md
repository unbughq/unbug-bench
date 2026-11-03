**Round 1 verdict: FAIL.** One blocking finding. Everything else is Major or a Nit with a small fix.

Scope: `docs/designs/pilot-admission-cleanup.md` at `f8037c6`, against baseline `7dbdc58`. It was reviewed as `zoom_out`, `design_critic` and `implementation_readiness`, against `heilmeier-standard.md` and `implementation-readiness-standard.md`. I also checked the plan in `abc11ef:docs/designs/pilot-run.md`, B's commits `2c174ba` and `0292abc`, and the startup design `bef877d`. Read-only; nothing saved.

## Blocking

**B1 — A new worker can be launched before the previous worker's Boat charge is settled. That burns a lifecycle slot for good.**
- **Where:** design lines 73–83 and 130–134; `factory/batch_holder.py:242-245, 820-823`; `factory/launch.sh:376` (`guard_init`); `0292abc:bin/boat-spend` lines 196–197.
- **Concurrency is freed early.** It counts operations with `retirement is None`. Retirement is set by `_reconcile_one` as soon as the deletion receipts exist, which is before cleanup has run the inventory check and B's `--settle` (that retries every 60 s or more).
- **So the next worker dispatches too soon.** Once operation A retires, the next operation can be reserved: the operator's next initial job, or an automatic `schedule_waits` successor. It then passes both `armed` checks and is durably marked `dispatch_started`.
- **The shell guard then refuses it.** After that, `launch.sh` → `guard_init` → `boat-spend --check` refuses with "infrastructure liability unsettled" while A's row is still `reserved` or `finished`.
- **The operation is lost for good.** `record_exit` keeps it pending, then `_reconcile_one` finds no creation and marks it `failed/preflight_refused`. Under this design it counts toward 6 and toward the job's 2, and because the identity is the same, replay returns the failed operation. One case is lost with no worker ever created.
- **Why this is the design's job.** Line 133 says "No new settlement hook is needed; the existing shell guard still owns admission". That is exactly the gap: the guard decides only after the durable dispatch point.
- **Minimal fix, required code:**
  - In the pilot branch of `armed`, at both call sites, raise `MoneyWait` unless every *other* operation in the batch with `dispatch_started` has a cleanup status of `complete` or `not_dispatched`. Read it from `location(home, other).with_suffix('.status.json')`.
  - With B merged, `complete` already means settled.
  - This keeps the wait before `dispatch_started`, so it becomes TEMPFAIL and is retried. No new file, hook or ledger read is needed.
- **Required test:** successor dispatch while the predecessor's status is `settlement_pending` or `uncertain` returns TEMPFAIL. The operation stays pending with `dispatch_started=False`, and no slot is consumed beyond the reservation.
- **Dependency (not code here):** any practice rows still unsettled in the home-wide ledger cause the same post-dispatch refusal for the first pilot job. Before activation, state "all home `boat-reservations.json` rows settled" as a precondition.

## Major (should fix; small)

**M1 — After a cleanup restart, the live worker's deletion can be delayed by many minutes.**
- **Where:** design lines 109–114.
- **Mechanism:** the loop steps operations one after another. Revalidating up to 6 remembered-terminal operations can each run `boat-call list` (100 s timeout) and B's `settle` (180 s timeout). That runs before the live worker's `step` gets to the 2700 s deletion deadline.
- **Fix:** each iteration, write all ready markers first. Then step the non-terminal dispatched operations, then revalidate terminal ones. The Boat TTL is only a backstop.

**M2 — Changing the policy or release mid-pilot breaks cleanup.**
- **Where:** design line 116; `batch_holder.py:109-113`.
- **Mechanism:** `_operations` refuses the whole journal if any operation's `release_sha256` or the `manifest_sha256` differs from the current policy. So "changes to policy require redeployment" really means a redeploy makes the restarted cleanup refuse *every* operation, including live workers.
- **Fix:** say so explicitly. The policy, release and pin are frozen from the first dispatch until every dispatched operation is terminal. Breaking that freeze leaves only the Boat TTL.

**M3 — The "fits the absolute deadline" claim is overstated.**
- **Where:** design lines 125–128.
- **Mechanism:** the `.started` file is written only after `boat new` returns, which can take up to `BOAT_NEW_TIMEOUT_SECONDS=300`, plus launch preparation. The TTL counts from the worker's own creation, so a VM can outlive `batch_deadline`.
- **Fix:** either require more than `ttl + 300 + margin` remaining at the second `armed` check, or reword: `batch_deadline` bounds admission, and VM lifetime is at most dispatch + creation latency + 3600 s.

**M4 — The unit and CLI details leave choices to the implementer.**
- **Where:** design lines 101–108.
- **Unit fields:** say the pilot unit copies `control/unbug-practice-cleanup@.service` exactly, except Description, ExecStart and practice env → `EnvironmentFile`. That keeps `HOME`, `UNBUG_CLOUD=boat`, `WorkingDirectory`, `LimitCORE=0` and `RestartSec=5`.
- **`--batch`:** state whether it is a bare flag or takes a value. If it takes a value, say it must equal the policy batch id.
- **Reboot:** practice units have no `[Install]` section, so after a VM reboot the pilot cleanup stays down. Dispatch fails closed, but that is a pit stop. Add `WantedBy=multi-user.target`, or record manual start after reboot as a known residual.

**M5 — Three more decisions the design leaves open.**
- **Order inside `_admit`:** do the window and cap checks run before or after the existing-identity replay? Line 74 implies cap before replay only for histories already over the bound. Specify it.
- **Holder start without a pin:** `key_holder.policy_load` calls `bind(...)` for every job (`key_holder.py:157-159`). The new bind refusal therefore makes the key holder and cleanup *fail to start* when the pin is missing or wrong, not just go inactive. State that this is intended and add it to test 1.
- **How the holder gets the pin:** line 105 says "holder deployment uses the same pin" but not how. Name it, e.g. a key-holder drop-in `EnvironmentFile=/home/user/.unbug-control/pilot.env`. Deploying it is the owner's dependency.

## Nits

- **N1 — Duplicated manifest values.** `max_lifecycles` and `max_lifecycles_per_case` are required to equal fixed constants, and `infrastructure_limit_usd` only cross-checks `--max-spend`. This is acceptable as explicit approval data; otherwise move them to constants in `pilot.py`.
- **N2 — Infrastructure ceiling wording.** With B, the real ceiling is `min(all historical caps)` minus all settled charges across the whole home, including practice (`boat-spend` lines 204–206). Line 45, "separate manifest ceiling", should say that.
- **N3 — Reuse existing helpers.** For the window check, call `practice.admission(record)` and `practice.deadlines` and add only the `starts_at` check, rather than reimplementing them.
- **N4 — Practice pins.** Adding to `TRUSTED_FILES` and editing the holder and cleanup changes `code_sha256`, so current practice pins become invalid. B's design already requires a re-pin; say so here too.
- **N5 — Objective wording.** The Objective uses jargon ("holder", "armed"), which the Heilmeier standard forbids. Write one plain sentence.
- **N6 — Report label.** An operation reserved but not dispatched before the window closes stays pending forever. Give it a report label (e.g. `window_closed`) so the outcome report has a terminal reading.

## Checked and OK

- **No legacy bypass.**
  - With the planned guards in `batch_request` and `bind`, the legacy `launch` branch (`key_holder.py:644-655`) also goes through `bind`.
  - The legacy `resume_launches` path is blocked by the `policy_digest` check.
  - `HOLDER_ENABLED` cannot skip the pin.
- **Creation paths.** `reserve` is the only place a new operation is created, and `schedule_waits` and provider waits go through `_admit`. A `--resume-launch` never creates a worker (`launch.sh:648-651`). With `n=1`, the guard loop makes at most one `guard_new` per operation. So "6 operations, at most 6 creations" holds.
- **Ready binding.** The PID, policy digest, operation and `launch_id` binding works. `launch_id` exists before dispatch. The second `armed` call is right before `dispatch_started` (`:820-823`).
- **Pin propagation.** Adding the pin to `ENVIRONMENT` carries it through `launch.json` to resumed launches and to the `batch_holder.py source|restore-check|collect` subprocesses.
- **Cleanup never expires by clock.** Collection and ACK do not check the deadline.
- **No new counter, operation field or ledger schema.**
- **Boundary with B is clean.**
  - B edits `step` and adds `bound_spend`/`settle`. This design edits `location`/`armed`/`main` and adds the batch loop, so the text does not overlap.
  - B's `settle` uses `location(home, op)`, which gives the same path for practice and the right path for the pilot (`authority.batch` is validated by `money.channel`).
  - `UNBUG_LAUNCH_STATE` is set by `control_resume`, so B's state binding works.
  - The startup repair (`bef877d`) touches `run.py`, `bench.py` and `factory_pool`, which this design does not edit.

## Dependencies and residuals (not required code here)

- B's settlement merge.
- All prior home ledger rows settled.
- The final manifest and pin bundle, plus the holder's pin delivery.
- Live provider startup and usage qualification.
- Diagnosis scheduling.
- Boat TTL as the last-resort deletion.

**Needed to pass round 2:** fix B1 (pilot gate in `armed` plus its test), and fold the M1–M5 wording and ordering into the design.

## Implementer disposition

Accepted B1 and M1–M5; revised design before round 2. N1 remains explicit
approval data. N2–N6 clarified, including window_closed reporting. No production
edits or additional settlement mechanism.
