# Goldfish design review 2: stream D item 3, money cleanup and settlement

Reviewer: `openrouter/~deepseek/deepseek-pro-latest` on the `opencode` provider
instance (T3 `delegate_task`), fresh context, read-only. Scope: the same
section at 320f9ae, plus the round-1 responses. Final report below, verbatim.

---

I've read the persona files, standards, ENGINEERING.md, the Murphy register, the round-1 review, the full design section, and all cited code (committed HEAD via `git show`, since the working tree carries the draft). Verdict follows.

# Goldfish design review 2 — "Third increment: money cleanup and settlement"

## Verdict: **FAIL** (one new blocker)

The round-1 findings B1/M2/N1–N3 are genuinely resolved, and M1's *narrow* claim (delete the marker to close the "total unknown → `money_wait`" window) is technically correct. But the fix deletes a factory marker that has a second, undocumented consumer — `actual_model_work` — and the design never accounts for it.

## Blockers

**B1 — Deleting the factory marker silently breaks `actual_model_work`'s process-start evidence.** `diagnosis.actual_model_work` (diagnosis.py:93–100) returns `bool(events or unpriced_invocations)`; its docstring states "Reservations and conservative gaps alone are not process-start evidence." The design's own increment-3 text (stream-d.md:1095–1096) says "an actually invoked zero-cash subscription process is work," and the replacement rule (stream-d.md:22–24) explicitly includes "a zero-cash subscription invocation."

The change makes those two statements contradictory. A claude/codex subscription call writes **no ledger event until its `result`/`turn.completed` usage arrives** (budget.py `consume_claude`/`consume_codex` only call `subscription_usage` on the terminal event). So a call that streams output then dies before usage yields: zero `events`, zero markers (removed by this design), and — via the new `complete_invocation` — an `estimated` reservation. That is byte-for-byte the shape `test_bare_denied_or_estimated_reservation_is_zero_work` (test_stream_d_projection.py:89–99) asserts is **zero work**: it plants `{'state':'estimated','estimated_gap_usd':'10.000000000'}` and asserts `actual_model_work` is False.

**Concrete failure:** a factory case whose writer (claude) repeatedly errors or is killed before producing a `result` exhausts its money via conservative estimated charges, with no event ever recorded. `actual_model_work` returns False → `pending_projection` sets `replacement_eligible=False` → B derives no replacement, violating the design's own "made at least one model invocation" rule. The design must either (a) keep the marker and make `_spending` (budget.py:437) stop counting a *reservation-bound* marker as unknown, or (b) teach `actual_model_work` to treat a non-denied estimated gap as work. Neither is mentioned.

## Majors

**M1 — The cancellation-failure path loses its "durable unknown-usage record."** The committed `_run_budgeted` cancellation block (budget.py:1153–1171) adds `starts.add('cancellation-failed:'+invocation)` (1158) precisely so the marker survives a failed stop, and its comment (1155–1156) reads "A failed stop cannot bypass the durable unknown-usage record below." The design removes that record for factory calls. When `stop_process()` fails the process may still be running; the reservation maximum (`invocation_maximum`) bounds a *stopped* call's requests, not a live runaway that was never killed. (The buffered-tail branch, 1203–1205, is safe — the process *is* stopped there, so the maximum bounds it.) The design neither addresses this path nor updates the now-false comment. Recommend keeping a factory-side unknown marker in this branch only, or asserting the process is confirmed-dead before dropping the record.

## Nits

**N1 —** Comment at budget.py:1155–1156 now asserts something the change falsifies; update it.
**N2 —** Line references drift (design says `check_limits` at budget.py:845; it's ~833–844; `pending_call` at run.py:385–387 is ~350). Cosmetic.

## Round-1 responses: do they hold?

- **B1 — holds.** Verified: every direct `complete_invocation` caller in `test_batch_accounting.py` (82,135,141,169), `test_stream_d_coverage.py` (85,89,154,176) and `test_router_cheap_maxima.py` (122,125) passes a `final_usage_known=True` receipt, so the draft's `_settle_leaf`-always change is a no-op for them. The one test that *does* change, `test_stream_accountant_links_unknown_usage_and_settles_once_above_five_dollars`, is correctly named and re-specified.
- **M1 — the fix mechanism is right for its stated symptom, but over-broad** (see B1/M1 above).
- **M2 — holds.** The authored `batch-release.json` is contract configuration like `job-money.json`; the row-8 proof rests on the real 5813be ledger, practice case and streaming accountant (`test_factory_call_over_old_paid_cap_completes_and_non_factory_stops`). `a.max_cost=None` placement is verified correct (before `c.card`/`recovery_config` build, run.py:2999–3003).
- **N1/N2/N3 — hold** (N2's `--continue-g11-review` is in the draft's `bind` forbidden set).

## Row 8/21 test plan (question 3)

Adequate for the *literal* rows: both use the real 5813be ledger + practice case through the real runtime/router/accountant with authored outputs, matching the row-10 closure standard. But the plan does **not** test the `actual_model_work` side effect, and the untouched `test_bare_denied_or_estimated_reservation_is_zero_work` now silently misclassifies real work. The design cannot pass until that regression is closed or explicitly accepted.

## Files read

`tools/egm/agents/{zoom_out,design_critic,implementation_readiness}.md`; `tools/egm/document_standards/{heilmeier,implementation-readiness}-standard.md`; `docs/ENGINEERING.md`; `docs/murphy-register.md`; `docs/reviews/stream-d-money-design-1.md`; `docs/designs/stream-d.md`; `factory/{budget,model_runtime,run,batch,diagnosis,batch_holder,batch_accounting,gate_state,coordinator,launch.sh}.py` (HEAD via `git show`); `tests/factory/{test_stream_d_runtime,test_batch_accounting,test_stream_d_coverage,test_router_cheap_maxima,test_stream_d_projection}.py`.

Skipped: did not run the suite (read-only); did not trace every `restart.py`/`carry_over.py` `max_cost` call site. Key risk: the `actual_model_work` regression is load-bearing for replacement derivation and must be fixed before merge.

---

## Elephant response

Both findings are accepted and fixed in the design. Nothing was rejected.

- **B1, fixed.** `diagnosis.actual_model_work` also counts a route receipt
  whose outcome is `done` or `interrupted`. The runtime resets an unstarted
  call to `denied`, so those two outcomes mean a process started. The gap
  predates this change: `finalize_accounting` already reconciles bound
  markers away before `record_exhaustion` reads them. The fix covers both.
  The bare-estimate projection test keeps its zero-work assertion and adds
  the started case. The settlement test checks the producer side.
- **M1, fixed.** A failed stop keeps the bound factory marker, so the total
  stays unknown and fails closed.
- **N1:** the comment is true again. **N2:** line references are approximate.

Because the verdict was FAIL, a fresh design review 3 follows.
