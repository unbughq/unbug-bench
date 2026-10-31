# Goldfish design review: `docs/designs/stream-d-qualified-allowances.md`

**Mode:** REVIEW. **Personas:** zoom_out, design_critic, implementation_readiness. **Standards:** heilmeier-standard.md, implementation-readiness-standard.md.
**Worktree:** `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c` (branch `t3/stream-d-implementation`, head 04f0ed8; the design file is untracked).
**Compared against:** stream-d.md item 7 and the "Item 7 remaining-increment checklist" entry *Qualified-path legacy allowance deletion — medium*, plus `factory/run.py`, `founder_ruling.py`, `founder_decisions.py`, `free_models.py`, `model_runtime.py`, `job_config.py`, `stress_progress.py`, `bin/diagnostic_budget.py`, `diagnosis.py`, `late_recovery.py`, `batch.py`, `gate_state.py`, and Murphy row 9.

## Verdict: FAIL (2 blockers, 4 major, 4 nits)

The design is short and aimed at the right things. Most of its deletion list matches real hooks on the batch path:
- saved max_total_calls inheritance, `run.py:3218-3221`
- `ruling_context`, `run.py:3270` and `:524`
- D1 recording, `founder_decisions.record`
- `raised_limits`, `:3315`
- `restore_gate_crash` / `salvaged_from` / `skip_build`, `:3319`, `:947`
- `free_models.apply` in `select_models`, `model_runtime.py:120`
- `feedback_allowed`, which still runs for modern receipts at `run.py:1361`

Two problems stop it passing:
- It misses a legacy allowance that Murphy row 9 names explicitly.
- It asks for "stale diagnostic claim" behaviour without saying what that behaviour is.

---

### B1. Blocker: the late-repair allowance (`--max-repairs`) is missed on the qualified path

**Scope:** `factory/run.py:3001-3036` (`validate_and_repair`), `run.py:3105`, `batch.py:146` (forbidden list), Murphy row 9.

**Finding.** `validate_and_repair` allows `max_repairs` (default 2) same-worker repairs after a later gate fails. When they run out (`if attempt == limit: return`), or a repair changes nothing (`repair_blocked … return`), the function returns. The card is left with `failed_gate` set and is not stopped, so `main` seals it as a finished failed case.

That outcome is not a stop. So:
- `diagnosis._trigger` never sees it, and no diagnosis runs;
- this happens even when `builder_rounds < rounds` (default 8 rounds against 2 repairs).

Two more facts make this a qualified-path leak:
- `--max-repairs` is not in `batch.bind`'s forbidden list, so a batch job can set it.
- Row 9 lists "two late repairs" alongside money and rounds as a legacy exhaustion allowance.

**Why it blocks.** The checklist entry this design closes says to "prove only cumulative batch money/deadline and scientific round rules govern it". That claim is false while this allowance stays.

**Recommendation.** On the batch path, pick one of these and state it in the design:
- (a) Remove the repair-count bound and let the round limit govern. Exhausting rounds already ends in `stop_defect` (`late_defect_needs_ruling:G*`), which diagnosis consumes.
- (b) Explicitly classify `max_repairs` and `repair_blocked` as scientific rules, with a stop label that diagnosis consumes.

Either way, add a `run.main` test where repairs are exhausted with rounds remaining, and assert the resulting stop or diagnosis route.

### B2. Blocker: "stale diagnostic claims" have no defined behaviour, and the edit site is ambiguous

**Scope:** Change section ("Real unfinished diagnostic validation is science…") and Tests ("stale diagnostic claims; genuine unfinished validation must still stop"). Code:
- `run.py:1011-1014` (`attack_diagnostic_unfinished`)
- `run.py:472-483` (`attack_diagnostic_context`)
- `stress_progress.py:64-65`, `:103-104`
- `bin/diagnostic_budget.py:14-17`

**Finding.** The design says the claimed-file allowance is "already bypassed". That is only true of `run.py:1512`.

The claim directory `diagnostic-budgets/attacker-{n}/claimed` is keyed by round only. On the modern path it still:
1. tells every re-review or category continuation at round n that the allowance is "EXHAUSTED" (`:474`);
2. raises `stress_validation_exhausted` before any category call (`stress_progress.py:103`) if a previous claim's `status.json` is not `completed`.

A worker killed during a diagnostic leaves `status: running`, because SIGKILL skips the `finally` that rewrites `status.json`. From then on, every resume of that round stops as `stress_validation_exhausted`, which is a diagnosis trigger. A crash therefore becomes a case outcome, against section 3's "Broken runs are never scored".

The design asks the tests to tell a stale claim from genuine unfinished validation, but gives no rule for doing so. Candidate rules include:
- key the claim by operation_id or review_attempt;
- treat a `running` or `error` status from a superseded operation as infrastructure;
- something else.

**Ownership is also unclear.** The checks sit in `stress_progress.py`, which the design excludes as lane 2's package.

**Recommendation.** The design needs to settle three things:
- the exact predicate that separates stale from genuine;
- which files change;
- whether lane 2 owns this.

Do not change `bin/diagnostic_budget.py`. It is in `gate_state.MEASURE`, so editing it changes the G4–G9 fingerprints and invalidates kept passes. If the stale-claim fix belongs to lane 2, say so, and remove the stale-claim test from this increment.

### M1. Major: "final_repair refuses before model work" has no stated location, and build can spend first

**Scope:** Change section on `final_repair`. Code: `run.py:1291-1301`, `build()` at `:536-547`, `:568`.

**Finding.** Today, a modern receipt with `final_repair` stops as `budget_exhausted` or `rounds_exhausted`, and only inside `write_and_attack`. Two things already run before that point:
- `build()` can call `ensure_freshness` through the `freshness_first` path (reviewer model calls) on hit or ambiguous rows;
- `write_and_attack` first runs `resume_provider_wait`.

If the check is simply swapped in at line 1297, "before model work" is false.

The change in stop label also matters for routing. `rounds_exhausted` and `budget_exhausted` are diagnosis triggers; `invalid_recovery_receipt` is not.

**Recommendation.** Name the check site, for example in `build()` before `freshness_first`, or in `main` before `build`. Make the test assert that no `opencode` or `pending_call` runs, including freshness reviewers, when hit rows are present.

### M2. Major: the batch path's `late_defect_needs_ruling` branch in `build()` is left undefined

**Scope:** `run.py:558-563`; `diagnosis.py:51`, `:456`.

**Finding.** `late_defect_needs_ruling:G*` is the modern stop for late rounds being exhausted, and diagnosis consumes it. Once `ruling` is removed from the batch path, `build()` re-raises that stop on every later ordinary resume of such a case, because `not ruling` is always true. This affects, for example, a factory-bug resume after diagnosis. The founder-ruling dependency then survives as an unconditional refusal.

The design deletes "founder ruling context" from build without saying what this branch becomes.

**Recommendation.** State it outright. One option: on the batch path this stop stays a hold until lane 2's outcome routing replaces it, and a test shows the hold. The other option is to name what resumes it.

### M3. Major: no edit-site list, and the path predicate is unstated for pre-install code

**Scope:** whole Change section; zero-decision rule.

**Finding.** The design lists concepts, not files and functions. Three of the hooks run before `job_config.install` and before `main`'s `try`:
- `:3218` (call-cap inheritance)
- `:3270` (`ruling_context`)
- `:3282-3283` (`first_resume`)

At those points, `factory_job(c)` is true only through `args.batch_release_sha256`. An implementer has to decide which predicate to use.

One consequence: a malformed legacy ruling at `:3270` currently raises outside the `try`, so no scorecard or DONE is written (compare Murphy row 46).

**Recommendation.**
- List the sites: `run.main` (`:3218`, `:3270`, `:3282-3283`, `record_founder_decisions` at `:3288`, the `raised_limits` / `restore_gate_crash` block at `:3315-3319`); `build()` (`:524-563`); `write_and_attack` (`:1361`, the final_repair site); `model_runtime.select_models:120`; `founder_decisions.record` (split the freshness-ruling record from the D1 check).
- Fix the predicate as `a.batch_release_sha256` for pre-install code.
- Have the malformed-artifact test also assert that the batch path writes the scorecard and DONE.

### M4. Major: Heilmeier gaps

**Scope:** whole document.

**Finding.** The design has no plain-language objective or impact statement: who is stopped today, and what changes for them. It has no risks section, for example:
- non-batch behaviour drift through the shared `founder_decisions` and `build` code;
- stop labels that change diagnosis routing (M1).

It also never states the cost ($0 inference, offline only).

**Recommendation.** Add three or four sentences covering these.

---

### Nits

- **N1.** "Delete … first_resume helper if there are no remaining callers": `tests/factory/test_free_models.py:77` calls it, and `test_stream_d_dispatch.py:202` stubs it. Say to delete those test lines too. Deleting it also removes the expired-cohort `ValueError` on non-batch resumes; the cutover expired at 2026-10-23T09:12:40Z for 19 listed cases. Note that this is intended.
- **N2.** `run.py:3311-3313` refuses an extension when `prev_card.get('salvaged_from')` is set. That is a historical field acting as a refusal, against the design's "evidence, never authorization". No modern checkpoints with this field exist yet, so either state the refusal stays deliberately or drop the `prev_card` clause.
- **N3.** The effort estimate ("small") disagrees with the checklist ("medium"). Make them match.
- **N4.** "Keep legacy retry/exhaustion calculations outside the modern path" is cosmetic. Modern is already exempt at `:1266`, `:1274` and `:1388`, and only `exhausted`/`infrastructure_attempts` are still computed. The replay tests above two and eight retries are worth keeping as proof; don't let this grow into a refactor.

### Checked and not leaks (no action)

- `budget.py:866` total-call limit: already bypassed for factory jobs.
- `writer_round_estimate`: bypassed for modern (`run.py:1449-1450`).
- Re-review limits: modern-exempt.
- `run.py:1512` claimed-file allowance: modern-exempt.
- `ruling` in `write_and_attack`: already `None` for modern (only `feedback_allowed` leaks; that is in the deletion list).
- `gate_continuation` authentication: an ordinary receipt, rightly kept.
- `batch.bind` already strips `--max-cost` and `--max-total-calls`.
- `job_config.install` refuses a missing config before work, so `factory_job` is not authentication, as the design says.

### Unnecessary scope

None material. The design adds no new interface, import route or rescue path. Leaving standalone compatibility tooling (`launch.sh --founder-ruling-sha256`, `key_holder`, `recovery.py`) and B's retire-only pre-schema cases alone is correct.

### Murphy rows

"None close" is right. When B1 is resolved, record that row 9's "two late repairs" part is addressed by this increment. The row itself stays open for item 8.

## Implementation response

B1 accepted: remove the batch repair-count bound; writer rounds remain the bound. B2 accepted: remove the ambiguous stale-claim test; diagnostic execution and its outcome recovery remain lane 2/item 8, as specified in stream-d.md diagnostic boundary. M1–M4 and N1–N4 clarified in the revised design. No blocker rejected. Fresh review required.

