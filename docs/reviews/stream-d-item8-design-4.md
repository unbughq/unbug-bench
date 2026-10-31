**Verdict: PASS. This is a design-only plan. I found 0 blockers, 2 majors and 4 nits.**

I worked read-only in `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`. I read `docs/ENGINEERING.md`, the three personas, and both standards (`heilmeier-standard.md`, `implementation-readiness-standard.md`). I then read Item 8 (`docs/designs/stream-d.md:3384–3670`) and its uncommitted diff (+79/−36). I also read the Murphy rows the section cites (8, 9, 10, 11, 12, 13, 15, 21, 39, new-batch-service-4, plus nearby B/E rows), the B practice plan, and review 3 of this design. Mode: REVIEW. Nothing was executed and no row is claimed closed.

## Does the diff match the requested amendment? Yes.

- **Sequential throwaway workers, concurrency one:** stated at 3404–3406. The text also says plainly that "one throwaway worker" described B's practice and was never a founder restriction. That matches the correction.
- **Ordinary launch path:** every worker, including checkpoint resumes, is created through the normal single launch path (3407–3408). This is consistent with the "One launch path" rule in section 4.
- **Deletion verified before the next creation:**
  - The plan requires a provider deletion receipt plus complete inventory absence (3409–3410). This matches B's evidence standard, which says inventory absence alone is not a receipt (B plan :220–224).
  - An uncertain creation or deletion blocks the next creation (3411).
  - A controller restart must reconcile the same operation rather than create a duplicate (3411–3412).
  - Pre-armed independent cleanup is kept (3412–3413).
- **No worker-reuse prerequisite on B:**
  - The bold reuse prerequisite is gone, and so is the "NOT RUNNABLE until reuse lands" sentence.
  - Table rows 1–3 and 5 now ask for sequential launch/deletion evidence and verified deletion instead of reuse.
  - 3414–3415 says explicitly that B owes no reuse support.
  - A search for one-worker, single-worker and reuse wording finds nothing left in Item 8. The plan still cannot run, because every table row stays blocked (3533).
- **Scope:** the amendment removes a B prerequisite rather than adding one, which fits "delete before adding". The additions (slot table, revised timeline, closure paragraph) are needed consequences of the change, not new scope.

## Arithmetic checks

| Check | Result |
|---|---|
| Worker slots: 3+2+1+2+4+6+2 | 20 = N ✔ |
| Infrastructure: I(20) = 0.40×20 + 2 | $10 ✔ |
| Model caps: 10+10+5+15+15+25+10 | $90 ✔ (alpha 40 + beta 50, unchanged) |
| Per-scenario model + worker: 11.20 / 10.80 / 5.40 / 15.80 / 16.60 / 27.40 / 10.80 | each equals cap + 0.40 × slots; they sum to $98, plus $2 shared = $100 ✔ |
| Timeline: 70 + 15×20 + 110 | 480 min = 8 h ✔ |

**Is $0.40 per lifecycle plausible?** It is stated as an admission ceiling, not a quote, and launch is refused if current prices don't fit. It is far above the real through-deletion bound of $0.00018 recorded in Murphy row new-router-gate-wall-1. It is much smaller than the USD 5 B reserved for its own practice worker, but that figure is a cap, not a measurement. Loss and uncertainty handling hold up: unknown charges stay reserved, worker cost is never divided by N, and infrastructure spend is never reset on a release change.

## Blocking findings

None.

## Majors

**M1. No rule for what happens if the 15-minute lifecycle allowance doesn't fit.** (3589–3597)
- Each worker's creation, boot, release installation and verified cleanup drops from the earlier 20 + 20 minutes to 15 minutes in total. No measurement backs this; review 3's N10 already called even 20 minutes unbacked.
- The plan says B/E must measure these times, but not what follows if the measurement is longer. The two readings:
  - The 110 minutes of slack absorbs it. For example, 20 minutes × 20 workers uses 100 of the 110.
  - Launch is blocked and the plan goes back for revision.
- "A failure to bound cleanup blocks launch" only covers failing to bound cleanup, not a bound that is larger than 15 minutes. Leaving this open breaks the zero-decision rule.
- **Fix:** add one sentence. For example: a measured per-worker lifecycle above 15 minutes draws from shared slack only while 70 + N×measured ≤ 480 minutes; otherwise the plan must be revised before approval.

**M2. Scenario 6 is split around scenario 7, but "one scenario's jobs admitted at a time" doesn't say what state scenario 6 must be in.** (3431–3432 vs 3464–3465)
- The beta-fixed order is now: scenario 5 resume, scenario 6's diagnosis and extension, then scenario 7, then scenario 6's replays on beta-plumbing and beta-science.
- So scenario 6's root (and maybe its replacement) is still admitted, holding reservations and its $12.50 / $12.50 allocations, while scenario 7 is admitted.
- The manifest author then has to decide two things:
  - Must scenario 6 reach a collected, quiescent checkpoint first (no live worker, no unsettled reservations) before scenario 7 is admitted?
  - Must scenario 6's replacement finish on beta-fixed, or is it carried across the later releases?
- **Fix:** state that scenario 6 is collected, and settled or conservatively retained, before scenario 7 is admitted, and that its jobs carry forward only through B's carry-over. Say whether the replacement finishes on beta-fixed.

## Nits

- **N1.** Line 1146 says a close_to_passing diagnosis "continues in the same worker into extension admission". Scenario 6's slot list counts diagnosis and extension continuation as separate workers. Both are compatible, because slots are ceilings. Say which path is expected, or that the extension slot is spare when 1146 applies.
- **N2.** Scenario 2 has two timeout cases (after one category, and before any category answer) but only 2 slots. Scenario 4's G16/G17 replay has no slot of its own. The manifest rule (revise the plan if more slots are needed) covers both, but naming where those replays run would avoid a revision.
- **N3.** Twenty deletions instead of one make the open E row new-isolation-outer-wall-1 (outer Boat callers can stop the owner before cleanup finishes) a direct risk to the "deletion verified before next creation" chain. Name it, and B's new-single-path-1 (post-migration store qualification), among the launch prerequisites.
- **N4.** Closure 3630–3631 ("Rows 8/21 retain their existing … scope") overlaps 3637–3638. Merge them into one sentence.

## Reasoning

**Zoom out.** The amendment simplifies. It drops a lifecycle feature (reusing one worker across launches, batches and releases) that nothing in production needs, and puts the ordinary create, checkpoint, delete loop in its place. That loop already exists and has a real receipt and inventory evidence standard. There are no premature details: the slot and timeline numbers are ceilings for the manifest, not pseudocode.

**Design critic.**
- *Heilmeier questions:* still answered. Objective, cost ($100 ceiling separate from B's $25), timeline (now up to 8 h, an abort deadline), risks (both the $5 Claude profile and the 15-minute lifecycle are explicitly unestablished), and exams (the per-scenario evidence plus the closure paragraph).
- *The new closure paragraph:* correctly stops sequential workers from weakening any criterion. Restores must cross different worker IDs, a same-worker restart cannot replace a checkpoint restore, and lifetime counters and spend must survive every deletion and relaunch.
- *Security and section 4 rules:* nothing changes. Each worker gets credentials and case material through the ordinary launch path, the exposure window is still one live worker, nothing depends on the Mac, and the flag stays False.
- *Residual risk (not introduced by this amendment):* if the control VM itself is lost, the control-VM cleanup timer may go with it. The exposure is still bounded to one worker.

**Implementation readiness.** Apart from M1 and M2, the remaining decisions are correctly pushed to the reviewed concrete manifest: CLI commands, input hashes, injection points and cleanup commands. Missing any of them blocks launch.

**Murphy rows.**
- Rows 9 and 39 stay open, with correct closing conditions.
- Row 13's live scenario is not waived.
- new-batch-service-4 (cross-batch carry-over) is still a named B prerequisite for scenarios 5 and 6.
- No row closes from this design.

## Elephant response

Accepted the PASS and all six findings; none rejected. M1 is resolved by an explicit admission rule: measured per-worker lifecycle overhead over 15 minutes requires a revised plan before approval; slack cannot waive it. M2 is resolved by completing scenario 7 before admitting scenario 6, with verified deletion and settled or conservatively retained usage. Scenario 6's replacement reaches terminal collection on beta-fixed; only the original carries into version replays through B's reviewed path.

N1 now says the extension continuation slot is spare when diagnosis continues in the same worker. N2 assigns both stress timeout observations to the first worker and the restore to the second, and runs G16/G17 on each guard attempt's worker; incompatible packing requires a revised manifest/slot budget, not omitted evidence. N3 explicitly names E's outer-call cleanup fix and B's migrated-store qualification. N4 removes the duplicate closure sentence. These are local documentation clarifications; no code, activation, row closure or live spend changed.

The final requested ceiling is USD 100: USD 90 model money, up to 20 sequential worker lifecycles at USD 0.40 each, and USD 2 shared infrastructure. Prices, lifecycle bounds, route feasibility and authenticated candidate availability remain pre-approval prerequisites rather than established facts.


Validation: the required `uv run --with numpy --with scipy python -B tests/run.py` passed locally before integration: 158 scripts, zero failures, exit 0. Local log: `/tmp/stream-d-item8-design-4-suite.log`, SHA256 28c05d8f3b1f994f5bb0f1399d08e8381061507af46b1d71b97f7a4fd23033de. The parent then confirmed that `f829df7` includes `eecd0c3` and passed its merged suite 158/0. This lane fast-forwarded to `f829df7` before committing the amendment; no production code was changed by this amendment. Verified the entire design prefix before Item 8, including lane 2's receipt-publication section, is byte-for-byte identical to `f829df7`. The final documentation passes `git diff --check`; budget arithmetic also passed. No additional suite was run after this documentation-only restoration.
