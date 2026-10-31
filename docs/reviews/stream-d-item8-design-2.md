**Verdict: FAIL. 1 new blocker, 3 majors, 5 nits.**

The earlier blockers B1–B4 and majors M1–M4 are fixed in the text, and the plan is honest about what it can't do yet. But a fresh check of the money code found a new contradiction: the scenario caps can't pay for any real saved candidate. Like the previous review, this one only read files. I made no edits, ran no tests and spent nothing.

## Earlier findings

| Item | Status | Where in `stream-d.md` |
|---|---|---|
| B1 smaller Claude profile | Fixed. A owns it as a mandatory, reviewed prerequisite with a ≤$5 target. The $15.05 writer call is cited as proof that $5 success isn't established. Scenarios that need it are marked NOT RUNNABLE, and the plan goes back to the founder if the profile can't work. | 3435–3447 |
| B2 one worker | Fixed. B owns a separate worker-reuse design. The plan refuses to quietly read the rule as "one worker at a time" and goes back to the founder if B declines. No new worker budget is implied. | 3404–3413 |
| B3 input candidates | Fixed. B owns the bootstrap. The legacy a869de archive is explicitly excluded. Four candidate types are listed with the manifest fields each needs, and building cases from scratch is excluded. | 3461–3477 |
| B4 batch layout | Mostly fixed. There are two batches, α (scenarios 1–4) and β (5–7), with bounds of $40 and $50. In β the root job and its replacement each get half the scenario cap, and B must add an admission stop. Gaps remain; see M2 and N1. | 3415–3428 |
| M1 paid version replay | Fixed. It is inside scenario 6's $25 cap. | 3497 |
| M2 cross-release carry-over | Fixed. It is unconditional and owned by B. | 3476, 3496 |
| M3 rollback | Fixed. Rollback is a new reviewed release with `DIAGNOSIS_ENABLED=False`. `plan()` then returns `diagnosis_unavailable` and queued entries are kept. | 3565–3568 |
| M4 timeline | Fixed. Each scenario has an abort deadline, and nothing gets a fresh two hours on restart. | 3508–3519 |
| N1–N4 | All fixed. | 3495, 3496, 3518, 3400 |

## Blocker

**B5. The scenario caps can't cover a real candidate's past spend.** (lines 3418–3421, 3481–3483, 3471, scenario 6)

- **How the money check works:** before each call, `budget.require_case_budget` adds the case's lifetime spend to its reserved calls and refuses the call if that reaches the job's commitment (`factory/budget.py:651–652`).
- **The design forbids resetting that spend.** A commitment turns into case spend rather than adding to it, "No overspend is erased", and B works out batch spend from each case's lifetime totals (`stream-d.md:59–64, 74–77`).
- **The plan's numbers are too small for real cases.** It sets α job commitments to the table caps ($5–$15) and β roots to half a cap ($5–$12.50), with batch bounds of $40 and $50. But every input must be an existing case, and recorded cases spent about $51 each. Scenario 6 even requires a case that has already run out of its ordinary money, so it has spent about $50.
- **Result:** every carried-in case is refused before its first call, and the batch bound is already used up when the batch is admitted.
- **Fix:** say that each cap is *new* spend. Set each job's commitment to the carried-in settled spend plus that scenario's share. Set the batch bound to the sum of carried-in spend plus $40 or $50. Keep the $90 as a new-spend total that the run manifest checks against the settled spend recorded for each candidate. Also confirm that scenario 6's extension money isn't treated as "reopened" ordinary money. If B's bootstrap can't express a carried-in starting spend without erasing anything, mark all candidate scenarios infeasible and go back to the founder.

## Majors

**M5. Candidates aren't tied to a rotation slot, so it's unclear which scenarios can actually run.**
- Each case's slot fixes which model family plays each role (`rotation-3writers.json`):
  - The strong calibrator is Anthropic only in slots 4 and 7. Everywhere else it is OpenAI, which has no enforced spending maximum.
  - Diagnosis uses the slot's reviewer family (`stream-d.md:326–328`). That is OpenAI in slots 4 and 7, Anthropic in slot 6, and a free route otherwise.
  - The writer is a free route in slots 4–8.
- What follows:
  - Scenario 4 needs a slot-4 or slot-7 candidate.
  - Scenarios 5–7 are impossible on slot 4 or 7 until OpenAI has an enforced maximum.
  - The account-2 check needs an Anthropic role that the chosen scenario actually exercises.
  - Scenario 1 may not need Claude at all. Saying so is conservative, which is fine.
- The NOT RUNNABLE lists also disagree with each other (3413, 3445, 3472). For example, 3472 leaves out scenarios 1 and 5 even though both need real candidates.
- **Fix:** add the required slot and role family to candidates (a)–(d). Map each scenario to its candidate. Replace the three scattered lists with one table showing which prerequisites block which scenarios.

**M6. Scenario 5 needs a third batch that the layout doesn't mention, and worker reuse isn't scoped to cover it.**
- The holder refuses any operation whose release differs from the batch's release (`batch_holder.py:108`). So the fixed release for scenario 5 means a third batch.
- That batch has no money bound, deadline or commitments in the plan, and the order of scenarios 6–7 relative to the faulty release isn't stated.
- One worker would have to serve three batches and three releases. B's reuse prerequisite only says "across ordinary checkpoint launches" (3408).
- **Fix:** add the third batch to the fixed layout, with its bound inside β's $50. State that B's reuse design must cover moving one worker across batches and releases, including installing each release.

**M7. The one-generation replacement policy is written as "if supported", but the code already shows it isn't.**
- `replacement_policy` only allows the fields `{schema, enabled}` (`batch_money.py:46–50`).
- With replacement on, a replacement that runs out of money would derive another replacement (`-r2`), each copying the root template's commitment.
- **Fix:** delete the "if supported" branch. Make B's qualification-only admission stop an unconditional prerequisite with acceptance tests.

## Nits

- **N5.** The closure section says the version replay happens "Across scenarios 5–6" (3538), but its cost sits only in scenario 6 (3497). Pick one.
- **N6.** The 105 minutes of scenarios plus 15 minutes of cleanup fill the whole two-hour lifetime. Worker creation, boot and installing up to three releases have no time left. Leave a margin, or shorten the scenario windows.
- **N7.** Line 3413 says "All restore scenarios" are not runnable, but with one worker every launch after the first is a restore. Say that the whole plan is blocked until worker reuse lands.
- **N8.** A job's case ID is built from the batch ID and job name (`batch_money.py`). Note that B's bootstrap must re-bind each candidate to that form, and that one candidate can't serve two jobs without separate copies.
- **N9.** State that scenario 5's faulty release and its fixed release both fall under the separately approved practice-release authority (3552–3557).

## What passes

- Row 9 (diagnosis outcomes) and row 39 (G10 capped-guard evidence) stay open, and their closure conditions are correct.
- G10 semantics are right.
- The account-1 fallback still needs real rate-limit evidence from the provider.
- No flag is flipped, there's no monkeypatching, and nothing is spent or authorized.
- The founder must approve the activation commit separately.

**Next step:** fix B5 and M5–M7, then get another fresh review. Feasibility stays conditional until A and B land the profile, bootstrap, worker-reuse and admission-stop prerequisites, and those get their own independent review before any launch.

## Elephant response

Accepted B5 and M5–M7 plus nits. Incremental budget is now distinct from lifetime commitments, with carried spend never erased; B must enforce per-scenario authority across releases and cap fresh replacements independently of root lifetime totals. Slot mapping, explicit release batches, admission-stop acceptance and time margin added. Fresh review required.

