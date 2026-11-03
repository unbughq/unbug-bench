# Goldfish review: Item 8 offline preparation, design round 1

**Verdict: NOT PASS.** I found 1 blocker, 4 majors and 5 nits.

I did not edit, run tests, call models or do anything live. I worked read-only in `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c` at 566c201, reviewing the diff `c3ee6d9..566c201`. That diff touches two files and `git diff --check` is clean. Mode: REVIEW, using the `zoom_out`, `design_critic` and `implementation_readiness` personas and the Heilmeier and implementation-readiness standards. I read it as a preparation and gap inventory, not as an executable plan.

## What checks out

- **Authority:** `batch-practice-manifest.md:109–117` matches the stated USD 100 within subscription limits, with OpenRouter on existing credit only and no top-ups. The amendment does not claim live permission.
- **Arithmetic:**
  - Alpha 10+10+5+15 = 40.
  - Beta 15+10+25 = 50.
  - Slots 3+2+1+2+4+2+6 = 20. The run table has 20 rows, and the 1a–6f labels add up the same way.
  - Worker caps are 0.40 × slots. The scenario totals sum to 98, plus 2 shared = 100.
  - Rj is shared per root, a fresh child starts at S=0, and there is no waste refund and no regrant on release changes (lines 62–88, 188–192).
- **Stale-status corrections:**
  - `token_prices.py:101–106` has the 5.5 profiles at $50/$10/$15 and the 4.5 compact/small profiles at $3/$5.
  - `model_router.py:47–49`: `route_maximum` covers only Claude profiles and OpenRouter, so Codex has no maximum.
  - The shared paid-spend gate matches `router-shared-paid-spend.md:8–9` (lifetime ceiling ≤ $11.63).
  - In the Murphy register, outer-wall-1/2 are closed and new-isolation-settlement-1 is open.
  - Practice report lines 85 and 116–117 back the RAM acknowledgement and the TLS deployment. Lines 70/89 show distinct accounts as "unverified (founder accepted)" and account-2 attribution as unproven.
- **Artifact paths:** these exist in producers:
  - `extension_evaluator.py:341` (`comparison-runs/N/<identity>`)
  - `extension_package.py:637–644` (`pair-attempts.json`, `pair-crash.json`)
  - `retain_diagnostic`
  - `stress_progress.py:54,91` (`round-N-categories/<digest>`, `*-partial-*`)
  - `extension_public_match.py:41,61,202`
  - `extension_package.py:334`
  - `runtime_revision`, which lives in `bin/run_validity.py:48–56`, not in `factory/`
  - the gate-cache, diagnosis and `job-money` files

  `subsequent_entry` really is the only producer of the current comparison (`extension_package.py:590`), and `propose()` writes nothing durable. So Q2 followed by a G4 change does force a fresh comparison in 6e.
- **Journal semantics in 6e/6f:** the retry key is `{identity(ext id, case hashes, versions), runtime_revision}` (`run_validity.py:66`). A hashed plumbing fix in 6f therefore resets the attempt allowance while keeping the same identity directory and committed records. That matches what lines 211–215 claim.
- **Murphy rows:** the current-comparison row is open, and the checklist appears in both docs. No row closes.
- **Ancestry:** b75c9b4 is an ancestor of c3ee6d9.

## Blocker

**B1. The 10- and 15-minute execution windows are already known to be too short for scenarios 4 and 6, and the plan's own rule then blocks admission. No gap records this.** (Amendment lines 229–238; `stream-d.md:3628–3650`; runs 7, 8 and 15–20.)

- **Evidence from local code:**
  - `run.py:3183` sets `calibrator_minutes` to 30, with the comment "strong tries took ~20 min".
  - `gate_state.py:157` pins `pilot_tries=3` and `calibrator_minutes=30` as science.
  - `stream-d.md:3856` records 144.4 G10 minutes out of 148.1 gate minutes historically.
  - `extensions.stages()` includes every gate in `GATES`, G10 among them, so an extension's gate run can reach G10.
- **Scenario 4** needs two G10 attempts that end with the cap `stop_reason`, plus G16/G17, all inside 10 minutes and without shortening the cap. That cannot happen unless the intended cap is a call or zero-token cap. The plan does not say which cap it means.
- **Scenario 6** must fit all of this into 15 minutes and one $12.50 root:
  - X1 diagnosis, writer, stress and the gate run;
  - X2 diagnosis;
  - the comparison, which includes stress;
  - Y diagnosis;
  - the 6f comparison resume;
  - and the 6b child's work, because the window is "shared across ALL slots".

  6a's single worker is also capped at a 2-hour lifetime against a historical 148-minute gate run.
- **No sub-allocation:** nothing stops a child (5c, 6b, 7b), which runs to its terminal stop, from using up the shared window before the root's later slots.
- Line 235 says runtimes that cannot fit "block admission and require a revised plan". So by the plan's own rule, runs 7, 8 and 15–20 cannot be admitted, yet the document presents the 70-minute, 8-hour and 2-hour figures as if they hold.
- **Fix (documentation only):**
  1. Add a gap O9: re-derive the windows and the worker lifetime from the pinned G10/G16/G17/writer caps and the measured serial G10 overhead, with a per-slot split of each window between root and child.
  2. Say which cap scenario 4's "capped" means.
  3. State that the current 8-hour total is known to be insufficient, and that revising it needs a fresh review (and founder sign-off on the deadline, if that is a founder parameter).

  No implementation is needed.

## Majors

**M1. The Q1 trigger and the 6a/6c boundary are not defined.** (Lines 181–183, 201–210; O6 at line 255.)

- 6a's X1 is also "a durable close_to_passing decision before entry". A Q1 written as "pause after durable decision before entry" would fire in 6a, which contradicts "diagnosis and first extension MUST fit 6a's worker".
- After extension N finishes, nothing says what stops 6a before the X2 dispatch. Diagnosis runs in-worker for X1, so the same loop would go straight on to X2.
- **Fix:** in O6, define the Q1 predicate. For example: the release manifest binds it to the scenario-6 root job, it fires only when the history holds at least one completed extension, and it is armed only on 6c. Also name the stop that ends 6a after N: either collection of N's exhausted generation ending that worker's assignment (cite the B path), or an explicit Q0 hook added to O6. Both must work without per-case rulings.

**M2. The order of 5b and 5c conflicts with replacement priority.** (Lines 176–178.)

- `batch_service.ordered_queue` (`batch_service.py:299–302`) ranks settlement first, then replacement, then resume. ENGINEERING §3 and `stream-d.md` both say "queued immediately at higher admission priority".
- On beta-fixed, ordinary ordering would run the carried child (5c) before the original's factory-bug resume (5b).
- **Fix:** either put the child first, or state the reviewed B later-batch admission rule that sets the order. Do not leave it to the manifest author.

**M3. The rule for whether scenario 6's money "fits" is not stated, and the amendment adds two paid diagnoses to the same $12.50.** (Lines 79–88; O2 at line 250.)

- X1, X2 and Y are Anthropic diagnoses (`stream-d.md` role map). Their reservations alone come to $9–15 at $3–5 each.
- On top of that come the writer, stress, the reviewer gates and G10/G16/G17. G10/G16/G17 have no enforced OpenAI maximum, and `max_cost=5` is pinned in the gate science settings.
- Admission is checked per call, so 6a can spend most of Rj and then refuse X2 or Y. The chain would end unproved after real money is spent.
- O2's phrase "worksheet ... within the unchanged caps" does not say whether the critical-path total or each next call must fit.
- **Fix:** before 6a, require that the summed honest maxima of every planned paid call through 6f fit $12.50. If not, state that the scenario is infeasible before launch, or explicitly accept late stranding with a stop rule.

**M4. Run 4 (2a) drops one of the two stress timeouts.** `stream-d.md` scenario 2 and line 3605 require both timeouts on the first worker: one after a retained category, and one that expires before any category answer. Run 4 lists only "after a committed category and before another category answer". The table claims to be the exact order. **Fix:** list both observations in 2a.

## Nits

- **N1. Scientific edit surface.** G4's version covers MEASURE plus `bin/run_validity.py` (`gate_state.py:24–29`). Those files are shared with G5, G6, G7, G10, G11 and G13–G17, and `run_validity.py` is also hashed into `runtime_revision`. State that:
  - the 6e change must be limited to G4-only runner source;
  - the 6f fix must touch only `runtime_revision`-hashed files outside `STAGE_DEPENDENCIES`, `runner_inputs`, `model_science` and the prompts;
  - both version vectors are computed offline and compared before the manifest is reviewed.
- **N2. 6d evidence.** Entry selection in 6d is not durable: `propose()` is pure, and `pending_call` is the first durable write. Name what 6d retains as proof: the current pair was valid with no new `comparison-runs` directory, plus the Q2 hook record.
- **N3. Idempotence replay.** Package replay idempotence for the old live cross-worker slot is now offline only (lines 201–204). Say in "Exams" that live cross-worker package restore is unexercised.
- **N4. Stale draft pin.** `docs/practice/b3/item8-draft.json` pins `stream-d.md` sha 89ad3f…, which already differed at c3ee6d9 and differs again now (a0b57c…). `preflight.py:94` would report drift. A0 should explicitly supersede this pin. No test reads it.
- **N5. Heilmeier gaps.** Impact ("who cares") is only implied. The O1–O8 sizes have no total or critical-path estimate. Add one line for each.

## Persona notes

- **Zoom out:** the amendment simplifies. It reuses existing producers, the `runtime_revision` journal and `PauseRequested`, and adds no new ledger or launch path. The scenario-6 packing is complicated, but each slot traces to a row-closure requirement.
- **Design critic:** apart from B1 and M1–M3, the risks are listed honestly. Prices, balances, route feasibility and candidate availability are all marked as preflight unknowns, not stated as facts.
- **Implementation readiness:** the gaps are sized and have owners. The decisions still left open are the B1 windows, the M1 trigger and stop, the M2 ordering and the M3 fit criterion.

## Elephant disposition

Accept B1, M1–M4 and N1–N5; reject nothing. Add O9 and explicitly invalidate the old 70-minute/8-hour/2-hour timing assumptions. Scenario 4 means real unchanged 30-minute per-attempt time_limit; O9 must derive all 20 per-slot root/child deadlines and billing bounds and obtain reviewed/founder-approved live deadline changes without increasing $100. O2 now requires the full honest invocation-maxima critical-path SUM before launch; current scenario 6 is explicitly infeasible for admission, not a late-stranding experiment. Both distinct stress timeout observations are named.

Define exact Q predicates, source bindings and durable Q evidence; Q1 becomes observation-only in combined diagnosis/plumbing slot 6c and Q2 pauses after valid unchanged entry selection before reservation. Main's existing extension_incomplete -> finalizer -> seal/DONE is the 6a boundary. The same code trace also exposed the need for distinct fault and diagnosis workers in scenarios 5/6: repack their existing slots, move idempotence claims to offline replay, add no workers/money. All READY replacements precede original resumes; scenario 5 additionally requires a reviewed O3 release-readiness guard (child queued immediately but cannot run under the fault release; diagnosis-only restore there). Without it the four-slot packing is explicitly infeasible, not an operator priority exception.

Constrain scientific edits to G4-only runner source and hashed plumbing outside science inputs, verify vectors offline, retain actual selected-pair/Q2/inventory proof, state live active-package restore is unexercised, explicitly supersede the stale non-launchable item8-draft source pin, and add impact/13–22 owner-day/8–10 working-day critical-path estimates. These are planning estimates, not execution authorization. No code, flag, provider query, model experiment, worker, policy or deadline is changed. Fresh final design review required; max two rounds remains.
