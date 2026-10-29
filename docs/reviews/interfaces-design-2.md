# Goldfish review 2: docs/designs/interfaces.md

Reviewer: fresh Claude subagent, personas design_critic + implementation_readiness, Mode: REVIEW, read-only. Verbatim.

**Re-review verdict: FAIL.** The rewrite closes my earlier findings 1, 2, 7 and 8. It partly fixes 3, 4, 5 and 6, but six BLOCKING findings remain, and they concentrate on the new router lease, the resume rule and B's admittability check. I stayed read-only.

**Answers to your questions now**
- **Can each stream build to it without guessing?** No. The join between A's router and D's reservations is still not specified (findings 2 and 3), and B has no defined way to ask the router whether a route is ready (finding 5).
- **Are ownership boundaries clear and non-overlapping?** No (finding 6).
- **Is the record safe for relaunch, without double-counting?** The relaunch side is safe now: the journal is keyed on (case, collected generation) and the stale record is moved aside on resume. Usage counting is still not proven safe (finding 4).
- **Is the merge order sound?** Yes. The writer ships off behind a flag and no batch runs between steps 4 and 6.
- **Is any Murphy row left without an owner?** No. All 52 rows carry a stream, and rows 7, 20, 28 and 35 now say B in both documents. Several owners need changes in files they don't own (finding 6).

**BLOCKING findings**

1. **Lines 34–41 and 119–121. Router leases never expire.**
   - When a call is interrupted, or the worker exits on a provider wait, nothing calls `model_router.finish(lease_id, usage)`.
   - So that lease keeps holding account capacity indefinitely.
   - B relaunches only when the router says the route is admittable. Leaked leases can therefore stop every relaunch on that account until `batch_deadline`.
   - **Fix:** give leases a time-to-live and a way to reclaim them. Also state who calls `finish` on the wait path, and the shape of `usage`.

2. **Lines 34–39. Nothing says who calls `admit()`.**
   - If A's model-call wrapper calls it (`opencode()` at `run.py:199`), D's code never sees the Lease before the call starts. D then can't write `repair_pending` or the stress re-review reservation (`run.py:1093` and `:1119`) with its `lease_id`.
   - **Fix:** say that D's code calls `admit()` itself, writes the reservation, then passes the Lease into the wrapper. Or name a hook in the wrapper. `opencode` already has a `before_attempt` parameter that could serve.

3. **Lines 59–71 and 92–95. The resume rule can't be implemented as written.**
   - The rule compares the `lease_id` in `repair_pending` with the record's, but the record has no `lease_id` field.
   - It also says "a record whose `parent_generation` matches" without saying what it matches. The resumed worker only knows the generation it was restored from, which is the output generation, not the parent.
   - **Fix:** add `lease_id` to the record. Then either delete `parent_generation` (nothing else reads it) or name exactly what it is compared with.

4. **Lines 84–91. Usage could still be booked twice.**
   - `settle()` marks `settled: true` in a file that is then moved aside. If the worker dies after settling but before its next checkpoint, the restored checkpoint still says `settled: false`, and `settle()` runs again.
   - That is safe only if the booking itself lives in the same checkpoint. The contract doesn't say where usage is booked: the case budget in the work directory, the batch money cap on the control VM, or the router's `finish`.
   - **Fix:** name the ledger, and make each booking idempotent by keying it on `wait_id` or `call_id`.

5. **Lines 119–121 and 132. B's admittability check has no API, and many cases could relaunch at once.**
   - Section 2 defines only `admit()`. If B calls it from the control VM, it gets a Lease that it can't hand to the worker, which leaks a lease as in finding 1.
   - Even with a check that doesn't hold capacity, every case waiting on the same account passes it at reset and relaunches together. Most hit a new Wait 60 seconds later, and each of those costs a VM boot, a restore, 60 seconds and a checkpoint.
   - So the claim on line 132 that "waiting costs no VM time" is not backed up. With no count cap, the loop is bounded only by the deadline.
   - **Fix:** add a check call that returns free capacity per route, and have B relaunch at most that many cases per route. Or put back a count cap.

6. **Line 9 and the table on lines 12–28. Not every file has one owner, and the "changes it makes for other streams" column misses needs that the register shows.**
   - **No owner at all:**
     - `budget.py` outside A's classifier, which covers rows D8, D21 and D39 and is the likely home of `settle()`;
     - `admission.py` (rows C24, C36, D12, E50);
     - `gate_pipeline.py` (B35, C41);
     - whatever writes the `provider_wait` object into the public card (lines 104–108).
   - **Owner has needs from other streams that the table doesn't list:**
     - `launch.sh` (E) needs B20, B33, B5 and B6, including Codex delivery at `:120` and `:410`;
     - `bin/boat-launch-guards.sh` (E) needs B16 and B33;
     - `key_holder.py` (B) needs E17 and E31;
     - `model_runtime.py` (A) needs D13 and E43;
     - `coordinator.py` (B) needs E29 and E50;
     - `restart.py` (A) needs E50;
     - `account_handoff.py` (A) needs E29;
     - `run_artifacts.py` (B) needs E43 and E45.

   Under the rule on lines 9–10, every one of these either stalls or breaks the rule.

**NITs**
- **Line 133:** listing `credential_expiring` with `credit` as "never clears on its own" contradicts line 24, where B owns automatic Codex renewal. It belongs with the waits that have no count cap.
- **Line 136:** "can be resumed in the next batch" can't work today. `bind()` rejects any card whose `batch_release_sha256` differs from the current batch (`factory/batch.py:141`). Delete the claim or give it an owner.

**FAIL**
