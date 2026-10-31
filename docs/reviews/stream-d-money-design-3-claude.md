# Goldfish design review 3 (Claude rerun): stream D item 3, money cleanup

Reviewer: a fresh Claude general-purpose subagent with no conversation
history, read-only, against 32eac28. It was used because the DeepSeek round 3
returned no final report (`stream-d-money-design-3.md`). A server restart
interrupted it once, and it was resumed with the same brief. Final report
below, verbatim.

---

**Verdict: FAIL.** The B1 fix holds, but the M1 fix does not. I reviewed the committed design at 32eac28 and read the drafts only to check it can be built.

### Blockers

**B1. The marker kept on a failed stop is deleted in the same call** (budget.py:1230–1235 and :313–314; model_runtime.py:461–463). On a failed stop (`cancellation-failed:`), `_run_budgeted` appends the bound marker. Control then returns to `_call`'s finally block, which always runs `complete_invocation` → `_settle_leaf`. Under the new design `_settle_leaf` runs on every receipt, and its last statement drops every marker with that `invocation_id`. The design says both things: "a failed stop keeps the bound marker" and "complete_invocation … also removes the marker bound to that invocation".
- Scenario: a Claude writer hits `timeout`, the SIGKILL fails, the marker is written, and microseconds later `complete_invocation` removes it. The case total reads as known, so the claim that it "fails closed" is false.
- A second hole: a stop that fails in the outer `finally` (budget.py:1248–1256), after `stalled`, `money_wait`, `cancelled`, `process_error` or `zero_tokens`, never adds a marker at all.
- No test covers either path.
- The money exposure is actually bounded by the gate. `model_call_gate.enforce` closes the gate on exit, `Allowance.reserve` refuses requests once closed, and the gate's cap is `lease.max_usd`, which equals the reservation maximum. So the simplest fix is to delete the exception and name the gate as the bound. If you keep a durable marker instead, note two things: `reconcile_reservations` removes it at the next call, and `batch_holder._extends` (:412–417) then refuses later generations, because the row is `estimated`, not `settled`.

### Majors

**M1. Row 21's "next admission proceeds" holds only because maxima are patched.** The draft test patches `invocation_maximum` to $2 and `route_maximum` to synthetic values. The real Claude lease maximum is $50 (token_prices.py:95, `claude_gate_maximum`). With real values, one Claude blip with no assistant usage is charged $50, the whole default ordinary budget. The next writer admission then raises `budget_exhausted` (run.py:386), the same outcome row 21 describes. The receipt already keeps `cap_used.settled_usd + held_usd`, a gate-bounded figure that is far tighter (about $8.66 per unknown request in test_model_call_maxima). That is what the row's own fix asks for ("settle from retained receipts/provider records"). Use it, and test with the real maximum.

**M2. The committed design leaves out route_receipts inheritance.** `run.main` builds a fresh `c.card` on resume, and the committed text never inherits `route_receipts`.
- Scenario: run 1 makes Claude calls that die before any usage, then stops. On resume those receipts are gone, `actual_model_work` reads False, and no replacement is derived.
- The draft fixes this at run.py:2856 and checks it in the test. The design must name that change and its test.
- "Saved cards carry no route_receipts" is true of the artifacts, not of the resume path.

**M3. The process-start evidence in the test is authored.** The settlement test stubs `_invoke` and sets `model_process_state['started'] = True` itself. So it never runs `on_started` (budget.py:1089), the reset to `denied` (model_runtime.py:413), or the changed marker branch (budget.py:1230). The "started outcome" assertion is therefore tautological. Use real `run_budgeted` with an emitter subprocess, as the row-8 test already does.

### Nits

- **N1** (model_runtime.py:461–464): `receipt_row.update` runs after `complete_invocation`. If accounting raises (for example `usage_event_shared`), a started call stays `admitted` and reads as no work. Update the row first.
- **N2:** if the runner is SIGKILLed mid-call, the in-memory receipt is lost, because cards are checkpointed only at quiescent boundaries (durable_checkpoint.py). The reservation becomes `estimated` with no start evidence, so replacement is wrongly withheld. This is rare.
- **N3** (run.py:3003 vs the g11 branch): a direct run with `--batch-release-sha256` and `--audit-g11` dies with a TypeError at g11_review.py:105 (`min(None, …)`). `batch.bind` blocks this and it fails closed, but `p.error` would be clearer.
- **N4** (coordinator.py:119–121): a batch card that stops before its first authorized `update_case_budget` has `max_cost` None and no `ordinary_limit_usd`, so it stops with "missing original limit". This is unreachable (launch.sh:494) and fails closed.
- **N5:** row 8's wording is still true for non-batch runs. Narrow it to batch jobs when closing it.
- **N6:** inherited `route_receipts` grow without bound, to thousands of rows on a 5813be-scale card.

### Answers

1. **Row 8:** yes for batch jobs. The test uses the real 5813be ledger and the real accountant, and the changed-stage set is checked. **Row 21:** the literal "total unknown" closes for bound reservations, but the proof uses authored maxima (M1). The row's own evidence, the attempt-6 Codex ledger with an unbound legacy marker, is outside scope ($33 import), and the Rows paragraph should say so.
2. **Receipts:**
   - In production a receipt cannot read `done` or `interrupted` without a started process. Start is flagged only after `Popen`, and a call that never started is reset to `denied`. `done` after that reset is reachable only through a stubbed `_invoke`.
   - Real work can read as zero in three cases: a resume under the committed design (M2), a runner kill (N2), and an accounting exception (N1).
3. **Process past its maximum:** no process can spend past its maximum, because the gate enforces the cap and closes on exit. But no failed stop leaves a lasting marker, which contradicts the design (B1).
4. **`max_cost` None:** safe. Every consumer either skips it for factory jobs, records None, or fails closed (N3, N4).
5. **Anything else blocking:** nothing beyond B1. M1–M3 must be fixed before diff review.

### Files read

- Standards and reviews: tools/egm/agents/{zoom_out,design_critic,implementation_readiness}.md; tools/egm/document_standards/{heilmeier,implementation-readiness}-standard.md; docs/ENGINEERING.md; docs/murphy-register.md (rows 8, 21); docs/designs/stream-d.md (lines 698–773 and 1568–2015); docs/reviews/stream-d-money-design-2.md.
- Factory code: factory/{model_runtime,budget,diagnosis,run,batch,batch_service,batch_holder,batch_accounting,gate_state,coordinator,model_call_gate,token_prices,model_router,job_config,durable_checkpoint,diagnosis_dispatch,key_holder,restore_ledger}.py; factory/launch.sh.
- Tests and evidence: tests/factory/test_stream_d_runtime.py, test_stream_d_projection.py and test_model_call_maxima.py; results/infrastructure/2026-10-28-codex-login-rotation/report.md.

---

## Elephant response

Every finding is accepted and fixed in the design. Nothing was rejected.

- **B1, fixed by deletion.** The failed-stop exception is gone. The design
  names the closed gate as the bound.
- **M1, fixed.** `_settle_leaf` charges a receipt without final usage at
  min(reservation maximum, `settled_usd + held_usd`), but only when the gate
  forwarded at least one request. Otherwise it keeps the maximum, because the
  unstarted default snapshot also reads closed with $0. The test uses the
  real OpenRouter and Claude gate maxima. On the committed code it fails
  with `budget_exhausted` and `money_wait`, and on the change it passes.
- **M2, fixed.** `route_receipts` inheritance is now in the design, and the
  test checks it.
- **M3, fixed.** The settlement test now runs the real `_invoke`, the real
  `run_budgeted` with a subprocess emitter (which fires `on_started`) and the
  real `Allowance` reserve, close and snapshot.
- **N1, fixed.** The outcome is recorded before accounting. **N2:** accepted
  as a known gap. **N3, fixed.** `run.main` refuses a G11 audit on a batch
  job. **N4:** noted, unreachable. **N5:** row 8 is narrowed when it closes.
  **N6:** noted.
- **Row 21 scope.** The design's Rows paragraph now says that unbound legacy
  markers stay on the $33 import path.

Because the verdict was FAIL, a fresh design review 4 follows.
