# Goldfish review 2: extension rule (docs/ENGINEERING.md section 3)

Reviewer: fresh Claude subagent, personas zoom_out + design_critic, Mode: REVIEW, read-only. Verbatim.

**FAIL.** One problem is still blocking. Your other fixes hold up.

**Resolved:**
- **B1 (budget):** fixed. An extension is now one writer round plus its stress round, with $10 drawn from the batch money cap, so it no longer depends on a case's own spent budget.
- **B2 (contradiction and double counting):** fixed. Line 5 of `docs/ENGINEERING.md` confirms this file wins over older docs, and keeping both sealed cases removes the double counting. The single-path doc's lines 36 and 65 are still stale. That is follow-up work for the other agent, not a blocker here.
- **N4 (who decides, resume cap):** fixed. The agent proposes, code enforces, and factory-bug resumes are capped at 3.

**BLOCKING: the progress test and the entry test don't match how gates actually run.**
Where: `docs/ENGINEERING.md:111-112` (entry test) and `:120-122` (progress test).

- **Gates stop at the first failure.** `factory/gate_pipeline.py:170-173` sets `failed_gate` and breaks. Gates after it never run. So "fewer failing gates" can only mean going from one failing gate to zero, which is a full pass.
- **A real step forward doesn't count.** Say an extension makes G5 pass, and the pipeline then reaches G11 and fails there. That is progress, but the count stays at one and the case retires. In practice the cap of 5 acts like a cap of 1, which undoes what the founder chose.
- **The record doesn't keep the history the test needs.** Every repair wipes the gate results (`factory/run.py:2324-2327` clears `gates`, `gate_results` and `failed_gate`). "Before the last extension" and "no gate went from pass to fail in the last round" need past results that are not kept. Gates also run only after the attack rounds finish, not every round, so "the last round" has no gate results to compare.
- **Some cases can never qualify.** A case that runs out of rounds during writing and attack never reaches the gates. It has no failing gate, so it can't meet the entry test even if it was nearly done. Register row 9 records cases reaching 9–10 rounds, which is this pattern.
- **Fix:**
  - Define progress in terms of the pipeline as it works: the first failing gate is later in gate order than before the last extension, and every gate that passed before still passes.
  - Require the case record to keep a snapshot of gate results for each extension instead of wiping them.
  - Either drop "in the last round" from the entry test, or say what happens to cases that never reached the gates.

**NIT: no evidence that $10 is enough.** An extension has to re-run the gates to measure progress, and some gates call models (G10, G16 and G17). Nothing shows that a writer round plus a stress round plus a full gate run fits in $10. Row 9 already lists an $8 minimum reservation for a writer round alone. If it doesn't fit, every extension runs out of money and the case retires regardless of progress.

**FAIL**
