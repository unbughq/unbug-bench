# Goldfish design review: `docs/designs/router-item8-prereqs.md` (review 1)

**Mode:** REVIEW. **Personas:** zoom_out, design_critic, implementation_readiness. **Standards:** heilmeier-standard.md, implementation-readiness-standard.md.

**Files read:** docs/ENGINEERING.md, the three persona files, both standards, the design, docs/designs/stream-d.md §"Item 8: live qualification and switch-on" (lines 3394–3637), tests/factory/test_model_call_maxima.py (all of it), factory/model_call_gate.py (`Allowance`, `Handler.do_POST`, `Gate`, `enforce`), factory/budget.py `_gate_bound`/`_settle_leaf` (236–310), and factory/model_runtime.py's receipt writer (440–475, 636).

## Verdict: FAIL. 3 blockers, 2 majors, 3 nits.

The direction is sound. An offline, free regression on the existing $50 Claude gate before smaller profiles is a reasonable first increment, and the limits it states (no row closes, synthetic labels, item 8 stays incomplete) are honest. It fails for two reasons. It does not say what the existing tests already prove. And it leaves the seam under test, the trigger, the stream shape and the expected values to the implementer. All three blockers can be fixed with a few paragraphs of text.

---

### B1. Blocker: the existing coverage isn't stated, and half the change duplicates a current test
**Personas:** zoom_out (reinventing the wheel), Heilmeier (state of the art)
**Scope:** "Change", second paragraph (lines 33–36); "Deletions and tests" (lines 45–46)

The second paragraph describes a test that already exists. `test_real_route_maximum_fits_D_decimal_authority_and_unknown_settlement_once` (test_model_call_maxima.py:336–383) already does every part of it:
- it acquires a real admitted router `Lease` through `store.rpc('acquire')`;
- it builds a synthetic authenticated `job_money` binding;
- it closes an `Allowance` with one held request and writes its snapshot into a usage receipt;
- it calls `budget.settle` and asserts the charge equals `settled_usd + held_usd`, with `0 < bound < 50`;
- it asserts the second `settle` returns 0 and that `ledger['events'] == []` ("Settlement never invents billed events").

Neighbouring tests cover most of the first paragraph too:
- `test_concurrent_reservations_and_close_never_refund_unknown` (210–239): late `finish` after `close` cannot refund, and a closed gate refuses `reserve`.
- `test_close_between_connect_and_request_cannot_reconnect_or_forward` (610–631): the real HTTP gate closes before the request is sent and ends with unknown=1, in_flight=0, and an unchanged snapshot.
- `test_factory_dispatch_preserves_lease_maximum_gate_and_invocation_identity` (402–466): a runtime interruption becomes `estimated`, and a second reconcile adds nothing.

The only window none of these covers is closing after the gate has forwarded the request and is relaying a response. That is the `sent=True` branch of `Handler.do_POST`: blocked in `response.read1`, then unblocked by `Allowance.close()` shutting down `connections` (model_call_gate.py:219–233, 548–565).

**Required:** add a "What exists today" paragraph that names these tests. Narrow the change to the uncovered window. Either drop the duplicate settlement assertions or justify each one as a delta, for example "the same as 336–383, but through the real runtime receipt writer" (see B2).

### B2. Blocker: the settlement seam and the close trigger are left to the implementer
**Personas:** implementation_readiness (zero-decision rule), design_critic
**Scope:** lines 27–29 ("Close the gate while the request is in flight") and 33–34 ("ordinary budget reservation/settlement path")

Each of these choices runs different production code. The design picks none.

**1. Close trigger.** These are four different paths:
- `active.close()` inside `enforce` (what the current tests do);
- leaving the `enforce` context, which runs `_wall_access` → `Gate.close` → `cap_used` snapshot (model_call_gate.py:639–668);
- `role_cancel.set()`;
- the gate deadline.

Setting the cancel event or passing the deadline only blocks *new* `reserve` calls. Neither shuts down the in-flight socket, so they don't prove "bounded completion" for an in-flight request. Only `close` does.

**2. How the snapshot reaches settlement.** It can be a hand-written receipt, as 336–383 does. Or it can come from the real `ModelRuntime.call` receipt writer (model_runtime.py:454–467), which derives `final_usage_known` from `cap_used['closed'/'unknown_requests'/'in_flight_requests']` and calls `complete_invocation`.

Only the runtime path is "the ordinary path" and "the accounting seam the new profiles will reuse" (line 20). A hand-written receipt is a fixture written by the test and proves nothing new.

**Required:** name the test. Name the trigger; the recommendation is leaving `enforce` through `runtime.call`, with a patched `run_budgeted` that leaves a request in flight and then returns or raises. Name the receipt producer; the recommendation is the real runtime writer. Name the settlement calls: `budget.settle` twice, or `reconcile_reservations` twice, and the byte-equality check after the second.

### B3. Blocker: the stream shape, the fixture row and the expected values are not given
**Persona:** implementation_readiness (test plan)
**Scope:** lines 26–31

**1. Fixture.** "Saved real Claude writer receipts" doesn't say which file or which row. The candidates are `20261029-real-public-cards.json.gz` through `real_iterations()`, or another fixture.

**2. Bytes before withholding.** These choices produce different gate paths:
- withholding before the response headers means `sent=False`, and the client gets a 502;
- withholding after the headers and `message_start` (with the real usage) means `sent=True`, and the client gets a truncated 200 stream;
- the design also doesn't say whether `message_delta` is sent.

The design must pick one. The headers-sent case is the new window from B1.

**3. Fixture extension.** The existing `ProtocolTests` upstream writes its whole body at once (532–551). The design says "reuse" it but doesn't say how a withhold/release event gets added without changing the other tests that use `setUp`.

**4. Expected values.** These aren't written down. From the code they should be:
- snapshot: forwarded 1, validated 0, unknown 1, in_flight 0, settled_usd 0, held_usd 8.655360 (W for the normalised 32768 output tokens), closed True, and `exhausted` stated explicitly;
- receipt: `final_usage_known` False;
- settlement: `estimated_gap_usd` `8.655360000`, which is `min(maximum 50, gate bound)` per budget.py:296.

**5. "Bounded completion" has no measurable assertion.** The design closes, then releases the upstream. If completion is only checked after the release, a gate that never aborts its upstream read still passes. The check must be that the gate handler finishes and the client read returns *before* the release, within a stated timeout.

**6. The late-refund check needs an observable.** `close()` shuts down the upstream socket, so the late terminal response probably never reaches `Usage.feed`. "Cannot refund" therefore needs something concrete: the snapshot is byte-equal after the release, and the upstream's late write fails or is never read.

### M1. Major: what the saved counters prove is overstated
**Personas:** design_critic (faulty assumption), zoom_out
**Scope:** lines 26–27 and 37–38

After `close`, the charge is the worst-case W whatever the replayed counters are. The counters can only matter if a late, smaller, valid usage reaches `finish`. Under B3.6 that probably can't happen.

**Required:** either state their limited role ("they make a hypothetical refund observably smaller than W"), or drop the replay. If kept, the counters must be sized so a refund would be detectable, meaning the real usage cost must be less than W.

### M2. Major: Heilmeier gaps and confusing numbering
**Standard:** heilmeier
**Scope:** whole document

- **Objective:** it isn't stated in plain words. A fresh reader meets "closed immutable cap snapshot", "retained worst-case usage" and "B" with no definitions. Add one plain sentence, for example: "Prove that if a Claude call is cut off mid-response, we charge its worst-case hold exactly once and never refund it."
- **Impact, risks, cost and timeline:** these are missing or only implied. The design says no paid calls, but gives no effort or time estimate. Its only risk is "might expose a defect".
- **Numbering:** "item 4", "prerequisite 4" and "1/2 … 3/5 … 4" (lines 21 and 55–57) follow the requirement list on lines 8–10. They conflict with the design's own ordered list on lines 12–17, where 1 is this cancellation regression. stream-d.md also has its own "Item 4". Use one numbering scheme and name the items instead of only numbering them.

### N1. Nit: plan for reuse by step 2
**Persona:** zoom_out
**Scope:** lines 12–14 and 19–21

stream-d.md (item 8 prerequisites) requires the smaller Claude profile to carry its own "interruption settlement" tests. Say that this regression will be parameterised over the lease or route maximum, so step 2 reuses it with the new profile instead of writing a second copy. Without that, the "free first step" partly turns into rework.

### N2. Nit: name the Murphy row placeholder
**Scope:** lines 40–41

"Such a defect gets a Murphy row before fixing": name it `new-router-item8-prereqs-<n>`, per ENGINEERING §2.

### N3. Nit: say how the full-suite log is recorded
**Scope:** line 47

"Unique committed log and record" should name the path pattern or the existing convention, so the diff goldfish can check it.

---

**To pass:** fix B1–B3 in the design text, then get a fresh design review. The majors should be fixed in the same edit, because they cost little. No code or production change is needed to resolve any finding.

## Implementation response

Accepted B1–B3, M1–M2 and N2–N3. Revised the design to target only mid-response
closure through the real runtime receipt writer, with explicit events, values,
timeouts and evidence limits. Dropped saved-counter replay because it would not
strengthen this fault test. N1 deferred: there is no smaller profile API to
parameterise yet; the future profile increment must extend this same test.
No finding rejected. Fresh design review requested before implementation.
