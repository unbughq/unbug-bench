# unbug-bench v2 — Experiment brief

**Status:** Draft for review, 16 October 2026
**Audience:** Everyone building the case factory, harness, judge, scoring, and contestant arms
**Replaces:** The case design and factory rules used in Pilot report 1 (15 October 2026)

---

## How to read this brief

This is a draft, and it is meant to be argued with. Every change below states what the pilot did, why that failed, what we propose instead, and why we think the proposal fixes the problem. If you think a reason is wrong, a fix doesn't fix what it claims to, or a fix creates a new problem, say so. Section 9 lists the assumptions we are least sure of, but challenges to anything in this document are welcome. Nothing here is frozen until the pre-registration step in Section 8.

One rule applies while you read and build: this brief describes **categories** of cases, never concrete bugs. Specific bugs, services, and scenarios must come from the case factory, and must never be seen by the founder or anyone working on Unbug. If you find yourself designing a specific scenario outside the factory, stop and route it through the factory instead.

---

## 1. The question

Can software own a business promise — build its protection, notice threats to it, and keep, repair, withdraw, or escalate — with **less human time** than a strong team using today's AI agents, while staying **just as safe**?

We test this on one promise in a real open-source shop (Medusa 2.19.0): *never sell more stock than exists.*

The hypothesis and margins are unchanged from the pilot:

- **Safety:** Unbug's rate of unsafe checkpoints is at most the strong baseline's (B) plus 5 percentage points.
- **Human time:** Unbug needs at least 30% fewer charged human minutes than B.

What changes is the exam, so that the hypothesis can actually be tested.

---

## 2. What the pilot showed

Once a grading error was corrected, every contestant kept the shop safe at every step, made no false claims, and asked no human anything. In round 2, every contestant found and repaired a protection switch-off hidden inside an innocent-looking change. Unbug v0.1 used roughly 1.7–2.9× the model usage of plain Claude Code and took longer.

The pilot could not test the hypothesis. Every contestant used zero human minutes, so there was nothing to reduce. The safety interval was −49 to +49 points against a 5-point margin.

The pilot's own conclusion was that announced changes do not separate today's agents. This brief takes that conclusion further: **the cases tested the part of the problem current agents already handle, and left out the parts where Unbug is supposed to help.**

---

## 3. Why the previous design failed

| Problem | What happened in the pilot | Consequence |
|---|---|---|
| The rules were fully specified | The promise stated every edge case; the fact sheet covered the rest | No contestant ever needed a human, so the human-time endpoint was structurally zero |
| One fix solved everything | A single database rule protected every sales path, including ones added later | Step 3 passed contestants who never noticed the new path; "keep" was a winning answer |
| Every change was announced | Each change arrived with a diff, a deploy log, and an instruction to check it | Only the "check this change" skill was tested, which current agents already do well |
| Changes landed before anyone could act | `bin/land` applied each change to the live shop before the contestant saw it | Prevention (blocking a bad change) was never possible, so it was never tested |
| Luck and care scored the same | Unbug rebuilt its checks when monitoring went blind; another contestant's checker happened to keep working | Identical scores; Unbug's evidence discipline was invisible |
| The factory had no check for whether a case could separate contestants | Gates G1–G12 check freshness, realism, fairness, and cheat-resistance only | The factory would have reproduced the pilot's flaw in every sealed case |
| Difficulty was calibrated on a weaker model | G10 uses DeepSeek V4 Pro as the honest student | A case DeepSeek finds hard may be easy for the actual contestants |
| The cheater looked for the wrong cheats | It tried block-everything and fake claims | The cheat that actually worked — fix once, then always answer "keep" — was never tried |
| Too few tries | One try per contestant per round | No result could be statistically meaningful |

---

## 4. Changes to the cases

Each scored case must contain every ingredient below, plus a mix of ordinary announced changes, including harmless ones, so crying wolf is still penalized.

### 4.1 Rules that can only be learned by asking

- **Previously:** The promise and fact sheet answered every question in advance.
- **Why it failed:** With nothing unknown, no contestant had a reason to involve a human. The human-time endpoint measured a quantity that was zero by construction, and the hypothesis could not be tested.
- **Change:** Each case includes at least one decision that is not in the promise and can only be learned by asking the shop owner, who answers from the fact sheet. Acting on a wrong guess counts as harm (see 6.1).
- **Why this fixes it:** Real promises are incomplete; much of the human cost in practice is making unmade decisions. A contestant that asks the right question pays a small, fixed cost; one that guesses wrong causes harm; one that asks about everything pays a lot. Human minutes now vary between contestants, so a 30% difference becomes measurable, and Unbug's claim to ask efficiently can win or lose.
- **Still could go wrong:** The asking cost (5 minutes) may be too cheap to separate careful from indiscriminate askers. See Section 9.

### 4.2 More than one service changes inventory

- **Previously:** Everything that sold stock wrote to the same database tables.
- **Why it failed:** A single constraint at that one chokepoint protected every path, including paths added later, so contestants were rewarded for a fix they didn't understand.
- **Change:** Each case includes at least one additional service that also changes inventory, with its own storage or interface, so no single database rule protects everything.
- **Why this fixes it:** The promise now spans components, which is the end-to-end property the hypothesis is about. A contestant has to map every writer and protect the promise across them. A one-place fix no longer covers later steps by accident.
- **Still could go wrong:** Adding a service increases harness complexity and judge surface. The judge must count oversells across all writers, not just the shop database.

### 4.3 Failures that arrive with no announcement

- **Previously:** Every change came with a diff, a deploy log, and an instruction.
- **Why it failed:** Being told "a change landed, check it" is the task current agents already solve. The capability Unbug v0.2's watcher exists for — noticing that protection broke when nobody said so — was never tested.
- **Change:** Each case includes at least one failure injected between steps with no change record and no instruction: for example, drift in configuration, a dependency, permissions, or another service's behavior. Per-change contestants are not called for it. The window stays open for a fixed time while shopping traffic continues.
- **Why this fixes it:** This is the decisive test of the hypothesis. A contestant that only acts when called cannot respond; one that keeps watching can. Exposure time (6.2) measures the difference directly.
- **Still could go wrong:** This gives a structural advantage to contestants with a watcher. That is intended — it is the product claim — but it means a win here shows the value of watching, not of Unbug's other features. Report it separately (Section 7).

### 4.4 A chance to block a bad change before it goes live

- **Previously:** Changes were applied to the live shop before the contestant saw them.
- **Why it failed:** Contestants could only repair after the fact. Prevention, the more valuable half of the design, could not be observed.
- **Change:** At least one step presents a change as *pending*. The contestant may approve, block, or escalate it before it lands. Approving a harmful change lets it land and harm is scored; blocking a harmless change is a false alarm.
- **Why this fixes it:** It separates "stops harm" from "cleans up after harm," which have very different costs in real systems, and it lets the exam reward prevention.
- **Still could go wrong:** Contestants may learn to block everything pending. Pending harmless changes and the false-alarm charge must make that strategy lose.

### 4.5 Checks go blind while protection also fails

- **Previously:** In the step where monitoring went blind, protection either held or was announced as broken.
- **Why it failed:** A contestant that checked properly and a contestant whose checker happened to keep working got the same score. The exam could not tell evidence from luck.
- **Change:** At least one step blinds every observation route a contestant can use and, in the same window, breaks protection on some path. A claim of "protected" without fresh, working evidence is then false assurance.
- **Why this fixes it:** Being right for the wrong reason now loses. Contestants that notice their evidence went blind and say "unknown," or rebuild their checks, are distinguished from ones that keep reporting old results.
- **Still could go wrong:** If blinding is too obvious, every contestant notices it and the step stops separating them. The factory should vary how it happens.

---

## 5. Changes to the case factory

### 5.1 Four model families, with rotating roles

The factory scales to four families:

| Family | Model and setting |
|---|---|
| Anthropic | Claude Opus 5.5, high effort |
| OpenAI | GPT 6.1 Sol, high effort |
| Mimi | Mimi v2.6 Pro |
| Meta | Muse Spark 1.3, max or xhigh depending on availability |

For each case, the four roles below go to four **different** families, rotating so each family writes an equal number of cases:

- **Writer:** builds the case, answer key, reference fix, and fact sheet
- **Cheater:** attacks the case (see 5.4)
- **Calibrator:** takes the case as a strong honest student (see 5.5)
- **Reviewer:** checks fairness and realism (a second reviewer from outside the four, such as the current Grok or Qwen, is optional)

Pin and record the exact model version and effort level for every role on every case. If Muse Spark's effort level differs between cases because of availability, record which; do not switch mid-case.

- **Previously:** No model family that sits the exam was allowed to help build it. Contestants are Claude and GPT, so the factory used neither.
- **Why it changes:** Stronger writers likely produce harder, more realistic cases, and four families give us enough writers to rotate roles and measure bias instead of only avoiding it.
- **Why this is acceptable:** The primary endpoint compares contestants **on the same model** (Unbug on Claude vs B on Claude; Unbug on GPT vs plain GPT, see 7). If a Claude-written case is biased toward or against Claude, it affects both Claude arms, so the bias largely cancels within the comparison. Balancing writers across families lets us test directly whether contestants do better on cases written by their own family.
- **Residual risk, and the safeguard:** Bias need not hit both arms equally. A case written by a contestant's own family may be "natural" to that model, leaving less room for any method to help. We pre-register a **sensitivity analysis**: report the primary endpoint on all cases and again excluding cases written by the contestant's own family. If the two disagree, we say so.
- **Information walls:** Factory transcripts are shredded as before. A Claude or GPT session in the factory shares no memory with contestant sessions; the walls protect against people and tools on the Unbug side seeing case content, and those walls are unchanged.

### 5.2 Updated case recipe

- **Previously:** A short, precise promise followed by announced changes, with bugs drawn mostly from race conditions that one database rule can fix.
- **Why it failed:** The recipe itself produced cases with every flaw in Section 3. Running the factory as-is would seal five more cases that cannot test the hypothesis.
- **Change:** The writer's instructions require every ingredient in Section 4, and require bug sources beyond single-table races.
- **Why this fixes it:** The factory is the right mechanism; it was given the wrong blueprint. Fixing the recipe fixes every case it produces.

### 5.3 New structural gates

Two gates are added before sealing. Neither depends on how any contestant performs.

- **G13, frozen first fix:** Take the reference fix from the first step, freeze it, and run it against every later step. If it passes all of them, the later steps test nothing, and the case is rejected.
- **G14, ingredients present:** Verify mechanically and by review that each ingredient in Section 4 is present and works as intended (for example, that the unannounced failure really breaks protection, and that the unstated rule really changes the correct behavior).

- **Previously:** Gates checked fairness, realism, freshness, and cheat-resistance, but not whether a case could separate contestants.
- **Why it failed:** A case can be perfectly fair and still useless if a single early fix carries it to the end. That is exactly what happened at step 3.
- **Why this fixes it:** G13 directly detects the pilot's failure mode. G14 guarantees the case exercises what the hypothesis is about.
- **Rejected alternative:** We considered sealing only cases where the strong baseline (B) struggles. We rejected it because selecting cases on B's failure rigs the comparison in Unbug's favor. Gates must test the case, never a contestant's result.

### 5.4 The cheater tries lazy strategies

- **Previously:** The cheater tried to pass by blocking everything or faking claims.
- **Why it failed:** The strategy that actually passed in the pilot — build one good fix, then answer "keep" forever — was never tried, and nor was claiming protection without checking.
- **Change:** In addition to its current attacks, the cheater must try at least: fix once and always answer "keep"; claim "protected" without fresh evidence; ask the human about everything; block every pending change. Each must fail the case. Any that passes gets the case fixed, as today.
- **Why this fixes it:** These are the cheap strategies a strong agent might drift into. If they pass, the case rewards laziness, and we find out before sealing rather than after scoring.

### 5.5 Difficulty calibrated on a strong model

- **Previously:** G10 used DeepSeek V4 Pro as the honest student and dropped cases it solved 0 or 10 times out of 10.
- **Why it failed:** DeepSeek is not what sits the exam. A case it solves 3 times in 10 may be trivial for Opus 5.5 or GPT 6.1 Sol.
- **Change:** The calibrator role (5.1) is a strong model from a family that did not write the case, taking it blind as a different Unix user, as before. DeepSeek may remain as an additional blind check.
- **Why this fixes it:** Difficulty is now measured near the contestants' level. The calibrator's results are used only to check that a case is solvable but not trivial, never to select cases on a specific contestant's performance.

### 5.6 Fairness includes "discoverable by asking"

- **Previously:** G8 required everything needed to be stated or discoverable.
- **Why it would fail now:** Cases with deliberately unstated rules (4.1) would look unfair to reviewers and be rejected.
- **Change:** Information available by asking the shop owner, and present in the fact sheet, counts as discoverable. Reviewers check that every unstated rule can be found that way.
- **Why this fixes it:** It keeps the fairness standard while allowing the cases the hypothesis needs.

---

## 6. Changes to scoring

The existing measures stay: oversell, at least 95% of fitting orders succeeding, confirmed orders staying confirmed, and claims versus reality. Human-minute charges stay as decided on 15 October.

### 6.1 Wrong guesses count as harm

- **Proposed:** Acting on an unstated rule in a way the fact sheet rejects is scored as harm at that checkpoint: unsafe, charged 60 minutes, like an oversell.
- **Why:** Without this, guessing is free and asking is charged, so the scoring would reward guessing.

### 6.2 Exposure time

- **Proposed:** During unannounced-failure windows, the judge probes the live shop at fixed intervals and records how long each path was unsafe, and how long it was unsafe while claimed protected.
- **Why:** The pilot's judge only checked after each step, so it could not measure how quickly a failure was caught. For unannounced failures, speed is the whole point.

### 6.3 Prevention vs repair

- **Proposed:** For pending changes, record whether harm was blocked, escalated, or allowed to land and repaired afterward.
- **Why:** Blocking and repairing have very different real costs, and the pilot could not see the difference.

---

## 7. Contestants and endpoints

### 7.1 Contestants

| Arm | Model | What it is |
|---|---|---|
| A | Claude Opus 5.5 | Plain Claude Code |
| B | Claude Opus 5.5 | Claude Code with testing tools; strong baseline |
| C | Claude Opus 5.5 | Unbug v0.2 with the watcher |
| C0 | Claude Opus 5.5 | One-shot Unbug, **paired** with C's own first session |
| G | GPT 6.1 Sol | Plain Codex |
| **G-U (new)** | GPT 6.1 Sol | Unbug running on Codex |

- **New arm, Unbug on GPT.** Previously, Unbug ran only on Claude, so we could not tell whether its results came from its method or from Claude. Adding G-U gives a two-by-two grid — method × model. If Unbug helps on both models, it is the method; if only on one, that is important product information. It also gives a second same-model comparison that is protected from writer bias (5.1).
- **C0 pairing.** The pilot's one-shot arm ran its own first session instead of continuing from C's (deviation D4). The comparison only isolates the value of ongoing ownership if both start from the same first session. This needs environment cloning mid-try.
- Fairness rules are unchanged: same budgets, tools, responder, fact sheet, and web policy within each model family; the baseline advocate gets the same tuning time and information as the Unbug builder.

### 7.2 Endpoints

- **Primary (unchanged hypothesis, same-model):** C vs B on safety (at most 5 points worse) and human minutes (at least 30% fewer). Decision rules as pre-registered in the pilot protocol.
- **Secondary:**
  - G-U vs G (Unbug's method on a second model)
  - C vs C0 (value of ongoing ownership)
  - Exposure time during unannounced failures
  - False assurance when checks go blind
  - Prevention vs repair on pending changes
  - Results on unannounced-failure steps reported separately from announced steps
- **Sensitivity:** Primary endpoint excluding cases written by the contestant's own model family; writer-family × contestant-family interaction.

### 7.3 Size and statistics

- **Cases:** 8 sealed cases, 2 written by each factory family, so writer bias can be checked.
- **Tries:** 5 per contestant per case.
- **Judge:** 30 runs per step under heavy traffic.
- **Analysis:** Checkpoints within a try are not independent. Use intervals that account for clustering by case and try (for example, a cluster bootstrap), with the Newcombe interval reported for comparison.
- **No extra runs after seeing results.**

---

## 8. Order of work

1. **Review this brief.** Challenge it; resolve or record disagreements.
2. **Update and freeze the protocol and case recipe**, including the cast changes in 5.1 and 7.1, which alter rules the original protocol fixed. This must happen before any scored run.
3. **Build harness support** (Section 10 lists dependencies).
4. **Build one new practice case** with every ingredient and pilot it, to check that the case and harness work, not to score anyone. Confirm G13 and G14 behave as intended.
5. **Run the factory** to build and seal 8 cases.
6. **Outside review of the judge** before the freeze, by an engineer or a panel of non-Claude models, since much of the judge was written with Claude.
7. **Run the scored exam.**
8. **Apply the stop rule** (below).

**Stop rule (proposed, to be adopted at step 2):** If Unbug on Claude is not clearly better than B on the cases built around its supposed strengths — incomplete intent, cross-service promises, unannounced failures — we rethink the product, not the exam.

---

## 9. Assumptions we want challenged

- **That human minutes are the right primary measure.** If strong agents need almost no human time even on harder cases, a 30% reduction may still be meaningless. Should exposure time or false assurance be primary instead?
- **That the asking cost is right.** At 5 minutes per question and 60 per harm, does the scoring reward the right balance between asking and guessing?
- **That writer bias cancels within same-model pairs.** We argue it largely does. Is that true for the kinds of bias a writer is likely to introduce?
- **That four writer families and 8 cases are enough** to detect writer bias. They are enough to detect a large bias, probably not a small one.
- **That unannounced failures are fair to per-change contestants.** They cannot respond by design. Is it right to include them in the primary endpoint, or only in a separate one?
- **That one promise generalizes.** Everything here tests one invariant in one shop. What would make a result transferable?
- **That the pending-change step is realistic.** Real teams review changes before merging; does our version reflect how that works, or does it give either side an unrealistic advantage?
- **That the factory's grading and the judge are correct.** The pilot's biggest error was in our own answer key. What else might we be getting wrong?
- **That 5 tries per case is enough**, given clustering.
- **That the information walls still hold** with Claude and GPT in the factory.

---

## 10. Engineering dependencies

These need building or verifying before the new practice case can run:

- Injecting a failure between steps with no change record — implemented with a private Harbor step that skips agent invocation ([verification](harbor/medusa-oversell-v2/VERIFICATION.md)).
- A background watcher that survives between steps in Harbor — verified on Harbor 0.24.0 with the same PID/UUID across ordinary sessions and an unannounced window ([probe](harbor/probes/unannounced-withdraw/VERIFICATION.md)).
- Live judge probes during failure windows, for exposure time — implemented and verified on the public 120-second window, with read-only administrator observations ([verification](harbor/medusa-oversell-v2/VERIFICATION.md)).
- A pending-change step: approve, block, or escalate before landing
- Additional services that write inventory, and a judge that counts oversells across all of them
- Cloning a live environment mid-try, for C0 pairing
- Unbug's runtime running on Codex, for G-U
- Four-family factory orchestration with role rotation and per-role version pinning

---

## 11. Unchanged

- The shop, promise, and claim formats (`guard/db.sql`, `guard/app.patch`, `claims.json`)
- Harbor and boat infrastructure
- Sealing with age encryption, fingerprints, and shredding
- The information walls: nobody on the Unbug side sees sealed cases, answer keys, or judge internals
- Human-minute charges as decided on 15 October
- The original hypothesis, margins, and decision rules

---

*Please add comments directly on any section, or reply with the section number and your challenge.*
