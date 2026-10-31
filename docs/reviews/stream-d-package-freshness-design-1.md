# Goldfish design review: `docs/designs/stream-d-package-freshness.md`

**Mode:** REVIEW
**Personas:** `zoom_out`, `design_critic`, `implementation_readiness`
**Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md` (plus `zoom-out-standard.md`, as the persona requires)
**Worktree:** `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-4ac6b632` at `eebbbda`. The design file is untracked. `docs/designs/stream-d.md` has an uncommitted checklist edit.

## Verdict: PASS

There are no blocking findings. The problem the design describes is real and the code shows it. The fix is the smallest one available, and it follows a pattern the code already uses.

## Checking the premise against the code

- **The card starts empty on resume.** `factory/run.py:3254` builds a new `c.card` that does not include `loop_freshness`.
- **Only a fixed list of fields is carried over.** `carry_context` (`factory/diagnosis_dispatch.py:280-287`) copies only the keys listed in `CARRY` (`factory/diagnosis_dispatch.py:23-28`), and `loop_freshness` is not one of them.
- **The scorecard is overwritten before the writer runs.** On an admitted replay, `apply` writes `scorecard.json` from `c.card` and returns the extension id (`factory/diagnosis_dispatch.py:240-242`). This happens before `write_and_attack`.
- **`loop_freshness` then finds no pointer.** It reads `scorecard.json` back (`factory/run.py:1072-1073`) to get `verdict_path`. That value is the only way `confirm_hits` reaches the fallback that reuses a completed review (`factory/run.py:2211-2236`).
- **The receipt can be missing when the answer is complete.** `review-completed.json` is written at `factory/run.py:2334`. The binding receipt `freshness-verdict.json` comes later (`:2340`), and only when every row is resolved. A crash between these two writes, or a restore that lacks the receipt, leaves a completed answer that only the scorecard pointer can recover. Without the fix, that review is paid for again.
- **Adding the key can't create a pass.** The fallback still checks four things: the completion marker binding, the case hash, the search binding, and the retrieval digest. It also requires the verdict file to be less than 24 hours old, and it applies the same fail-closed `checked_freshness_verdict`. A carried path is only a hint, which is what the design claims (lines 17-18, 42).
- **A stale carried value can't change retry decisions.** The only code that reads `card['loop_freshness']` is `recovery.freshness_retry_stop` (`factory/recovery.py:88-91`). It acts only when `terminal_stop == 'freshness_unresolved'`. That stop is raised only by `loop_freshness`, which overwrites `c.card['loop_freshness']` first (`factory/run.py:1066-1078`).
- **Nothing to reuse instead.** The change uses the existing deep-copy path. It adds no new helper or mechanism, and there is nothing more lightweight to reuse.

## Blockers

None.

## Non-blocking findings

1. **Major (non-blocking), readiness: lines 27-29, "remove only binding receipt to model documented restore window."** "Documented restore window" doesn't refer to any doc. The implementer has to work out which failure to simulate. The real window is a kill between `factory/run.py:2334` and `:2340`, or a restore that is missing `freshness-verdict.json`. State that, and say to delete `freshness-verdict.json` while keeping `review-completed.json`, `verdict.json` (younger than 24 hours) and `retrieval/`.

2. **Major (non-blocking), readiness: lines 24-26, test targets not named.**
   - **Dispatch test:** "Extend dispatch tests" should name the test to extend. The natural one is `tests/factory/test_stream_d_dispatch.py:324` (`test_main_recovers_admitted_writer_before_ordinary_launch_twice`). It already does two replays and feeds the published card back through `self.c.checkpoint_card = published`. The new test should seed `checkpoint_card['loop_freshness']` with nested values, then assert two things after each replay: the published `scorecard.json` holds an equal copy, and that copy is not the same object.
   - **Freshness regression:** the design doesn't say which file it goes in. `tests/factory/test_freshness_restore_fixes.py` is the right place. Its `retain_verdict` helper (`:136-141`) and the restore, changed-case and stale tests (`:143-183`) already cover the validator side. Name that file and helper so the implementer reuses them and doesn't build a third harness.

3. **Nit, zoom-out: lines 26-32, the test plan overlaps existing tests.**
   - Existing tests already prove that a missing marker, a changed case, or a stale verdict forces a new review (`test_freshness_restore_fixes.py:162-183`), and line 34 admits this.
   - The one new property is that the pointer survives `carry_context` plus the republish. One composed test is enough: carry, publish, run `loop_freshness`, assert no reviewer call. One negative case (missing marker) is enough on top of that.
   - Keep the public-match → G2 failure assertion. It is cheap and shows that a carried path can't change the outcome.

4. **Nit, design critic: a stale carried value can be published.** If the extension round never calls `loop_freshness`, for example because nothing is flagged and it returns early at `factory/run.py:1032`, the published card keeps the previous round's `loop_freshness`. As shown above, this is harmless. Add one sentence to the design saying that no consumer treats it as current-round evidence, so a later reader doesn't "fix" it.

5. **Nit, design critic: the 24-hour mtime limit applies.** The 24-hour check at `factory/run.py:2218` still applies. If a resume comes more than 24 hours after the review finished, it pays for a new review. That is correct fail-closed behaviour, but line 42 should say it as a known limit.

6. **Nit, Heilmeier.**
   - **Objectives:** lines 5-12 are internal shorthand: "carry_context whitelist", "G2", "Lane 1 legacy allowance". The standard asks for no jargon. One plain sentence would do, such as: "After a diagnosis-approved extension resumes, the factory forgets it already has a finished freshness review and pays for it again."
   - **Timeline:** not stated.
   - **Lines 19-20:** "Delete loss of the fallback across publication" isn't a deletion, and the "Lane 1" line isn't explained. Cut both, or rephrase: the honest wording is that the change deletes nothing.

7. **Nit, records.** "Supports Murphy row 9; closes none" (lines 37-38) follows the rules in `docs/ENGINEERING.md` §2. The link to row 9, the money and writer-round exhaustion row, is indirect: it is about avoiding repeated paid review. One clause explaining the link would help.

## Scope and phasing

- The `docs/designs/stream-d.md` edit is consistent: it splits the large package item into increment 1 (this design) and increment 2.
- The change is about one line of code plus tests, and leaves the suite stable.
- Activation stays false and no rules in section 4 change, so no founder approval is needed.

**Result: PASS.** Findings 1 and 2 are recommended before implementation. The rest are optional.

## Implementation response

No blockers. Accepted the recommended test targets and restore-window clarification. Reused the existing harness; kept one missing-marker negative case plus public-match recovery. The change deletes no code. No Murphy rows close.

