# Goldfish design review: `docs/designs/router-item8-prereqs.md` (review 2)

**Mode:** REVIEW. **Personas:** zoom_out, design_critic, implementation_readiness. **Standards:** heilmeier-standard.md, implementation-readiness-standard.md.

**Files read:**
- docs/ENGINEERING.md, the three persona files and both standards.
- The design, and the review it answers: docs/reviews/router-item8-prereqs-design-1.md.
- docs/designs/stream-d.md, the item 8 prerequisites around lines 3394–3540.
- tests/factory/test_model_call_maxima.py: `MaximaTests` lines 1–75, 200–260 and 330–475, plus all of `ProtocolTests`.
- factory/model_call_gate.py: `Allowance.finish/snapshot/close`, `Usage`, `HOP_HEADERS`, `Handler.do_POST`, `Gate`, `_wall_access`, `enforce`.
- factory/model_runtime.py: `call`, `dispatch`, the `_call` receipt writer at lines 340–500, and the `_invoke` gate block at lines 620–682.
- factory/budget.py: `ledger_transaction`, `_gate_bound`, `_settle_leaf`, `settle`, `complete_invocation`, `reconcile_reservations`, and the `cancelled` raise at line 797.
- factory/model_router.py `running`, and docs/murphy-register.md rows 9, 21 and 39.

## Verdict: PASS. 0 blockers, 0 majors, 6 nits.

All three blockers and both majors from review 1 are fixed in the text, and I checked each fix against the code. The expected values match what the code produces. The test as designed would fail if any of these broke:
- `Allowance.close` stops shutting down the upstream socket;
- the in-flight hold stops being retained;
- the runtime receipt writer stops treating unknown requests as non-final usage.

Nothing left open blocks implementation.

---

## Checking review 1's findings

### B1, existing coverage: fixed
"What exists today" (lines 26–35) names the four tests review 1 listed, and gives each one's scope correctly. The change is now narrowed to the window none of them covers: the gate has forwarded the request, sent the headers, and is relaying the response (`sent=True` in `Handler.do_POST`). The settlement assertions that remain are justified as a delta at lines 81–83: they go through the real runtime receipt writer and the automatic `complete_invocation`, not a hand-written receipt. The list misses one relevant test (N1 below), but that does not change the gap.

### B2, seam and trigger: fixed
I traced the chain in the code and it is accurate.
- **Test name:** given (line 39).
- **Trigger:** the fake `run_budgeted` raises `BudgetError('cancelled')` inside `enforce`. That runs `_wall_access`'s finally, then `Gate.close` (model_call_gate.py:580), then `Allowance.close`, which retains the active hold, adds one unknown and shuts down the upstream connections. `enforce`'s finally then writes the snapshot into `cap_used`.
- **Receipt and settlement:** control returns to `_call`'s finally (model_runtime.py:441–473). It writes the receipt with `final_usage_known` False, because `unknown_requests` is non-zero, and then calls `complete_invocation`.
- **Realism:** `'cancelled'` is the label real `run_budgeted` raises (budget.py:797). In `_call` it gets no `failure` mapping, so it is re-raised.
- **Outcome:** because `on_started` is called, `model_process_state['started']` is True and the outcome stays `interrupted`, not `denied`.
- **Settlement calls:** `reconcile_reservations` twice, each byte-identical. This holds: `ledger_transaction` only writes when the sorted JSON changes (budget.py:116). `_settle_leaf` on an estimated, non-final row recomputes the same gap. `unpriced_invocations` was already added by `complete_invocation`.
- **Wording:** the design correctly refuses to claim that `cancel.set` alone interrupts a socket.

### B3, stream shape, fixture and values: fixed
- **Fixture:** synthetic counters, labelled as synthetic, with the replay dropped.
- **Withhold point:** after the 200 headers and `message_start`. `message_delta` and `message_stop` are sent only on release.
- **Fixture extension:** an optional object that defaults to None, so the other tests using `setUp` are unchanged.
- **Values:** I checked them against the code and all match.
  - Snapshot: forwarded 1, validated 0, unknown 1, in_flight 0, settled 0, held 8.655360 (one 32768-token request, the same as the 43.2768 / 5 in the existing tests), closed True, exhausted False. 8.65536 is well under $50, so `enforce` does not convert the exit to `model_call_cap`.
  - Ledger: `_gate_bound` = 0 + 8.65536, `min(50, ·)` = 8.655360000, booked 0, state estimated.
- **Bounded completion:** asserted before release, within 5 s. The gate and client timeouts are 30 s, and the gate's downstream socket timeout is `min(15, remaining)`, so the 5 s check cannot pass just because a timeout expired.
- **Late-refund check:** bytes are compared before and after release, the closed gate's `reserve` returns None, and the upstream's late-write attempt is waited for.

### M1, saved counters: fixed
The replay was dropped, and the design says why (line 46).

### M2, Heilmeier gaps and numbering: fixed
- **Objective:** stated plainly (lines 3–5).
- **Impact and order:** lines 21–24.
- **Risks, cost and timeline:** lines 92–98, which name the scheduling or hang risk and its mitigations, an estimate of one session plus reviews, and zero provider spend.
- **Checkpoints:** the focused module, then the full suite, then the diff review.
- **Numbering:** one ordered list with named items. The conflicting "item 4" references are gone.

### Review 1's nits
- **N2:** fixed. The design uses `new-router-item8-prereqs-<n>` (line 88).
- **N3:** fixed. The log and record path pattern is given (line 102).
- **N1:** deferred with a reason: there is no profile API to parameterise yet. Since it was a nit, that is acceptable.

---

## Remaining findings (all nits)

### N1. Nit: the closest existing test is not cited
**Personas:** zoom_out (reuse), Heilmeier (state of the art)
**Scope:** "What exists today", lines 28–35

`ProtocolTests.test_successful_cli_cannot_hide_gate_unknown_usage_in_real_runtime_receipt` (test file around 442–471) already does the following:
- runs the real `ModelRuntime.call` through the real HTTP gate and the loopback upstream from this same `setUp`;
- uses a fake `run_budgeted` that makes a real client request;
- asserts that the runtime-written receipt has `final_usage_known` False, `unknown_requests` 1 and `closed` True;
- asserts the router has no live lease.

Its scope differs from the new test: it uses a malformed but complete response, has no job binding (the ledger stays unchanged), and closes nothing mid-response. It is still the closest precedent, and it lives in the class the new test joins. Cite it as existing coverage, and as the template for the client and runtime wiring. Combine it with the dispatch test's job-binding pattern.

### N2. Nit: the client sees a clean EOF, never `IncompleteRead`
**Persona:** design_critic (faulty assumption)
**Scope:** lines 41–42 and 61

`HOP_HEADERS` (model_call_gate.py:40) includes `content-length`, so the gate strips the upstream Content-Length. Instead it sends `Connection: close` with no length. The client therefore reads the prefix and then a normal EOF, and "or IncompleteRead" cannot happen. The upstream Content-Length only bounds the gate's own `read1`.

The test's real observable is already stated: the client received exactly the `message_start` bytes. Drop the `IncompleteRead` alternative, or note that the gate strips the length.

### N3. Nit: name the exception and timeout parameters the test uses
**Persona:** implementation_readiness
**Scope:** lines 48–66

- The test should state that `runtime.call` raises `BudgetError` matching `^cancelled$`. That error is re-raised because `_call` maps it to no `failure`.
- It should state that the 30 s limit comes from `runtime.call(..., timeout=30)`. The dispatch test's parsed args default to a 4-hour `agent_timeout`.
- It should state that the gate instance is observed through `kw['cancel']`, which `_invoke` passes to `run_budgeted` (model_runtime.py:652).

These are derivable from the code, but writing them down removes guesswork.

### N4. Nit: "blocked in response.read1" is not strictly guaranteed
**Persona:** design_critic
**Scope:** line 35 and lines 52–55

Waiting until the client has the full prefix proves the handler has relayed `message_start`. It does not prove the handler has gone back into `read1`. If `close` lands between the write and the next `read1`, the call returns empty, or raises `ValueError` on the closed reader, which is caught at model_call_gate.py:568. The outcome is the same either way, and both cases are in the `sent=True` window. Either describe the window as "after headers and prefix were relayed", or accept the small ambiguity explicitly.

### N5. Nit: list the files touched explicitly
**Standard:** implementation-readiness (target scope)
**Scope:** "Change and exact test"

Add a short list:
- modify `tests/factory/test_model_call_maxima.py`, specifically the `ProtocolTests.setUp` fixture and the new test method;
- create `docs/reports/router-item8-prereqs-suite-<UTC>-<nonce>.log` and its `.md`;
- create the review files;
- no production files.

Also name the fields of the "stalled-response object". From the text they are: a prefix-sent event, a release event, and a late-write-attempted event.

### N6. Nit (optional extra assertion): the interrupted-call record
**Scope:** lines 79–83

Because the error is `cancelled` and the call was invoked, `_call` appends one entry to `c.router_interrupted_calls` with this lease's `call_id` (model_runtime.py:475–479). Asserting exactly one such entry would cover the hand-off to recovery at no extra cost. Optional.

---

## Standards summary

- **Heilmeier:** all eight questions are answered. A few labels remain unexplained ("stream B", "account-2 acceptance"), but the plain objective sentence makes the document readable for a newcomer.
- **Implementation readiness:** the design makes every decision except the trivially derivable ones in N3 and N5. It is one phase, and the codebase stays buildable. The test plan covers the happy path, which is mid-response closure, and the edge cases: late write, reserve after close, and a repeated reconcile.
- **Murphy:** "No row closes" is stated explicitly, with rows 9 and 39 left open and the reason given. Related row 21 is already closed. This is consistent with ENGINEERING §2.

**To proceed:** no blocking finding is open, so implementation may start. N1–N5 are cheap text fixes and can go in the same commit. The diff goldfish should check:
- the client receives exactly the prefix bytes;
- the 5 s completion bound is measured before release;
- release and join happen in `finally`;
- the `setUp` default leaves every existing `ProtocolTests` test unchanged.

---

I'm read-only, so I did not save this file. The writer should save it verbatim as `docs/reviews/router-item8-prereqs-design-2.md`.

## Implementation response

PASS accepted. N1–N5 clarified in design and implementation; N6 included as an
additional assertion. No blockers or rejected findings. The parent's subscription
authority paragraph was added while review was running; the diff reviewer must
also check it against the explicitly supplied parent instruction.
