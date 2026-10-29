# Goldfish review 4: docs/designs/interfaces.md

Reviewer: fresh Claude subagent, personas design_critic + implementation_readiness, Mode: REVIEW, read-only. Verbatim.

**Verdict: FAIL, on one BLOCKING finding.** It is a one-line fix. Everything else from my earlier rounds is closed except a few NITs. Still read-only.

**Closed in this pass**
- **Leases:** they now expire, and `finish` books nothing, so a dead worker frees its capacity within 3 minutes and the account can't be held indefinitely.
- **Who calls `admit()`:** D's code calls it when it holds a reservation; otherwise A's wrapper does.
- **Resume rule:** it now matches the record's `lease_id` against `repair_pending`, and `parent_generation` is gone.
- **Double-counting:** `settle()` books into the case's own budget file inside the same checkpoint as the record, and is keyed on event IDs and `wait_id`. The batch money cap is computed from collected cards, so nothing is booked twice.
- **Mass relaunch:** `capacity(route)` plus jitter keeps relaunches within free slots, and there are now 10 relaunches per reason, with `credential_expiring` treated as renewable.
- **Ownership:** it now runs by Murphy rows and contracts rather than whole files, the public-card write is assigned to A, and the next-batch claim is deferred with an honest note about `bind()`.
- **Murphy rows:** all 52 have a stream, and rows 7, 20, 28 and 35 say B in both documents.

**BLOCKING**

1. **Lines 35–41 and 63–75: nothing says what D does when its own `admit()` call returns a Wait.**
   - Section 3 says "the worker" waits until the condition has lasted 60 seconds, then writes the record, checkpoints and exits. Section 1 says A writes the record.
   - But in the path where D holds a reservation (writer rounds and stress re-reviews, which covers most paid calls), the Wait comes back to D's code, not A's wrapper.
   - The contract names no A function that D hands the Wait to. It also doesn't say who keeps re-checking for 60 seconds. Both A and D would have to guess, and either both implement it or neither does.
   - **Fix:** name one A function, for example `model_router.await_lease(role, case, deadline) -> Lease`. It re-checks for up to 60 seconds and, if the condition persists, writes the record, checkpoints and exits with `provider_wait`. D calls it instead of a bare `admit()`.

**NITs**
- **Line 59 vs lines 47–50:** line 59 still says `finish(lease_id, usage)`, which contradicts the new `finish(lease_id, outcome, receipt)`. Delete line 59.
- **Lines 124–128:** the resume rule covers only `repair_pending`. A wait during a stress review leaves `review_pending` set. Today's resume code (`run.py:984-1030`) treats that as `interrupted_review` and uses up a re-review attempt, which section 5 forbids. Extend the rule to stress-review receipts that carry a `lease_id`.
- **Line 149:** "relaunched at most once" doesn't say what happens when a launch fails outright, for example VM provisioning fails. The journal needs a launched/failed state so a failed launch is retried instead of stranding the case until the deadline. B's design can define this.
- **Line 166:** stopping after 10 relaunches for `rate` or `quota` is at odds with the "no capacity excuses" rule in section 4 of `docs/ENGINEERING.md`. It's acceptable as a backstop, but say so explicitly.

**FAIL**
