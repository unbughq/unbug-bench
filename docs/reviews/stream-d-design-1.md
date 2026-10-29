# Goldfish review, round 1: Stream D design (`docs/designs/stream-d.md`)

**Mode:** REVIEW, read-only.
**Personas:** zoom_out, design_critic and implementation_readiness.
**Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md` and `zoom-out-standard.md`.
**Scope read:** `docs/designs/stream-d.md`, `docs/designs/extensions.md`, `docs/designs/stream-d-cost-evidence.json`, and the `docs/factory-single-path.md` diff (2 lines). I also read the code they reference:
- `factory/run.py`
- `factory/gate_state.py`
- `factory/gate_pipeline.py`
- `factory/late_recovery.py`
- `factory/budget.py`
- `factory/admission.py`
- `factory/rotation.json`
- `factory/model_runtime.py`

I also read `docs/ENGINEERING.md` §3 and the Murphy rows 8, 9, 10, 11, 12, 13, 15, 21, 35 and 39.

## Verdict: NOT PASS

Two blocking findings are open. Most of the design is sound, and the blockers are fixable in the document.

## Answer to the specific question: deleting the $15 allowance

**Is it honest about the evidence gap? Yes, with one overstatement.** I checked it against the JSON.
- The only identified writer receipt above $15 is `builder-1` in 873d7f, at $15.053. It is round 1, not an extension.
- The later rounds are $0.74 (`builder-8`) and $4.33 (`builder-10`). Writer cost alone would fit in $15.
- No card records a G16/G17 pass (verified), and only 3 of 54 VM cards show G10 passes with no attributable rerun cost.
- Paid stress cost cannot be known, because attacker events are recorded at $0 on a then-free route.

The conclusion is correct: the evidence cannot price a writer + stress + G10/G16/G17 package. Deleting a number that has no source is right. The exception is the word "disproves" (Finding M1).

**Does it preserve bounded automation? Not yet.** The design now relies on one control, the cumulative batch money/deadline bound, and does not own, specify or locate it in code (Finding B1). I found no batch-wide money enforcement in `factory/*.py`. The only batch-level reference is a design doc (the manifest "total spend cap" in `factory-single-path.md`). The money bound exists only per case, as `limit_usd` 70 on the cards.

Per-case exposure after the deletion is bounded only by the batch. As my own arithmetic, not evidence: five extensions at $15–33 for the writer alone is about $75–165 per case before stress and gates. The founder should size the batch bound knowing that.

## Blockers

### B1. The batch money bound is the sole extension control, but it is unowned and unspecified
- **Severity:** Blocker.
- **Scope:** "Proposed section 3 amendment"; "Resume, accounting and checkpoints" (atomic reservation); "Cost evidence" last paragraph; Main risks.
- **Finding:**
  - The design says "Reserve money atomically before every call" and "the batch manifest supplies the sole authorized cumulative model dollar bound". It does not say where that bound is enforced.
  - Cases run in parallel across workers and VMs. An atomic reservation therefore needs a shared ledger that spans workers, but the design names none.
  - The code has an existing seam. `factory/admission.py:64` ("missing or stale shared admission reservation") and the `awaiting_shared_reservation` state in `run.py` already provide a cross-worker reservation. The design does not say to reuse it.
  - The design says deadline too, but never defines it. The existing options are the key-holder deadline (`key_holder.py:384`) and the coordinator's `--deadline` (the original collection deadline).
  - The cards also show a `limit_usd` of 70, while the exhaustion trigger is "$50". The design does not say which constant governs once the case exits ordinary work.
- **Fix:** Add one subsection to the design containing:
  - the owner of the shared batch ledger (reuse `admission.py` reservations);
  - a statement that extension, diagnosis and replacement dispatch fails closed when the manifest has no money bound or the reservation is missing or stale;
  - the definition of "deadline";
  - how the per-case `limit_usd` behaves after diagnosis (disabled for extensions, but still accumulating spend).

### B2. Imported unknown usage freezes the whole batch, which contradicts Murphy 21 and the target property
- **Severity:** Blocker.
- **Scope:** "Resume, accounting and checkpoints": "otherwise retire that case and hold all remaining batch model money until settled."
- **Finding:**
  - For live calls the design does the right thing. Missing usage is charged at the reserved maximum, marked as estimated, and a late receipt replaces it once.
  - For imports with no reservation, the fallback is to halt all model spending batch-wide, with no named settler and no timeout.
  - One case with an unreconcilable imported usage record then stops the batch. That is exactly the pit stop ENGINEERING §3 forbids, and it does not close row 21 ("charge a preauthorized conservative reservation instead of assuming zero").
- **Fix:** Use the same estimated-maximum charge for imports. If no maximum can be derived (no route, no token bound), retire only that case and charge it at its recorded total plus the largest observed identified invocation. Never freeze the batch.

## Major

### M1. The "disproves $15" wording is overstated
- **Scope:** "Proposed section 3 amendment" and the "Cost evidence" section.
- **Finding:**
  - The evidence is mixed. The $15.05 round is round 1. Extension-comparable late rounds were $0.74–$4.33.
  - The $32.6137984 event is correctly described as unlabeled, but it is a single 168-call result event. It could be a multi-round aggregate.
  - The JSON also shows that e15450 has $30.10 across 124 unattributed events, which is 57% of that case's $52.79. The prose omits this. It strengthens the honest conclusion that even the latest case's spend cannot be attributed.
- **Fix:** Say the evidence "does not support, and cannot replace" $15, rather than "disproves" it. Add the e15450 unattributed total. Print the observed identified writer range ($0.45–$15.05) as a non-binding planning input for the founder.

### M2. Unbounded retry loops are limited only by the batch bound
- **Scope:** "Resume, accounting and checkpoints" (malformed repair), "Diagnosis and factory-bug routing" (diagnosis retry), and infrastructure continuation.
- **Finding:**
  - With every per-failure allowance deleted, a deterministic failure repeats until it drains the whole batch. Examples are a diagnosis that is always malformed, or schema repair that never produces valid output.
  - The user prefers deleting caps. That is compatible with a termination rule that is neither a count nor a price.
- **Fix:** Retire on exhausting the approved route list from A. Each approved same-family route gets one attempt at an identical input digest. A repeat of the same failure on every route retires the case. No per-case dollar or count cap is added.

### M3. "Retires for that bound" is undefined
- **Scope:** "Extension eligibility and progress", last paragraph.
- **Finding:** It is unclear whether this is a permanent retirement or a pause that a larger batch bound could resume. Nothing says whether it is an outcome the founder sees.
- **Fix:** Define it as retired in this batch. It is never resumed by a later bound. It is recorded in the case card with its settled spend.

### M4. Extension rounds collide with the round-exhaustion check
- **Scope:** "One extension = one logical writer round…"; `run.py:2308` and `:1098`.
- **Finding:**
  - `validate_and_repair` calls `stop_defect` when `builder_rounds >= c.args.rounds` (8).
  - An extension writer round makes `builder_rounds` 9–13. The check then re-fires at once, before the new round's gates run.
  - The design says repairs are set to zero inside extensions but does not say how the round counter works.
- **Fix:** State the exhaustion predicate as `builder_rounds >= rounds + extensions_started`, or as an extension flag that bypasses the check. Name the exact lines. List which "final-fix loopholes" are deleted. The existing reservation at `run.py:1156` is the likely candidate.

### M5. The stage/version vector is not defined, and `gate_state.py` cannot supply it for every stage
- **Scope:** "Extension eligibility and progress" (identical ordered stage/version vectors); the "Reuse … `gate_state.py`" list.
- **Finding:**
  - `gate_state.py` fingerprints only `REUSABLE` gates (G4, G5, G6, G8, G9, G13, G14, G15, G16). G1, G2, G3, G7, G10, G11, G17 and stress have no per-gate dependency fingerprint.
  - The only "version" is the global `VERSION = 3`. A bump of it invalidates every gate at once.
  - ENGINEERING says "versioned per gate", but the code derives that from input digests.
- **Fix:** Define the vector as the per-gate input digest (`inputs(c, gate, bench)`) for gates that have one. For the others, add a dependency inventory in the extension design. State that a global `VERSION` bump counts as "all gates changed" and rebases lazily.

### M6. Version rebasing cost and noise are not handled
- **Scope:** "Compare identical ordered stage/version vectors only…"
- **Finding:**
  - Re-evaluating the entry revision under new gate versions can mean re-running model gates (G10/G16/G17). Cost multiplies by the number of cases.
  - A model gate can disagree with itself across runs. "True regression retires" does not say how code tells noise from a real regression.
- **Fix:** Say rebasing happens only when a further extension is being considered. Say frontier is compared on the rebased vector. Define regression as an entry pass that fails under the same version with complete, valid evidence.

### M7. The 15-minute writer yield is an unproven new mechanism
- **Scope:** "Long writer calls must yield draft/handoff boundaries at least every 15 minutes…", and the row 35 test ("mid-writer boundary").
- **Finding:**
  - The writer is a CLI process. Nothing in the repo or the design shows it can be asked to yield or suspend and then continue the same logical operation.
  - Row 35 only asks for off-worker checkpoints at "safe boundaries".
  - This is the largest unspecified item in the design, and it is also a required test.
- **Fix:** Either specify the mechanism (for example, kill and resume from the saved worktree draft, with the retained findings) and who owns it, or drop mid-writer checkpointing from D and from the row 35 closing test. Hand it to E explicitly.

### M8. The `factory_bug` refund has no record schema
- **Scope:** "Move affected failed operations … to `infrastructure_waste` by unique operation ID."
- **Finding:** The existing validator in `budget.py` accepts only `kind == 'infrastructure_kill'`. It also requires a derivation with `amount == ceil(max(maximum, maximum/elapsed*killed))` and ledger-event bounds. A factory-bug refund needs a new `kind`, an amount computed from the settled receipts for those operation IDs, and a fix-attribution digest. None is specified.
- **Fix:** Specify the new record fields and validator branch. Clarify that infrastructure waste counts toward the batch bound and is also kept on the separate infrastructure line.

### M9. No priority between extensions and replacements on the same money
- **Scope:** "Exhaustion queues one replacement per original immediately", together with extension entry.
- **Finding:**
  - Both draw from the same batch bound. Nothing says which reserves first.
  - The old "at most two replacements per target slot" was removed, so a replacement of a replacement now looks unbounded except by money.
  - `factory-single-path.md` (batch record line, founder approval line) still lists "case/replacement limits" and "finite case/replacement/batch caps".
- **Fix:** State FIFO on the shared ledger, or replacements first. State whether replacements chain. Remove the stale replacement-cap wording in the single-path doc or restore a rule.

### M10. Stale exhaustion rules remain in `docs/factory-single-path.md`
- **Scope:** The diff changes two lines only (item 9 and the "Rounds, calls or money exhausted" row).
- **Finding:** These still describe allowances that stream D deletes:
  - the same-worker retry row, "Three retries";
  - the "Infrastructure error before any model call" row: "At most three retries, delays 1/5/15 minutes … Exhaustion retires/replaces";
  - the "Worker TTL / crash" row: "Unknown in-flight cost/outcome requires reconciliation by maintainer", which conflicts with automatic settlement under rows 21 and 39.
- **Fix:** Either mark these as superseded by stream D, or reword them in the same commit.

### M11. The diagnosis family statement is stale
- **Scope:** "Use the configured reviewer family … currently Xiaomi/MiMo where configured."
- **Finding:**
  - `rotation.json` records that on 2026-10-20 MiniMax and DeepSeek replaced MiMo and Muse.
  - The slot reviewers today are deepseek, minimax, openai and anthropic.
  - `model_runtime.family()` still maps mimo to xiaomi, so the code path exists but the statement is wrong.
- **Fix:** Define the diagnosis family as the case slot's `reviewer` family from `rotation.json` at the bound checkpoint. Remove the "currently Xiaomi/MiMo" statement.

### M12. No per-file change list, and the readiness standard is not met
- **Scope:** "Implementation and exams".
- **Finding:** The design lists modules to reuse but not what changes in each, and the three phases have no per-phase tests. Missing items:
  - the exact deletions (`run.py:2400` `--max-cost 5.0` and `run.py:1949`);
  - the new `extension_history` field, its schema and its location in the checkpoint;
  - the per-invocation maximum used for reservation. It names "route-enforced token/call bounds" and defers to E without saying where the number comes from.
  - Test assertions are one-line summaries, with no expected numeric outcomes.
- **Fix:** Add a table of file → change → test. Specify the reservation maximum (for example, route token bound × `token_prices.py`). State what happens when the maximum exceeds the remaining batch money (queue or retire).

### M13. Heilmeier gaps
- **Scope:** Top of the design.
- **Finding:** The design never answers in plain words what is being attempted, who benefits, or what the payoff is. It is dense with G-numbers and terms such as "frontier" and "stage/version vector". Cost and timeline are only "three working days" and "no paid run". The mid-term exam is the test list.
- **Fix:** Add three plain sentences for objective, impact and risk/payoff. Add the planning range from M1 under Cost.

## Nits

- **N1.** The first-extension predicate (complete stress coverage with no open blocker, bound to the current case/stress version) is code-checkable and fits the pipeline's first-failure stop. No change is needed. Note in the design that a case that never reached any gate can still qualify.
- **N2.** Snapshot persistence is correct. `stop_defect` pops `gates`, `gate_results` and `failed_gate` and calls `invalidate`, and `extension_history` lives outside those keys. Name the code path that guarantees `invalidate` never touches it.
- **N3.** The JSON mixes `sha256` of file bytes (local cards) with `canonical_json_sha256` (VM cards). It embeds `/Users/bugsincode/...` paths. It carries each receipt three times. It does not record how `labeled_G16_G17_events` was computed. Add the extraction method or script hash.
- **N4.** The 3-day estimate looks optimistic for ten rows plus fault replay.
- **N5.** Rows 10, 35 and 39 need saved public-practice bundles with worker loss. The design defers capturing them, so those rows will stay open. Say so.
- **N6.** I did not independently locate the "$8 writer reservation floor" constant. `run.py:1080` and `:1157` are the register's pointers.
- **N7.** The amendment edits a founder-adopted §3 bullet. The user's stated preference for deleting caps covers it, but cite that in the design.
- **N8.** `extensions.md` and ENGINEERING §3 line 120 now point at each other and at stream-d. Nothing breaks, but update the §3 pointer when the amendment lands.

## What passed

- **Same-gate-version comparison rule:** the structure is sound (see M5 and M6 for the open details).
- **Extension limits:** zero repairs inside an extension is consistent with `validate_and_repair` at `run.py:2294`, and one writer round per extension is consistent with progress gating by frontier.
- **Reuse:** the design adds only diagnosis and extension logic and reuses existing modules.
- **Scope:** it is design only, ENGINEERING §3 stays active, and nothing here changes a running policy.

**Verdict: NOT PASS.** Blockers B1 and B2 must be fixed. M1–M13 should be fixed in the same revision.


## Elephant resolution

All findings accepted; none rejected. B1: B owns admission/aggregate money and
an absolute manifest deadline; reuse shared admission commitments and fail
closed on missing/stale authority. Ordinary thresholds are separate from job
commitments. B2: an imported unknown charge gets an explicitly authorized $33
empirical reservation per invocation and only that case retires; no batch freeze.

M1: changed “disproves” to “unsupported”, added the identified range and
unattributed e15450 total. M2: deterministic same-input failure retires after
approved routes are exhausted; provider conditions still wait. M3: defined
retired_batch_bound. M4: active extension bypasses ordinary round stop, retains
cumulative rounds, and deletes post-loop final-fix calls. M5/M6: specified
scientific versions and inventories, lazy entry rebasing and valid regression.
M7: dropped the unsupported writer-yield mechanism and deferred mid-call work
to E, leaving that part of row 35 open. M8: added factory_bug waste schema and
receipt-sum validator. M9: replacements first, FIFO, existing per-slot limit.
M10: updated stale retry/unknown-outcome wording. M11: checkpoint slot family.
M12: per-file phased plan, maximum-charge formula, and numeric settlement exams.
M13: plain objective/payoff/risk plus wider timeline and observed costs.

Nits: named snapshot-preserving late_recovery paths, documented evidence
extraction below, widened estimate, stated missing-artifact rows remain open,
and cited the user’s allowance-deletion preference. ENGINEERING pointer changes
belong to implementation. Added the newly supplied interfaces contract
9699e5d+c49c754: D calls await_lease before writer/re-review reservations; settles
incremental usage on resume in the case ledger; matches pending lease IDs;
archives waits; exempts every section 5 counter; preserves B’s reviewed wait
backstops and merge/flag order. Round 2 reviews this revised contract-bound draft.
