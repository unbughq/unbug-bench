No blockers remain, so the verdict is **PASS** (0 blockers, 0 major, 4 nits). B1 and B2 are both resolved. I checked the revised design against the code at head 04f0ed8, and its claims match what the code does. Full review text below for the parent to save verbatim.

---

# Goldfish design review 2: `docs/designs/stream-d-qualified-allowances.md`

**Mode:** REVIEW. **Personas:** zoom_out, design_critic, implementation_readiness. **Standards:** heilmeier-standard.md, implementation-readiness-standard.md.
**Worktree:** `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c` (branch `t3/stream-d-implementation`, head 04f0ed8; design untracked).
**Compared against:**
- review 1 (`docs/reviews/stream-d-qualified-allowances-design-1.md`);
- in `stream-d.md`: item 4 at lines 2190-2234, the item 4 diagnostic boundary at 2482-2492 and 2670-2679, item 8 scenario 2 at 3601, and the item 7 checklist at 3714-3731;
- code: `factory/run.py` (`build`, `restore_gate_crash`, `write_and_attack`, `validate_and_repair`, `main`), `late_recovery.stop_defect`, `diagnosis._trigger`, `founder_decisions.record`, `model_runtime.factory_job` and `select_models`, `free_models`, `job_config.install`, `stress_progress`;
- tests: `test_free_models.py`, `test_stream_d_dispatch.py`, `test_repair_progress.py`, `test_attack_recovery.py`, `test_stream_d_retries.py`.

## Verdict: PASS (0 blockers, 0 major, 4 nits)

Both review 1 blockers are resolved, and nothing the revision adds creates a new one. All four majors (M1–M4) are addressed with edit sites named.

---

### B1 (late-repair allowance): resolved

The design picks option (a) on the modern path. `validate_and_repair` stops reading `max_repairs`, and only `builder_rounds >= args.rounds` → `stop_defect` ends the repairs.

I checked this against the code:
- **The stop is a diagnosis trigger.** `stop_defect` (`late_recovery.py:99-114`) raises `late_defect_needs_ruling:G*`. `diagnosis._trigger` (`diagnosis.py:51-56`) accepts that label exactly when `builder_rounds >= recovery_config.rounds`. The stop it relies on is therefore the one diagnosis already consumes.
- **The loop still ends.** Each round either returns, raises, or changes the case. A changed case means a writer round ran. On the modern path that round starts at `builder_rounds + 1` (`run.py:1225`) and records `builder_rounds = n` (`:1479`). So the round check at `:3018` eventually fires. An unchanged case returns via `repair_blocked`.
- **The test is right.** It uses `max_repairs=0` and more than two changed repairs via `run.main`, and asserts pending diagnosis instead of a seal. That is the route review 1 asked for.
- **Row 9 is recorded correctly.** The note at line 115 is right.

`repair_blocked` is now stated as a scientific no-change result, with no stop label. That settles the open decision; see N2 for one small test gap.

### B2 (stale diagnostic claims): resolved by explicit deferral, consistent with stream-d.md

The design takes out the ambiguous stale-claim test. It also forbids edits to `stress_progress`, `bin/diagnostic_budget`, `diagnostic_env` and the attacker prompts, which keeps the G4–G9 fingerprints intact.

The deferral matches the parent design:
- `stream-d.md:2197-2199` keeps the shared `attacker-{round}` guard and grants no new diagnostics.
- `:2482-2492` routes an interrupted diagnostic to `stress_validation_exhausted` and leaves automatic recovery explicitly to item 7/8.
- Scenario 2 (`:3601`) requires an exhausted diagnostic to reach pending diagnosis with no new allowance.

The SIGKILL case review 1 raised is therefore not scored. It becomes a diagnosis trigger, never a case verdict (`:2480-2481`), and recovering from it belongs to the "All diagnosis outcomes" checklist item. The "diagnostic allowance branches" part of the checklist is met: the one per-attempt allowance is the claimed-file check at `run.py:1512`, which the modern path already bypasses. The design now says so.

The "existing tests cover that distinction" claim holds:
- completed claim: `test_attack_recovery.py:55-57`;
- timeout claim exhausting before more category work: `test_stream_d_retries.py:413-419`.

### M1–M4 and review 1 nits: resolved

- **M1 (final_repair refusal site).** The check goes in `build()` before `freshness_first`, and at `write_and_attack` entry between `job_authority.for_case` and `resume_provider_wait` (`run.py:1126-1127`). Both points exist as described.
  - The claim "a modern operation never writes it" holds. The modern branch at `run.py:1592-1598` raises before the `final_repair` write at `:1610-1612`.
  - `invalid_recovery_receipt` is an existing label (`:1281`, `:1318`, …), and the design states it is not a diagnosis trigger.
- **M2 (late_defect branch).** On the modern path the hold is preserved explicitly, with no founder or late-defect load. Diagnosis dispatch runs before `build` (`run.py:3305-3314` vs `:3349`). Continuation is explicitly left to lane 2. This removes the implicit founder dependency without inventing a resume path.
- **M3 (edit sites and predicate).** Edit sites are listed, and the predicate is `a.batch_release_sha256` before install.
  - `model_runtime.factory_job` (`:41-42`) already reads `args.batch_release_sha256`, so `founder_decisions.record` at `run.py:3290`, before install, sees the right value.
  - `job_config.install` returns `money_wait` when `batch_release_sha256` is missing, so a run with only `--factory-job-config` never reaches the batch path.
  - Excluding `ruling_context` at `:3270` on the batch path removes the raise that happened outside `try`. The scorecard/DONE assertion is kept.
- **M4 (Heilmeier).** Objective, impact, cost ($0 offline), risks (non-batch drift, changed stop semantics), size (medium) and exams (the tests) are now all present (lines 32, 58-62).
- **Review 1 nits:**
  - N1: the `first_resume` helper and its tests (`test_free_models.py:77-78`, `test_stream_d_dispatch.py:202`) are deleted. `c.free_transition_first` has no readers. The non-batch side effect is stated as intended.
  - N2: the extension refusal on `salvaged_from` is kept deliberately.
  - N3: effort is medium.
  - N4: the design now says no cosmetic refactor.

### Other claims checked, no action

- **`restore_gate_crash` exclusion for batch work** (`run.py:915-947`). This function is what sets `salvaged_from` and `skip_build` (`:946-947`). Excluding it sends batch crash checkpoints through ordinary `build`, then through gate receipt authentication. The design requires a test for exactly that route.
- **`founder_decisions.record`.** Splitting off `freshness_archive_ruling` (`:27-29`) from the D1 check and record (`:30-34`) is a clean early return.
- **`select_models`.** Gating `free_models.apply` (`model_runtime.py:120-121`) to non-batch work is a single call site.
- **`feedback_allowed` (`run.py:1363`).** Excluding it on the modern path just leaves `authorized_feedback` false, so no other logic depends on it.

---

### Nits (optional)

- **N1.** The Murphy section names rows 9 and 39 but not row 13. Row 13 is the open row for the retained diagnostic-exhaustion recovery (`stream-d.md:2489-2492`). One clause naming it would make the deferral easy to trace.
- **N2.** `validate_and_repair` is being rewritten, but the only `repair_blocked` test (`test_repair_progress.py:52`) is unit-level and non-batch, with `max_repairs=2`. Add a modern-path assertion that an unchanged repair still seals with `repair_blocked` and `failed_gate` and is not counted as a repair. Also state in one line that this outcome is a sealed gate failure, not a diagnosis.
- **N3.** The `build()` check runs after `diagnosis_dispatch.dispatch` in `main`, so "before model work" holds only because diagnosis is off and the modern path never writes the marker. Either say "before author/stress/freshness work", or note that dispatch comes first.
- **N4.** The objective (lines 3-8, 58-59) is still dense with jargon (cohort cutover, D1, holder). One sentence for a newcomer would meet the Heilmeier "no jargon" bar.

### Unnecessary scope

None. The design adds no module, import route or rescue path, and it deletes `first_resume`.

### Murphy rows

"None close" is correct. The design rightly records that row 9's "two late repairs" part is addressed while row 9 stays open.

## Implementation response

PASS accepted. Optional nits addressed: clarify diagnostic row 13 remains open, describe unchanged repair as sealed gate failure, qualify pre-work refusal as author/stress/freshness work, and test modern unchanged repair.

