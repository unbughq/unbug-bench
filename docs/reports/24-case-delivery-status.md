# Delivery status: 24 qualified hidden cases

Snapshot: 2026-11-04. Source base: `fbca505894bda2b5ac6042994ed46a507e678925`.
Preparation only; no deployment, worker creation, model call or spending.

## Where we stand

**Zero current exam-ready acceptances verified in this audit.** There are two
historical cases worth requalifying and one quarantined case. The factory has
reviewed and offline-tested changes, but its repaired live lifecycle still needs
proof before production admission. Source is now in the private GitHub repository;
cloud agents can return reviewable branches instead of loose patches.

This is a bounded audit of canonical local and control-VM public scorecards, not
an exhaustive search of R2 or every isolated run directory. It does not claim that
no recoverable generation exists elsewhere. No keys or case contents were read.

## Inventory

The local snapshot has 51 cards: 1 practice, 34 stopped/incomplete, 13 failed-gate,
and 3 historical G1–G15 all-pass cards. The current control VM snapshot has 54
cards and the same three historical all-pass candidates. These are overlapping
inventories; **do not add 51 and 54 together**. All 51 shared public cards match
byte-for-byte; the three VM-only cards are stopped/incomplete. No newer fully qualified ready set
was established. Current acceptance requires more than the historical G1–G15 set.

| Case suffix | Retained evidence | Disposition / exact next evidence |
|---|---|---|
| `86b100` | Original encrypted archive present locally and hash-matches its card. October 22 scoped repair reviewed; paired BASE diagnostic: broken plain app in 3/3 valid trials, reference 14/14 checks in each trial, legitimate completion 100%. | Recovery candidate. Run the configured full qualification, fresh fairness/calibration and rehearsal; reseal a new bound generation. The diagnostic is not a full pass. |
| `18681d` | Original archive present and hash-matches its card; scoped document/key repair independently reviewed. | Recovery candidate. Prove the counter/web overlap race first, then full qualification, calibration, rehearsal and reseal. |
| `fcde6b` | Original archive present and hash-matches its card; later R4 reproduced stale compensation corrupting newer business state; R5 found no safe narrow correction. | Quarantined. Do not spend this pilot redesigning it or count the historical pass. |

These repair dispositions come from the latest matching public repair records
found, dated October 22, not a new content audit. The stated full qualification
includes G1/G3/G4/G5/G6/G7/G8/G10/G13/G14/G15/G16/G17, conditional G2/G9 refresh,
G11 if the fresh tester passes, and G12 after acceptance. Follow the pinned current
pipeline and affected-gate fingerprints; never manufacture pass receipts for an
inapplicable or skipped gate. Preserve every original archive and scorecard.

If both recovery candidates pass, we still need **22 fresh accepted cases**.
If neither passes, we need **24**. The three fresh completion-pilot cases count
toward that total when accepted; they are not an additional quota.

Retained public snapshots and their hashes: [inventory index](completion-pilot-inventory/summary.json).
Repair records remain in the original local evidence store, with hashes in that
index; private repair payloads are not copied to GitHub.

## Finite work queue

| Order / owner | Deliverable | Current state / stop condition |
|---|---|---|
| 1 — existing Claude cloud release owner | Review and finish the saved-smoke carry on its own branch; return GitHub branch/PR, exact source, tests and review. | Pending returned evidence. Root must fetch and validate the combined source. Session creation is not completion. |
| 2 — root, after release acceptance and concrete deployment authority | Deploy/pin the repaired release without changing old journals; complete the saved no-model smoke, independently verify collection, publication ACK, same-stop meter/recheck, exact deletion operation and settlement. | Live lifecycle unproven. At most two new qualification attempts is a proposal, not permission. No real cases before this passes. |
| Parallel — existing Claude cloud registry owner | Finish stale-history/reselection validation. | Does not block serial builds. Must pass before increasing admission concurrency. |
| Parallel — root preparation | Inventory and completion-pilot proposal. | This report and [completion plan](../designs/completion-pilot.md). No active manifest or launch pin created. |
| 3 — factory implementation/review, then founder launch decision | Replace the diagnosis pilot's short timing with a separately pinned completion profile; validate cleanup/restart/accounting binding and prepare the exact manifest. | Required implementation is specified in the plan. Current pilot rejects the proposed timing. |
| 4 — root, with approved launch bounds | Build three distinct fresh cases serially through the full pipeline. | A failure/hold is recorded as such; it is not pilot success. Stop admissions on money, ownership, settlement or publication uncertainty. |
| 5 — root and separately assigned case auditors | Requalify the two recovery candidates while building toward qualified totals 3, 10, 17, 24. | Recovery qualification requires scoped access and its own budget/admission; it is not enabled by the fresh pilot. Parallelism only after admission/spend/cleanup evidence passes. |
| 6 — root | Independently audit and freeze 24 encrypted cases, hashes, deterministic scoring and exam launch procedure. | No exam-ready claim until the acceptance ledger names all 24 qualifying generations. |

The November 3 scoreboard is historical. Current source has 81 Murphy rows,
34 closed and 47 open; this report closes none. Only failures on this delivery
path block the bounded pilot. Examples include live stop/meter/deletion settlement,
selected-route cancellation/isolation, publication/restart proof and completion
admission timing. Broader fleet/replacement features must not be silently assumed.

## Measurable next decision

The next paid milestone is **one verified repaired lifecycle**, then **three
qualified fresh cases**. Record yield, elapsed time, priced inference, actual cash
where available, compute and infra waste separately. Do not buy another broad
redesign after an unsuccessful milestone: preserve the evidence, identify its
specific failure and return a bounded correction or a shortfall decision.

No completed-case cost or ETA has yet been established. The proposed pilot is how
we obtain that evidence; it is not a promise that 24 cases will finish in a day.
