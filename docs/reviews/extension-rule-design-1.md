# Goldfish review 1: extension rule (docs/ENGINEERING.md section 3)

Reviewer: fresh Claude subagent, personas zoom_out + design_critic, Mode: REVIEW, read-only. Verbatim.

**FAIL.** Three blocking problems and two nits. All three of your example questions turn out to be blocking.

1. **BLOCKING: "Remaining budget" is undefined, and for money-exhausted cases it is zero.**
   - Where: `docs/ENGINEERING.md:109-110`.
   - The case budget is $50 at list price (`factory/budget.py:191`, `docs/factory-single-path.md:65`). `docs/murphy-register.md` row 9 records cases that stopped at $51–52.
   - So a case diagnosed for running out of budget has nothing left, and no extension can ever fit. The rule only works for cases that ran out of rounds, and it doesn't say so.
   - The rule also never says what an extension is: more rounds, more dollars, or both.
   - Fix: define an extension as N extra rounds inside the original $50 cap, or as a separate envelope with an explicit size and total.

2. **BLOCKING: It contradicts other rules.**
   - `docs/factory-single-path.md:36` says running out of rounds or budget retires the case. Line 65 says "No automatic limit increases."
   - In the same bullet, line 116 says "The replacement launches at once and never waits on the diagnosis." Read literally, every case diagnosed close to passing also gets a replacement. The batch then pays for up to 5 extensions plus a replacement for the same slot, and nothing says which result counts if both pass.
   - Fix: say the replacement launches only when the case retires, or define how the slot is accounted for while both run. Then amend the single-path doc to match.

3. **BLOCKING: "Measurable progress" can't be checked from case records.**
   - There is no "open findings" count in the case records. Findings are scattered across stress review, G8 fairness votes (`factory/run.py:1928`) and G11 flags (`factory/run.py:2195`). Some are deliberately sealed: `factory/fairness.py:1` says "Findings never leave the seal".
   - The count is noisy anyway. A fresh reviewer run can close two findings and raise three new ones.
   - "A gate moved from fail to pass" ignores another gate moving from pass to fail in the same extension, so a case can thrash between gates and still count as progressing.
   - Fix: base the test on gate results already in the case record, computed by code. For example: the number of failing gates went down and no gate went from pass to fail.

4. **NIT: The diagnosis agent grades its own extensions, and factory-bug resumes have no cap.**
   - The same agent grants an extension and then judges whether it made progress. The cap of 5 and the progress check should be enforced in code, with the agent only proposing.
   - A loop of extension, then a factory-bug diagnosis, then a resume never counts against the 5. The cost goes to the infra-waste line, but the loop itself is unbounded.

5. **NIT: The cap isn't justified, and "close to passing" has no entry test.**
   - The old rule allowed one extension. Five extensions of unknown size on top of the default 8 rounds could reach the 14-round sunk-cost case this change is meant to prevent.
   - The text gives no reason for 5 and no measurable condition for "close to passing".

Smaller fix overall: keep "one extension at most" and define it as a fixed number of rounds within the existing $50 cap. That covers the stated intent without new progress metrics.

**FAIL**
