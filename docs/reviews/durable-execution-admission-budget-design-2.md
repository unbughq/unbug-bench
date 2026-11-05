# Admission budget design review 2: deadline interpretation

Fresh read-only goldfish, different model family; Mode: REVIEW. Verbatim response:

---

**Review verdict: finding 1 can be resolved, with no redesign.** A case reserved before the deadline may have its workflow created after it. That is consistent with the approved design and contract, but not for the reason revision 2 gives. One related blocker remains at line 48, and it is a one-sentence fix.

**Scope:** I reviewed finding 1 and the boundary it depends on. I did not re-review findings 2–7. I read the clone's working tree, including its uncommitted `engine.py`, and the DBOS 3.4.0 source. No tests were run and no files were changed.

## Finding 1

**Verdict: resolved in substance, no longer blocking.** The behaviour finding 1 described still exists: a recovered batch can create the case after the deadline. Rejecting that behaviour is not justified, for three reasons.

**1. "Starts" cannot mean physical work in the approved design.**
- `contract.py:346` says "no new case or extension starts after this".
- ADMIT runs on a concurrency-1 queue (`durable-execution.md:109`), and each attempt also needs a slot (`:183`).
- `attempt_workflow` has no deadline check (`engine.py:190–229`). A case created before the deadline can therefore make its first paid call long after it, with no crash at all.
- `policy.py:114–115` says the deadline stops new cases and extensions, not a running step.
- WP5a says the same (`de/wp5a:factory/run.py`, above `ENGINE_PLUMBING_STOPS`). It also replaces the batch deadline with the attempt deadline, so a late case is not refused by the runner.

**2. The same contract sentence already uses a recorded decision for extensions.**
- `engine.py:522–523` checks the deadline through a recorded `now_step()`, then starts the extension later.
- That code is draft WP1, so it is precedent rather than approval.
- Today's `admission_open()` then `start_case()` (`engine.py:582–593`) has the same gap. Revision 2 does not widen it.

**3. Finding 1's remedy cannot be built in the batch workflow, and would gain little.**
- The clock may only be read through a step (`durable-execution.md:334`), and replay returns the old value.
- DBOS forbids a child start inside a step (`dbos/_context.py:279–280`: `assert cur_ctx.is_workflow()  # Not in a step`).
- Any check in the batch is therefore a recorded read followed by a separate start, which is the same gap.
- The only single-step option I can see is a root start through `DBOSClient` (`_client.py:144`). I did not test it, and it gives up the atomic parent/child record.
- That option would close a window of milliseconds, while the ADMIT queue window of hours stays open.

**Exposure:** at most one case per crash, because admissions are decided one at a time.
- It costs at most `case_money_usd_micros` (default $50), inside a hold already counted against the bound.
- A case admitted this way cannot extend (`engine.py:522`) and gets no replacement while the deadline blocks admission (`:582–584`).

### Replay cases

| # | Scenario | Result | Verdict |
|---|---|---|---|
| 1 | Kill before the reserve commits, recovery after the deadline | Retry creates the row, zero-settles it, returns EXPIRED, no case | Sound |
| 2 | Kill after the reserve commits, before the step is recorded, recovery after the deadline | Same key finds the hold, releases it, returns EXPIRED. No child can exist because the start follows the record | Sound; meets "release only when no case can still use it" |
| 3 | Kill after the zero-settle, before the record | `reserve` returns the old grant and `settle` repeats idempotently (`ledger.py`, `_finish`), returns EXPIRED | Sound while the clock stays past the deadline (see the clock nit) |
| 4 | Kill after ADMITTED is recorded, before the child, recovery after the deadline | No clock re-read; child created late; ADMIT re-reserves the same key and gets the same grant | Acceptable, for the reasons above |
| 5 | Kill after the child commits | Child row and parent operation commit in one transaction (`_sys_db.py:5580`), so the proposal's atomicity claim holds. Replay attaches | Sound |

### Delayed-reservation cases

| # | Scenario | Result | Verdict |
|---|---|---|---|
| 6 | Reserve blocks on the batch lock across the deadline | Post-reserve clock read catches it; zero-settled | Sound; closes finding 1's slow-reservation window |
| 7 | Last clock read is before the deadline, but the step record lands after it | ADMITTED is recorded after the deadline. A crash before the record gives EXPIRED instead | Both outcomes are safe, but line 14's "committed before the deadline" is false here (Major A) |
| 8 | Barrier delays the batch before it probes | The probe reads the clock itself and returns EXPIRED | Sound |
| 9 | Child created in time, ADMIT queued past the deadline | Runs late | Approved behaviour, unchanged |

## New findings

### Blocker B1: the start retry at line 48 can break replay
- **Scope:** `durable-execution-admission-budget.md:48–49`, "the batch retries the same DBOS operation and ID".
- **Problem:** a workflow-level retry is unnecessary, and a literal `try/except` loop can make recovery fail.
  - `init_child_workflow` already retries connection failures indefinitely and commits both records together (`_sys_db.py:557–570`, `:5567`).
  - The engine config does not set the opt-out (`engine.py:683–686`).
  - Each call advances the function ID (`_context.py:281`).
  - If a caught failure were followed by a second call, the child would be recorded at the later ID. Replay's first call would then succeed at the earlier ID, and the next operation would hit the recorded child. I expect `DBOSUnexpectedStepError`. This comes from reading the code, not from running it, and I did not read all of `init_child_workflow`.
- **Fix:** replace the sentence with: "The batch does not wrap or retry `start_workflow`. DBOS retries connection failures and replay handles crashes. Any other exception fails the batch with the hold intact; the hold is never settled on a guess." Add a test that the workflow has one start operation per admission.

### Major A: correct the boundary wording before implementation
- **Scope:** lines 11–18, 40–42, 61, 105 and 114–115.
- **Problem 1:** "essential to allow already-admitted cases to continue across outages" is false. A case with no workflow has no state to continue, and a first step inside the case could expire it. The boundary is a cost choice.
- **Problem 2:** "already-started" misdescribes a case with no workflow, worker or model call.
- **Problem 3:** "committed before the deadline" contradicts case 7.
- **Fix:**
  - Use "admitted" and drop "already-started".
  - State the cutoff as the last clock read of the probe execution whose ADMITTED result is recorded.
  - State that a crash before that record re-reads the clock.
  - State that a crash after it may create the case late, and that at most one case is exposed per crash.
  - Give the honest reason: a recorded decision is unavoidable, and physical start is already allowed to lag it.

### Major B: record the definition where the rule lives
- **Scope:** `durable-execution.md:178–187`, with `contract.py:346` left unedited.
- **Problem:** the definition exists only in a WP1 proposal. Line 186 distinguishes "no new case starts" from cases "already running", and an admitted case with no workflow is neither.
- **Fix:** add one sentence to the parent design saying that for case limits, "starts" means admitted under this cutoff. No `contract.py` edit is needed, since the sentence interprets the rule rather than changing it. This still needs the design review that this document is already getting.

### Major C: pin the accepted late-creation behaviour in tests
- **Scope:** lines 101–106.
- **Fix:** the kill-after-record test, with recovery past the deadline, must assert:
  - no second probe;
  - no second reserve row for the case;
  - exactly one `case_workflow`, created after the deadline;
  - the same key stays held until ADMIT settles it;
  - no replacement and no extension.

  Add case 7 with an injected stall, and name the fault-injection test file, because line 101 doesn't.

### Nit: the pre-reserve clock read is redundant
- **Scope:** lines 31–33.
- **Fix:** the recovery path must reserve anyway, so "reserve, then read the clock once" covers every case with fewer branches.

### Nit: a clock stepped backwards is a residual risk
- **Scope:** lines 32–35.
- **Problem:** if the clock steps back across the deadline between a zero-settle and the retry, `reserve` returns the settled grant and the probe reports ADMITTED with no hold. The frozen ledger protocol cannot reveal the row's state.
- **Disposition:** this needs a backward clock step across the deadline plus a crash in a tiny window, and the later settle fails loudly. Note it and add no code.

### Nit: the probe should be the only deadline authority
- **Scope:** `engine.py:582–584`, `:612–613`.
- **Fix:** say so explicitly. `admission_open()`'s clock read may remain only as a fast path.

## If the founder wants a stricter rule

If the deadline should mean "no new case does paid work after this", that is a parent design change, not a fix to finding 1.

A feasible version adds a recorded deadline gate to a case's first ADMIT before `lease_step`. Past the deadline it releases the grant, ends the case with a new unstarted status, and sends the batch any pending acknowledgement. This also covers queued ADMITs, which matter far more than the crash window, and it leaves a small gap between the gate and dispatch. I don't recommend it for this change.

## Recommended disposition

| Item | Disposition |
|---|---|
| Finding 1 | Resolved; keep the admission boundary |
| B1 | Open and blocking; fix in revision 3 |
| Majors A–C | Fix in the same revision |
| Findings 2–7 | Not assessed here |

---

## Resolution

| Finding | Disposition |
|---|---|
| Prior review finding 1 | Resolved in substance; revision 3 clarifies the cutoff and planned replay tests. |
| B1 | Revision 3 removes workflow-level start retries; fresh review and implementation test pending. |
| Majors A–C | Revision 3 corrects the boundary wording, updates the parent design, and specifies the requested tests; fresh review pending. |
| Nits | Revision 3 uses separate recorded reservation and clock steps, avoiding re-evaluation after a recorded clock decision; fresh review pending. |
| Prior findings 2–7 | Still require independent review. |

