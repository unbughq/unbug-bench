# Goldfish review 3: docs/ENGINEERING.md

Reviewer: fresh Claude subagent (general-purpose), personas zoom_out + implementation_readiness, read-only. Verbatim.

**PASS.** Both blockers and all four nits from the last round are fixed, and I found no new blockers.

**Blockers from the second pass**
- **B1, disagreement rule (lines 45–50): resolved.** There is now one outcome: the second goldfish decides. The founder is involved only when a fix would break a section 4 rule, so the rule no longer contradicts itself.
- **B2, closing a row (lines 80–84): resolved.** `Closed by` holds the test path, written in the fix commit, and the merge commit records when the row closed. That can actually be done.

**Nits from the second pass: all resolved**
- **Standards copied:** the 5 standards are in `tools/egm/document_standards/`. The only change in the copied files is the standard path in `tools/egm/agents/zoom_out.md:44`, and `tools/egm/README.md` declares it.
- **`Mode: REVIEW`:** line 68 tells the goldfish to use it.
- **No-design reviews:** lines 69–70 say a change with no design is reviewed against its commit message.
- **Trailers:** lines 57–58 list every review file in the merge commit's `Reviewed-by:` trailers.

**New NITs (optional)**
- **Register header (`docs/murphy-register.md:9`):** it still says `Closed by (test, commit)`, but the rule now puts only the test path there. Rename the column to `Closed by (test)`.
- **Which standard to use (lines 32–33):** `design_critic` and `implementation_readiness` say to check against a "Target Standard" but give no path, and the flow doesn't name one. Add one line, such as "design review uses `heilmeier-standard.md`; readiness uses `implementation-readiness-standard.md`", so a goldfish doesn't have to guess.
- **Line 69 wording:** it reads like an instruction given every time. Rewording it to "if the change skipped step 2, say so and review against the commit message" would be clearer.

## Elephant resolution

- Nit 1: renamed the register column to `Closed by (test)`. Fixed.
- Nit 2: named the standards for design and readiness reviews. Fixed.
- Nit 3: reworded the no-design instruction. Fixed.
