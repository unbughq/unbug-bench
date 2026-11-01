# Goldfish DESIGN review — `stream-d-factory-bug-attribution.md` @ `975b1ed`

Mode: REVIEW (fresh, read-only). Binding text: Review 5, design lines 321–402. Reviews 1–4 and their M1–M3/N1–N3 dispositions are treated as *unverified claims*, not precedent.

## Verdict: **NOT PASSING**

Review 5 fixed the *shape* of the three objections but not the *mechanism*. Four of the six corrections still have no implementable seam in the code they touch, and one of them (M1) is provably false at the second hold. The design is not yet a specification an implementer can follow without inventing policy.

---

## Blockers

### B1 — M1 is false: the second hold re-claims the first finding's operations
**Design:** 325–332 ("empty eligible set for the replay attempt … empty second finding").
**Code:** `diagnosis.py:344–345` builds each finding under a *fresh* `exhaustion_id` with its own `eligible_operation_ids`/`failure_receipts`. `_write_input_tree` (`diagnosis.py:478–545`, names tuple 523–527) freezes **the whole `work/factory-failures` directory**, so the *original* attempt's schema-1 record is copied into every later hold's input tree. `eligible()` (design 78–83) has no exclusion for operations already in a v2 waste record. `reclassify_factory_bug` (`budget.py:423–449`) appends, then `case_spending` → `_spending` rejects any operation overlap (`budget.py:505–521`), so the transaction rolls back and raises `invalid_waste_attribution`.

Net: hold #2 does not get "an empty eligible set" — it gets a **non-empty, overlapping** set and the hold fails. Same defect fires for two distinct bugs in one batch. M1's test ("empty second finding") cannot pass as written.

**Required fix:** make eligibility finding-scoped: `eligible(evidence_root, case, finding_id)` excludes operations already attributed by a *different* finding's v2 record in the frozen ledger (excluding only *other* finding_ids, so `_read_factory_bug_finding`'s recomputation still equals the stored set for finding #1 — otherwise B2's equality check breaks on restore). Pin that classify treats an all-already-attributed eligible set as "no new record, hold succeeds". Add a test for two sequential holds and two same-batch holds.

### B2 — M2's held terminal is clobbered by the generic `BudgetError` handler
**Design:** 336–340, 352 ("Preserve factory_bug_held … held markers unchanged").
**Code:** `_complete_factory_bug` writes `terminal_stop='factory_bug_held'` (`B diagnosis.py:315`). Phase 3 then raises `money_wait` (M2 line 338) or `usage_reconciliation_while_active` (M3 line 376–377) from inside `resume_factory_bug`, which `run.py:3399–3407` catches generically:

```python
c.card['terminal_stop'] = 'paused' if isinstance(error, PauseRequested) else str(error)
c.exhaustion_occurred = ... or isinstance(error, BudgetError)
```

So the card ends at `terminal_stop='money_wait'`: the held marker is gone, contradicting design line 268 ("Never clear the held card before attribution succeeds") and the stated test. `record_exhaustion` (`diagnosis.py:121–144`, invoked at `run.py:3133`) passes its `factory_bug_held` guard and then `_trigger('money_wait')` is False, so no new exhaustion is minted — but the card is already wrong.

The sentence "The dispatcher returns its ordinary checkpoint refusal" (line 341) does not help: in B, `_dispatch` returning `False` means *continue with ordinary work*, not *stop* (`diagnosis_dispatch.py:292`, `run.py:3344–3346`). No return value expresses "held".

**Required fix:** name the seam. Either a dedicated `HeldWait`/`AttributionPending` exception that `run.py` maps to "write `factory_bug_held`, do not set `exhaustion_occurred`", or have `resume_factory_bug` catch its own `money_wait`/guard failures, rewrite the card, and return the refusal. Same treatment for `invalid_waste_attribution`/`waste_attribution_mismatch` raised after a durable admission.

### B3 — `reclassify_factory_bug` forbids the growth the design mandates
**Design:** 119–126 ("A v2 update may only grow operation_ids … grow event_ids").
**Code:** `budget.py:437–441`. The existing-record branch compares an identity tuple that **includes `operation_ids`** and raises `waste_attribution_mismatch` on any difference. Growth is therefore rejected at the very function the design names as the v2 write authority. Design line 387 only assigns changes to `_spending`; it never says this branch is replaced by the grow-and-validate rules.

**Required fix:** state that `reclassify_factory_bug`'s existing-record path becomes version-aware: v1 keeps the current identity equality; v2 validates monotone growth (superset `operation_ids`, consistent `event_ids`, single null→value resume-pair transition) and reruns `case_spending` in the same transaction.

### B4 — M3's drain is attached to a scope that does not exist
**Design:** 357–363 ("For factory attempt scopes only … On scope teardown … wait for admitted requests").
**Code:** `owner_server` is a `@contextmanager` (`exam_responder.py:66–193`) consumed per calibrator call at `run.py:2666`: `with channel as instruction: model_call(...)`. Its `finally` (179–192) does `cancel.set(); server.shutdown(); thread.join(timeout=1); server.server_close()` — i.e. it tears down **immediately after the model call**, long before `GatePipeline.check`/`evaluate`. `daemon_threads = True` and `block_on_close = False` mean in-flight `do_POST` threads keep running detached, with no registry (`exam_responder.py:174–176`).

So M3's test ("owner invocation finishes after gate evaluation but within drain") is impossible at that location, and "one 30-second deadline for the whole drain" has no owner. Also unspecified: `shutdown()` must complete before snapshotting; registration must precede `super().process_request`; and how a drain-timeout `InvalidInfra` raised from `finally` interacts with an in-flight `BudgetError`/`CaseProblem`.

**Required fix:** pick one. Either (a) move the owner endpoint to attempt scope (register the server with `c` at scope entry, drain at scope exit, register each request in `process_request` under a lock before the thread starts), or (b) keep per-call endpoints and say the drain is per-call, with the attempt refusing publication if any call's drain timed out. Then pin exception precedence (in-flight error wins; drain failure attaches as evidence, not a mask) and that the snapshot is taken only after `shutdown()` + full join.

### B5 — Phase 3 silently drops B's ledger-active refusal and `resume_provider_wait`
**Design:** 260–270 moves prepare-dispatch/lock/guard/reconcile/classify into `resume_factory_bug`.
**Code:** B's `_dispatch` runs `if d.resume_factory_bug(c): return False` at line 292 — *before* `prepare_dispatch`, the lock, `resume_provider_wait(c)`, `reconcile_reservations`, and the `ledger.get('active') or pending → usage_reconciliation_pending` check at 308–315. The design reproduces the lock, the active-*call* guard and the reconcile, but not the **ledger** `active`/pending check, and it does not say whether `resume_provider_wait` runs. `archive_pilot_state` (`run.py:2727–2743`) kills pilots but never clears `ledger['active']`.

**Required fix:** add the same `ledger.get('active')` / pending-reservation refusal inside phase 3 before reconciliation, and state explicitly whether `resume_provider_wait(c)` is called on the held-resume path (and with what card).

---

## Major

**M1-a (F) — which set does `classify` use?** Design 86–93 normalizes `affected_operations` to the intersection; 106–113 then says "classify only operations whose reservations …". It never says whether the candidate set is `finding['eligible_operation_ids']` or the model-narrowed `diagnosis.factory_bug.affected_operations`. If it is the latter, a model can shrink waste attribution, which contradicts the code-derived-attribution premise. Pin: classify uses the finding's code-derived eligible set; narrowing affects only the diagnosis narrative. (`diagnosis.py:219` currently forces `affected_operations=[]`; say that this line changes to the intersection.)

**M2-a (G) — `_spending` v2 branches are named only by reference.** `budget.py:500–521` requires v1-only `fix_commit`/`fix_attribution_sha256` and `bool(ids)`, and compares the amount through `usd(...)`. Design line 111 requires v2 records with empty `event_ids` and zero amount, and 104 requires a nine-decimal *string* amount. Name each change: drop the v1-only field checks for v2, allow empty `event_ids` when `operation_ids` are all zero-cost settled, compare the amount as a string/Decimal, and define "unknown versions refuse" (hard `invalid_waste_attribution`, not `unpriced += 1`, or say which). Also require a single shared validator used by both `_spending` and `reclassify_factory_bug` so the two cannot drift.

**M3-a — late settlement has no ledger source.** 148–159 says classify grows the record after scope exit, and 111–113 says estimated operations stay pending in the immutable finding. But `eligible()` and B2 read only the **frozen** tree (line 244), while settlement lands in the **live** ledger. Nothing states that a later re-dispatch re-runs classify against the *live* ledger keyed by the finding's frozen operation identities. Without that sentence the M2 "subsequent final receipt may allow the same admission to complete normally" path cannot move the cost into waste, and the estimate stays ordinary spend forever.

**M4-a — "request context retains the original closed attempt" has no site.** M3 lines 347–350 assume a closed-attempt guard that refuses new reservations. No such guard exists in `budget`/`reconcile_reservations`. Name where the closed attempt id lives and where the refusal is raised, or drop the claim and state plainly that late reservations are ordinary (line 349 already says that) without asserting an unbuilt mechanism.

---

## Verified correct (do not re-litigate)

- One-proof exclusivity *intent* is coherent: a replay `InvalidInfra` publishing only the schema-2 receipt and never a schema-1 record is the right rule; the failure is B1/B3, not the principle.
- `_settle_leaf` is the correct site for the v2 string branch (`budget.py:328–335` is float-only today).
- B's return contract is accurately described: `resume_factory_bug → True`, `_dispatch → False`, `run.main` routes only `type(routed) is int` (`run.py:3344–3346`). Confirmed, but see B2 for what "returns False" cannot express.
- N3's precondition is real: `job_authority.read` rejects an expired deadline with `retired_batch_bound` (`job_authority.py:46–49`), and `_resume_bindings` does call `read(cursor, cursor)`. The limitation is honestly inherited, not invented.
- `schedule_waits` resubmits only `terminal_stop == 'provider_wait'` (`batch_holder.py:412–426`), so a held card is not auto-resubmitted — the "no scheduler loop" claim holds.
- No row closures: `new-stream-d-outcome-routes-1` and row 9 remain open, consistent with the brief.

---

## Answers to the five verification questions

| Question | Answer |
|---|---|
| One replay proof / immutable finding | Intent yes, mechanism **no** (B1, B3). |
| Explicit held terminal for never-final receipts | **No** — `run.py` clobbers the held label (B2). |
| Bounded owner request-thread drain | **No** — attached to the wrong scope, no registry (B4). |
| v2 `_spending` and B return/deadline contracts | `_spending` under-specified (M2-a); return contract accurate; deadline precondition accurate. |
| Design implementable without invented policy | **No** — M1-a, M3-a, M4-a still require the implementer to choose policy. |

I did not write a review record under `docs/reviews/` because the brief is read-only; say the word and I will save this verbatim as `...-design-6.md`.

*Skipped: re-reading Reviews 1–4 prose beyond their recorded dispositions; did not run any code or tests. Risk: B1 and B2 are the two failures that will show up as hard errors the first time the integrated exam runs two holds, so they are not deferrable.*

## Elephant disposition

All B1–B5 and M1-a–M4-a are accepted. Rewrite the design as one specification; no blocker is rejected. Reconciliation ordering follows the actual B code: remaining pending rows are checked after reconciliation, with a pre-reconciliation active-ledger guard. Fresh review required before implementation.
