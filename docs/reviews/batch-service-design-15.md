**Verdict: PASS.** Both review-14 blockers are fixed, the code and fixtures match the design, and nothing blocks the design record. There are four optional Nits. I changed and saved nothing, didn't touch the parent checkout, and spent nothing. The D test files I ran all passed.

---

# batch-service design review 15: Increment2b.2 final integration against merged D 3a (9cb25e6 / cfe616f)

**Verdict: PASS. No Blocker or Major findings. Four optional Nits.**

**Scope:**
- **Reviewer:** fresh goldfish, read-only.
- **Personas read first:** zoom_out, design_critic, implementation_readiness. Mode: REVIEW.
- **Standards:** heilmeier-standard.md, implementation-readiness-standard.md, docs/ENGINEERING.md.
- **Worktree:** `t3-ded79ec5` at HEAD 34bffa2, plus the working-tree diff to `docs/designs/batch-service.md`, `docs/designs/status.md` and `docs/murphy-register.md`.
- **Reviews read:** 11–14 with their resolutions.
- **Code read:** `factory/diagnosis.py`, `factory/recovery.py:14`, `factory/batch_service.py` (`_enqueue`, `_replacement`, `plan`), `interfaces.md` §8, status.md "Factory bug held".
- **Tests run:** `test_stream_d.py`, `test_stream_d_coverage.py` and `test_stream_d_projection.py` all return OK. cfe616f is an ancestor of HEAD.

## Review-14 resolutions, checked against code

| Item | Result |
|---|---|
| **B1: malformed `diagnosis_state`** | **Resolved.** The design now says real D returns `exhaustion:false` and `pending_projection:None`, so B queues nothing (no settlement, diagnosis or child) at both totals, and B never infers exhaustion. This matches `diagnosis.exhaustion`, which returns False when `'diagnosis_state' in card and _state(...) is None`. The stranded hold is recorded as Murphy row `new-batch-service-3` (open, activation prerequisite). |
| **B2.1: saved cards** | **Resolved.** e15450 passes, because card 52.786583492 equals D's figure. 5813be refuses `invalid_accounting_input` (card null vs D 13.779870815). The known variant of 5813be is explicitly labelled as authored. |
| **B2.2: null-T coverage** | **Resolved.** The design says neither saved card reaches this path and that D's direct legacy-coverage tests own the proof. |
| **B2.3: infrastructure queue** | **Resolved, verified by probe and code trace** (details below). |
| **B2.4 and labels** | **Resolved.** All five refusal labels are mapped to exact conditions, including card/D disagreement mapping to `invalid_accounting_input`. |
| **Harness** | **Resolved.** B re-drives `budget.settle`/`complete_invocation` with the `AccountingTests.setUp/ledger/reserve/receipt/wait` helpers. All of them exist at `test_stream_d.py:42-71`. B never calls `_settle_leaf`. |
| **Nits 1–3** | **Resolved.** Adapter-off returns `diagnosis_unavailable` even for stored facts. Absent state on non-exhausted cards is an activation prerequisite. Higher-precision disagreement refuses (fail-closed). |

### B2.3 detail: infrastructure queue

I ran real D on the 5813be card with authored diagnosis states:

| Authored state | `exhaustion` | `pending_projection` |
|---|---|---|
| pending infrastructure | True | `{pending, replacement_eligible:false}` |
| completed `factory_bug`, `terminal_stop: factory_bug_held`, no marker | False | None |
| same, with infrastructure marker | True | None |

Tracing those facts through `_enqueue` (`batch_service.py:262-279`):

- **Known, pending:** the projection is present and the total is known, so B queues one `resume` request with reason `exhaustion`. `_replacement` is False because the projection is not eligible, so no child.
- **Known, completed:** the projection is None and the total is known, so nothing is queued and no child is derived, with or without the marker.
- **Null, pending:** B queues one `settlement` resume.
- **Null, completed with marker:** `exhaustion and unknown` is true, so B queues one `settlement` resume. No child.

All of this matches the design text and the parent clarification. status.md maps `factory_bug_held` to exactly `factory bug: see finding <id>`. The null variants depend on the planned shared normalization helper, because the current `.get` chain raises on `case_budget:null`. The design names that fix.

## Unchanged and consistent

- P−R−ε with ε = (2·len(M)+1) nanodollars.
- A known overrun returns the full T.
- The estimated map is replaced on every checkpoint.
- `usage_coverage` is called only when T is null.
- Decrease identity is `invocation_id` alone.
- The provenance gate comes before stored-facts replay and before D.
- No B stop predicates.
- A child only from a present eligible projection.
- `DIAGNOSIS_ENABLED` stays False; no ACK, holder or source authority.
- No readiness claimed. Heilmeier items are answered: objective, limits, risks, $0 cost, exams.

## Nits (optional)

1. **Stale "final review" text.** Line ~1284 says "Name the exact source paths and D SHA in the final design review after 3a lands; their absence currently blocks implementation qualification." Lines ~1313–1318 say "Name … test_stream_d_projection.py … in the final review" and cite 8b8ece6 as supporting evidence. This *is* the final review. The status paragraph (1005–1009) already names cfe616f and the paths, and the merged projection test now holds the completed-state regression. Delete or past-tense these sentences so no one reads them as a remaining block.
2. **Phase journal scope.** "Completed … yields None and no queue" and "queue only a same-owner settlement resume in both … phases" do not say whether pending and completed run on one journal or two. On one journal, the earlier pending resume row stays in `ordered_queue` (and in the null case there are two settlement rows, keyed by generation). Say "adds no queue row" / "adds one settlement row", or name separate journals.
3. **Murphy table break.** `docs/murphy-register.md:66` is a blank line, so row 67 (`new-batch-service-3`) renders outside the table. Remove the blank line.
4. **Gate vs `retired_batch_bound` order.** The design does not say whether the deadline refusal in `plan` comes before or after the provenance gate. Both refuse without mutation; only the label precedence differs. One clause pins it.

No finding was rejected. Prior findings from reviews 11–14 stay resolved. Activation readiness was not assessed, as instructed.


## Elephant resolution

PASS accepted. Optional nits resolved: stale gate language updated, phase tests
use fresh journals, Murphy table repaired, provenance precedes deadline. No
findings rejected. Offline implementation only; all activation gates remain.
