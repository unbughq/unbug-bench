# Goldfish review 2: docs/ENGINEERING.md

Reviewer: fresh Claude subagent (general-purpose), personas zoom_out + implementation_readiness, read-only. Verbatim.

**FAIL.** The rewrite fixes all 8 original findings, but it adds 2 small blockers, both one-line fixes: the disagreement rule contradicts itself, and the row-closing rule can't be done as written. I didn't run the test suite.

### The 8 original findings

1. **Who runs the goldfish, what pass means, where results go:** resolved. Line 10 says the elephant starts the reviews, line 44 defines pass, and lines 55–57 say where reviews are saved.
2. **Who may reject a blocking finding:** resolved. Lines 45–48 bar the elephant from rejecting findings on its own work. The new wording causes new blocker B1 below.
3. **Founder approval missing from the flow:** resolved. Lines 14–16 now say the founder approves only designs that change a §4 rule or a security property.
4. **Uncommitted edits against "commit every change", and the merge target:** resolved. Step 1 (lines 20–22) gives one branch or worktree per change, step 4 commits on that branch, and step 6 merges into `factory-simplify`.
5. **No way to record a closed row, and colliding row numbers:** resolved. Lines 73–81 cover closing and numbering. The register gained a `Closed by (test, commit)` column, and all 53 table lines have the same column count. The commit part causes new blocker B2 below.
6. **One-line exemption, persona use per step, test command:** resolved. Lines 30–31, 32–33, 37–38 and 36 cover each.
7. **Goals written as if they were true today:** resolved. §3 is now "Target properties" and says they are "not true yet" (line 85).
8. **`CLAUDE.md` copy and Mac-only persona path:** resolved. `CLAUDE.md` is now a symlink to `AGENTS.md`. The personas are copied into `tools/egm/agents/`, and the 5 copied files match the f0ba151 checkout exactly.

### New BLOCKING

- **B1, lines 46–50: the disagreement rule contradicts itself.** "That goldfish's verdict stands" means the second goldfish has the final word. The next bullet then escalates to the founder "when the two reviewers still disagree", which is exactly what happens when the second goldfish overturns the first. Pick one. Either the second goldfish's verdict is final and the founder bullet goes, or a split between the two goldfish goes to the founder and "verdict stands" goes.
- **B2, lines 75–76: the row-closing rule can't be done literally.** A commit can't contain its own hash, so `Closed by` can't name "the commit" "in the same commit as the fix". On top of that, a squash or rebase at merge changes the branch hash. Say `Closed by` holds the test path plus the merge commit, filled in at step 6, or the test path alone.

### New NITs

- **Line 36:** zoom_out step 1 checks against `resources/document_standards/zoom-out-standard.md`, which wasn't copied over. Copy `resources/document_standards/` too, or tell the goldfish to skip that step.
- **Lines 32 and 37:** the personas branch on a `Mode` setting, so the flow should say to pass `Mode: REVIEW`.
- **Lines 30–31 and 37:** for a fix that skips the design, the diff review has no design to review "against". Say it reviews against the commit message.
- **Line 57:** a change usually has at least two review files (design and diff), so the `Reviewed-by:` trailer should list all of them.

`docs/designs/` and `docs/reviews/` exist and are empty, which is fine.
