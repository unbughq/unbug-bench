# Goldfish design review 1: stream D, writer continuation and durable intent

Reviewer: `openrouter/~deepseek/deepseek-pro-latest` on the `opencode` provider
instance (T3 `delegate_task`), fresh context, read-only. Scope: design section
"Second increment: writer continuation and durable intent" in
`docs/designs/stream-d.md` at d77e84e.

Files read: `docs/designs/stream-d.md` (item 2, item 1, "Remaining increments"), `docs/ENGINEERING.md`, `docs/murphy-register.md` (rows 9, 10), `docs/reviews/stream-d-completion-diff-1.md`, `factory/run.py` (`_opencode` 190–220, `resume_provider_wait` 274–306, `pending_call` 323–385, `write_and_attack` 1015–1470), `factory/model_runtime.py` (`_call` 315–514), `factory/budget.py` (`reserve_invocation` 138–172, `complete_invocation` 357–371, `reconcile_reservations` 384–401, `_settle_leaf` 235–314), `tests/factory/test_stream_d_runtime.py`, `tests/factory/test_stream_d_admission.py`.

## Verdict: PASS

No blockers, no majors. Findings below are nits; the three-window model is accurate, promotion is sound, and the parity fix is correct.

## Blockers

None.

## Majors

None.

## Nits

### N1 — the row-10 closure claim sits alongside the module docstring that denies it
- **Evidence:** `tests/factory/test_stream_d_runtime.py:1–7` ("These tests do not close Murphy rows or qualify B/E rollout.") vs the design's "row 10 closes with these test names" and item 2's "Closes row 10."
- **What goes wrong:** ENGINEERING §2 requires "closed only when a test on real artifacts proves it," with the elephant setting status in the same commit as the fix. The design correctly makes closure *contingent* ("If diff review accepts that…"), but the test module's own docstring still asserts no row closes. At implementation time these two statements conflict and a reviewer may cite the docstring against the claim.
- **Fix:** Note in the design that this increment will revise the module docstring (and register entry) in the same commit that closes row 10, or specifically name which tests close it so the docstring can be scoped.

### N2 — `complete_writer` extraction must preserve `c.card['builder_rounds']`
- **Evidence:** the `writer_completed` closure sets `c.card['builder_rounds'] = n` at `run.py:1322`, not just `phase`, `repair_pending`, `output_sha256`. The design says promotion "uses the same producer as `on_complete`," extracting it to `complete_writer(c, receipt, path)`.
- **What goes wrong:** The loop also sets `builder_rounds = n` at `run.py:1331`, but a *promoted* resume skips `pending_call` entirely and goes to the increment-1 completed path. If the extraction drops the `builder_rounds` write, a promoted completion resumes validation with `builder_rounds` stale (0), breaking round accounting the test asserts (`builder_rounds == 2`).
- **Fix:** State explicitly that `complete_writer` writes `builder_rounds` as the closure did, and assert it in the `returned`-window tests.

### N3 — promotion trusts `outcome == 'done'` without `final_usage_known`
- **Evidence:** `model_runtime.py` sets `outcome='done'` (417) independently of `final_usage_known` (456–461); a CLI can exit 0 with unidentified events. The design's promotion condition checks only `outcome == 'done'`.
- **What goes wrong:** Not a correctness bug — "the author call finished" is sound basis to avoid a second paid call, and the case files are written before the CLI exits. But the design omits that `done` does not imply settled accounting; the reservation may still be `estimated` with an unpriced invocation.
- **Fix:** One line: promotion is about completion of authoring, not settlement; the estimated reservation still reconciles normally. Optionally require `final_usage_known` for a belt-and-braces check, or justify why it is deliberately not required.

### N4 — extension-admission intent is claimed but not traced
- **Evidence:** `pending_call`'s extension branch (`run.py:333–345`) raises unless the receipt lacks `schema_version`/`operation_id`/`phase`/`lease_id`/`invocation_id`/`resumed_from_wait`/`extension_id`; the intent check is placed "before `await_lease`" (346) after `job_authority.for_case`. `test_stream_d_admission.py:45–49` passes a stripped `receipt()`.
- **What goes wrong:** The design asserts "every writer admission, ordinary or extension, therefore writes intent" and that `receipt()` gains intent fields, but the actual extension receipt is produced via `extensions.propose()`/`admit()`, not the test helper. The design does not show the intent fields surviving into the extension admission receipt.
- **Fix:** Add one sentence: the extension proposal carries `before_repair_sha256`/`repair_requested`/`findings_report`/`input_problems` through `admit()`, so the pre-lease check passes and the published `attack-state.json` retains them.

### N5 — the `if report and problems:` skip also covers a dead branch
- **Evidence:** the block at `run.py:1265` guards legacy `authorized_feedback` logic (`feedback_allowed`, set only on the non-modern path 1216), which is `ruling`-driven and `None` for modern (`run.py:1023`).
- **What goes wrong:** The design frames the skip as parity for *all* modern receipts, but for modern the block's `authorized_feedback` branch is already unreachable. The skip is still correct and simpler, but the rationale ("re-freshness/freshness clears findings") describes only half of what the block did.
- **Fix:** Note that the block is largely legacy founder-feedback machinery already inert under `modern`; skipping it is a simplification, not merely a parity guard.

## What passes

- **Q1 — windows correct, none missed.** Window 1 (mid-call, phase pending, no done receipt: `.get` defaults at `run.py:1313–1314`), window 2 (returned, usage receipt `outcome:done` written at `model_runtime.py:448–462` + `complete_invocation` 465, but `on_complete` not yet run: phase stays pending), window 3 (completed, handled by increment 1). A pre-CLI kill (reservation reserved, no `before_attempt`) folds into window 1; a mid-`on_complete` kill folds into window 2/3 by the atomic receipt write. No window is silently dropped. Stress-tester interruption is correctly out of scope (row 10 is writer-only).
- **Q2 — promotion is sound.** The `done` usage receipt is keyed by `lease_id`; the ledger reservation (written at `budget.py:166`) retains `operation_id`/`invocation_id` even after `_settle_leaf` (`budget.py:281` only mutates `event_ids`/`estimated_gap_usd`/`state`). `outcome=='done'` requires the CLI to have exited 0 *after* writing the case, so partial output cannot be promoted; the `invocation=='builder-<round>'` and operation/invocation-id match guards reject fallback-leakage or another operation's lease. The null-`lease_id` (`resumed_from_wait`) non-promotion is correct because that state only arises from an `interrupted` (not `done`) lease. It cannot fail to promote a genuinely finished call that left a `done` receipt.
- **Q3 — parity fix correct, no needed check dropped.** The uninterrupted loop applies `loop_freshness` once, at stress-review time (`run.py:1417`), before the next writer; the resume `if report and problems:` block re-runs it a second time. The `unfinished_validation`/`interrupted_review` checks in that block (1268–1284) are already enforced during stress (`1420–1423`) before any writer receipt can exist, so nothing is lost by skipping. The `validated-with-problems` resume correctly reproduces the uninterrupted `report`+G1-problems → writer(n+1) flow.
- **Q4 — intent check placement and callers safe.** Placed before `await_lease` (`run.py:346`), after resume settlement, so no reservation is minted for a receipt that will later refuse. Only two production callers exist: `run.py:1324` (writer, intent written at 1315–1316) and `run.py:1401` (stress, skipped). The `receipt()` helper gaining the four fields covers the direct test callers; `before_repair_sha256`/`repair_requested` are always written for a first round (1305–1306), and the `resumed_from_wait` pending reset (297) does not erase them.
- **Q5 — tests discriminate.** Each planned test (returned-window promotion, mid-call single re-call with byte-identical context, strict-intent refusals, validated parity) fails if its change is reverted — e.g. dropping the `if report and problems:` skip re-invokes `loop_freshness` (patched to raise), and dropping promotion doubles `builder-*` calls. The row-10 closure draw on saved real practice bytes + the 5813be ledger through real runtime/router/ledger code matches the row 22/23/36 standard, and the design honestly gates closure on the diff review and suite.
- **Q6 — no obviously simpler equivalent.** Window 2 could alternatively be closed by writing the completed receipt inside `_call`'s `finally`, but that would entangle `_call` with writer-specific receipt shape; the design's minimal `complete_writer` extraction plus one directory scan is the smaller change.

Skipped: I did not run the suite (read-only, as instructed) and did not trace `extensions.propose()/admit()` internals to confirm intent fields survive extension admission (N4). Risk for the user: the row-10 "closes" wording must be reconciled with the test-module docstring at implementation time, or the diff reviewer will flag the same contradiction.

## Elephant response

PASS accepted. All five nits are taken into the design (corrections paragraph
appended to the increment-2 section); none is rejected.

- **N1 fixed.** If row 10 closes, the same commit scopes the runtime test
  module docstring to name the row-10 tests, and updates the register row.
- **N2 fixed.** `complete_writer` keeps the `builder_rounds = round` write; the
  `returned`-window tests assert `builder_rounds`.
- **N3 fixed.** The design states that promotion proves authoring finished, not
  that usage is settled. An estimated or unpriced reservation reconciles
  through the existing path. `final_usage_known` is deliberately not required:
  requiring it would pay for a second author call to fix an accounting gap.
- **N4 corrected.** No production extension caller exists yet (item 7);
  `extensions.propose()`/`admit()` produce the extension entry, not the writer
  receipt, which the caller of `pending_call` builds. The pre-lease check is
  what makes intent mandatory for that future caller; the design now says so
  instead of claiming the trace.
- **N5 fixed.** The design notes that the skipped block's founder-feedback
  branch is already inert under `modern`, so the skip is also a simplification.
