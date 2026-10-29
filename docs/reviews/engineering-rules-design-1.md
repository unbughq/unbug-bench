# Goldfish review 1: docs/ENGINEERING.md

Reviewer: fresh Claude subagent (general-purpose), personas zoom_out + implementation_readiness, read-only. Verbatim.

**FAIL.** I found 4 blocking and 4 nit findings. The rules state what should happen but not how: who runs the review, what counts as a pass, where the result is kept, and how a row is closed.

1. **BLOCKING: §1 flow, steps 2, 4 and 5 (lines 21–26).** Nothing says who runs the goldfish, what output counts as a "pass", or where the review is saved. Without that, step 5's "commit only after the goldfish passes" can't be checked. Name the runner (the elephant starts it), define pass as "zero BLOCKING findings left open", and require the review to be saved somewhere that can be checked, such as `docs/designs/<topic>.review.md` or a commit trailer.

2. **BLOCKING: §1 line 25, "explicitly rejected with a reason".** It doesn't say who may reject a blocking finding. If the elephant can overrule its own reviewer, the review means nothing. It also doesn't say what happens when the elephant and goldfish disagree, or when two goldfish disagree. State that a rejected blocker goes to the founder, or to a second goldfish from another model family, and that the reason is recorded next to the review.

3. **BLOCKING: line 14 against lines 18–26 and §3 line 48.** Line 14 says the founder "approves designs", but the five-step flow has no founder approval step. §3 also says only reviewer disagreements about a case reach the founder. A new agent can't tell whether to wait for the founder between steps 2 and 3. Either add the step or change line 14 to "approves trade-offs when asked".

4. **BLOCKING: line 22 against line 86.** Step 3 says "Leave the change uncommitted" and step 5 says "commit and merge", but §4 says "Commit every change on `factory-simplify`" and never touch `main`. That leaves "merge" with no target. There is also no rule for parallel agents, such as one branch or worktree per change, so several agents leave uncommitted edits in one checkout. The current git status shows exactly that: 11 modified and 6 untracked files. Fix it with: branch or worktree per change, then merge into `factory-simplify` after the goldfish passes.

5. **BLOCKING: §2 line 42 and the register structure.** "A row is closed only when a test proves it" has nowhere to go in the register. The table has only a `Status` column, all 52 rows say `open`, and there is no field for the test path or commit that closed a row. It also doesn't say who changes the status, or how parallel agents avoid giving two new rows the same `#`. Add a `Closed by (test, commit)` column and a rule like "the elephant closes the row in the same commit, and the goldfish checks it".

6. **NIT: §1 lines 19 and 28–31.** It's unclear whether a "one-line fix" skips only the design or the goldfish review too. It's also unclear which personas run at which step: is it zoom_out plus implementation_readiness at both steps, with design_critic added only for the design? Line 33 says "the full suite must be green" but doesn't name the command; it's `tests/run.py`.

7. **NIT: §3 and §4 lines 47–80, mixing goals with rules.** "Broken runs are never scored", "no human pit stop", the automatic diagnosis agent and plumbing roll-forward are things the factory should do, not instructions for an agent editing code. The register shows they aren't true today (rows 9, 38–41). Label them "target properties; see register rows", or agents will think they already hold, or will build them without a design.

8. **NIT (could be cut): `CLAUDE.md` and line 28.** `CLAUDE.md` is a copy of `AGENTS.md`. Make it a symlink or a single `@AGENTS.md` line so the two can't drift apart. The persona path is hard-coded to `/Users/bugsincode/...`, which only works on the founder's Mac, against the "No Mac dependency" rule. Use a path inside the repo or the upstream repo at commit f0ba151. I checked: that checkout is at f0ba151 and includes `design_critic.md`.

On the register's structure: the columns are consistent and the A–F workstreams are defined. The only structural gap is the missing closure column in finding 5.
