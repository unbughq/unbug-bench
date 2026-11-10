# Case factory

> **DRAFT for founder review. Not in force.** Decisions marked **FOUNDER DECISION**.

The factory builds the **scored (sealed) cases**. Unbug builders must never see their
contents. Unbug builders include the founder, the Office employees, **and the Claude
sessions that help build Unbug**. The founder designs the factory and sees only scorecards
and fingerprints. The gate order is adapted from Shipd Olympus: cheapest checks first,
and no money is spent on a later gate while an earlier one is failing.

## 1. What one case contains

| Part | What it is |
|---|---|
| App + pin | Repository, exact commit, lockfile, Docker image digest |
| Promise | The plain-language rule a business owner would approve (like CONTESTANT.md) |
| Bug | A way the app breaks the promise today. Fresh: no public issue, PR, fix or discussion |
| Reference fix | Proof that the case is solvable through the guard interface |
| Traffic + judge extensions | How the bench drives the bug and decides "broken" |
| Change scenarios | Scored variants of the PROTOCOL.md catalog (names, numbers and paths changed) |
| Surprises | 2–4 per case (case count: **8 cases, 2 per writer family**, V2.md). Each is stated in the promise or **discoverable** from the app, repo, running system or an owner answer in the fact sheet. Never a hidden requirement |
| Answer key | Every acceptable response per checkpoint (keep / repair / withdraw safely / escalate), plus the expected claims |
| Fact sheet | What the human responder may answer. The founder sees it only after the freeze |
| Provenance | The real-world bug report(s) the pattern is based on, with links |

## 2. Where bugs come from

**DECIDED 2026-10-14: a mix of all three.** Every case records its source; results are
reported per source, and synthetic cases count only in secondary analysis. Options:

1. **Port a real pattern.** Take a bug pattern that real shops reported (in Medusa, Saleor,
   Vendure, Spree, Magento, Shopify forums…) and find or adapt it in the pinned app.
   *Recommended:* realism comes from evidence, freshness from the new instance.
2. **Hunt real unreported bugs** in the pinned app for other promises (refunds ≤ amount
   paid, promotion usage limits, gift-card balance ≥ 0…). This is the most realistic
   option, but the yield is uncertain. Report the bugs to the maintainers after the experiment.
3. **Plant synthetic bugs** (mutation-style). This is cheap and unlimited, but the
   realism is weakest. Use it for dev cases only.

## 3. Roles (all separate from Unbug builders)

| Role | Model family | Does |
|---|---|---|
| Writer (builder) | Rotating Anthropic, OpenAI, Xiaomi, Meta | Builds all case parts |
| Stress-tester (attacker) | A second family | Tries wrong fixes and lazy strategies |
| Strong calibrator | Anthropic (Claude subscription) or OpenAI (Codex subscription); never the writer family | Never solving marks the case **hard** (kept, reported as its own group; founder 2026-10-18). One early try right after G5 labels the case `likely_hard` or `solvable` hours before G10; a label only, never a rejection (`--no-early-probe` skips it) |
| Reviewer | The remaining fourth family; optional outside-family second reviewer | Fairness and realism; every reviewer must approve |
| Easy calibrator | GLM 5.3 Flash (OpenRouter or OpenCode Go) | Rejects only if it solves every try |
| Outside SRE (human) | — | Audits before freeze and after unsealing; holds the key if possible |

V2.md supersedes the former ban on contestant families in the factory. Four distinct
families fill writer, stress-tester, strong calibrator and reviewer. `factory/rotation.json`
balances eight cases, two written by each family. Exact model IDs and efforts are recorded
per role on the scorecard; explicit role flags override a slot and still must satisfy family
separation. Claude and GPT run only through their subscription CLIs. No automatic fallback.
Information walls and sealed transcripts remain unchanged. Report the primary same-model
comparison both with all cases and excluding that contestant's writer family (BRIEF-v2 7).

## 4. Gates

**FOUNDER-APPROVED DECISION 2026-10-16:** the factory only screens cases. Its defaults
are `--rounds 1` (one builder/attacker round, plus a final builder fix/precheck pass when
needed), `--pilot-tries 3`, and `--runs 10` per G4–G7 checkpoint. Flags can raise each.
The **scored exam still uses 30 judge runs**; this does not change exam scoring.
G1 runs after every builder pass; failed prechecks go to the next builder prompt and skip
that round's attacker. Failure after the final fix stops before later gates.

**FOUNDER-APPROVED DECISION 2026-10-24:** the economic stopping rule supersedes
fixed writer/stress-tester rounds: default `--case-budget 50` USD at model list price
for the whole case, including writer, stress tester, reviewers, calibrators and every
other role, after which further pursuit of correctness is economically unfeasible.
Before a new round, its remaining budget must cover at least $8 or the highest
observed writer-plus-stress round cost, whichever is greater. Otherwise perform the
final fix while budget remains and stop `budget_exhausted`, stress review unresolved.
`--rounds 8` remains a high safety cap; unchanged repairs still stop. An in-flight
role finishes; spending beyond the ceiling stops at the next role boundary with a
checkpoint. **Gate strictness and verdicts are unchanged; gates alone certify quality.**
Explicitly raising a stopped case's budget and/or rounds permits checkpoint recovery
with cumulative spending and the latest stress findings retained; it never passes a gate.

**FOUNDER DECISION 2026-11-10:** a case is attacked at most twice (`ATTACK_ROUNDS`,
`factory/durable/engine.py`). A stress round covers all four categories before it reports,
so the writer gets every finding in one list; a finding ends its own category, never the
round. The findings of the first round are fixed and the case is attacked once more. The
findings of the second round get one final writer fix, whose own checks replay every saved
cheat, and the case then goes to the gates whatever round, extension or writer-round count
it has reached. A gate repair after that is not attacked again. This restores the 16 October
path (builder, attacker, final fix, gates): since the durable rebuild a case reached the
gates only after a clean stress round, which 0 of 26 finished rounds were, so no fresh case
was ever gated. A case that began under the older rule keeps its recorded rounds and is
governed by the cap from the step it continues at. Gate strictness is unchanged.

The pre-approved continuation ceilings are `--max-role-calls 250`, `--max-total-calls 700`
and `--max-cost 5` (observed priced OpenCode events). Sized from case 2 (2026-10-15): its
writer used 176 calls in round 1 alone and three rounds used about 490; one round plus the
fix pass, panel and the legacy three pilot tries was estimated at about 520; v2 uses six calibrator tries. Raise flags deliberately for larger runs. Subscription usage is
recorded separately, not billed against that observed-cost ceiling.
A model call stops after 15 minutes without output (`--no-progress-minutes`, environment
`FACTORY_NO_PROGRESS_MINUTES`), provider limits/refusals, or 3 consecutive zero-token
responses (`--max-zero-tokens`). Persistent rate limits mean two notices without token
progress. Stops kill the model process group, checkpoint work, write a resumable scorecard
and `~/sealed/DONE`, and never wait for authorization. Resume retains cumulative usage;
exhausted cost/total-call ceilings need higher explicit flags, not a reset.

| Gate | Passes when | Tooling |
|---|---|---|
| G1 Prechecks | All parts present; promise ≤ 300 words; no leak words; patches apply | `factory/run.py` G1 (structural checks verified by dry run on the practice fixture, 2026-10-14; content-count checks unchecked) |
| G2 Freshness / scope | Web + GitHub search finds no issue, PR, fix or discussion for the bug; the bug fits how the app is really used. Since 2026-10-20 (founder) a searcher's flagged hit fails only once the case's reviewer confirms it is this bug, in this app, at a version that still applies; the provenance pattern and other apps do not count; an unclear verdict keeps the hit | to build (agent + logged searches) |
| G3 Build | Image builds offline-reproducibly; `bin/setup` works on fresh volumes | `factory/run.py` G3 → `bin/setup` on fresh volumes (verified by dry run on the practice fixture, 2026-10-14; offline build unchecked) |
| G4 Bug is real | Plain app breaks the promise under bench traffic, at a measured rate | `factory/run.py` G4 → `bin/checkpoint` with `guards/none` (verified by dry run on the practice fixture, 2026-10-14) |
| G5 Solvable, no over-blocking | Reference fix passes all factory screening runs (10 by default); legitimate sales succeed | `factory/run.py` G5 → `bin/checkpoint` (reference + every scenario key) (verified by dry run on the practice fixture, 2026-10-14) |
| G16 Judge breadth | A different-family tester writes an independent fix from the statement and promise; a rejected fix needs an independent, valid review distinguishing an incorrect fix from a case defect | `factory/fairness.py`; immediately after G5; findings stay encrypted; live qualification pending |
| G17 Zero-solve diagnosis | After G10, every failed strong attempt must be explained; missing information or a narrow judge goes back to the writer, and an invalid review blocks certification | `factory/fairness.py`; only an all-`wrong_fix` verdict earns the `hard` label; live qualification pending |
| G6 Cheats fail | Block-everything + all generic cheating probes + case-specific cheats fail | `factory/run.py` G6 → `bin/checkpoint` per cheat + `bin/verify-negative` (verified by dry run on the practice fixture, 2026-10-14) |
| G7 Flakiness | Repeat G4–G6 with a new seed on another day; same verdicts | `factory/run.py` G7 (new seed, same VM and day; verified by dry run on the practice fixture, 2026-10-14) |
| G8 Fairness | Panel: every surprise and judge check is stated or discoverable; nothing grades wording | to build (checklist + panel) |
| G9 Realism | Panel: provenance is real and the case resembles it | to build (checklist + panel) |
| G10 Two testers | Easy GLM solves fewer than all tries (zero allowed); strong solving zero tries marks the case hard, not rejected | Isolated Unix user, fresh workspace/state per attempt |
| G11 Fake pass | Every calibrator pass survives the fake-pass check. Since 2026-10-19 the static rules follow CONTESTANT.md: a pinned `search_path`, per-function settings, `GRANT EXECUTE` on a guard function, and in app patches conditional SQL writes and delays (backoff) are review notes, not failures; behaviour (data and stock diffs, catalog changes, 5 fresh-seed stress re-runs) still decides (an independent review judged 3/3 such flags false positives); the scorecard lists the rules that fired | `factory/run.py` G11 → `bin/fake-pass-check` + case re-run (verified by dry run on the practice fixture, 2026-10-14, reference as stand-in pass) |
| G13 Frozen first fix | Frozen establish reference is unsafe or wrong at a later step | `bin/strategy`, after G5 |
| G14 Ingredients | Wrong guesses falsify intent checks; one-place fails the second writer; harmful/harmless pending approval behaves as keyed; blind monitors coincide with failed previous protection | Structure in G1, checkpoint checks after G13 |
| G15 Lazy strategies | Each of claim-without-evidence, ask-everything and block-all-pending is unsafe, wrong, or costs at least 30% more minutes than safe/correct honest-reference | `bin/strategy`, after G14 |
| G12 Seal | Encrypted archive + SHA-256; scorecard published to the founder | `factory/run.py` G12 (`age`, shred; verified by dry run on the practice fixture, 2026-10-14 with a throwaway key) |

Execution order: G1, G2, G3, G4, G5, G8, G9, G6, G13, G14, G15, G7, G10, G11, then G12. G8–G9 (review) also run in the writing phase once the stress tester is satisfied, so complaints go back to the writer in the same run (founder 2026-10-18: 2 of the first 3 cases failed fairness after ~9 h of checks).
G13–G15 depend on scripted strategies, never contestant performance. All gate results and
failed_detail are recorded on the scorecard using structural counts, not case content.
Strategies that ask for the very same bench execution (same scenario and guard bytes, report, runs,
seed) share one execution inside a runner process and are scored separately; no run count or pass
rule changes (`bin/strategy` `execute_shared`).

**Not copied from Olympus:** "the strongest models must fail" (that would skew results
against our contestants' model) and "deterministic tests only" (our bugs depend on timing
and ordering, so we use repeated runs and statistics instead).

## 5. What the founder sees

One scorecard per case, for example:

```
case-2  sha256:9f1c…  gates G1–G15 passed  reviewers 2/2 approve
plain app broke the promise 9/10   reference fix 10/10   cheats 0/24 passed
calibrators: strong solved 3/3; easy solved 1/3 (pinned models and efforts in JSON)
surprises: 3   scenarios: 11   provenance: 2 real reports
```

The scorecard does not show the promise text, the app area, the bug or the surprises.

Calibration diagnostics (2026-10-18) add fixed-label counts only: time/call limits,
no fix submitted, a fix failing some/all judged runs, and execution errors. Stop
and outcome are separate: a timed-out attempt can still leave a successful fix.
Unavailable historical facts are marked unrecorded. Interrupted provider/process
calls remain interruptions rather than new scored failures. These labels do not
change gates, budgets, case selection or exam scores; see `factory/README.md`.
Both the baseline and Unbug sit the same cases. A case is not evidence for Unbug
merely because calibration finds it hard.

## 6. Sealing

**DECIDED 2026-10-14: option 1 on a Hetzner server** in its own project, separate from
the founder's other infrastructure. Options, from strongest to weakest:

1. Builder runs on a separate machine or cloud account. The encrypted archive key is
   held by the outside SRE.
2. A separate macOS user account on this Mac, with an encrypted archive and the key held
   off-machine. Agent transcripts stay in that account.
3. A separate directory plus delegated agents in T3. *Weak:* the child-thread transcripts
   are readable in the app, and results return to the delegating session.

Whichever option is chosen, the factory's reports to the founder (and to any Claude
session that helps build Unbug) carry only the scorecard and the hash.

## 7. Void rules (fixed before scoring)

A case is removed **for every contestant equally** if any of these hold after unsealing:

- the outside reviewer (or panel, if there is none) finds a surprise or judge check that
  was not stated or discoverable, including by a fact-sheet answer from the owner;
- the answer key is wrong for a response that some contestant gave;
- the bug or its fix was published before the run;
- any leak to an Unbug builder is found.

Voided cases are reported with their reasons. Cases are never voided because of who won.

## 8. Rotation

A case is spoiled once it is published or used in a public report. Build fresh cases for
every round; retired cases become dev cases.

## 9. V2 case contract

Every scored case includes unstated rules learnable only by asking, a second
inventory writer with independent storage/interface, harmful and harmless pending changes,
a blind step while prior protection fails, and an unannounced failure with a fixed live window.
Bug sources must extend beyond single-table races. The promise still permits legitimate sales.

case.json contains ingredients with unstated_rules [{id, scenario, intent_check,
fact_sheet_anchor}], second_writer {service, path}, pending {harmful: [ids], harmless: [ids]},
blind [ids], and unannounced [ids] (at least one). Ship guards/wrong-guess/<rule id>/ and guards/one-place/.
Intent checks grade shop behaviour under traffic, never a transcript. The fact sheet anchors
must answer every unstated rule; reviewers verify discoverability and all monitoring routes.
Pending scenario/key fields and scoring are exactly V2.md section 3. No pending patch, SQL
or hooks land when blocked. Harmful approval is tested under the preceding reference.

Harbor defines the case step order; case.json steps (scenario IDs) is the fallback.
answer-key.json entries can name a complete case-relative reference_guard and needed_questions
(count); references persist between steps. Defaults: guards/reference, then public practice
examples/repaired when applicable, and one needed question per newly introduced unstated rule.
See factory/README.md and builder.md for deterministic script conventions.

Phase 2 requires `delivery: unannounced` and `window: {duration_sec, interval_sec}`
with finite positive seconds and interval no larger than duration. Categories include
configuration drift, dependency failure, permission changes, and another service changing
behaviour. The factory chooses specifics. No change record, instruction, workdir upload,
or per-change agent call is permitted. Every arm may leave background watchers running.
Use the Harbor 0.24 wrapper in `harbor/phase2/run.py`; a judge-only `window.json` in the
step directory declares the injection, normal API traffic, database probes and answer key.
Keep the step's required `instruction.md` empty. This descriptor never enters the box.
G14 requires each failure to cause harm under the preceding reference guard and checks
that the injection is absent from contestant-visible material. Reviewers also inspect
the built box and logs for indirect advance hints. Probes read real database state as
administrator, never monitor logins, and never submit probe orders or reset the live shop.
Report sampled unsafe seconds and unsafe-while-claimed-protected seconds per path, with
unknown probe time and interval resolution. These measure observed unsafe state; a safe
sample is not a proof that protection would survive an untried order. Silent windows
count in the primary endpoint and are also reported separately. Human-minute prices stay
unchanged. A missing/slow probe invalidates the window rather than implying safety.

Live exposure readers are private judge code. Each independent service must have
a frozen live reader returning the existing orders/units/canceled adapter shape,
using administrator read-only database transactions rather than monitor APIs or
caches. The host-only descriptor may carry `reader_source` defining
`async def read(reader, name)`; the read_sql/sqlite transport is documented in
`harbor/phase2/README.md`. G14 also runs a no-watcher live control under the prior
reference and requires exposure to observe its broken paths while claims remain
protected. A reader that silently reports safety cannot pass that control.
