**Verdict: PASS.** No blockers and no majors; three optional nits. The full review is below for you to save verbatim.

---

# Goldfish diff review 1: `stream-d-qualified-allowances`

**Mode:** REVIEW. **Personas:** zoom_out, implementation_readiness. **Standard:** implementation-readiness-standard.md.
**Worktree:** `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`, branch `t3/stream-d-implementation`.
**Diff:** `04f0ed8..9ce1737`, one commit: "Remove legacy allowance hooks from qualified launches".
**Reviewed against:**
- `docs/designs/stream-d-qualified-allowances.md`;
- the passing design review `docs/reviews/stream-d-qualified-allowances-design-2.md`.

## Verdict: PASS (0 blockers, 0 major, 3 nits)

## Checks against the design's edit sites

**1. Ordinary modern launch (`run.main`): matches the design.**
- **Saved call ceiling.** `a.max_total_calls` is no longer inherited from the saved scorecard when `a.batch_release_sha256` is set (`run.py:3230`).
- **Founder ruling.** `ruling_context` at entry is skipped for batch work (`:3281`).
- **Dead code removed.** The `first_resume` helper, its assignment and its two test assertions plus the dispatch stub are deleted. Nothing in `factory/`, `bin/` or `tests/` still mentions `first_resume` or `free_transition_first`.
- **Gate authentication.** `authenticate_gates` still runs for every resume.
- **Non-batch-only steps.** The `raised_limits` import and explicit-flag parsing moved into a block guarded by `not factory_job(c)` (`:3323-3330`), and `restore_gate_crash` now runs only inside that block.
- **Batch crash checkpoints.** These now go through ordinary `build`, so `salvaged_from` and `skip_build` are never set.
- **Extension refusal.** The refusal on `salvaged_from` is unchanged.

**2. Preserved non-batch behaviour: equivalent to before.**
- **Old guard.** The block used to be guarded by `a.resume and extension_id is None`. `extension_id` can only be set when `factory_job(c)` is true (`:3313-3318`), so for non-batch work the new guard `a.resume and not factory_job(c)` covers exactly the same runs.
- **Non-batch `validate_and_repair`.** The new `while` loop keeps the old semantics:
  - `attempt` goes up only after a repair that changed the case;
  - an unchanged repair still returns with `repair_blocked`;
  - `attempt == limit` returns at the same point as before;
  - the `repairs[].attempt` numbering is the same (old `attempt+1` equals new post-increment `attempt`);
  - the log string is unchanged.
- **Non-batch late defects.** The handling at `run.py:561-566` is untouched.
- **Non-batch model choice.** `select_models` still calls `free_models.apply` for non-batch work.
- **Focused tests:** `test_repair_progress.py` (3 tests) and `test_free_models.py` both pass.

**3. Repairs are limited by author rounds, not `max_repairs`.**
- **No cap read.** On the modern path, `limit=None` and `max_repairs` is never read. Repairs end only when `builder_rounds >= c.args.rounds`, which calls `stop_defect` and raises `late_defect_needs_ruling:G*`. `diagnosis._trigger` accepts that label when the round count is reached.
- **Extension mode can't spin.** An extension raises `extension_comparison_pending` (`:3357`) before `validate_and_repair`, so the unbounded loop is never reached there.
- **Test coverage.** `test_late_repairs_ignore_zero_legacy_limit_until_writer_round_exhaustion` runs through `run.main` as a subprocess with `--max-repairs 0`. It gets 3 changed repairs, `builder_rounds` reaches 4, diagnosis is pending on `late_defect_needs_ruling:G8`, and G12 does not pass. This is the route the design asked for.
- **Unchanged repair.** `test_unchanged_modern_repair_remains_scientific_failure` covers it: `repair_blocked`, `failed_gate` G8, no repairs recorded, no `diagnosis_state`, and the case seals.

**4. Final-repair refusal and authority ordering.**
- **In `build()`.** The order is:
  1. the ruling, skipped for batch work;
  2. `reject_legacy_final_repair`;
  3. the modern late-defect hold;
  4. freshness and author work.
- **In `write_and_attack`.** The order is:
  1. `job_authority.for_case`;
  2. `reject_legacy_final_repair`;
  3. `resume_provider_wait`.

  This matches the edit site named in design-review M1.
- **The refusal is not a diagnosis trigger.** The refusal raises `stress_review_unresolved:invalid_recovery_receipt`, and that label is not in `_trigger`'s list (`diagnosis.py:45-57`).
- **Missing authority.** `founder_decisions.record` returns early for batch work, so a missing authority reaches `job_config.install` and stops with `money_wait` before `build` (`test_missing_authority_stops_before_build`).
- **Test coverage.** `test_final_repair_refuses_before_freshness_or_role_work` covers both entry points. It makes freshness, provider-wait, opencode and founder-context calls fail if reached.

**5. Founder feedback and the D1 call cap.**
- **D1.** `founder_decisions.record` still records `freshness_archive_ruling`, then returns before D1 validation for batch work.
- **Feedback.** `authorized_feedback` is short-circuited by `not modern`, so `feedback_allowed` is never called on the modern path.
- **Mutation check.** I removed `not modern and` in a temporary `git archive` copy (the worktree was not modified). `test_completed_stress_findings_never_consult_founder_feedback` then fails with "founder feedback", so the test is not vacuous.

**6. Scope.**
- **Diagnostic guard untouched.** There are no edits to `stress_progress`, `bin/diagnostic_budget`, `diagnostic_env` or the attacker prompts.
- **Nothing added.** No new module, import route or rescue path.
- **Murphy and activation.** No Murphy row is closed and nothing is activated, which matches "None close".
- **Lane 2.** Its writer/stress/gate package and outcome routing are not touched.

**7. Isolation test change.** Moving the post-ready fault injection from `free_models.py` into a source replacement in `run.py` keeps the same boundary. The pre-ready `gate_pipeline` fault is unchanged.

**8. Tests and records.**
- **My focused runs:** `test_stream_d_qualified_allowances.py` (10 OK), `test_repair_progress.py` (3 OK), `test_free_models.py` (PASS), `test_stream_d_dispatch.py` (56 OK).
- **Committed suite record:** the log ends "161 test scripts run; 0 failed", and the JSON shows `exit_code` 0. The earlier failed run is kept and explained.

## Nits (optional)

- **N1. The modern repair loop has no local stop of its own** (`run.py:3016-3047`). It ends only because every changed repair runs a writer round that raises `builder_rounds` (`:1234`, `:1488`); batch money also bounds it. If some future path inside `write_and_attack` changed the case without a writer round, the loop would keep going until money ran out. A one-line comment stating this assumption would help the next reader. No code change is needed now.
- **N2. A non-dict `attack-state.json` gives the wrong refusal** (`reject_legacy_final_repair`, `run.py:1123-1125`). `jload(...).get` raises AttributeError on a JSON list or scalar, so the run ends as `runner_error:AttributeError` instead of `invalid_recovery_receipt`. It still fails closed, so this is cosmetic.
- **N3. The isolation test can't detect a missed injection** (`test_isolation_timeouts.py:268-274`). The `str.replace` injection doesn't assert that it matched. If the `inherit_recovery_history(c, prev_card)` line is re-indented or renamed, the injection silently does nothing. The test would most likely still fail on its exit and `DONE` assertions, but an explicit `assertIn` before the replace would make the cause obvious.

## Murphy rows

None are closed, and none are claimed. Row 9's "two late repairs" part is addressed, as the design states; row 9 itself stays open, as do rows 13 and 39.

## Implementation response

PASS accepted. No blockers or majors. Optional nits N1–N3 deferred; no runtime or test changes after the reviewed commit. No Murphy rows closed. The qualified-path legacy allowance checklist item is complete; lane 2 package/outcome work and item 8 qualification remain separate.

