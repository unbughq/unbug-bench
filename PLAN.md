# Action plan

**Last updated:** 2026-10-14
**Goal:** test the smallest Unbug loop against strong baselines on one promise ("never sell
more stock than exists") in a real app (Medusa 2.19.0), with results we can trust.

Three tracks run in parallel, then everything is locked and run. Track 3 is the critical
path: nothing is scored until the sealed cases exist and the Unbug loop is built.

## Done

- [x] Judge hardened against blinding (hidden rows, fake table, changed operators, deleted orders)
- [x] Wrong fixes fail: block-everything, timing-only, order-only, checkout-only, reservation-sum-only (20 cheating probes)
- [x] Sales paths covered: store checkout, admin draft orders, admin order edits, cancel-then-resell, deleted reservations
- [x] Calibration: plain Medusa oversells 30/30, block-everything passes 0/30, reference fix passes 30/30, 0 errors, 0 invalid (rerun 2026-10-14 after the judge fixes: same result)
- [x] Memory checked: 941 MiB peak against the 3,456 MiB cap

## Track 1 — Finish the exam (Claude)

- [x] Check the judge against a plain reference version of the promise on thousands of random fake shop states (5,000 states, `tests/live/judge/`; 0 disagreements after the 4 fixes below)
- [x] Build the change scenarios (the maintenance test; catalog in PROTOCOL.md): 12 of 12 dev scenarios (S0, S2–S11) match their answer key, 3 runs each, 0 errors; S1 (Medusa upgrade) still pending
- [x] Heavier traffic: more buyers at once, random delays, so timing-only fixes cannot pass by luck: a fix with no lock passes 28/30 normal runs but 2/30 heavy runs; the reference fix still passes 30/30
- [x] Fake-pass check: review every passing contestant fix for tricks, not just the known cheats: reference fix clean, 2 of 2 cheating fixes flagged
- [x] Replay command: re-run any stored fix and get the same verdict: 6 of 6 replayed runs gave the same verdict

## Track 1b — Run on Harbor (after the bench agent finishes)

- [x] Port the practice case into a Harbor multi-step task: on boat, the reference fix scores reward 1 on all 4 steps (3/3 runs each, 0 errors, escalates when the monitor goes blind); plain Medusa scores 0 and unsafe on all 4; one 4-step try takes 17–19 min. Rerun on the fixed judge with changes landing in the box: reward 1 on all 4 steps (23.5 min); plain Medusa unsafe on all 4
- [x] Changes land in the contestant's running app (`bin/land`) with light background customers (`bin/shoppers`); monitor login `arm_monitor` documented for every contestant; reporting rules in CONTESTANT.md for every contestant
- [x] Ask-the-human channel: canned responder tested inside Harbor with both oracle and actual Codex; cumulative sidecar log collected, configured 5 min/question. Live/model answerer remains untested.
- [x] Web-visit logging: HTTPS paths, sanitized metadata, opaque model API TLS, bypass regressions, sidecar artifacts; actual Medusa install/build/setup/reset works through proxy (`harbor/webproxy/`)
- [x] Monitor survives nonfinal step/verifier boundary: same process identity in oracle and actual two-session Codex probes; final teardown stops it (`harbor/smoke-lifecycle/`, `harbor/codex/`)
- [x] GPT/Codex contestant adapter: Harbor 0.24.0, Codex 0.162.1 / gpt-6.1-sol, subscription auth; simple and combined infrastructure smokes passed. No Claude or full contestant practice run started.
- [x] Where to run: boat.dev works (full VMs, Docker native; bench unchanged 10/10 and 10/10; new copy from a snapshot in 4 s). Daytona dropped for now (fallback only)
- [x] Boat vs Hetzner for scored runs: boat. The no-lock fix under heavy traffic (what we score with) passed 1/30 on each of two boat machines and 1/30 on the Mac. Under normal traffic the two boat machines disagreed (21/30 vs 30/30), so score only with heavy traffic and run each contestant's paired tries on the same machine
- [x] boat $20 plan active (2026-10-14): 100 machines, no 2-hour cap, 555 h/month. Renews 2026-11-14: cancel in the billing portal after the experiment
- [x] Boat default 4 vCPU/8 GB stress recalibration: plain app oversold 30/30, refuse-all passed 0/30 (normal orders 0/30), reference passed 30/30; zero errors/invalid across90runs. All core hashes match local source. Evidence: results/infrastructure/2026-10-14-boat-calibration/. Recalibrate again if scoring runtime or judge changes.

## Track 2 — Case factory (founder designs, agents run)

- [x] Draft the case factory, gates adapted from Shipd Olympus (FACTORY.md, draft)
- [ ] Founder reviews the gate checklists (fair, discoverable, not leaked, not trivial)
- [ ] Sealed builder (a different model family from Unbug's, separate workspace) builds 5 scored cases with 2–4 hidden surprises each
- [ ] Founder sees scorecards and fingerprints only, never the contents

Rules carried over from Olympus: cheapest checks first; no existing public fix; fail before / pass after;
flakiness check; every test or surprise must be stated or discoverable; grade behaviour, not wording;
fake-pass review; any edit or model change makes old results stale.
Rules **not** carried over: "top models must fail" (it would skew results against our own
contestants' model; use a different-model pilot and drop only 0% or 100% cases); "deterministic tests
only" (our bugs depend on timing and ordering; use repeated runs and statistics instead).

## Track 3 — Smallest Unbug loop (founder, clean-room session)

Build on the practice case (#17032) only.

- [ ] Promise → exact checks, plus a few sharp questions to the human about exceptions
- [ ] Map of every path that writes stock or orders, kept up to date
- [ ] Its own monitor of real outcomes that knows when it is blind
- [ ] Change reviewer: on every change, keep / repair / withdraw safely / escalate
- [ ] Honest report (`claims.json`): "unknown" allowed, "protected" only with evidence
- [ ] Small question budget (human minutes are half the score)

## People (founder)

- [ ] Find one outside SRE for a few paid hours: review before lock, audit after unsealing
- [ ] Fallback if none: a panel of AI reviewers from 2–3 different companies; label results "not externally reviewed"
- [ ] Baseline advocate (an agent, not the founder) tunes contestants A and B

## Decisions

Decided 2026-10-13:
- [x] Deleting a live order's reservation and reselling counts as overselling
- [x] Contestants get normal SRE resources, including the open web (logged); scored cases must be unpublished bugs
- [x] Each scored case carries several hidden surprises; the founder never sees them
- [x] Unbug keeps its direction; this exam defines what the smallest loop must do

Decided 2026-10-14:
- [x] Bug sources: a mix of real-pattern ports, hunted real bugs and planted bugs (planted bugs count only in secondary results)
- [x] Builders: OpenAI + Meta Muse Spark 1.3; reviewers from two other families; pilot not on Claude
- [x] 2026-10-15 (founder): Claude and GPT run only on the Claude and ChatGPT subscriptions (Claude Code, Codex), never through OpenCode or OpenRouter. Writers: GPT 6.1 Sol (Codex) and Muse; cheater (attacker): Claude Opus 5.5 (Claude Code), so a case Claude cannot cheat is one the Claude contestants cannot cheat either. Claude does not write cases (shared blind spots with every main contestant). Reviewers and pilot stay on Go.
- [x] 2026-10-15: the first case out of the factory (ported bug, Muse writer) failed the basic precheck (G1) after 3 rounds with the attacker still objecting; unusable. The factory now shows the writer the precheck result every round and puts the failed structural checks on the scorecard
- [x] Sealing: a Hetzner server in its own project; encrypted archive
- [x] 5 scored cases to start
- [x] 2026-10-16 (founder): real bugs the factory finds (`port`, `hunt`) are reported upstream after the exam. Each such case carries a sealed `disclosure.md` (G1 requires it); after scoring, the founder decrypts them and files issues for any bug Medusa has not fixed. Secrecy is only for exam freshness.
- [x] 2026-10-16 (founder): two difficulty testers (v2 brief, fix 1). A strong tester (Claude or GPT) may only reject a case it never solves (fairness at contestant level); a weak non-contestant tester (GLM 5.3 Flash, replacing DeepSeek V4 Pro) rejects a case it solves every time (too easy). Easy cases are never rejected on a contestant family's results.
- [x] 2026-10-16 (founder): v2 adopted for building ([BRIEF-v2.md](BRIEF-v2.md), contract in [V2.md](V2.md)), with five fixes: two difficulty testers; watching parity for every arm (phase 2); extra questions cost more and ask-everything must lose; wrong guesses scored from shop behaviour only; power calculated before scoring. Built in three phases; the 5-case v1 factory run is cancelled.
- [x] 2026-10-17 (founder): this round is a **measurement round**, labelled so before it starts: a non-pass reads "not enough data to tell", not "Unbug failed". 24 cases, rule C (one-sided 95%, original thresholds), the strict 5-point safety margin; 3 tries per case if the budget allows, otherwise 2 with a third try on a subset chosen before scoring. No interim look (it saves under one case on average; `analysis/README.md` round three). Cases are built in batches to catch factory problems early. Supersedes "5 scored cases to start".
- [x] 2026-10-17 (founder): the exam is fixed before any of this: every brief/reviewer must-fix in place (unstated rules, second inventory writer, unannounced failures with watching parity, pending changes, blind checks, wrong guesses visible in the shop, steeper question costs, non-contestant difficulty tester, frozen-first-fix gate).
- [x] 2026-10-17 (founder): report more than pass/fail: saving and safety difference with intervals; try-to-try consistency as a disagreement rate with kappa; variance between tries vs between cases (sizes the next round).
- [x] 2026-10-17 (founder): before any decisive round, estimate the cost of 72-192 cases; if out of reach, plan a narrower claim now. Freeze rules, sizes, analysis, interpretation and the next-round sizing rule before scoring.
- [x] 2026-10-17 (founder): compute on Hetzner cx33 (scored exam: cx33 only, one machine type per round); boat only as a premium fallback for non-scored work.

**pre-registered rerun rule (2026-10-17):** A trial with a Claude subscription meter status of `rejected` or an HTTP 429 from `api.anthropic.com` is an infrastructure failure, never a score. After the reported subscription reset, rerun the whole trial with the same sealed case, arm, try number and pinned Claude account. Allow at most two reruns after the original attempt; a third usage-limit failure is recorded as missing, with all attempts retained. Running trials are never paused or killed for pacing.

- [x] Judge follows the promise exactly: more reservations than stock (with nobody owed too much) is a warning, not a failure

Judge fixes (applied 2026-10-14; judge test 0 disagreements, all 19 cheating probes still fail, recalibrated):
- [x] Split "too many reservations" into a warning field
- [x] Clamp negative owed units to 0
- [x] Skip custom order lines with no product (stops the crash)
- [x] Judge every product, not only the 7 the traffic uses
- [x] An AI stand-in answers contestants' questions from the fact sheet, with a fixed minute cost per question; the founder answers one case for real to check the stand-in
- [x] Budget: subscriptions (Codex, Claude) plus banked resets; cheap Hetzner cloud servers; about $400–750 total. Pin CLI and model versions, and record list-price cost anyway

Open (defaults in PROTOCOL.md):
- [ ] Pass thresholds (default: at most 5 points less safe than the strong baseline, at least 30% less human time, at least 95% of legitimate sales succeed)
- [ ] Pinned model, token / money / time budgets
- [ ] Pilot on the practice case to measure allowance per try: approved 2026-10-15, one try each for A, C0 (fresh, not paired) and GPT on boat; Unbug v1 run by the founder
- [x] Tries per contestant per case: 5 for the first scored round, topped up to 10 once allowance per try is measured (decided 2026-10-15)
- [ ] Run "Unbug one-shot" (default yes)
- [x] B's advanced tools: fast-check 4.10.2 (property-based) and Stryker 10.0.0 (mutation), in every box at /opt/tools, named only in B's prompt (`contestants/arm_b.py`); Unbug may use them (decided 2026-10-15)
- [ ] Human SRE + AI contestant: deferred to a later round (known limit of this round)

## Lock and run

- [ ] Outside reviewer tries to cheat the exam, and reviews the case recipe and scoring, not just the judge (2026-10-17, founder: the exam was designed with Unbug's strengths in mind)
- [x] Fingerprint/archive tooling with source, directory/mode, archive and runtime-image drift checks (`bin/freeze`, `harbor/FREEZE.md`); local snapshot is not a binding experiment lock
- [ ] Fingerprint everything; founder reviews the commit
- [ ] Run all contestants
- [ ] Unseal, audit (void rules written before scoring), report with error ranges
