**Verdict: BLOCKING.** One blocker, two majors and five nits. This is goldfish design review round 1 of 2, `Mode: REVIEW`, run read-only on `t3/isolation-o5b` @ 7f1c09e. I used the zoom_out, design_critic and implementation_readiness personas against heilmeier-standard and implementation-readiness-standard. I made no edits, model calls or live actions.

## What holds (checked against code)

- **The retirement branch sits in the right place.** `extension_package.stress` is called only from `package.run` (`extension_package.py:520`), and that call is outside the `write_and_attack` try. So a raised `BudgetError` reaches `run.main`'s handler, which sets `terminal_stop` from the label, marks the card stopped, runs `finalize_accounting` and saves a checkpoint (`run.py:3416-3450`). No new durability mechanism is needed.
- **It ends without a score.** No `Records.save` or `extensions.complete` runs, so the history row stays open (`outcome None`).
  - `diagnosis.exhaustion` returns False twice over: the `retired` prefix check, and the open-history check (`diagnosis.py:87-93`).
  - `record_exhaustion(new_exhaustion=True)` returns early. The existing completed state goes through `_trigger`, which fails for this label (`diagnosis.py:139-144`).
  - `pending_projection` gives None, so B's `_enqueue` queues no replacement or resume (`batch_service.py:262-297`).
  - No diagnosis or replacement is created.
- **Retirement itself makes no model calls.**
- **The automatic retry paths already reject the label.**
  - `RETRY` (`recovery.py:11`) does not match it.
  - It is not in `HOLDER_STOPS` (`recovery.py:209`), so the holder only relaunches when an operator raises limits.
  - A relaunch goes dispatch → `apply` → `package.run` (when `DIAGNOSIS_ENABLED`). That hits `write_and_attack`'s exhausted-receipt stop (`run.py:1197-1201`), which `package.run` catches before calling `stress()` again. So a replay reproduces the retirement without paid work.
- **The retirement conditions are sound for the exhausted shape.** A report that is exhausted and contains only requests means `loop_freshness` cleared nothing:
  - with no flagged rows it returns early;
  - if it excludes rows, it clears the request and the round passes, so the receipt is not exhausted;
  - if a row is unresolved or a public match, it raises before exhaustion.

  So there is no clearance proof the retirement could skip over. The design's exclusions (review-incomplete sentinel, mixed real defect, any metadata, unfinished validation or diagnostic, missing exhaustion) match `freshness_only_clearance` exactly (`run.py:1028-1033`).
- **The evaluator boundary is described correctly as code.** `extension_evaluator.stress:217-221` scores a request-only report with no metadata as a failure. The design does not change it.

## Findings

### 1. Blocker: a request-only report with no metadata whose request was independently cleared still holds forever

- **Where:** design lines 5-14 and 23-41 (the claim "This replaces the hold"); code `extension_package.py:378-386`, `run.py:1036-1131` and `run.py:1621-1645`.
- **What happens:**
  1. The attacker prompt (`factory/prompts/attacker.md:57-66`) has the reviewer flag ambiguous matches as `hit`/`ambiguous` rows in `case/freshness.jsonl`. It may also write the exact `[freshness-review] independent verdict required` line in `blocking` while `freshness_review` is absent or `[]`.
  2. `loop_freshness` reads those flagged rows from `freshness_lines(c)` whatever the report metadata says. It runs `confirm_hits`, and on exclusion writes `round-N-writer.json` and `round-N.clearance.json` (`run.py:1121-1130`).
  3. The round passes with `next_phase='extension_comparison'` and the receipt is not exhausted (`run.py:1636-1641`).
  4. `package.stress` then sees no findings. It tries clearance only when `freshness_review` or `freshness_review_malformed` is set (`:380`), so it skips clearance. The original `result['blocking']` is non-empty, so it refuses with `extension_execution_pending` (`:384-386`).
- **Why this blocks:** the result is the same un-diagnosed, parked `extension_execution_pending` that O5b describes, from the same report signature (request-only, no metadata), but for a pass whose clearance was authenticated. The new branch does not catch it because it requires exhaustion, and retirement would be the wrong answer anyway because the case passed.
- **Fix (minimal, same function, reuses existing proof):**
  - Change the clearance trigger at `:380` to run when there are no findings and any of these holds: `freshness_review`, `freshness_review_malformed`, or the report's `.clearance.json` exists (`report.with_suffix('.clearance.json')`, the path `cleared_stress` already reads).
  - `cleared_stress` already authenticates the proof and requires `parsed == freshness_only_clearance(original)`, so it can only remove request lines. Without a valid proof it still refuses as today.
  - Add "no `.clearance.json` and no `-writer.json` for this report" to the retirement conditions, so retirement can never override a proof.
- **Tests:**
  - **Positive:** a request-only report with no metadata, a flagged `freshness.jsonl` row, and the real `loop_freshness` with only `confirm_hits` authored to exclude. Expect a stress pass that proceeds to gates, not retirement.
  - **Negative:** the same setup with the clearance file tampered. Expect `extension_execution_pending`.
- **Acceptable alternative only with parent agreement:** leave this shape out of scope explicitly. Narrow the claim in lines 5-14 to "exhausted request-only", and add a test showing it still holds.

### 2. Major: the design misstates how B treats money for a retired job

- **Where:** design lines 56-58 and exam 4 (lines 107-109); code `batch_money.py:318-358` and `batch_service.py:268-297`.
- **What the code does:**
  - B never releases a job's money authority on a terminal stop. `aggregate` keeps counting `max(held_usd, known_floor_usd)` for every job until the batch ends, and `advance_locked` only moves `source_generation`.
  - With unknown usage, `_enqueue` asks for a settlement resume only when `exhaustion` is True, which it never is here. So unknown usage keeps the full hold and no settlement relaunch happens.
- **Why it matters:** the sentence "B's normal publication/settlement path remains responsible for releasing money authority" is false. It could lead the implementer to add release code, or to assert something that does not exist.
- **Fix:** replace it with: "B keeps the job's held reservation exactly as for any terminal stop, with no release, no new authorization and no settlement resume. Case-level reservations are settled by `reconcile_reservations` in `finalize_accounting`."
- **Exam 4 must assert:**
  - B's `plan` returns `facts.exhaustion=False`, `pending_projection=None` and an empty queue, for both known and unknown totals;
  - `aggregate(state)` and the job's `held_usd` and `known_floor_usd` are unchanged by the retired generation;
  - for unknown usage, `card_total(card) is None` stays None and no `settlement` request is queued.

### 3. Major: the evaluator's opposite treatment is mentioned but its effect is not stated

- **Where:** design lines 71-74; code `extension_evaluator.py:217-221`, `extension_package.py:696-701` and `run.py:1621-1626`.
- **What happens:**
  - When a later extension is admitted, `subsequent_entry` re-runs stress through the comparison evaluator. A request-only report there with no metadata becomes a scored stress failure, which feeds `extensions.progress` and can produce `retired_no_progress`. That is a request scored as a defect, which O5b says must never happen.
  - In ordinary rounds, the same lines also go to the writer as `problems`.
- **Why it matters:** a pilot case can reach the first path after one extension. The design's wording ("different entry conditions do not authorize a package outcome") hides that effect.
- **Fix (no code needed for this increment):** state it as an accepted residual, outside this change, with one sentence each:
  - comparison re-runs can still score a request-only report with no metadata as a stress failure, which can end in `retired_no_progress`;
  - the ordinary writer loop forwards request lines as writer problems.

  Add it to the handback risks. Do not widen scope.

### 4. Nit: the problem statement overstates the current behaviour

- **Where:** design line 8 ("repeats `extension_execution_pending` forever").
- **What the code does:** nothing relaunches this card automatically. The label is not in `RETRY` or `HOLDER_STOPS`, and B queues nothing. `batch_status` shows it as "unknown stop" with "check case" (`batch_status.py:168-171`).
- **Fix:** say plainly that the case parks and needs a human. The value of this change is removing that pit stop (ENGINEERING §3, first property) and counting the case as retired. That also fills the Heilmeier impact question, which is currently answered only by what the change does *not* claim (line 14).

### 5. Nit: the objective is not written plainly

- **Where:** design lines 3-19.
- **What's wrong:** Heilmeier asks for an objective with no jargon. Lines 3-19 open with O5b, d814231, "freshness metadata" and `extension_execution_pending`.
- **Fix:** add one plain lead sentence, for example: "When the stress reviewer's last allowed round only asks for an outside freshness check but gives no link to check, stop the case as retired instead of leaving it parked, and never count the request as a defect."

### 6. Nit: implementation details the implementer should not have to decide

- **Invalid-infra check:** name the exact call. `if comparison._pending(False, result): raise InvalidInfra('invalid package gate result')`, before any card change.
- **Status mapping:** extend the branch at `batch_status.py:142` to `stop in ('retired_factory_bug_limit', 'retired_stress_request_only')`. Add the STOPS entry with the stated reason text.
- **Dispatch replay (line 66):** the relaunch-route test must patch `batch_service.DIAGNOSIS_ENABLED=True`. Otherwise `apply` stops with `extension_comparison_pending` (`diagnosis_dispatch.py:259-264`, `STOPS:31`) and overwrites the retired label without reaching the package guard. Note this behaviour when diagnosis is disabled as an accepted label overwrite.
- **Exam 1 (real `loop_freshness`):** require that the saved case's `freshness.jsonl` has no hit or ambiguous rows for the retirement positive. Patch `confirm_hits` to raise `AssertionError` so no HTTP or reviewer path can run.

### 7. Nit: the cross-batch export filter does not list the new label

- **Where:** `batch_transfer.py:244-245`.
- **What's wrong:** the filter excludes some retired stops, but not this one (nor, already, `retired_no_progress` or `retired_extension_limit`).
- **Fix:** optionally add the label there. Otherwise state that it is out of scope for the pilot.

## Scope note

The design correctly avoids multi-scenario clamps, schema changes, new journals, model replay and changes to diagnosis scheduling. It closes no Murphy rows and claims none. Retiring is the cheapest bounded outcome O5b allows. Fixing finding 1 needs one changed condition and one added clause in the same function, reusing `cleared_stress`; it is not a broader rewrite.

## Implementer disposition

Accepted all required findings and nits. Design revised before round 2: consume
existing authenticated clearance even without report metadata; retirement requires
both clearance artifacts absent; money stays held without a settlement resume;
comparison/writer residuals, disabled diagnosis replay and cross-batch limits are
explicit. No production edits yet.
