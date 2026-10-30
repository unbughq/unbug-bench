# Goldfish diff review 1: stream D, writer continuation and durable intent

Reviewer: `openrouter/~deepseek/deepseek-pro-latest` on the `opencode` provider
instance (T3 `delegate_task`), fresh context, read-only. Scope: `428868b..4f9f931`
in worktree `t3-21bef30c`, branch `t3/stream-d-implementation`. The reviewer
ran only `tests.factory.test_stream_d_runtime` (38/38 pass), not the full suite.

**Files read:** `docs/ENGINEERING.md`, `docs/designs/stream-d.md` (increments 1 & 2, "Remaining increments"), `docs/reviews/stream-d-continuation-design-1.md`, `docs/reviews/stream-d-completion-diff-1.md` (N1/N2), `docs/murphy-register.md` (rows 9, 10, 22, 23, 36), `factory/run.py` (receipt load, `write_and_attack`, `pending_call`, `resume_provider_wait`), `factory/model_runtime.py` (`call`/`_call`), `factory/budget.py`, `tests/factory/test_stream_d_runtime.py`.

## Verdict: PASS

## Blockers

None.

## Majors

None.

## Nits

### N1 — `resume_operation` is still write-only; the promotion `pop` is dead code
- **Evidence:** `factory/run.py:1136` sets `c.card['resume_operation']` at load (pending), and `factory/run.py:1212` pops it at promotion. A repo-wide grep finds no reader of `resume_operation` anywhere.
- **What goes wrong:** The `pop` at `:1212` has no functional effect because the field is never consumed. Whether it is popped or not, nothing in the resume or promotion path reads it. It is harmless, but it is the only "handling" of `resume_operation`, and neither the design section nor the correction paragraph explains what the field is for or why promotion must clear it.
- **Fix:** Either delete the now-dead `resume_operation` writes/pop if the field has no other consumer, or add one line of intent to the design explaining what `resume_operation` signals and why promotion drops it. No code behaviour changes either way.

## What passes

- **Design match (Q1).** `writer_intent_valid`, `complete_writer`, `writer_call_done` are all module-level in `factory/run.py` exactly as specified. The strict pending/completed intent check sits in the `modern_writer_unit and not awaiting_stress` block (`run.py:1208–1209`) *after* the completed output-hash check (gated by `resume_writer_validation`, which is only true for `completed`, so the pending path — where `output_sha256` is `None` — correctly skips an output-hash comparison; precedence for completed receipts is unchanged). Promotion (`:1211–1215`) reuses `complete_writer` (the same producer `on_complete` now calls via lambda at `:1354`) and folds into the increment-1 completed path. The `if report and problems:` skip is gated `not modern_writer_unit` (`:1297`), so legacy and stress-unit receipts keep the block. `pending_call`'s admission check (`:360–361`) fires for `role == 'writer'` *before* `await_lease`, and also precedes the `extension_proposal` branch, making intent mandatory for the future extension caller (design-review N4). The pending-merge reads saved intent directly with no `.get` defaults (`:1349–1351`).

- **Correctness (Q2).** `writer_call_done` (`run.py:334–341`) cannot promote a partial or unrelated call: it requires a 32-hex `lease_id`, a `usage-receipts/<lease>.json` with matching `lease_id`, `invocation == 'builder-<round>'` and `outcome == 'done'` (CLI exited 0 only after writing the case), plus a ledger reservation whose `operation_id`/`invocation_id` equal the receipt's — which rejects fallback-leakage and other operations' leases. A `null` (`resumed_from_wait`), missing, or `interrupted` lease is not promoted. After promotion, `resume_writer_validation`/`skip_writer` are set True and the receipt runs the unchanged-repair → G1/early → stress path identically to a completed receipt (asserted by the `returned`-window tests). `complete_writer` preserves `builder_rounds = receipt['round']` and leaves `repair_requested`/`before_repair_sha256` untouched, so the unchanged-repair comparison is against the pre-edit baseline. No path causes a second paid author call, a renumbered round, or a reservation before refusal: the admission check precedes `await_lease`/reservation (test asserts `await_lease` not called and ledger unchanged). Legacy V1 receipts, stress receipts, and `validated` receipts are all untouched (the intent check is gated to `pending`/`completed` modern writer receipts; stress calls pass `role='stress_tester'`). `final_usage_known` is deliberately not required, matching design-review N3 and the elephant's stated trade-off.

- **Tests discriminate (Q3).** Each change has a test that would fail on revert: dropping the `if report and problems:` skip re-invokes `loop_freshness` (asserted absent); dropping promotion doubles `builder-*` calls and leaves `phase != 'completed'`; dropping the strict-intent check lets malformed/missing `repair_requested`, `before_repair_sha256`, `findings_report`, `input_problems` through; dropping the `pending_call` check fails `test_writer_admission_requires_durable_intent`. N1 and N2 from the completion-diff review are folded in exactly as described: `g1` is dropped from the fail-if-called list with a comment (`test_stream_d_runtime.py:618–620`), and `provider_resume_done`/`model_resume_state['done']` are reset to force a true fresh-process resume (`:551`, `:586`). Inputs are real: the hash-verified practice case bytes (`invalid-runs-practice.json.gz`) and the real 5813be ledger via `cards()`; only model outputs and kills are authored.

- **Murphy row 10 (Q4).** Closure is justified under ENGINEERING §2. The six cited test names all exist and together exercise every row-10 boundary (mid-call, returned-before-completion, completed, validated-with-problems) on real saved artifacts through the real runtime/router/ledger code, with only model output and kills authored — the same standard as rows 22, 23, 36. The register entry is in the same commit, and the module docstring was scoped to name the row-10 closure (design-review N1), removing the prior self-contradiction.

- **Simpler? (Q5).** No simpler equivalent suggests itself. The alternative (writing the completed receipt inside `_call`'s `finally`) would entangle `model_runtime` with writer-specific receipt shape; `complete_writer` extraction plus one directory scan is the minimal change.

Skipped: I did not run the full suite (a sibling process owns it) — only the permitted focused module, which passed 38/38 — and I did not trace `extensions.propose()/admit()` internals (design-review N4 notes there is no production extension caller yet). Risk to note: row 10's "Router=Partial" column value is pre-existing and unchanged by this diff, but the register carries no "implemented fraction" semantics, so "closed" with a `Partial` adjacent column may read ambiguously to a future reviewer.

## Elephant response

PASS accepted. No blocking or major findings.

- **N1 rejected, with reason.** `resume_operation` is not dead. No Python
  reads it, but it is a field on the published scorecard (`c.card`). It labels
  a resumed pending unit as a `provider_wait` or `crash` continuation for
  collection and audit (see diff-7 and diff-9 reviews, which discuss its
  `kind` label). After promotion, the unit is not a continuation: the call
  finished and no second call is made. Popping the label stops the card from
  claiming a `crash` continuation that never ran. Keeping the pop.
- **Router column note.** "Router: Partial" is that row's pre-existing
  router-dependency column, not an implementation fraction. Rows 36 and 40 are
  also closed with "Partial" in that column. No change.

## Validation

Command: `uv run --with numpy --with scipy python -B tests/run.py` at 4f9f931.

Result: `155 test scripts run; 0 failed.` Exit status 0. No test failed by
timeout, so no rerun was needed. The log line "boat-call: command timed out" is
expected output from a test of that timeout path. Local log:
`/tmp/stream-d-continuation-suite-4f9f931.log`, sha256
`2a85f53e359eb506ecfcabca4ea5b2a2cd2f37ab9c1036913fd7eca61ba236fc`.

Before the suite, each of the four changes was reverted one at a time against
`tests.factory.test_stream_d_runtime`. Each revert failed at least one of the
new tests: the `if report and problems:` skip (2 tests), promotion (3),
strict pending intent (1 test, 12 subtests) and admission intent (1 test, 5
subtests).

Murphy row 10 closes in 4f9f931. Row 9 and D rows 8, 11, 12, 13, 15, 21 and 39
stay open. `DIAGNOSIS_ENABLED` stays false. Nothing was pushed, merged into
factory-simplify, or changed on main.
