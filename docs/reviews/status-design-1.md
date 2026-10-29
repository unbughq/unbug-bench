# Goldfish review 1: docs/designs/status.md

Reviewer: fresh Claude Sonnet subagent, personas zoom_out + design_critic, Mode: REVIEW, read-only. Verbatim.

1. **BLOCKING: the data source cannot show running cases.**
   - The doc reads only `sealed/*.scorecard.json`. In the 297 real cards I checked, the card is written when a worker stops or a checkpoint is collected. 211 have `status: stopped`, and the other 86 are older cards with no `status` field.
   - The "running" count, the "marked running, no card update for 1h20m" rule and the "at G11 for 6h" rule need a live heartbeat. The card isn't one.
   - A live heartbeat does exist: `<case>.progress.json` sits next to the card. It holds per-stage `status`, `updated_at` and `elapsed_seconds` (e.g. `role:writer`, `role:reviewer`), which is close to the `stage` and `stage_since` the doc proposes adding.
   - Read progress.json (or the work-dir equivalent) instead of changing the card. That deletes the "Card change" section and the new writer coupling.
   - If the card change stays, say who writes it between collections. As written, the "no card update" rule is a real stuck case that can't fire.

2. **BLOCKING: several rules reference fields that do not exist on public cards.**
   - Not found in any of the 297 cards:
     - `retry_after`, `provider_wait`, `provider_wait_unrecoverable`. These appear only as proposals in `docs/designs/interfaces.md`.
     - Any "reviewer disagreement" field. The closest real signals are `terminal_stop` values such as `stress_review_unresolved:*`, `freshness_unresolved` and `freshness_review_unavailable`, plus `admission.status` of `evidence_incomplete`.
     - Anything for "retired".
   - Batch balances (Boat wallet, OpenRouter credit) are not on any card.
   - Rules 1, 4, 5 and 8 therefore depend on interfaces still in design, or on a source the doc never names. State that dependency, or cut those rules until the fields exist.
   - Say how the balance data is obtained. Otherwise rule 8 reads from nowhere.

3. **BLOCKING: the cost and round rule uses the wrong keys, and the real data would miss or misfire it.**
   - Spend and limit are `case_budget.spent_usd` and `limit_usd`. The round limit is `recovery_config.rounds` against `builder_rounds`.
   - Cards from before the budget block have no `case_budget`: 266 of 297 are missing it. `recovery_config` is missing on 252, and `builder_rounds` on 195. The doc says missing stage data shows `stage ?`, but it does not say the same for money and rounds.
   - The doc's own example has the wrong limit: `$58 / $70`, where the real card shows `52.79 / 70`.
   - The limit moves with founder rulings (55 to 70), so read `limit_usd` rather than a constant.
   - The rule should fire at 80% of either budget or rounds and stay silent when the keys are absent.

4. **NIT: the "3× the median stage time, at least 2 hours" rule is noisy and misses the worst case.**
   - A batch has about 24 cases, and early in a batch the median is built from one or two samples. Stages like G11 have bimodal duration, so the 3× rule will flag normal cases.
   - It also can't flag a case stuck at the first stage of a new batch, because there is no median yet.
   - The fixed `no_progress_minutes: 45` already in `recovery_config` makes the separate 1-hour no-update rule duplicate it. Replace the median rule with a single absolute "same stage for more than N hours" threshold and drop the median computation.
   - If real stage durations are needed, take them from `gate_minutes`, which is already on the card.

5. **NIT: the "same stop reason on 3 or more cases within 1 hour" rule is probably noise.**
   - Today `paused` is the stop reason on 148 of 211 stopped cards. Anything that stops a whole batch at once, such as a provider limit or a restart, produces 3 or more at once.
   - The rule also needs a stop timestamp that the card doesn't carry. Use the file mtime of the card, or the progress `updated_at`.
   - Exclude `paused` and `complete`, or fold the rule into the provider and credit line.

6. **NIT: the status output is missing the founder's most obvious question, "what do I need to do?"**
   - Each flag has a message but no action: "needs ruling", "relaunch", "top up".
   - Add a plain "done / total sealed" line, since the founder wants to know how close the batch is.
   - Say what happens when `sealed/` is empty or a card fails to parse: show the case as `unreadable` and flag it.
   - Say where the stop reason comes from: `terminal_stop`, or the ledger.
   - Size: the "50–80 lines" estimate is plausible, and the idea of one command with no dashboard is right. Cutting the median rule and the repeat-stop rule shrinks it further.

FAIL. The design is the right size, but findings 1 to 3 mean the rules cannot run as written. The doc needs to name a live source (progress.json) and use only fields that really exist in the cards.
