# Goldfish review, round 2: Stream D design (`docs/designs/stream-d.md`)

**Mode:** REVIEW, read-only. No writes, launches, decryption or paid calls.
**Personas:** zoom_out, design_critic, implementation_readiness.
**Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`, `zoom-out-standard.md`.
**Binding contract:** `/Users/bugsincode/Developer/unbug-bench/docs/designs/interfaces.md`. Its history is 9699e5d, c49c754 and 4a10966.

**Scope read:**
- `docs/designs/stream-d.md`, `extensions.md` and `stream-d-cost-evidence.json`.
- The `docs/factory-single-path.md` diff.
- `docs/reviews/stream-d-design-1.md`, including its elephant resolutions.
- `docs/ENGINEERING.md` §3–4 and Murphy rows 8, 9, 10, 11, 12, 13, 15, 21, 35 and 39.
- Code, searched for reuse and checked against the design's claims: `factory/run.py`, `budget.py`, `model_runtime.py`, `gate_state.py`, `late_recovery.py`, `key_holder.py`, `ttl_continuation.py`, `g11_review.py`, `coordinator.py` and `fairness.py`.

## Verdict: NOT PASS

Two blocking findings are open (B1, B2). Both are fixable in the document. The round-1 findings were addressed, and the structure is sound.

**Round-1 resolution check:**
- B1 and B2 from round 1 are addressed in prose: the shared admission reservation and `batch_deadline`, and the $33 per-unknown-invocation import estimate.
- M1–M13: I checked each against the text and found a real fix for each.
- New problems in the revised text are listed below, and none of them re-opens a round-1 rejection.

## Rollout prerequisites vs. design choices

**External rollout prerequisites.** The design states these correctly. They must not be guessed around in D:
- B's batch deadline, admission, and aggregation of money from collected cards.
- B's journal, relaunch, key and publication path.
- A's record writer, `finish`, and the receipt format at `call_id`.
- E's route request and token bounds, and E's cancellation and join.
- C's scoring eligibility.
- Merge order: single path → E → C → A → D → B, with `UNBUG_PROVIDER_WAIT=0` until B.
- Public-practice crash and capped-call bundles for rows 10, 35 and 39 (the design says so).
- The founder's authorization of the batch money, the deadline and the import policy.

**Unresolved design choices.** These belong to D and are not yet decided. Each is a finding below:
- B1: the scope and scientific effect of deleting `max_cost`.
- B2: the lease-ID rule when a wait repeats on a pending round.
- M1–M7.

---

## Blockers

### B1. Deleting the "$5 cap" is under-scoped and silently changes scientific gate versions
- **Severity:** Blocker.
- **Scope:** "Change and deletions"; "Implementation and exams" item 2 (`run.py`, `gate_state.py`); Murphy row 8.
- **Finding:**
  - **Where `max_cost` lives.** The design deletes "`--max-cost=5` checks (including calibration child limits near old line 1949)". `max_cost` is wired through far more than that:
    - `budget.py:263` and `:307` enforce it. Row 8 itself cites these lines, but the design's `budget.py` list does not mention deleting them.
    - `run.py:2400` (default), `:2499` (passed into the recovery config) and `:1949` (calibration limits).
    - `model_runtime.py:345` passes `max_cost=c.args.max_cost` to `run_budgeted`.
    - `coordinator.py:28` and `:162` carry it as a recovery-config field that must be unchanged on relaunch.
    - `ttl_continuation.py:34`, `:155`, `:175` and `:244` refuse continuation once priced cost reaches `config['max_cost']`. This is row 8's symptom at the continuation layer.
    - `key_holder.py:311` refuses recovery at `cost >= job['max_cost']`.
    - `g11_review.py:105` and `:113` clamp the audit to `budget['cost'] + 0.50`. This is another hidden allowance.
  - **Consequence for the goal.** Leave any of these and a case with more than $5 of paid spend is still refused at that layer. That is the exact failure the design claims to remove.
  - **Scientific versions.** `max_cost` is also part of the gate fingerprints:
    - `gate_state.py:124` is in the stress `judge_dependencies` settings.
    - `gate_state.py:141` is in the `settings` for G8, G9 and G16.
    - `run.py:1949` is in the `limits` of `calibration_identity`, which hashes G10 attempts.
  - **What deleting it does to those versions.** Removing `max_cost` from those digests changes the version of stress, G8, G9, G16 and G10, and everything that depends on them, for every in-flight case. The design's own rules say a changed version means "never rename an old result to new" and "retain evaluator/calibration code, prompts, model identities and scientific settings". The design never says whether `max_cost` is accounting or a scientific setting. For G10 it arguably is scientific, because a priced-spend ceiling decides when an attempt is "capped" (row 39).
  - **Contradiction with the success criteria.** The design promises "gate standards stay unchanged", yet this deletion triggers mass re-evaluation. It also quietly contradicts "a gate change re-runs only the gates that changed".
- **Fix:**
  1. Add a complete deletion table of every `max_cost` site above (file, line, action). Include the replacement control: the invocation reservation against the job commitment.
  2. Decide and write down what `max_cost` is for versioning. For example:
     - Keep it as a frozen literal in the scientific inventories and remove only the enforcement. State the ceiling this implies for G10 capped attempts.
     - Or declare it accounting, drop it from the digests, and state that the first extension after the change costs a one-time version change with the §"Compare identical… vectors only" rules applied. Include a cost estimate for the affected gates.
  3. Add an exam: on a saved card, the digests of G8, G9, G16, stress and G10 before and after the change must match, or the version change must be listed as intentional.

### B2. A repeated provider wait on one pending round is not covered by the lease-matching rule
- **Severity:** Blocker (strict contract compatibility, interfaces §§2–3, 5).
- **Scope:** "Batch bound and reviewed interfaces", the bullets starting "For writer `repair_pending`…" and "A live wait whose `lease_id` matches…".
- **Finding:**
  - **The matching rule.** Under interfaces §3, a live `provider_wait.json` is treated as a wait only when its `lease_id` equals the `lease_id` in a pending receipt (`repair_pending` or `review_pending`). Otherwise the pending receipt is a crash and "follows D's ordinary crash rules".
  - **The first wait works.** Round n takes lease L1. It writes the receipt with L1. A wait happens, and the record carries L1. On resume it matches. So far the design is right.
  - **The second wait does not.** After resume, the continuing writer call must take a new lease. D calls `await_lease` itself for writer calls. The design never says the pending receipt's `lease_id` is rewritten. Two cases follow:
    - **Denied before admission.** The resumed worker's `await_lease` can itself exit with `provider_wait`. The new record then has `lease_id: null` ("denied before admission"). The pending receipt still holds L1. They do not match, so the next resume sees a crash and consumes `interrupted_repair` or a re-review attempt.
    - **Admitted, then waiting.** The call is admitted as L2 and then waits. The record carries L2, but the receipt still holds L1. This also misclassifies as a crash.
  - **Why it matters.** This breaks "waits consume none of rounds/extensions/restarts/…", and the design's own exam of "four reset/outage waits still resume within batch bounds". A reset wait that repeats is the normal case. Waits chain 15, 30, 60 minutes.
- **Fix:** D owns the crash rules, so this needs no change to A's record. Specify:
  1. **Before re-admission.** On resume, after `settle`, D rewrites the pending receipt in place: `lease_id: null` and `resumed_from_wait: <wait_id>`. The counter and the ID are unchanged.
  2. **Matching rule.** A receipt with `resumed_from_wait` set is "pending, awaiting a lease". A live record with `lease_id` null, the same role, and that receipt matches. A record with a new `lease_id` matches only the receipt that holds it.
  3. **After the new lease.** D writes the new `lease_id` into the receipt only after `await_lease` returns, atomically with the reservation.
  4. **Crash rule.** A kill between steps 1 and 3, with no live record, is a provider continuation (the settled record sits in `provider_waits/<wait_id>.json`). It is not `interrupted_repair`.
  5. **Exams.** Add a three-consecutive-waits exam for both writer and stress review. Include a kill at each step above.

---

## Major

### M1. The money reservation for wrapper-admitted calls has no join key to A's record and receipt
- **Scope:** "Resume, accounting and checkpoints" ("Reserve money atomically in the case ledger before every call"); the `settle` bullet; interfaces §§2–3.
- **Finding:**
  - **Reservation vs. lease.** D reserves money before every call, but only writer and stress re-review calls have D obtain the lease. For all other calls (stress attackers, reviewers, calibrators, G10, G16, G17, diagnosis) the wrapper calls `await_lease` after D has already reserved. The design says only for pre-admission writer waits that "no reservation" is written. A denied-before-work wait on a wrapper-admitted call can therefore leave a money reservation that nothing releases.
  - **No join key.** A's record holds `wait_id`, `role`, `route`, `lease_id`, `call_id`. It holds no D invocation ID. For non-writer calls the reservation has no `lease_id` either. The design's formula "reserved invocation maximum − already-booked" has nothing to look up.
  - **Concurrency.** G10 overlap can have several calls in flight, but the contract has one `provider_wait.json` per case.
- **Fix:**
  - State that the reservation key is D's invocation ID.
  - State how `settle` finds it, for example by `role` plus the single `pending` reservation. Define a rule for more than one pending reservation.
  - State that `denied_before_work` with a null `lease_id` and null `call_id` releases the reservation and books $0.
  - Ask A, through the owner of the interface, to state whether concurrent calls can have more than one record.
  - Unmatched pending money reservations must follow the conservative crash rule, with an explicit statement that this overcharges relative to a true wait.

### M2. The commitment channel between B and D is a new cross-stream contract that is not in `interfaces.md`
- **Scope:** "Batch bound and reviewed interfaces", first two paragraphs; per-file item 3 (`coordinator.py`/`admission.py` "expose D's eligibility and money commitment checks").
- **Finding:**
  - **No documented interface.** Interfaces §5 and §1 give B the batch cap and say it "never books separately". They do not define a per-job commitment, how B assigns it, how a running worker learns it, or how it is converted when a card is collected.
  - **The design leans on it.** It uses `case_budget.limit_usd = spend + assigned commitment`, "return to B without calling" and "missing/stale refuses dispatch".
  - **Ownership rule.** Interfaces §1 requires a goldfish-reviewed change to `interfaces.md` for a new contract.
  - **Cannot be guessed.** The implementer cannot guess the channel (argument, manifest field, checkpoint field, or admission file), the field names, or what "stale" means.
  - **Sizing.** How B sizes a commitment across 24 parallel jobs is also unspecified. That is a fairness risk: one job could receive the entire unspent bound.
- **Fix:**
  - Write the minimum D needs as a proposed addition to `interfaces.md`: field names, where they live, staleness rule, and conversion at collection. Send it for review as a B-owned contract. D does not own it.
  - Mark this explicitly as an external rollout prerequisite (B). The implementation plan cannot start on D until it exists.
  - Add a sentence on the worst case: one case may consume its whole commitment, and the commitment size is B's decision.

### M3. The ordinary exhaustion predicate and `model_runtime.py` are not specified
- **Scope:** "Change and deletions" ("Delete … $8 writer reservation floor"); "Batch bound" (`ordinary_limit_usd`, `limit_usd`).
- **Finding:**
  - **Today's trigger.** The ordinary $50 stop is `limit_usd − spent < writer_round_estimate`, at `run.py:1083` and `:1159`. The estimate has the $8 floor at `model_runtime.py:198`.
  - **What is missing.** The design deletes the floor and keeps `ordinary_limit_usd` "as the trigger". It never gives the new predicate, for example `spent ≥ ordinary_limit` versus `remaining < next invocation maximum`.
    - The first can overshoot $50 by a whole round.
    - The second can trigger far below $50 when route maxima are large ($33 vs. a $50 limit).
  - **Where the limit comes from.** `limit_usd` is recomputed on every call from `args.case_budget` in `update_case_budget`. The design's "after diagnosis `limit_usd` is cumulative spend plus the commitment" needs a change there, but `model_runtime.py` is absent from the per-file list.
  - **Where `ordinary_limit_usd` is stored** is not stated.
- **Fix:** Name the predicate, the storage field, and the edits to `update_case_budget`, `require_case_budget` and `writer_round_estimate` (delete or replace). Add an exam with numbers: spent $44, round maximum $12.

### M4. The `factory_bug` waste record can double-count unless `case_spending` is also changed
- **Scope:** "Diagnosis and factory-bug routing", the `budget.py` validator branch.
- **Finding:**
  - **How totals work today.** `case_spending` adds `waste` on top of `known` (event costs). That is correct for the legacy `infrastructure_kill`, which has no events.
  - **Why this record differs.** A `factory_bug` record names `event_ids` that are already in the ledger and already in `known`. The design says reclassification "moves existing cost, never adds it twice or reduces batch total". The listed work is only a validator branch.
  - **Result.** Without removing those events from `known`, `total_spent_usd` double-counts them. The case budget is also not relieved.
- **Fix:** Specify that `case_spending` excludes the record's `event_ids` from `spent_usd` and counts them once in `infrastructure_waste_usd`. Keep the batch `total_spent_usd` unchanged. Add an exam with the numbers.

### M5. "Replacement-per-slot limit (default two)" has no source after this diff
- **Scope:** "Change and deletions" ("Replacement chains are allowed only within the manifest's existing replacement-per-slot limit (default two)"); the `docs/factory-single-path.md` diff.
- **Finding:**
  - **Reference is gone.** The only place the single-path doc stated "at most two replacements per target slot" was the row this diff rewrites, and the rewrite removes it. Nothing in the code or the remaining docs defines a replacement-per-slot limit or a default of two. The doc now says only "manifest case/replacement limits".
  - **Tension with intent.** A chain that is "only within the existing limit" refers to something that no longer exists. If the limit is removed, replacement chains are bounded only by money, and each replacement gets a fresh $50 trigger.
  - **Stated preference.** The user prefers removing caps, so this should be a stated decision rather than an accidental survivor.
- **Fix:** Pick one and write it into the single-path "Batch record" text and `stream-d.md`:
  - A named manifest field (for example `replacements_per_slot`, default 2), or
  - No count limit, with chains bounded only by the cumulative bound and the deadline.

### M6. The $33 import reservation is internally inconsistent and can drain the batch bound
- **Scope:** "Resume, accounting and checkpoints" ($33 per unknown invocation); "Cost evidence".
- **Finding:**
  - **Contradiction.** The $33 is derived from `ca2f9bdf-…:result`, which the design itself says "lacks an invocation label… do not call it an identified writer round; it may aggregate multiple logical rounds" (168 calls in the JSON). The same event is then the "largest authenticated invocation receipt" per invocation.
  - **Direction of error.** It is a plausible conservative number, but it is not a bound. The design discloses this, and the founder authorizes the policy.
  - **Exposure.** An imported case with N unknown invocations is charged `$33 × N`, booked into the shared bound, for a case that is then retired. Ten unknown invocations is $330 against a $50 ordinary case, which could consume a large part of the batch bound for a case that will never run again.
- **Fix:**
  - Reword the justification as "empirical, aggregate-derived; not an invocation maximum".
  - Make the import dry run print the total estimated charge per case and per batch, so the founder authorizes a number rather than a policy.
  - Replace the estimate on late receipts, which is already stated.
  - Say that this charge counts against the cumulative bound.

### M7. The "commit writer completion before G1" and extension flow touches the receipt shape without naming the schema
- **Scope:** "Resume, accounting and checkpoints" ("Extend existing receipts: operation ID, input/version binding, phase `pending|completed|validated`…"); "Extension eligibility and progress".
- **Finding:**
  - **No field-level schema.** Extension history has a schema with fields. The extended writer and stress receipts (`attack-state.json` and the round receipt at `run.py` ~1094 and ~1124) do not.
  - **Open questions:** `operation_id` format, `phase` transitions, and how `output digest` binds the draft.
  - **Key-name collision.** The existing keys `repair_pending`, `review_pending` and `review_attempt` stay, but the design adds new keys beside them.
- **Fix:** Add one JSON example of the extended writer receipt and one of the stress receipt. Include `operation_id`, `phase`, `lease_id`, `resumed_from_wait` (from B2), the output digest and the next phase. Add the migration for existing receipts.

---

## Nits

- **N1. Heilmeier "Impact".** "The payoff is unattended completion" does not say who cares (the founder, bench integrity, throughput). One sentence fixes it.
- **N2. Heilmeier "Cost".** The design honestly gives no package price. Say plainly in the cost section that the founder's bound is the only dollar limit, and that one case's worst case is five extensions at the reservation maximum.
- **N3. Zoom-out, new module.** `factory/diagnosis.py` plus `prompts/diagnosis.md` is justified (a new case-level schema). State why the existing read-only audit pattern in `g11_review.py` or `sealed_audit.py` is not reused, or reuse its role dispatch.
- **N4. Zoom-out, scope.** Per-gate inventories for G1/G2/G3/G7/G10/G11/G17 and stress are only needed if gate versions change during the extension window. State that they are computed lazily and not built eagerly.
- **N5. Evidence file.**
  - I verified: 54 VM cards; 3 G10 passes; 0 G16/G17 passes; the $16.0 waste on 873d7f; e15450 with 124 unattributed events at $30.09905083 (57% of $52.7866); the builder costs; the $32.6137984 event with 168 calls and no invocation label; the $0.0042488 preflight; the $0.032489508 and $0.041890088 freshness totals.
  - I did not verify the "41 events" and "26 events" counts for `attacker-8` and `attacker-9` against the JSON. Please point to their lines.
  - The extraction method is now present. It has local `/Users/bugsincode/...` paths, which is fine as provenance.
- **N6. Wording.** "Eight writer rounds/$50 remain the ordinary diagnosis trigger" and "up to five extensions" appear in several places. Keep one authoritative statement.
- **N7. Note on `builder-freshness`.** Freshness author edits cost $2.5–$2.9 per event in the JSON and are writer-family calls outside `builder-N`. The "one writer per extension" rule covers them, but the "identified writer range" omits them. Say so.

---

## What passed

- **Contract compatibility, matched to interfaces.md:**
  - **§2.** D calls `await_lease`, writes the reservation with `lease_id` only afterwards, passes `lease=lease`, and never calls bare `admit()`. A owns renewal and `finish`.
  - **§3.** Settle once on resume before any call. Union of booked event IDs with the receipt. Book only the missing usage or a conservative gap. Case ledger, same checkpoint as `settled`. Idempotent on `wait_id` and event IDs. The $10 example is arithmetically right (booked $5, adds $5; replay adds $0; a final $8 releases $2). Records move to `provider_waits/<wait_id>.json` before the first new call. No checkpoint hash in A's record.
  - **§4–5.** B's 10-per-reason and credit-once backstops are kept. Waits consume no rounds, extensions, restarts, holder attempts, coordinator launch actions or stress re-review reservations.
  - **§6.** Merge order and the flag are stated correctly. No owned interface shape is changed.
  - The gaps are B2 and M1–M2, all inside D's own ownership or marked as B's.
- **Extension mechanism:**
  - First-extension predicate: complete stress coverage, no open blocker, bound to current versions, evaluated from the frontier. It is code-checkable and reaches cases that cleared stress without a gate.
  - `extension_history` lives outside `gates`, `gate_results` and `failed_gate`. `late_recovery.stop_defect` pops exactly those keys, so snapshots survive.
  - Deleting the post-loop final-fix path at `run.py` ~1155–1186 is consistent with "one writer per extension".
  - The `validate_and_repair` bypass for the active extension ID is the right shape. Zero repairs inside an extension matches the code at `run.py:2294`.
- **Cost honesty:** deleting the unsupported $15 rather than inventing a replacement matches the evidence. The user's preference for deleting caps is cited.
- **Single-path doc:** the stale retry rows and "unknown outcome needs maintainer reconciliation" are reworded. The "Approve" line is updated.
- **Reuse:** the design reuses `budget.py`, `restore_ledger.py`, `gate_state.py`, `late_recovery.py`, `admission.py` and the coordinator/holder paths.

**Verdict: NOT PASS.** Fix B1 and B2 in the document, and address M1–M7 in the same revision. After that, a round 3 should confirm each fix. No finding is a request to change an owned interface shape.


## Elephant resolution

All findings accepted; none rejected. B1: enumerated every max_cost enforcement,
identity, restore, holder, continuation and audit site; classified it as cumulative
accounting and explicitly version-migrated stress/G8/G9/G16/G10 and dependent G17.
Expected rerun price is unmeasurable from these receipts; maximum is the assigned
commitment. B2: pending receipt is reset to null lease with resumed_from_wait
after settlement; null same-role denial and a newly returned L2 match correctly.
An authenticated settled archive handles a kill during re-admission. Added
three-wait/kill exams for writer and stress without counter consumption.

M1: reserve only after Lease for every call, UUID invocation key mapped to lease,
wrapper helper integration, zero charge for null denied-before-work, conservative
unmatched crash accounting. Serialize model dispatch per case so the single A
record cannot race; mechanical work can still overlap. No A shape change.
M2: specified the minimal money channel as an explicitly proposed B-owned
interfaces addition, not existing contract; B adoption/review is an external
prerequisite before D relies on it. B chooses sizing; a case may spend it all.
M3: named ordinary admission predicate and storage, model_runtime/budget edits,
and $44 spent/$12 maximum example. M4: case_spending excludes classified event
IDs from case spend, includes them once as waste; $12 becomes $8+$4, total $12.
M5: remove replacement count limits explicitly in both design and single-path.
M6: call $33 empirical aggregate-derived, print and authorize per-case/per-batch
dry-run numbers (10 unknowns=$330); keep charge in cumulative cap and replace on
late receipts. M7: schema-v2 writer/stress examples, UUIDs, phases/digests,
continuation fields and strict legacy migration.

Nits: founder/bench impact, worst-cost authority, audit dispatch reuse, lazy
inventories, numbered-round range excluding freshness author calls, and evidence
locations: stream-d-cost-evidence.json invocation_totals under VM 873d7f attacker-8
has 41 events; e15450 attacker-9 has 26. No findings rejected; round 3 verifies.
