# Item 8 design review 3: live qualification and switch-on (`docs/designs/stream-d.md:3384–3619`)

**Verdict: PASS as a design-only, conditional qualification plan. 0 blockers, 2 majors, 5 nits.**

I read `ENGINEERING.md`, the three personas, both standards, item 8 in the working tree (238 new lines, not yet committed), reviews 1 and 2, `factory/rotation-3writers.json`, the diagnosis-family rule (`stream-d.md:326–328`) and `batch_service.resolve_job`. This was read-only: no edits, no tests, no spend.

## Earlier blockers

| Earlier finding | Status | Where |
|---|---|---|
| B5: new spend vs lifetime S+E | **Fixed.** Each scenario cap is NEW spend. A root's commitment is S+E, never E alone. Ledgers are never reset. Ordinary exhaustion stays exhausted. | 3426–3450, 3527–3529 |
| Cross-release authority and a fresh replacement clamp | **Fixed.** B must check cumulative authority across retired releases before granting the next one. B must add a reviewed clamp that gives the child its own S+E with S=0, and must never copy the root's past spend. | 3431–3445 |
| Exact release batches and a shared $50 | **Fixed.** Alpha, then beta-fault, beta-fixed, beta-plumbing and beta-science, in a fixed order. Scenarios 6–7 never run under the faulty release. All beta batches share one $50 of new spend (7.5+12.5+5 = 25, doubled to 50). Alpha has $40 (10+10+5+15). The arithmetic checks out. | 3415–3424 |
| Mandatory admission stop | **Fixed.** It is unconditional, and its saved-artifact acceptance list covers: one replacement only, no r2, no duplicate admission on replay, no inflated child S, no E regranted on a release change. | 3452–3457 |
| Slot/role map and required OpenAI maxima | **Fixed.** I checked slots 1, 4 and 6 against `rotation-3writers.json`, and every family named is correct. OpenAI maxima are required for scenarios 4 and 6. One table replaces the three scattered lists. One omission remains; see M9. | 3505–3529 |
| One worker across batches | **Fixed.** B's reuse prerequisite now covers checkpoint launches, batches and immutable releases, including verified release installation. The whole plan stays NOT RUNNABLE until it lands. | 3405–3413 |
| Bootstrap case lineage | **Fixed.** Case IDs are derived from the batch and job, each job gets its own immutable copy, and lineage, ledger and artifacts are preserved without editing old cards. | 3507–3511 |
| Deadline margin | **Partly fixed.** The windows are smaller (80 minutes of scenarios), and creation, boot and install now have 20 minutes. But the total is still exactly 120 minutes, with no slack; see N10. | 3558–3570 |

All earlier nits (N5–N9) are fixed. N5 now reads "Within scenario 6 alone" in both places.

## Majors

**M8. The plan doesn't say where scenario 5's replacement runs.** (3416–3418, scenario 5 row)
- The replacement is queued in beta-fault, the release that contains the injected fault.
- Removing the fault means a new release, and holder bindings can't change. So the queued replacement either runs under the fault, or it has to be moved to beta-fixed.
- If it runs under the fault, it would hit the fault, run out of money and stop at the no-r2 rule. That doesn't satisfy "original/replacement both remain eligible if they seal".
- If it moves, it needs the same cross-release carry-over the original needs, plus its own $7.50 carried across without being regranted.
- As written, the manifest author has to make this choice, which breaks the zero-decision rule.
- **Fix:** add one sentence. Either the replacement is carried to beta-fixed under B's carry-over and clamp, or it stays in beta-fault and its outcome there is the expected result. Then add that to B's carry-over scope.

**M9. Scenarios 6 and 7 are missing prerequisites in the table.** (3513–3520, 3487)
- **Scenario 7 needs the Claude profile.** `resolve_job` deep-copies the root template, so scenario 7's replacement inherits slot 1, which has an Anthropic writer. That needs A's small Claude profile, but row 7 doesn't list it.
- **Scenario 6 needs cross-release carry-over.** It spans beta-fixed, beta-plumbing and beta-science, so it always needs that carry-over. Line 3487 says "Scenario 5 ALWAYS needs" it. Row 6 only says "all lifecycle/admission prerequisites".
- **Fix:** add the small Claude writer profile to row 7, and name cross-release carry-over in row 6.

## Nits

- **N10.** 80 + 20 + 20 = 120 minutes, which is the whole lifetime. Installing five releases in 20 minutes isn't backed by any measurement. Either keep an explicit slack (say 10 minutes), or say that the plan aborts at the last checkpoint once remaining time is below the cleanup bound.
- **N11.** Line 3446, "Baselines are only used to calculate the *additional founder approval*", reads backwards. What's meant is that new spend = settled total − S, and that figure is checked against the approval. Say it that way.
- **N12.** Scenario 6 has 15 minutes for diagnosis, a replacement, a writer + stress + gate pass and two batch-switched replays. The text already admits a scenario may come out unproved. It would help to state that the replays run only if the extension finishes inside its window.
- **N13.** Account-2 evidence is tied to scenario 4, but scenario 1, which runs earlier, also makes Anthropic writer calls in slot 1. The private correlation should cover the scenario 1 window too, or that window should be explicitly excluded.
- **N14.** Line 3527, "Account-2 usage is measured on scenario 4's Anthropic call", repeats line 3554. Keep one.

## What passes

- The plan authorizes nothing and keeps the $100 as a ceiling. It forbids forged inputs, invented policy fields and monkeypatching.
- The legacy a869de archive is excluded, and building cases from scratch is excluded.
- Rows 9 and 39 stay open with the right conditions for closing them. Row 13's live check isn't waived.
- G10 semantics are right: a capped or missing guard is inconclusive.
- The rule for falling back to account 1 is strict.
- Rollback is a new pinned release, and queued entries are kept.
- The flag stays False until a separately reviewed, founder-approved activation commit.

**Next step:** M8 and M9 should be fixed in the text before B and A start their prerequisite designs, but they don't block passing this design. Launch still depends on A's profiles and maxima, B's bootstrap, worker reuse, carry-over, clamp and admission stop, item 7's joins, a reviewed concrete manifest and founder approval.

## Elephant response

Accepted PASS. Addressed M8: carry both original and queued replacement to beta-fixed, preserving each allocation. Addressed M9: explicitly name scenario-6 carry-over and scenario-7 replacement's small Claude writer profile. Nits: add 10-minute slack and cleanup cutoff; clarify incremental-spend formula; gate version replays on remaining scenario-6 time; correlate both scenario-1 and scenario-4 account-2 windows; remove duplicated account sentence. No flag, code or spend authorized by the plan.
