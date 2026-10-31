# Goldfish design review: `docs/designs/stream-d-admitted-execution.md`

**Mode:** REVIEW. **Personas:** zoom_out, design_critic, implementation_readiness. **Standards:** heilmeier-standard.md, implementation-readiness-standard.md, plus zoom-out-standard.md, which the zoom_out persona requires.

I reviewed read-only in worktree `t3-4ac6b632` at HEAD `80d16ea`, which has an uncommitted `stream-d.md` checklist diff. I read the design and the code it routes through: `factory/diagnosis_dispatch.py` (`_dispatch`, `replay`, `apply`, `invoke`), `factory/extensions.py` (`active`, `writer_receipt`, `writer_continuation`, `propose`, `admit`), `factory/run.py` (`write_and_attack`, `pending_call`, `complete_writer`, `build`, `main`), `factory/diagnosis.py` (`_state`, `exhaustion`, `record_exhaustion`), `factory/gate_pipeline.py` (`early_review`), and the fixtures in `test_stream_d_dispatch.py` and `test_stream_d_admission.py`.

**Verdict: does not pass. There are 3 blocking findings.** The routing is safe in its main lines. The decision only executes when the flag is on and active history exists. It cannot accidentally become a new spend authority, because `exhaustion()` and `record_exhaustion` refuse while history is active. No production caller passes `extension_proposal` (`test_stream_d_admission.py:662`). But the plan is not yet bounded or implementable as written. Three behaviours that decide spend and correctness are left to the implementer.

---

## Blocking findings

### B1. The execution entry point is unspecified, and running `write_and_attack` "directly" does not skip the heuristics it contains
- **Severity:** Blocker (implementation readiness, zero-decision rule; design_critic, unmitigated risk)
- **Scope:** design lines 19–21; `factory/run.py:1120–1180`, `:3254–3300`
- **Finding:** The design says to run the existing `write_and_attack` loop directly and skip selection, prototype and build heuristics. Those heuristics are not in `build()`. They are the first ~60 lines of `write_and_attack` itself:
  - the `complete` check;
  - `statement_precheck` and `reselect_candidate`;
  - the `prototype` loop, which makes unreserved `opencode(... "builder-prototype")` calls.

  The `complete` check depends on `case.json`, `answer-key.json`, scenario keys, or `models_used` plus a clean `g1`. A writer killed mid-edit can leave those files missing or invalid. Then `complete` is False, and the code goes on to prototype or reselect. That is the second writer the design forbids (lines 23, 32).

  The design also leaves these choices open:
  - the call shape: a new parameter, an extracted loop function, or a guard;
  - what `prev` is passed in (see B2);
  - what the "worker-local extension identity" is: `extension_id`, the history row, or something else;
  - how `main` carries it. Today `main` ignores `dispatch`'s return at `run.py:3259`, and that call comes before `raised_limits`, `restore_gate_crash`, `sealed_audit.recover`, Compose and `pick_models`;
  - which `main` branch replaces `build(c)`, and how that interacts with `a.dry_run` (no `pick_models`, so `attack_binding` has no `c.models`), `late_gate_rehearsal`, `audit_fairness`/`rehearse_only`, `statement_only` and `salvaged_from`.
- **Guidance:** Name the exact seam, for example "extract lines 1182–1574 into `attack_rounds(c, prev, *, ceiling)`, and have admitted execution call only that." Name the `main` insertion point, and state that admitted execution refuses every non-ordinary mode. Name the identity type. Add a test: a pending admitted writer whose case files are missing or invalid makes no prototype or reselect call.

### B2. Same-round stress recovery is silently skipped when `prev` carries `failed_gate`
- **Severity:** Blocker (design_critic; the same "silently skipping" class this design exists to fix)
- **Scope:** design lines 29–33; `run.py:1301` and `:1371–1373`; `diagnosis_dispatch.CARRY` includes `failed_gate`; `run.py:922` (`restore_gate_crash` sets `failed_gate`)
- **Finding:** The pre-loop recovery block for a stress receipt runs only when `not prev.get("failed_gate")`. Otherwise it takes `elif not modern_writer_unit: report = None`, which leaves `start_round = n + 1`. The loop ceiling is the admitted round `n`, so `range(n+1, n+1)` is empty and the run ends in `rounds_exhausted` without running the pending stress round.

  This is reachable. `late_defect_needs_ruling:G*` is a diagnosis trigger (`diagnosis.py:51`). `failed_gate` is carried into the card, and `restore_gate_crash` can set it after dispatch. Ordinary `build()` strips `failed_gate` only for G2 and G3.

  The design's test list has "same-round stress recovery with no second writer", but does not say what `prev` is. So the test may never exercise this.
- **Guidance:** State exactly what `prev` admitted execution passes. For example, the checkpoint card with `failed_gate`/`failed_detail` removed, because the admitted intent already holds `input_problems`. Also say whether `restore_gate_crash` runs before admitted execution. Add a test: a pending stress receipt at the admitted round, with a gate-failure exhaustion origin, resumes stress.

### B3. Re-entry after a completed admitted round is unbounded, and the G8/G9 early review is neither allowed nor forbidden
- **Severity:** Blocker (bounding; design_critic cost)
- **Scope:** design lines 29–37; `run.py:1365–1371`, `:1543–1550`; `gate_pipeline.py:107`
- **Finding:** On a stress pass, the loop calls `early_review(c)`. That runs gates G8 and G9 with reviewer model calls (`gate_attempt.execute`, two attempts each). The design says to "stop before gate/package completion" and "never reach … gate repair", but it does not say whether this in-loop gate traversal belongs to the admitted round. The checklist's next item ("join … to one gate traversal") suggests it does not.

  Re-entry is also unbounded. After this change, the stop is `extension_comparison_pending`, or `rounds_exhausted` for a failed round. The history row stays active (outcome `None`), so `diagnosis_state` stays `completed/close_to_passing`. Every later resume therefore goes `replay → apply → execute` again.

  For a passed stress receipt, the pre-loop block re-runs `loop_freshness` and `early_review` on every resume. Its cache `c.early` is in memory only. That is repeated paid reviewer and gate work with no count bound. Only the batch money bound limits it. Today the same resume just stops for free.
- **Guidance:**
  1. Decide whether `early_review` (G8/G9) and `loop_freshness` reviewer calls run inside admitted execution, and write that down.
  2. Require admitted execution to detect a finished admitted round before any model or gate call, and stop with the same label. The signals are a validated stress receipt for `row['round']` with `stress_review` completed, or a receipt with `exhausted=True`.
  3. Add a test: two resumes after success and two after failure, with zero model or gate invocations and the same stop label each time.

---

## Major findings (not blocking, but should be fixed in this design)

### M1. The admitted intent's `round_limit` invariant is undefined, and replay can reject the "above ordinary cap" case
- **Scope:** design lines 22–25; `run.py:1216–1225`; the admission fixture `test_stream_d_dispatch.py:243`, which builds the intent from `runtime.receipt` with `round_limit=8`
- **Finding:** The receipt parser requires `0 <= n <= saved_limit`. The design makes `round_limit` immutable, and also makes the ceiling the history round, independent of `args.rounds`. If an admitted intent says `round=9, round_limit=8`, as the current fixture pattern produces, recovery raises `invalid_recovery_receipt` before the loop starts. Nothing defines what `round_limit` must be in an admitted intent. The next increment's admission caller will then have to guess.
- **Guidance:** State the invariant: the admitted intent has `round_limit == row['round']`, `writer_receipt` checks it, and the parser uses the history round, not `saved_limit`, for admitted work. Say how a stress receipt written with `round_limit = ceiling` is checked on replay.

### M2. Passing the result back through `invoke` is unreachable (YAGNI)
- **Scope:** design lines 15–17; `diagnosis_dispatch.invoke` and `apply`
- **Finding:** `invoke` only runs when diagnosis is pending. Pending state cannot coexist with active history, because `record_exhaustion` and `exhaustion()` refuse it. Also, `_state` deliberately drops the last row when it checks the origin of a completed `close_to_passing`. So `apply` from `invoke` always sees `active(c) is None` and stops. The design asks for return plumbing, and implicitly a test, for a path no real artifact can produce.
- **Guidance:** Keep `invoke`'s `apply` stopping unconditionally. Route execution only from `replay`. Say so, and delete the `invoke` clause.

### M3. The decision is not tied to the active row
- **Scope:** design line 10; `apply` (`extensions.active(c) is not None`)
- **Finding:** Routing checks only that some active row exists. It never checks that `row['exhaustion_id']` equals `manifest['exhaustion_id']` of the decision being replayed. The current state machine makes a mismatch unlikely. But this is the authority check that turns a diagnosis into a writer and stress spend. It should be explicit and tested, not inferred from `record_exhaustion` behaviour.
- **Guidance:** Require a match, with `diagnosis_input_invalid` on mismatch. Add one test with a mismatched row.

### M4. Scope of "preserve immutable intent on pending replay" is ambiguous
- **Scope:** design lines 24–26; `run.py:1419` (`{**resume_unit, **writer_receipt}`) and `:1446` (validated `binding` without `binding_sha256`)
- **Finding:** Both described defects are real. But it is unclear whether the fix covers every modern pending writer or only admitted ones. For ordinary writers, keeping the old `release_rereviews`/`release_review_attempts` changes ordinary recovery accounting. "Keep ordinary round-limit tests" does not settle it.
- **Guidance:** Name the scope. If it covers all modern writers, list which ordinary tests prove the behaviour is unchanged.

### M5. Heilmeier: objectives and impact are not in plain language
- **Scope:** design lines 1–17
- **Finding:** The objective is written entirely in project jargon: "B job authority", "lane-1 entry points", "5813be", "worker-local extension identity", "comparison-pending". It never says, in plain words, that a case the diagnosis judged close to passing gets exactly one more writer and stress round. Impact, cost and timeline are each implied in a phrase ("no live inference", "one large cycle"), not answered. A fresh reader can only follow it after reading `stream-d.md`.
- **Guidance:** Add a 3–4 line plain objective and impact, and a one-line cost statement ("$0 inference; tests offline").

---

## Nits
- **N1.** Lines 54–55: "Authored model/stage controls" in the same sentence as "real … harness" conflicts with real-artifacts rule §4. Name which inputs are real saved bytes and which are controls.
- **N2.** Line 62: name the result-record path, for example `docs/reviews/stream-d-admitted-execution-suite-<n>.md`.
- **N3.** Line 38: list the expected stop label for each interruption (provider wait, infrastructure, pause) during the admitted writer and stress round, so the tests are enumerable.
- **N4.** The Murphy citation is correct: row 9 is open and this design closes no row. The `stream-d.md` checklist entry matches this scope.

---

## Confirmed sound (no action needed)
- **Defects:** the three code defects the design names are real:
  - the clamp `min(args.rounds, saved_limit)` at `run.py:1221`;
  - the replay overwrite at `:1419`;
  - the binding changed without its hash at `:1446`.
- **Flag and lock:** checking `DIAGNOSIS_ENABLED` inside `apply` keeps disabled replay unchanged. Returning out of `_dispatch` releases `model_dispatch_lock` before inference.
- **Ordering:** reconciliation and the ledger check come before `replay` in `_dispatch`, as the design requires.
- **Spend:** routing grants no new spend authority. The writer goes through `pending_call` → `writer_continuation` → the existing reservation.

**To pass:** resolve B1–B3 in the design text. M1 and M3 should go in the same revision, because they decide the authority and ceiling checks the blocker tests will exercise.

## Elephant response

B1–B3, M1–M5 and N1–N3 accepted. The revised design specifies the guarded entry, replay-only identity, stripped previous gate feedback, immutable ceiling, terminal receipt checkpoint, and no early panel review. No findings rejected. A fresh reviewer must verify these resolutions before implementation.

