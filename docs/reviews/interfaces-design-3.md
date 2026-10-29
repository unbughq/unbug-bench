# Goldfish review 3: docs/designs/interfaces.md

Reviewer: fresh Claude subagent, personas design_critic + implementation_readiness, Mode: REVIEW, read-only. Verbatim.

**Verdict: FAIL.** I re-read §3 and checked it against `factory/budget.py`. The new settlement rule closes my double-counting finding, but five BLOCKING findings remain, because §1, §2 and §4 have not changed since my last review. Still read-only.

**Closed by this change**
- **Double-counting (was finding 4).** Usage is booked into the case's own budget file in the work directory. That file goes into the same checkpoint as the wait record, and `budget.py:277` already skips events it has seen. If the worker dies after settling but before checkpointing, the record and the bookings roll back together. Because `settle()` is keyed on event IDs and `wait_id`, running it twice books nothing new.
- **The record lacking `lease_id`** (part of finding 3). Line 68 adds it.

**Still BLOCKING**

1. **§2, lines 34–41: leases never expire.**
   - Nothing says whether the worker calls `finish(lease_id, usage)` on the wait path.
   - Leases have no time-to-live and no way to be reclaimed when a worker dies.
   - A leaked lease keeps holding account capacity, so the router never reports the route as admittable. B's step 2 on line 127 then holds every relaunch on that account until `batch_deadline`.

2. **§2, lines 37–39: nothing says who calls `admit()`.**
   - If A's wrapper `opencode()` (`run.py:199`) calls it internally, D's code never sees the Lease before the call runs.
   - D then can't write `repair_pending` (`run.py:1093`) or the stress re-review reservation (`run.py:1119`) with the `lease_id`.
   - **Fix:** name the seam: either D's code calls `admit()` and passes the Lease into the wrapper, or the wrapper uses its existing `before_attempt` hook.

3. **Lines 100–101: "a record whose `parent_generation` matches" still doesn't say what it matches.**
   - The resumed worker knows only the generation it was restored from, which is the output generation, not the parent.
   - Now that `lease_id` is in the record, `parent_generation` adds nothing to the check.
   - **Fix:** delete it from the rule, or name what it is compared with.

4. **Lines 127–129 and 140: B's readiness check has no API, and many waiting cases can relaunch at once.**
   - §2 offers only `admit()`. If B calls it from the control VM, it gets a Lease it can't hand to the worker, which leaks a lease as in finding 1.
   - A check that doesn't hold capacity lets every case waiting on one account relaunch together at reset. Most hit a new Wait about 60 seconds later, each costing a VM boot, a restore and a checkpoint.
   - So "waiting costs no VM time" (line 140) is not backed up, and there is no count cap.
   - **Fix:** a check that returns free capacity per route, with relaunches limited to that number.

5. **§1, lines 12–28: files still lack owners, or need changes the table doesn't list.**
   - **No owner:** the rest of `budget.py`, which now holds the per-call usage booking that §3 depends on and is the likely home of D's `settle()`; `admission.py`; `gate_pipeline.py`; and whatever writes the `provider_wait` object into the public card (lines 112–116).
   - **Changes owners must make for other streams but aren't listed:**
     - `launch.sh` (E) for rows B20 and B33;
     - `bin/boat-launch-guards.sh` (E) for rows B16 and B33;
     - `coordinator.py` (B) for rows E29 and E50;
     - `model_runtime.py` (A) for rows D13 and E43.

**NITs (unchanged)**
- **Caps table:** `credential_expiring` is listed as never clearing on its own, but B now owns automatic Codex renewal, so it should be in the uncapped group.
- **"Can be resumed in the next batch":** `bind()` rejects any card from a different batch release (`factory/batch.py:141`), so this can't work today.

**FAIL**
