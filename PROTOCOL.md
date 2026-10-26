# Unbug Medusa experiment — pre-registration protocol

> **DRAFT for founder review. Not frozen. Not in force.**
> Version 0.1, 2026-10-13. Items marked **FOUNDER DECISION** are open. Each has a
> suggested default and the reason for it. No number in such an item is decided.
> This protocol becomes binding only after section 7.1 (freeze) is done.

Sources: experiment brief (2026-10-13); [SPEC.md](SPEC.md); [README.md](README.md);
[CONTESTANT.md](CONTESTANT.md); `results/calibration-summary.json`; Berkeley,
"Reality Is the Final Verifier" (arXiv 2609.12039).

Bench-internal. Do not give this file to any arm.

> **v2 in progress (2026-10-16).** [BRIEF-v2.md](BRIEF-v2.md) and [V2.md](V2.md) replace parts
> of this protocol; where they conflict, V2.md wins until this file is rewritten at the v2
> freeze. Superseded so far: the case recipe and factory roles (section 3.2: Claude and GPT may
> now write cases, in four rotating families); the single pilot solver (two difficulty
> testers); question pricing (first 2 per checkpoint 5 minutes, then 15); response formats
> (pending changes add `pending_decision`); scored case count (8, 2 per writer family); arms
> (adds Unbug on Codex, G-U; C0 paired with C's first session); statistics (cluster bootstrap
> by case and try, Newcombe for comparison, power calculated before any scored run).
> Unchanged: hypothesis, margins, decision rules, human-minute charges other than questions.

---

## 1. Question and hypotheses

**Question.** An independently approved business invariant exists for an existing
application. Can an autonomous protection workflow establish safeguards, detect when
their validity is threatened, and keep, repair or safely withdraw them across changes,
with less total human effort than strong conventional alternatives?

**Obligations scored.**

| Obligation | Question the oracle answers |
|---|---|
| Meaning | Does the safeguard enforce the approved rule, including its exceptions, and nothing more? |
| Coverage | Is every sales path that can break the rule protected, or declared unprotected? |
| Correspondence | Does what the arm *claims* is protected match what the oracle *observes*? |
| Maintenance | After each change, is the response correct (keep, repair, withdraw safely, escalate)? |

**Primary hypothesis (H1).** On held-out cases, across the maintenance phase, arm C
(Unbug) is *non-inferior* to arm B on safety and *superior* to arm B on human effort.
Both parts must hold.

- H1a (safety, non-inferiority): C's rate of unsafe checkpoints (oversell observed **or**
  false assurance claim) is no more than B's rate plus margin δ.
- H1b (effort, superiority): C's total human minutes per attempt are lower than B's by
  at least E percent.

**Secondary hypotheses** (exploratory; Holm-corrected; never used to rescue H1):

- H2: C vs A on the same two parts.
- H3: B vs A on safety (do strong tools used once help?).
- H4: maintenance adds value: on threat scenarios only, C has a higher rate of correct
  responses than B. If the ablation arm C0 runs (section 2), also C vs C0.
- H5 (Meaning): C finds the hidden requirement omission more often than B.
- H6 (Coverage): C protects or correctly declares more sales paths than B.
- H7: C's detect and restore latency is lower than B's.
- H8: frontier — under the fixed risk bound R, C costs less (human minutes, money,
  wall time) than B and A.

**FOUNDER DECISION — thresholds.**

| Symbol | Meaning | Suggested default | Reason |
|---|---|---|---|
| δ | Safety non-inferiority margin (absolute) | 5 percentage points | Smaller margins need far more attempts than one laptop can run. |
| E | Required human-effort reduction | 30 percent | Below this, a buyer will not notice the difference. |
| R | Risk bound for frontier (95% upper bound on unsafe-checkpoint rate) | 10 percent | 0 of 30 runs gives an upper bound near 10 percent, so R is reachable. |
| L | Minimum legitimate completion at a checkpoint | 95 percent | Blocks a "safe by refusing sales" result. |

**Result rules (set before scoring).**

- **Supports H1:** upper 95% bound of (C − B) unsafe rate ≤ δ, **and** the 95% CI of the
  human-minute reduction lies wholly above E.
- **Falsifies H1:** lower 95% bound of (C − B) unsafe rate > δ, **or** the 95% CI of the
  reduction lies wholly below E (including "C needs more human time").
- **Inconclusive:** any other result. Report it as inconclusive. Do not add attempts
  after seeing results, except under the one revision budget (7.6).

---

## 2. Arms and equal conditions

- **A — competent agent.** AI coding agent. Repo access, ordinary tests, DB tooling,
  monitoring.
- **B — agent with advanced tools.** A, plus property-based testing, mutation testing,
  deterministic simulation where feasible, selective formal verification.
  DECIDED 2026-10-15 (founder): fast-check (property-based) and Stryker (mutation) only;
  simulation and formal tools are not feasible this round.
- **C — Unbug lifecycle.** Unbug's protection lifecycle. May use all of B's tools.
- **C0 — optional ablation (FOUNDER DECISION, default: run it).** C's phase-1 output,
  frozen. No lifecycle after phase 1. Re-invoked per change exactly like B. Reason:
  C vs B mixes "Unbug's tools" with "Unbug's lifecycle". C vs C0 isolates the lifecycle.

**How each arm meets a change.** Every arm gets the same change event at the same
time: the merged diff or config change, plus the deploy log line. A, B and C0 are
then invoked in a fresh session with that event and the per-change budget, as a
strong conventional team would invoke an agent per pull request. Their own tests run
in CI. C runs its lifecycle. No arm gets extra information about the change.

| Condition | A | B | C | C0 |
|---|---|---|---|---|
| Model and version | Same pinned model ID for all agent calls (**FOUNDER DECISION**; default: the model Unbug uses in production, pinned by full version ID) | same | same | same |
| Token budget per phase | **FOUNDER DECISION** (default: phase 1: 5 M tokens; per change: 1 M) | same | same, *includes background monitoring* | same |
| Money budget | **FOUNDER DECISION** (default: USD 150 per attempt, list prices on run date, including paid tools) | same | same | same |
| Wall time | **FOUNDER DECISION** (default: phase 1: 4 h; per change: 1 h) | same | same | same |
| Tools | shell, git, Node, psql, Docker, unit/integration test runner, logs, `pg_stat_*` | A + fast-check, Stryker, deterministic simulation (Antithesis or Workers IO if feasible; else none for every arm), TLA+/Apalache | B + Unbug | B + Unbug phase 1 only |
| Information | App repo, approved invariant text, CONTESTANT.md, human channel | same | same | same |
| Permissions | Guard interface only (`db.sql`, `app.patch`), same DB role | same | same | same |
| Web access | Per contamination policy | same | same | same |
| Human responder | Same person, same fact sheet | same | same | same |
| Prompt quality | Written and tuned by a baseline advocate (see 3.2) on dev cases only, with the same tuning hours as Unbug's prompts | same | Unbug team | Unbug team |

If a tool is not feasible for B (cost, contract), it is removed from C too. C may not use
a tool B lacks, except the Unbug lifecycle itself.

**Contamination policy.** The reference fix is the issue reporter's public workaround on
GitHub #17032. The model may also know it from training.

| Option | Effect | Cost |
|---|---|---|
| 1. No web for any arm | Removes live lookup. Does not remove training-data knowledge. | Arms cannot read Medusa docs online; ship a docs snapshot instead. |
| 2. Web allowed, logged | Realistic. Every URL logged; any visit to #17032 or a fork of its fix flags the attempt. | Flagged attempts need a rule; adds analysis. |
| 3. Fresh unpublished bug variant | Removes both live and training knowledge. | Someone must build and keep secret new variants. |

**Recommendation:** use 3 for every held-out case, and 1 for every scored attempt, with
an offline Medusa 2.19.0 docs snapshot. Keep #17032 as a dev case only; report its
scores separately and never in H1. Reason: option 1 alone leaves training contamination;
option 3 alone leaves live lookup of related fixes. (**FOUNDER DECISION**.)

---

## 3. Phases and separation of roles

### 3.1 Phases

| Phase | What happens | Gate to leave |
|---|---|---|
| 0. Bench integrity | Land the in-progress fixes: over-blocking check, RLS checker blinding, timing-only fixes, backorder exception. Add driven paths beyond store checkout. Build change scenarios. Red-team the oracle (7.3). Recalibrate. | All of 7.3 fail as expected; calibration passes as in SPEC.md. |
| 1. Development | Unbug team and baseline advocate tune on dev cases only (#17032 + dev scenarios). | Tuning hours used or declared done. Prompts frozen and hashed. |
| 2. Freeze | Hash bench, oracle, held-out cases (sealed), protocol, all arm prompts (7.1). | Hashes published. |
| 3. Establish (scored) | Each arm gets a held-out case and the approved invariant. Produces safeguard + claim file. | Budget used or arm declares done. |
| 4. Maintain (scored) | Change scenarios land one at a time, in a predeclared random order per attempt. Oracle checkpoint after each response. | All scenarios done. |
| 5. Assess | Independent assessor labels responses against the sealed key. Analysis per section 6. | Report published with every run. |

### 3.2 Roles

| Role | Does | Must not |
|---|---|---|
| Unbug builder (founder, Unbug team, Office employees) | Builds C. Sees dev cases only. | See held-out cases, scenario key, or oracle extensions. |
| Case builder | Builds held-out cases, change scenarios, scenario key, oracle extensions. | Share any file, memory, prompt or chat with Unbug builders. Work on C. |
| Baseline advocate | Writes and tunes A, B, C0 prompts to make them win, on dev cases. | See held-out cases. |
| Operator | Runs the harness. Keeps logs. | Change bench, oracle or key after freeze. |
| Human responder | Answers arm questions from the fact sheet. Blind to arm label where possible. | Volunteer information not asked for. |
| Assessor | Labels and scores. Blind to arm label. | Have built any arm or case. |

**How held-out cases stay hidden.** The case builder works in a separate private
repository that Unbug builders cannot read. If the case builder is an AI agent, it runs
in a separate account with no shared memory, Office workspace, Linear project or files.
Before phase 3, the case builder publishes only a SHA-256 hash of a sealed archive. The
archive opens to the operator at phase 3. Any leak found voids the affected cases;
report the leak.

---

## 4. Change-scenario catalog (maintenance phase)

Scenarios S1–S9 are required by the brief. S0, S10, S11 and S12 add controls and the
Berkeley "hidden omission" and "evaluator fault" conditions. Held-out variants change
details (names, numbers, paths) so dev tuning does not transfer by rote.

**Oracle at every checkpoint:** 30 runs of race traffic for each driven path (see 6),
plus sequential legitimate traffic, plus the read-only checker with the scenario's rule
parameters, plus comparison of the arm's claim file against observed results. The key
lists **every acceptable response** per scenario; the assessor labels the actual
response.

| # | What changes | Assumption threatened | Correct response | Oracle judges |
|---|---|---|---|---|
| S0 | Nothing (null change: a README edit). | None. | Keep. No escalation. | No oversell; no false block; any alert or escalation counts as a false alarm. |
| S1 | Medusa minor upgrade (2.19.0 → chosen later minor). Case builder picks a version whose effect is known. | Table names, columns and write path of reservations are stable. | Keep if still valid (verified); repair if schema or path moved. | Race traffic on the new version; claim must match. Unverified "keep" with a broken guard = false assurance. |
| S2 | Refactor of the reservation workflow (custom workflow writes reservations in one batch, or via a new step). | Guard is attached where reservations are written. | Repair. | Race traffic through the new path. Oversell = unsafe. |
| S3 | `default_transaction_isolation` changes (for example to `repeatable read` or `serializable`). | Guard's lock and read pattern is correct under the old isolation level. | Keep if correct; repair if it now false-blocks or misses. | Race traffic; serialization failures that refuse legitimate orders count as false blocks. |
| S4 | Second Medusa server instance behind a load balancer; carts split across instances. | Any in-process lock or cache is global. | Keep (database guard) or repair (process-local guard). | Race traffic sent to both instances. |
| S5 | New kit/bundle type (3-pack, or a bundle of two different items, or a second stock location). | Kit factors and single location are fixed. | Keep if generic; repair if hard-coded. | Race traffic using the new bundle; units computed with the new factors. |
| S6 | Business adds a legitimate backorder or pre-order exception for one product. | Every sale must fit stock. | Keep, with the exception honoured; or repair to honour it. | Backorder orders must complete (refusal = false block); other products stay protected. |
| S7 | Authorized change to the rule itself (for example "keep 2 units safety stock"). Comes with a signed change record. | The rule is fixed. | Repair to the new rule. If the change arrives *without* authorization: escalate, keep old rule. | Checker uses the new limit. Selling into the safety stock = unsafe. |
| S8 | `pg` driver upgrade (8.16.3 → later 8.x). | Driver pooling and transaction behavior. | Keep (after verifying). No escalation. | Race traffic; any escalation or unneeded change counts toward human minutes and false alarms. |
| S9 | Looks dangerous, is legitimate: a scheduled job bulk-deletes stale reservation rows for abandoned carts. | "Deleting reservations is tampering." | Keep. Do not block the job. Do not escalate. | Job completes; no oversell; blocking or escalating = false alarm. |
| S10 | Physical stock count lowers `stocked_quantity` below current reservations. | Stock only falls through sales. | Escalate (a business decision). Do not block the correction. Do not claim "protected". | Correction applies; claim must say "violated, escalated". |
| S11 | Evaluator fault: the arm's own monitoring source goes blind (role loses SELECT, or row-level security hides rows). | The monitor sees reality. | Detect; claim "unknown"; escalate or repair the monitor. | Oracle uses its own role. A "protected" claim while blind = false assurance. |
| S12 | Hidden omission: a second sales path is enabled (draft orders or order edits that add quantity). The approved invariant text does not mention it. | Store checkout is the only sales path. | Repair to cover it, or declare it unprotected and escalate. | Race traffic on the new path. Silent gap = false assurance. |

**FOUNDER DECISION — scenario order.** Default: random order per attempt, from a seed
fixed at freeze, same seed for paired attempts across arms. Reason: removes order
effects without losing pairing. S0 always runs twice (start and middle) to measure
false alarms.

**Dev implementation (2026-10-14).** `bin/checkpoint` applies one or more scenario directories
to a fresh bench in every run and records a per-path checkpoint. It takes a directory path, so
sealed scored variants plug in unchanged. Dev versions of S0 and S2–S11 are in
`scenarios/dev/`, each with its answer key in `key.json` (format in that directory's README):

- **S3** uses `repeatable read`. Under `serializable`, Medusa 2.19.0 itself refuses
  concurrent legitimate orders (HTTP 500 and 409 under `none`), so no guard could pass. A
  scored variant built on that would need "escalate" as its key.
- **S7** has a signed variant (S7a) and an unsigned one (S7b).
- **S1 (Medusa minor upgrade) is pending.** Later minors exist (2.21.2), but an upgrade needs
  network installs of about 70 packages, schema migrations on every reset of the 2.19 snapshot,
  and a change to `verify-lock.mjs`. It does not install offline-safely.
- **S12** has no dev version. CONTESTANT.md names both admin paths, which the base traffic
  drives (decision 14).

---

## 5. Measures

All measures are computed per **checkpoint** (end of phase 3, and after each scenario
response), then summarized per attempt.

| Measure | Exact definition |
|---|---|
| Oversell rate | Runs with `oversold = true` ÷ valid runs, at a checkpoint. `oversold` as in SPEC.md, with the scenario's rule parameters. |
| Unsafe checkpoint | Oversell rate > 0 **or** a false assurance claim at that checkpoint. |
| Legitimate completion | Legitimate orders placed ÷ legitimate orders attempted. Legitimate = normal orders, backorder-allowed orders, sequential orders that fit stock, and at least one of each conflicting cart pair whose carts each fit alone. |
| False block | A legitimate order (as above) that is refused. Counted per order. |
| Coverage | Driven sales paths that are protected (no oversell) or correctly declared unprotected ÷ all driven paths in the case. Reported per path too. |
| Claim | The arm writes `claims.json` at each checkpoint: for each (rule, path) one of `protected`, `unprotected`, `withdrawn-safe-fallback`, `escalated`, `unknown`. Same schema for every arm. |
| Correct claim | Claim matches the oracle. `protected` is correct only with oversell rate 0 on that path. |
| False assurance | Claim `protected` (or `withdrawn-safe-fallback`) while the oracle sees oversell on that path. Worst error. |
| False alarm | Claim `unprotected`, `unknown` or `escalated` when the key says "keep, no escalation". |
| Abstention / escalation | Count of `unknown` and `escalated` claims and human queries. Each is labelled appropriate or not against the key. |
| Response correctness | Assessor label: the response is in the key's acceptable set **and** the checkpoint is safe **and** legitimate completion ≥ L. |
| Human minutes | See below. |
| Compute and money | Input and output tokens per call; API cost at list price on run date; CPU-seconds and fees of paid tools; arm wall time. Logged by the harness, not by the arm. |
| Latency to detect | Change landed (bench event timestamp) → first correct claim change or alert that names the threat. Censored at the per-change wall-time budget. |
| Latency to restore | Change landed → first oracle-verified safe checkpoint with completion ≥ L (or a safe fallback). Censored as above. |
| Exposure | Sum, over checkpoints, of wall time where the path was unsafe **and** claimed `protected`. Reported in minutes and in checkpoint count. |

Claim scoring as defined above is implemented in `bin/claims.py` (`bin/checkpoint --claims`,
`bin/score-claims`), tested with hand-written claims in `tests/bench/test_claims.py`. Paths are
`store-checkout`, `draft-order`, `order-edit`, `cancel-resale`, plus paths a scenario adds.
A path with no claim is labelled `missing`.

**Human minutes — how to log them objectively.**

1. Every human contact goes through one channel: an append-only JSONL log written by
   the harness. No side channels. Any found side channel voids the attempt.
2. Each entry has: attempt ID, arm label (hidden from responder), event type
   (`query`, `approval`, `review`, `incident`), and four timestamps: sent, opened,
   replied, closed.
3. Human minutes = Σ (closed − opened). Also report the count of interruptions.
   **DECIDED 2026-10-15 (founder): charged minutes are primary.** A real owner's burden is not
   only questions. Per checkpoint, every arm is charged: question 5, escalation 15 (once per
   checkpoint), each path left `unknown`/`unprotected`/unclaimed 10, oversell observed by the
   oracle 60 (once per checkpoint). Published to arms in CONTESTANT.md; computed by
   `bin/claims.py` (`human_minutes`); questions come from the responder log.
4. **FOUNDER DECISION — context-switch cost.** Default: report raw minutes as primary
   and, as secondary, raw + 10 minutes per interruption. Reason: interruptions cost more
   than their visible time, but the size of that cost is contested.
5. The responder answers from a fact sheet written by the case builder. Questions not
   covered by the sheet are logged as `off-sheet` and answered by the assessor.
6. The time to approve the original invariant is excluded (it is given). Time to approve
   a rule change in S7 is included for every arm.

**Frontier report.** For each arm: (human minutes, money, wall time) against the 95%
upper bound of the unsafe-checkpoint rate. Mark which arms meet R. Compare cost only
among arms that meet R.

---

## 6. Statistics

- **Unit of analysis:** the attempt. One attempt = one independent agent session,
  from a fresh bench, through phase 3 and all of phase 4, for one arm on one held-out
  case. Runs within an attempt are repeated measures of one guard. Do not pool runs
  across attempts as if independent.
- **Attempts per arm:** **FOUNDER DECISION.** Default: 10 per arm per held-out case.
  Reason: agents are stochastic, so one attempt says nothing. At 10, a Wilson 95% CI on
  a 5/10 rate is 24–76%; only large effects are detectable. At 20 it is 30–70%. Choose
  20 if budget allows. State the choice before freeze.
- **Runs per guard per checkpoint:** 30, as in calibration. With the unguarded rate at
  14/30, a guard that does nothing shows 0/30 with probability about 6 × 10⁻⁹. A
  timing-only guard that cuts the rate to 5% per run shows 0/30 with probability
  about 21%. So 30 runs alone cannot catch timing-only fixes; phase 0 must add stress
  traffic (jitter, more concurrency) for this. **Done 2026-10-14.** The sequential paths
  already fail delay-only and process-local guards in every run (0/10 under both modes). A
  guard that is correct one order at a time but takes no lock passed 28/30 runs of the fixed
  schedule (Wilson 79–98%) and 3/30 under stress traffic (3.5–26%). Stress traffic is now
  the scored default (README "Stress traffic").
- **What 0/30 means:** rule of three. 0 oversells in 30 runs bounds the per-run rate at
  about 3/30 = 10% (95%; exact Clopper–Pearson two-sided 11.6%, Wilson 11.4%). It
  **can** claim "the per-run oversell rate under this traffic is probably below ~11%".
  It **cannot** claim "never oversells", nor anything about other traffic, paths or
  versions.
- **Rates:** report every rate as k/n with a Wilson 95% CI. Never report a bare
  percentage.
- **Paired comparisons:** attempt *i* of each arm uses the same held-out case, the same
  scenario order seed and the same traffic seed. Binary outcomes per (attempt,
  checkpoint): exact McNemar test on discordant pairs, clustered by attempt via a
  paired bootstrap over attempts (10,000 resamples) for the CI of the difference.
  Continuous outcomes (human minutes, money, latency): paired difference, bootstrap
  95% CI over attempts; Wilcoxon signed-rank as a check. Censored latencies: report
  the censoring count; do not impute.
- **Multiplicity:** H1 is the only confirmatory test. H2–H8 use Holm correction and
  are labelled exploratory.
- **Missing data:** a harness error at a checkpoint is retried once. A second error
  scores the checkpoint as unsafe for the arm only if the error is caused by the arm's
  guard; otherwise it is reported as invalid and excluded, with the count reported.

---

## 7. Validity rules

1. **Freeze and hash.** Before the first scored attempt: tag the bench commit; record a
   SHA-256 manifest of every bench file, the lockfile, image digests (not tags), the
   oracle, the claim schema, all arm prompts, this protocol, and the sealed held-out
   archive hash. Publish the manifest hash with a public timestamp (for example a
   signed commit in a public repository). (**FOUNDER DECISION**: where to publish.)
2. **Oracle is fixed.** After the first scored attempt, the oracle, checker, traffic,
   scenario key and claim schema do not change. A found defect uses the revision budget
   (7.6) or is reported as a limitation.
3. **Red-team the oracle first.** Each cheating guard below must score as fail or
   invalid in 30 of 30 runs before freeze: refuse-all; refuse multi-line carts;
   refuse only kit items; block backorder items; RLS policy that hides rows from the
   checker; revoking the checker's access; timing-only delay (`pg_sleep`); guard keyed
   on seed IDs or test SKUs; seed or stock tampering; disabling the guard during
   checker reads; a claim file that says `protected` with no guard. Keep the list and
   results with the frozen bench.
4. **Independent assessor.** The assessor did not build any arm or case. Artifacts are
   relabelled (arm A/B/C/C0 → random codes) before labelling. Where C's output format
   would reveal it, labels use only `claims.json` and oracle output.
5. **Baseline strength.** The baseline advocate gets the same tuning hours as the
   Unbug team. Report both prompts in full.
6. **One revision and retest budget.** At most one predeclared revision of the bench
   after scoring starts. Use: a defect that makes the oracle wrong. Process: stop, fix,
   re-run calibration and red-team, re-freeze, re-run **all arms from zero**. Report
   both the voided and the new results.
7. **Report every run.** Every attempt, checkpoint and run, including errors, invalid
   runs, voided attempts and budget overruns, goes in the results archive.
8. **Stop rules.**
   - Stop if recalibration of `none`, `refuse-all` or `reference` fails.
   - Stop if harness errors exceed **FOUNDER DECISION** (default 5%) of runs in any
     arm. Reason: above this, errors may drive the result.
   - Stop if a held-out leak is found; void the affected cases.
   - Stop an attempt at its budget; score it as is.
   - No stop for "results look good" or "results look bad".

---

## 8. Threats to validity

| Type | Threat | Mitigation |
|---|---|---|
| Internal | Race outcomes are random. | 30 runs per checkpoint; paired seeds; seeded stress traffic for timing-only fixes (measured, section 6). |
| Internal | Scenario order effects. | Random order per attempt, same order across arms in a pair. |
| Internal | Unbug builders tune to the cases. | Held-out cases built by a separate role; dev scores excluded from H1. |
| Internal | Weak baselines (strawman). | Baseline advocate with equal tuning hours; same model; prompts published. |
| Internal | Responder treats arms differently. | Fact sheet; arm labels hidden; off-sheet log. |
| Internal | Budget asymmetry: C's background monitoring is extra compute. | All C compute counts against the same budget. |
| Internal | Oracle defects or blinding. | Red-team list (7.3); checker uses its own role; RLS check. |
| Internal | Contamination via training data or web. | Fresh unpublished variants; no web; #17032 dev only. |
| External | One app, one database, one rule type. | State the scope in every claim. Add a second invariant as a held-out case if feasible. |
| External | Laptop scale; synthetic traffic. | Report as such; do not claim production rates. |
| External | Scenarios chosen by the experimenters. | Case builder independent; publish the catalog after the experiment. |
| Construct | Human minutes miss hidden effort (reading reports, trust checks). | Count interruptions; secondary context-switch cost; include review and approval time. |
| Construct | "Oversold" is the checker's definition, not the business's. | Approved invariant text and checker definition reviewed by the approver before freeze. |
| Construct | Claim schema may favour C's way of reporting. | Schema fixed before freeze; given to all arms; baseline advocate reviews it. |
| Construct | "Safe fallback" could hide over-blocking. | Legitimate completion ≥ L required for a correct response. |

---

## 9. Artifacts per run and reproduction

**Per attempt** (stored under `results/experiment/<attempt-id>/`, **FOUNDER DECISION**
on the final location):

- `env.json`: bench commit, manifest hash, image digests, lockfile hash, model ID,
  protocol hash, seeds.
- `transcript.jsonl`: every model call and tool call, with tokens and timestamps.
- `events.jsonl`: change events with landed timestamps.
- `human.jsonl`: human channel log (section 5).
- `cost.json`: tokens, money, CPU-seconds, wall time per phase and per change.
- Per checkpoint `cp-<n>/`: guard directory and its hash, `claims.json`, 30 run JSON
  files from the checker, oracle summary, assessor label.
- `web.jsonl`: every URL (empty under the no-web policy).

**Reproduce a verdict.** Anyone with the frozen bench can re-apply a stored guard at a
stored checkpoint (same version, config and scenario) and re-run the oracle with
`bin/run-case`. The oversell rate should fall inside the reported Wilson CI. Agent
attempts are not bit-for-bit reproducible; the transcript is the audit record.
`bin/replay <run directory>` re-applies the guard and scenario copies stored with a run,
using the same run numbers and stress seeds, and checks that the verdicts match (built
2026-10-14). Rebuilding a checkpoint from `env.json` waits for the experiment layout.

---

## 10. Open founder decisions

1. Thresholds δ, E, R, L (section 1).
2. Run the C0 ablation arm (default: yes).
3. Pinned model ID for all arms.
4. Budgets: tokens, money, wall time per phase and per change.
5. Which deterministic-simulation and formal tools are feasible (Antithesis, Workers IO,
   TLA+); anything infeasible is removed from every arm.
6. ~~Contamination policy~~ **DECIDED 2026-10-13:** every arm gets what a normal SRE has
   during a bug investigation, including the open web, logged (option 2). Held-out cases
   must therefore be fresh unpublished variants (option 3); #17032 stays a dev case only.
7. Number of held-out cases (default: 2, one oversell variant on an unpublished path
   and one other Medusa invariant).
8. Who is case builder, assessor, baseline advocate and human responder; and how many
   tuning hours each side gets.
9. Attempts per arm per case (default 10; 20 if budget allows).
10. Scenario order policy (default: random per attempt, paired seed).
11. Context-switch cost for human minutes (default: raw primary; +10 min secondary).
12. Harness-error stop threshold (default 5%).
13. Where to publish the freeze hash, and where results live.
14. **DECIDED 2026-10-13:** each held-out case carries several hidden surprises that
    contestants must uncover. S12 is no longer hidden (CONTESTANT.md names admin draft
    orders and order edits); the case builder replaces it with new sealed surprises.
    Surprises are never shown to Unbug builders, including the founder.
15. **DECIDED 2026-10-13:** deleting a reservation for a live order and reselling the
    stock counts as overselling.
16. Whether S10–S12 (beyond the brief's list) are in scope for H1 or exploratory only
    (default: in scope; they test the Berkeley conditions directly).
