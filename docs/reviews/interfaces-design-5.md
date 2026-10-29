# Goldfish review 5: docs/designs/interfaces.md

Reviewer: fresh Claude subagent, personas design_critic + implementation_readiness, Mode: REVIEW, read-only. Verbatim.

**Verdict: PASS.** No BLOCKING findings remain. I re-read the whole revised `docs/designs/interfaces.md` and the register, and stayed read-only.

**What closed this pass**
- **The one seam:** every caller goes through `await_lease()` (lines 35–46), and it only ever returns a Lease.
  - A Wait before admission therefore can never leave a reservation behind.
  - A provider condition during a call is still handled by the wrapper, which records the `lease_id`. So both paths produce a record the resume rule can match.
- **The stale `finish` line** is gone.
- **Stress-review resume:** the rule now covers `review_pending` as well as `repair_pending` (lines 128–134), so section 5's promise that waits never use up a stress re-review now has a rule behind it.
- **Failed launches** now have a state and a retry (lines 154–159), and the cap is labelled a broken-router backstop (line 174).
- **Murphy rows:** rows 7, 20, 28 and 35 say B in the register, and every row still has an owner.

**My five questions**
- **Can each stream build to it without guessing?** Yes.
- **Are ownership boundaries clear?** Yes. Ownership runs by Murphy rows and contracts, and the merge order settles overlaps.
- **Is the record enough for a safe relaunch without double-counting?** Yes.
- **Is the merge order sound?** Yes.
- **Is any Murphy row left without an owner?** No.

**NITs (optional)**
1. **Line 60:** it still says "after `admit` returns a Lease". It should say `await_lease`, to match line 35.
2. **Line 157:** "E's infrastructure-retry rule" should point to row 29 by number. Also say that `failed` means the launch verifiably did not start a worker. If the holder times out with the outcome unknown, the key should stay `pending` until that launch is reconciled. Otherwise one generation could get two workers, and both would spend.
3. **Lines 133–134:** only "a `repair_pending` with no matching record" is defined as a crash. Add the same sentence for `review_pending`.
4. **Lines 199–200:** while the flag is off, `await_lease()` has to keep using the old in-worker wait rather than exit. Saying so lets D code against the step-4 build without guessing.

**PASS**

## Elephant resolution

All four nits fixed in the committed version.
