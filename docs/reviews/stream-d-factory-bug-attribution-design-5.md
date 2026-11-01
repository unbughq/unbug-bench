## Design review — `stream-d-factory-bug-attribution.md` (fresh reviewer, read-only)

**Reviewed:** worktree `t3-21bef30c`, HEAD `3a99fee` (moved forward during review from `ac3115e`; only `docs/reviews/stream-d-outcome-routes-diff-3.md` + `tests/factory/test_stream_d_dispatch.py` were added, design file unchanged since `18c56b9`). Design content: lines 187–319 ("Review 2 corrections") treated as binding and superseding.

**Standards applied:** `docs/ENGINEERING.md` (elephant/goldfish, Murphy register), personas `zoom_out` / `design_critic` / `implementation_readiness`, `heilmeier-standard.md`, `implementation-readiness-standard.md`. Prior findings read verbatim from `docs/reviews/stream-d-factory-bug-attribution-design-2.md`. The unavailable attempts 1/3/4 records were **not** treated as approval, and nothing here relies on them.

**Baseline confirmed (design is not implemented):** no `factory/factory_waste.py`; `_read_factory_bug_finding` still has `eligible_operation_ids != []` / `failure_receipts != []` (`diagnosis.py:329–330`); `_settle_leaf` still unconditionally rewrites `float(usd(...))` with no schema branch (`budget.py:328–335`); `_write_input_tree`'s names tuple (`diagnosis.py:523–527`) contains none of `factory-failures`, `factory-replays`, `job-money.json`, `job-money-history.json`.

---

## Verdict

**PASS — no blocking findings.** Prior B1/B2 and M1–M5 are resolved against actual code. Three new Majors must be folded into the binding section before implementation; none is money-corrupting, and none invalidates the design's core approach.

---

## Prior findings — resolution check

| Prior | Status | Evidence |
|---|---|---|
| **B1** exact reservation/owner join | **Resolved** | Corrections 191–205 specify the five-field element set, byte-equality to the frozen row via `row.get('parent_call_name')`, key = `row.lease_id`, scope case = `c.case_id`, ledger = `c.ledger`, stage/hash code-owned. Matches the real row shape (`budget.py:166–170`, which does carry `parent_call_name`). `money_owner` (200–205) is sourced only from `job_authority.for_case` (`job_authority.py:54–75`), never a card. |
| **B2** empty-set guard / byte-equivalence | **Resolved** | 235–247 removes exactly the `!= []` predicate at `diagnosis.py:329–330`, recomputes from the retained `inputs/` tree with `_input_bytes` no-follow reads, and preserves old empty findings (`[]/[]`) byte-for-byte. The "preexisting empty finding + newly nonempty proof refuses" clause closes the upgrade hole. |
| **M1** three durable phases | **Resolved** | 249–275: hold → durable B admission append → classify inside `resume_factory_bug` after append, before `admitted_card`; only then the scorecard clear. This matches B's actual commit order (`resume_factory_bug`: `history.append` → `atomic_json` → `admitted_card`), so the counter commit point is the append. |
| **M2** `_settle_leaf` v2 | **Resolved** | 292–299 now branches on `schema_version` and forbids `float` for v2, exactly the line 328–335 rewrite. |
| **M3** `resume_scope` precondition | **Resolved** | 222–231 requires the last durable `factory-bug-resumes` entry, full tuple match against `_resume_bindings`' chain, `_read_factory_bug_finding` against the old bound owner, and forbids a same-batch marker. Reuses the helper (no duplicate transition logic). B's chain is the only transition authority. |
| **M4** grow-only v2 predicate | **Resolved** | 279–290 gives the five-field immutable identity, superset-only `operation_ids`, exact settled event union, `estimated_gap_usd == 0`, no cross-record overlap, and keeps pending ops in the finding. Note `reclassify_factory_bug`'s current 7-field identity tuple (`budget.py:440`) includes `operation_ids`, so it must be branched for v2 — the corrections say this ("compares these fields exactly"), which is sufficient. |
| **M5** frozen input allow-list | **Resolved** | 207–220 adds the four names explicitly and keeps "freeze only after ordinary verified install/authentication and reconciliation". `_write_input_tree` is indeed the only producer (`diagnosis.py:523–530`). |
| **N1–N3** infra/stress/owner-thread scope | **Resolved in intent** | 304–319. N3's correction is the source of new Major M3 below. |

---

## New findings

### M1 — Replay-attempt failure proof has two eligible sources and mutates an immutable finding

- **Severity:** Major
- **Affected scope:** design 60–67 (failure record), 88–92 + 235–247 (finding immutability / exact recompute), 148–158 (replay receipt + "classify adds … to the same finding record"), 283–288 (no cross-record overlap), vs `factory/diagnosis.py:322–337`.
- **Finding:** (a) A replay-linked attempt that ends in `InvalidInfra` can satisfy *both* producers: the schema-1 failure record (line 60, "a completed failed attempt publishes one record") **and** the schema-2 replay receipt with `outcome:"invalid-infra"` (line 150). The design never says it is one *or* the other. If both are published, the same reservations become eligible through `eligible()` and through the "additional replay proof" path, and the hold's new record overlaps the previous record — which line 288 forbids and `reclassify_factory_bug` refuses. If only the replay receipt is published (the coherent choice), the new hold's `eligible()` correctly returns `[]` (line 99, "no record and the normal hold") and the cost belongs to the *previous* record — but the design never states that rule. (b) Line 157–158 says classify adds ops to "the same finding record". The finding is immutable and its `eligible_operation_ids`/`failure_receipts` are exactly recomputed (`diagnosis.py:322–337`); writing there would fail the next `_read_factory_bug_finding`. It must be the same **v2 waste record keyed by `finding_id`**, and the scope-exit classify must run before any new hold's `persist_factory_bug` writes a new finding under a new `exhaustion_id`.
- **Requested fix:** add one binding sentence: an `InvalidInfra` on a replay-linked attempt publishes **only** the schema-2 replay receipt (never a schema-1 failure record for the same attempt); its reservations grow the original finding's v2 record at scope-exit classify, and a subsequent hold legitimately has an empty eligible set. Say "the same waste record, never the finding", and pin the order: scope-exit classify → hold persist. Test: replay attempt → `InvalidInfra` → exactly one proof, one record, no overlap, empty second finding.

### M2 — `money_wait` on a never-final estimate is a permanent deadlock, not a wait

- **Severity:** Major
- **Affected scope:** design 113–118 ("retained as pending attribution … retries on hold replay after reconciliation"), 268–270 (`money_wait` before card clearing), vs `factory/budget.py:300–307, 403–420`.
- **Finding:** `reconcile_reservations` synthesizes `final_usage_known: False` when a receipt is missing (`budget.py:417–418`), and `_settle_leaf` keeps `state='estimated'` for any non-final receipt (`budget.py:300–307`). Only a real final receipt can promote the row. So if a failed attempt's receipt never becomes final, phase 3 raises `money_wait` on **every** retry with the same durable admission (no debit consumed), and B's `_resume_bindings` only admits a later batch — so the case can never resume and the ops can never be classified. The design's "retries after reconciliation" is therefore not a recovery path in this branch.
- **Requested fix:** state the terminal explicitly. Either (i) define a finalization step that turns a reconciled, receipt-less reservation into its reserved ceiling with final semantics before classification, or (ii) declare that such a case stops at `factory_bug_held` with `money_wait` and needs operator/new-batch action. Add the test: no receipt ever → one `money_wait`, no new debit, no infinite retry loop.

### M3 — "After all owned child calls have joined" is not true for owner HTTP calls

- **Severity:** Major
- **Affected scope:** design 60–67 and 311–319, vs `factory/exam_responder.py:174–192`, `factory/model_runtime.py:45–52, 415–419`, `factory/run.py:322`.
- **Finding:** the corrections require owner requests to share the tester's attempt via a captured context copy (311–313), but the owner responder's request threads are not joined: `ThreadingHTTPServer`, `daemon_threads = True`, `block_on_close = False`, and only the `serve_forever` thread is joined with `timeout=1` (`exam_responder.py:174–192`). An owner request still in flight when the attempt scope exits records into the shared attempt **after** the receipt was frozen (conservative: that reservation stays ordinary) or is lost, and its name remains in `active_model_calls` (`model_runtime.py:415/419`). Also, phase 3's "assert no active_model_calls" is a bare `assert`; the codebase's guard is `raise BudgetError('usage_reconciliation_while_active')` (`run.py:322`, reused by B at `diagnosis_dispatch.py:295`).
- **Requested fix:** either drain the responder before publishing (join request threads with a bounded wait that fails the attempt as infrastructure, never freezes a partial receipt), or state that a late owner reservation is deliberately left ordinary and cannot appear in the record. Replace the `assert` with the existing `usage_reconciliation_while_active` BudgetError. Test: an owner call that finishes after the gate returns — no crash, no duplicate, no ordinary/waste double count.

---

## Nits

- **N1 — `_spending` is the real v2 acceptance site, and the binding section only names `_settle_leaf`.** `budget.py:505` hard-requires `record.get('schema_version') == 1`; a v2 record therefore makes `_spending` set `unpriced += 1`, and `total_spent_usd` becomes `None` (`budget.py:550`), so `reclassify_factory_bug`'s own check (`budget.py:447`) raises `invalid_waste_attribution` in the same transaction. Line 103 ("budget's shared valuation") does assign the work, but one line in 292–299 should name it: "and `_spending`'s factory-bug branch accepts schema 2 with the same exactness". This fails loudly, not silently.
- **N2 — dispatcher return wording.** "return True to dispatch's ordinary path" (line 266) reads as `_dispatch` returning True. In B, `resume_factory_bug` returns True and `_dispatch` then returns **False** (`diagnosis_dispatch.py:292`), after which `run.py` continues the ordinary path because `dispatch`'s return is only checked for `int` extension ids (`run.py:3341–3347`). Say it that way.
- **N3 — `read(value, value)` still enforces a live batch deadline.** `job_authority.read` rejects `batch_deadline <= now` (`job_authority.py:46–47`), so a historical `money_owner` from a retired batch cannot be shape-validated. This is inherited, not new: B's `_resume_bindings` already calls `read(cursor, cursor)` on every chain entry, so `retired_batch_bound` is raised before D's check. State it as a precondition of cross-batch evidence (carry-over only while the predecessor's deadline is live), or D's "historical receipts remain private evidence" will be read as broader than it is.

---

## Concurrency & safety summary

- **Concurrent attribution:** G10 `copy_context` per submission plus innermost scope is sound; owner-thread propagation is the weak point (M3), because the task receipt's join claim has no join behind it.
- **Exact owner/usage joins:** B1's predicate is now concrete and matches `reserve_invocation`'s real row (`budget.py:166–170`). Ledger-row identity is correctly not treated as a money certificate.
- **Immutable evidence:** frozen-tree discipline is right (`diagnosis.py:322–337`, `523–530`); M1 is the one place immutability wording slips.
- **Late receipts:** grow-only v2 plus the `_settle_leaf` branch are consistent with the current code; M2 is the missing terminal for the no-receipt case.
- **Crash/settlement ordering:** phase 1 history → finding → card, phase 2 append as counter commit, phase 3 append-or-reuse then classify then scorecard clear, all idempotent on `finding_id`. This matches B's actual write order, and the "ledger admitted / scorecard lagging" case resolves correctly because B reuses the existing `admission`.
- **B join:** hook inside `_dispatch` at 292 (before `resume_provider_wait`/`reconcile_reservations`) is the right seam; the return-value nit (N2) is the only ambiguity.

---

## Readiness

Implementation-ready after M1–M3 are written into the binding section and N1–N3 are corrected. The design's code claims about scope placement (`gate_pipeline.check` 38–62), retry policy, G10 submission, frozen-tree names, and the B merge point all check out against the tree.

**Skipped / not checked:** the separate routing-consumer diff; the full suite; live-run artifacts for `new-stream-d-outcome-routes-1`'s "real saved monetary events" closure; and attempts 1/3/4's reviewer records (unavailable, non-approvals). No tests run, no writes made.

**Risk the user must know:** M2 is the one to settle deliberately — a crash that leaves a non-final receipt makes every future resume of that case a permanent `money_wait`, and no test in the current list covers the never-final branch. Secondary: M3's "joined" claim is the only thing standing between an owner straggler and a receipt that silently omits an owned child.

## Elephant disposition

All M1–M3 and N1–N3 are accepted. The next binding revision specifies one replay proof, immutable findings, explicit held terminal for never-final usage, bounded owner draining, the existing active-call refusal, v2 valuation and B return/deadline preconditions. No blocking finding is rejected.
