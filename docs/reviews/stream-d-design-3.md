# Goldfish review, round 3: Stream D design (`docs/designs/stream-d.md`)

**Mode:** REVIEW, read-only. I made no writes, launches, decryption or paid calls.
**Personas:** zoom_out, design_critic, implementation_readiness.
**Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`, `zoom-out-standard.md`.
**Binding contract:** `/Users/bugsincode/Developer/unbug-bench/docs/designs/interfaces.md`, read at the current tip. Its history is 9699e5d, c49c754 and 4a10966.

**Scope read:**
- `stream-d.md` in full, `extensions.md`, and `stream-d-cost-evidence.json`.
- The `docs/factory-single-path.md` diff, plus a keyword search of the rest of that file.
- `stream-d-design-{1,2}.md`, including both elephant resolutions.
- Code checked against the design's claims:
  - `factory/run.py`, `budget.py`, `model_runtime.py`, `gate_state.py`, `late_recovery.py`, `recovery.py`.
  - `restart.py`, `coordinator.py`, `ttl_continuation.py`, `key_holder.py`, `g11_review.py`, `admission.py`.
  - `carry_over.py`, `rotation.json`, `bin/run-exam`, and the Murphy rows.

## Verdict: NOT PASS

**One blocker is open (B1).** It is a repeat of the round-2 class: the "complete" paid-cap deletion list is not complete. Every other round-2 fix holds up against the contract and the code. There are eight majors. They are mostly tightenings the zero-decision rule requires, and one (M3) is a real accounting trap.

**Round-2 fix verification:**

| Round-2 finding | Status |
|---|---|
| B1 (`max_cost` sites, version effects) | **Partly fixed.** All 9 listed files have accurate line references. The scientific-version analysis is correct. The list omits live sites (new B1). |
| B2 (repeated waits on a pending round) | **Fixed.** Walk-through below. |
| M1 (invocation → lease join, $0 denial, serialized dispatch) | **Fixed.** One ambiguity (N1) and one conflict (M4). |
| M2 (B-owned money channel) | **Fixed as a proposal.** It is correctly marked as an external prerequisite. |
| M3 (ordinary predicate, storage, `model_runtime`) | **Fixed** for the predicate and storage. A pass-through site was missed (M2). |
| M4 (`case_spending` reclassification) | **Specified, but an implementation trap remains** (M3). |
| M5 (no replacement count) | **Fixed,** with a new degenerate case (M5). |
| M6 ($33 estimate, authorized numbers) | **Fixed.** |
| M7 (v2 receipt examples) | **Partly fixed** (M6). |
| Nits | Fixed. Audit-dispatch reuse is real (`sealed_audit.py` and `g11_review.py` exist). Lazy inventories are stated. The numbered-round range excludes freshness-author calls. I also verified the `attacker-8` (41) and `attacker-9` (26) event counts, which sit in `vm_cards[4]` (873d7f) and `vm_cards[7]` (e15450). |

**B2 walk-through against interfaces §3:**
- L1 interruption matches the receipt's L1 lease.
- After a settled resume, the receipt is reset to `lease_id:null, resumed_from_wait:W1`, and W1 is archived before `await_lease`.
- A denied-before-admission W2 (null lease and call IDs) matches the unique pending role. It books $0 and the cycle repeats.
- A newly returned L2 is written atomically with the reservation.
- A kill with no live record is proven by the validated archive named in `resumed_from_wait`.
- This keeps A's record shape unchanged and follows §3's "move to `provider_waits/` before the first new call". The three-wait exam covers each step.

**Evidence file, checked against the design's prose:**
- Identified `builder-N` receipts range from $0.4463424 (`builder-4`, e15450) to $15.0531879 (`builder-1`, 873d7f). This matches.
- e15450 has $30.09905083 across 124 unattributed events.
- Three VM cards have G10 passes. Zero cards have G16/G17 passes.
- The $32.6137984 event has 168 calls and no invocation label, so $33 is the ceiling of that number.
- The "unsupported, cannot establish another price" wording is honest.

## External prerequisites vs. D design gaps

**External (correctly stated, not D's to fix):**
- B's adoption and review of the money channel in `interfaces.md`.
- E's request and token bounds, cancellation and join.
- C's scoring eligibility.
- A's `model_router`, `await_lease` and record writer. None of these is in the tree yet; no `model_router` file exists on this branch.
- The merge order and the `UNBUG_PROVIDER_WAIT=0` flag.
- Public crash and capped-call bundles for rows 10, 35 and 39, which stay open (stated).
- Founder authorization of the batch bound, deadline and import numbers.

**D design gaps:** B1, M1–M8 and the nits below. All can be fixed in the document.

---

## Blockers

### B1. The paid-cap deletion inventory is called complete but is not
- **Severity:** Blocker (same class as round-2 B1).
- **Scope:** "Remove the paid cap everywhere" ("Complete paid-cap deletion list"); Murphy rows 8 and 11.
- **Finding:** The design says that after its list "no launch, resume, gate, audit or continuation may enforce [`max_cost`]". Code search shows live enforcement it never names:
  1. **`factory/restart.py:72`.** `restart.plan` refuses restart with `cost >= option("--max-cost", 5)`. The error is "missing, invalid or exhausted cumulative usage". This is the same-worker automatic retry planner. The single-path doc keeps it, and the design only says `restart.py` "preserves A's wait exemptions".
     - Any case with at least $5 of priced spend still cannot be auto-restarted. That is exactly the failure row 8 describes.
     - The same function also enforces `retries < 3` at `:57`. Row 11 cites this line as the restart allowance.
     - It also checks `require_case_budget(budget, option('--case-budget', 50))` at `:76`. That reads the ordinary $50 from argv, not the commitment, so an extended case with spend above $50 is refused here too.
     - The design says it deletes "restart allowances" but names no site and does not say whether `restart.py:57` is deleted or kept.
  2. **`bin/run-exam:250/270/279`** and `tests/bench/test_run_exam.py:71–90`. The exam-owner runner builds `args.max_cost` from `--owner-max-cost` (default 5.0) and runs through `model_runtime.opencode` → `run_budgeted(max_cost=…)`.
     - This runner has no case ledger or job commitment (`ledger=work/"budget.json"`). It is a real paid model during exams, and `bin/run-exam` is listed among G16's dependencies in `gate_state.DEPENDENCIES`.
     - Deleting the `max_cost` argument from `run_budgeted` and the forwarding at `model_runtime.py:345` either breaks it (an unexpected-argument error) or silently removes its only cap.
     - The design's rationale, that `max_cost` is "not a per-contestant scientific exposure limit", does not cover this runner.
  3. **The allowance sites for rows 11 and 12.** The prose deletes "restart/stress-rereview/holder-recovery/diagnostic allowances" but lists no lines:
     - `run.py:916`, `:936` (`rereview_limit = 2`).
     - `run.py:1027` (`infrastructure_attempts >= 8`).
     - `run.py:1110` (`diagnostic_allowance_exhausted`).
     - `key_holder.py:185–196` (`counted >= 3`, the cohort attempt cap).
     - `carry_over.py:37–39`, `:242` and `:330–340` (`OPERATIONS`, `INFRASTRUCTURE_LIMIT = 8`, "case allowance exhausted", "case budget exhausted"). These feed the import path, where D's $330 dry-run lives.
     - The `restart.py` and `key_holder.py` edits are in A/B-owned areas. Interfaces §1 requires that each such edit be named.
  4. **Docs and fixtures.** `factory/README.md:404–423` documents `--max-cost 5`. Roughly 25 test files and 8 fixtures encode it. Not listing these is acceptable only if the search exam is the safety net.
- **Fix:**
  1. Add `restart.py` (`:57`, `:72`, `:76`), the allowance sites in item 3, and the `bin/run-exam` decision.
  2. For `bin/run-exam`, either keep an optional `max_cost` on the shared runner for non-factory callers and say so, or give the exam owner an explicit replacement control.
  3. For each deleted allowance, state the owner stream and whether the line is deleted or the counter is only exempted for waits (§5).

---

## Major

### M1. Which stops are "exhaustion", and how the founder-ruling path is retired, is unspecified
- **Scope:** "Change and deletions"; "Extension eligibility and progress"; per-file item 2 (`recovery.py`).
- **Finding:** The central trigger is "eight writer rounds/$50 → diagnosis". Today a gate failure at the round limit does not stop as `rounds_exhausted`.
  - `validate_and_repair` calls `late_recovery.stop_defect` when `builder_rounds >= args.rounds` (`run.py:2308`).
  - That raises `late_defect_needs_ruling:<gate>`, and `recovery.py:164` refuses resume without `--founder-ruling-sha256`.
  - That is the founder pit stop this design exists to remove. The design never mentions this stop reason, `founder_ruling.py`, or `recovery.raised_limits` (the explicit `budget_raised` / `rounds_raised` path).
  - Post-loop, `run.py:1155–1186` also emits `budget_exhausted` and `stress_review_unresolved:rounds_exhausted`. Deleting that range wholesale ("final-fix call path") would also delete the stop-reason emission the diagnosis trigger needs.
- **Fix:**
  1. Add a table of the terminal stops that enter diagnosis: `budget_exhausted`, `stress_review_unresolved:rounds_exhausted`, `late_defect_needs_ruling:*` at the round limit, and the post-extension "gate still failing" state.
  2. State which part of 1155–1186 is deleted (the writer call) and which is kept (the stop emission).
  3. State that the diagnosis-plus-code result replaces the founder ruling and `raised_limits` for these stops. Zoom-out check: say why the existing `limits_raised` and `ruling.allowances.round_limit` mechanism (`run.py:921–929`) is not reused for the extension round, instead of a new active-ID bypass.

### M2. The effective money limit has four read sites; the design names two
- **Scope:** "Batch bound" (`ordinary_limit_usd`, `limit_usd`); per-file `model_runtime.py` / `budget.py`.
- **Finding:**
  - The design updates `update_case_budget` and `require_case_budget`, which read `card['case_budget'].limit_usd`.
  - But `model_runtime.py:351` passes `case_budget=c.args.case_budget` into `run_budgeted`, and `budget.py:255` calls `require_case_budget` with that value.
  - `c.args.case_budget` is also serialized into `recovery_config` (`run.py:2498`) and must match on relaunch (`coordinator.py:162`).
  - Unless these carry the commitment too, an extension's first call is refused with `budget_exhausted` at $50.
- **Fix:** Name the single source of the effective limit and say how the argv value, `recovery_config.case_budget`, the card summary and the in-call check all derive from it.

### M3. Reclassifying `factory_bug` waste will double count unless the totals remainder is handled
- **Scope:** "Diagnosis and factory-bug routing" (`case_spending` excludes classified event IDs).
- **Finding:**
  - `budget.py:72–75` compares the sum of the events it counted against `ledger['cost'|'list_cost_usd'|'estimated_subscription_cost_usd']`.
  - Any shortfall is added to `legacy_unattributed`.
  - If classified events are skipped before the sums, the ledger totals still include them, so the same cost reappears in `spent_usd` as a remainder. With $12 booked and $4 classified, the result is $12 case + $4 waste = $16, not $8 + $4.
  - The named $12 → $8/$4/$12 exam would catch it, but the design should say how.
- **Fix:** State that the observed sums include the classified events (so the remainder is zero), and that only the role breakdown excludes them.

### M4. Per-case model serialization conflicts with the G10 overlap and with the single-path doc
- **Scope:** "Serialize model dispatch per case… Remove concurrent model-role fan-out in this mode"; "During G10 overlap persist isolated committed attempts…".
- **Finding:**
  - `run.py:2151` runs the strong and easy calibrators concurrently in a `ThreadPoolExecutor`. `docs/factory-single-path.md` line 122 keeps this as "permitted independent calibrators".
  - The design removes concurrent model fan-out, then later says to persist attempts "during G10 overlap". These cannot both hold.
  - "This mode" is undefined.
  - If it is implemented by setting `concurrent_roles=False`, that arg is part of the stress, G8, G9 and G16 settings digests (`gate_state.py:130/141`). That would silently widen the declared migration set.
  - The wall-time cost of serializing G10 against the batch deadline is not stated.
- **Fix:**
  1. Say which of the two statements wins.
  2. Implement serialization as a lock, not by changing `concurrent_roles`.
  3. Acquire the lock before `await_lease`; otherwise two threads can each hold an admission while one A record exists.
  4. State the expected G10 wall-time effect, or that it is unmeasured.

### M5. A zero-spend replacement chain is not bounded
- **Scope:** "Delete replacement count limits: chains share only the cumulative batch money/deadline bound."
- **Finding:** Exhaustion is defined partly as `spent + next_writer_invocation_max > ordinary_limit`.
  - If the maximum is high or misconfigured, a fresh case with $0 spent is "exhausted" before its first call.
  - It queues a replacement that does the same. There is no count cap, and no money is spent, so only the deadline and VM cash stop it.
  - The earlier decision to remove the count cap stands. It still needs a non-count, non-price stop.
- **Fix:** For example, queue a replacement only if the original made a paid call, or retire the chain when a replacement exhausts having spent $0. This matches the round-1 "no count or price, deterministic failure retires" principle.

### M6. The v2 receipt examples are not a complete schema, and the resume clamps are not addressed
- **Scope:** "Resume, accounting and checkpoints" (the two JSON examples); `run.py:916–934`.
- **Finding:**
  - The examples omit existing keys the resume code requires: `round_limit`, `binding` (a per-key dict used for `binding_changed`), `report`, `release_rereviews` and `release_review_attempts`.
  - They add `binding_sha256`. It is unclear whether that replaces or supplements `binding`.
  - On resume, the code takes `round_limit = min(c.args.rounds, saved_limit)` (unless raised or ruled) and rejects `n > saved_limit` as "invalid round".
  - A round-9 extension receipt therefore fails resume unless `round_limit` or the clamp is made extension-aware. Rows 10 and 11 exercise exactly this path.
- **Fix:** State "v2 = v1 fields + these new fields". List the new fields. State how `round_limit` and the `n <= saved_limit` check treat an active `extension_id`.

### M7. The reservation maximum has no feasibility check against $50 or the commitment
- **Scope:** "Reserve money atomically… Maximum = enforced request count × (…)".
- **Finding:**
  - Observed identified writer rounds are $0.45–$15.05, with a median near $2. A worst-case product of request count and context-window maxima is likely well above that.
  - Because `spent + next_writer_max > $50` triggers diagnosis, an oversized maximum diverts every case before work (see M5).
  - The design defers the bound to E but sets no acceptance range. It also does not say what happens if the maximum exceeds the commitment on a fresh case.
- **Fix:** Add a pre-implementation exam that prints each role's route maximum next to the observed receipts. Add a rule: if any approved route's writer maximum exceeds the ordinary limit, D does not enable, and E must supply a tighter bound. Mark this as an E prerequisite.

### M8. Existing tests that encode the deleted behavior are not listed
- **Scope:** "Implementation and exams".
- **Finding:** `tests/factory/test_carry_over_fingerprints.py:78` (the `max_cost` settings subtest) fails by design after the `gate_state.py` change. Other tests that build `max_cost` args or fixtures will also break: `test_budget.py` (:209, :402, :418, :645), `test_ttl_continuation.py`, `test_g11_review.py`, `test_restart.py`, `test_key_holder.py`, `test_coordinator.py`, and `test_run_exam.py`.
- **Fix:** List the test files to update or delete. The search exam alone does not tell the implementer which expectations to rewrite.

---

## Nits

- **N1.** "Case-local lock held from admission through wrapper finish": say that the lock is taken before `await_lease` (see M4).
- **N2.** Two labels cover similar ends: B's `provider_wait_deadline` (interfaces §4) and D's `retired_batch_bound`. State when each applies.
- **N3.** `money_wait` (in the B-owned proposal) is a new terminal stop that is not in interfaces §4's list. This is B's to define; note it as part of the prerequisite.
- **N4.** D merges at step 5 and B at step 6, but D needs B's job file. Name the fixture path D's own exams use for the job commitment, since B's real channel is absent until step 6.
- **N5.** "Stress re-review" and `review_pending` are used interchangeably. `review_pending` is written before every attacker call (`run.py` ~1138), not only re-reviews. Say the §2 rule applies to all of them.
- **N6.** Heilmeier: objective, risk, cost (honest, with the planning range), timeline (5–8 days) and exams are all present. Impact is one sentence; that is enough.

## What passed

- **Contract compatibility.**
  - D calls `await_lease` for writer and stress reservations, passes `lease=lease`, and never calls bare `admit()`.
  - `settle` runs once on resume, before any call, in the case ledger, with the `settled` flag in the same checkpoint.
  - It is idempotent on `wait_id` and event IDs.
  - It books only the missing usage or a conservative gap. The $10 example is arithmetically right.
  - All six §5 counters are exempt, and B's reviewed wait backstops are kept.
  - Merge order and flag handling are stated correctly, and no owned contract shape is changed.
- **Diagnosis.**
  - The family rule (the slot's `reviewer` family) is right: in all 8 rotation slots the reviewer differs from the writer and the strong calibrator.
  - The strict schema is bound to a checkpoint hash.
  - The `factory_bug` record fields and the operation-ID routing are specified.
- **Extension mechanism.**
  - Gate order matches `run.py:GATES` (G16 before G8, G17 after G10, G12 excluded).
  - The first-extension predicate is code-checkable.
  - `late_recovery.invalidate` and `stop_defect` pop only the named gate keys, so `extension-history.json` survives repairs.
  - Same-version comparison with lazy rebasing and "regression = valid entry pass fails" is sound.
  - Repairs are zero inside an extension, one writer per extension, and freshness-author and final-fix writers are excluded.
- **Cost honesty.** The design deletes $15 rather than inventing a replacement, discloses that G10/G16/G17 package cost is unmeasured, and bounds worst case by the commitment. The user's allowance-deletion preference is cited, and the $15 deletion is deferred to the ENGINEERING amendment at implementation.
- **Single-path doc.** The retry, exhaustion, unknown-outcome, batch-record and approval lines are updated and agree with stream D.
- **Row discipline.** The rows stay open until real-artifact tests exist.

**Verdict: NOT PASS.** Fix B1. Address M1–M8 in the same revision (M1, M2 and M6 are required for the zero-decision rule). Then a round 4 should confirm. No finding asks to change an owned interface shape or reopen an accepted choice.


## Elephant resolution

All findings accepted; none rejected. B1: inventory now includes restart.py’s
three-retry, priced-cap and original-$50 guards (A-owned); stress rereview/eight
infra/diagnostic guards (D); holder cohort cap (B-owned); carry_over’s legacy
allowance admission (D); and old TTL/preparation count enforcement (B-owned).
All minimal cross-owner edits are named. The shared runner keeps optional
numeric max_cost for bin/run-exam’s unchanged $5 owner cap; factory disables
it only with validated job authority. README/test/search expectations distinguish
factory admission from the separate exam-owner control.

M1: named four exhaustion states, diagnosis replaces founder_ruling/raised_limits
for them; preserve stop emissions while deleting only builder-precheck and its
G1/early final-fix calls. Active-ID extension is not a fungible human round grant.
M2: validated job authority is the single effective source through args, card,
recovery_config, runtime forwarding, in-call guard, coordinator and restart.
M3: accumulate full observed event totals before reclassifying the role breakdown,
so classified costs cannot reappear as legacy_unattributed. M4: per-case RLock
before admission, not concurrent_roles mutation; only mechanical work overlaps,
G10 wall time can approach sum not max, measured impact unknown. Single-path
wording follows it. M5: zero-work exhaustion retires the replacement chain.
M6: V2 is additive to all V1 fields; binding hash supplements binding; saved
round-limit and resume clamp validate the active extension’s exact round.
M7: route-maxima vs real-receipt report and writer max<=ordinary limit are an E/A
qualification prerequisite before enabling D; fresh insufficient money does not
spawn replacements. M8: explicit list of existing tests and expectations to
update, retaining unchanged exam-owner test coverage.

Nits: lock before await, provider_wait_deadline vs retired_batch_bound,
money_wait belongs to B’s proposed contract, authored job configuration fixture
paired with a real practice bundle, and every review_pending uses D admission.
Also specify writer completion before the wrapper’s automatic checkpoint, not
only before G1. No objections/rejections remain; round 4 verifies the revision.
