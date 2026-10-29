# Goldfish review 3: extension rule (docs/ENGINEERING.md section 3)

Reviewer: fresh Claude subagent, personas zoom_out + design_critic, Mode: REVIEW, read-only. Verbatim.

**PASS.** The third revision has no blocking problems. The new progress rule fits how the gate pipeline actually runs: it stops at the first failure (`factory/gate_pipeline.py:170-173`), so how far a case gets is the honest thing to measure. The earlier blocker is fixed:
- **Real progress now counts.** A case whose first failure moves from G5 to G11 is progressing.
- **Stage 0 covers the gap.** Cases that never reached the gates now have a way to qualify.
- **Snapshots are required.** The record must keep them, and repairs may no longer wipe them, so progress can be checked from case records.

Worst-case spend is now capped: 5 extensions × $15 = $75 per case from the batch money cap, plus at most 3 factory-bug resumes. No path loops without limit.

**NITs (none blocking):**

1. **The "close to passing" entry test is gone.**
   - Where: `docs/ENGINEERING.md:111`.
   - The second revision had one. This one only says "an extension", so whether to grant the first extension is purely the agent's call.
   - The spend is capped at $15, so this isn't blocking. A simple test computed by code would restore the earlier fix: for example, the case reached the gates, or its stress review shows no open blocking finding.

2. **A gate change can retire a good case.**
   - Where: the progress rule at `:128-130`, read together with the gate-change property at `:139`.
   - Gates are versioned per gate. If a gate changes between two snapshots and a previously passing gate now fails, the case counts as no progress and retires, though the case itself didn't get worse.
   - The rule should compare against the same gate version, or skip a snapshot that a gate change invalidated.

3. **The $15 figure rests on an assumption with no source.**
   - Where: `:117-119`.
   - "About $5 per round" doesn't say whether it includes the gate re-run. The gate run includes model gates (G10, G16 and G17), and register row 9 lists an $8 minimum reservation for a writer round alone.
   - If $15 is too little, extensions run out before reaching the gates, and the case retires early. That is the outcome the change is meant to avoid. The doc should point to a real cost receipt.

4. **One extension could quietly use several writer rounds.**
   - Where: `:115-116`.
   - The current gate loop runs up to 2 repairs (`factory/run.py:2297`), and each repair calls the writer again.
   - The rule should say whether those repairs are disabled inside an extension, or count against its one writer round.

5. **The bullet is now a design, not a target property** (the zoom-out reviewer's concern).
   - Where: `:104-133`.
   - Section 3 says a change working towards a target property needs a design. This bullet now carries a 30-line mechanism and a cost justification that belong in the stream D design.
   - It could shrink to the property and its limits (at most 5 extensions, required progress, allowance drawn from the batch money cap), with the details moved to stream D.

**PASS**

## Elephant resolution

- Nit 5: the rule is shortened to its limits, and the mechanism moved to `docs/designs/extensions.md`. Fixed.
- Nits 1–4: recorded as open items for stream D in `docs/designs/extensions.md`. They will be closed by that design's review.
