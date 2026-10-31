# Stream D item 7: qualified launch without legacy allowances

## Problem

Authenticated batch jobs already bypass old paid/restart/holder/stress caps,
but worker entry still evaluates founder rulings, raised-limit recovery,
call-cap rulings and expired paid-to-free cohort policy. Build and stress feedback
also consult founder authorization. These can refuse or alter modern checkpoints.

## Change and deletions

Keep the single B launcher and job_config installation. Remove from its batch
path saved max-total-calls inheritance, founder ruling context, D1 call-cap
recording, raised_limits, crash-salvage routing, paid-to-free model cutover and
founder-authorized stress feedback. factory_job selects this path but is NOT
authentication: job_config/install and job_authority still refuse missing authority
before work. Keep ordinary gate receipt authentication and recovery.
Delete the unused free_transition_first assignment and first_resume helper if
there are no remaining callers. Non-batch compatibility tools retain their behavior;
B pre-schema retirement stays unchanged. No import/rescue route is added.
Historical fields remain evidence, never authorization. Preserve freshness policy
recording separately from the obsolete D1 call ceiling. Batch role selection uses
pinned rotation/explicit models, without cohort cutover.
Within write_and_attack, keep legacy retry/exhaustion calculations outside the
modern path. Modern receipts with final_repair refuse invalid_recovery_receipt
before model work; they cannot enter legacy final-fix handling. Existing modern
history validation remains. Real unfinished diagnostic validation is science,
distinct from the already bypassed legacy claimed-file attempt allowance.

Lane 2 owns writer/stress/gate package and diagnosis outcome routing; exclude those.
No activation, scientific threshold, per-invocation limit or section 4 change.
Expected effort: a medium implementation/full-suite/review cycle plus fresh reviews
for blocker fixes. Prefer deletion; retain narrowly necessary compatibility guards.

## Tests

Use saved practice bytes and the historical 5813be ledger from stream D fixtures.
Job envelopes/model outputs are authored controls, not live qualification. Add
ordinary run.main subprocess coverage reaching build with installed authority
and forbidden legacy hooks, including exhausted historical call limits and malformed
legacy ruling artifacts. Crash checkpoints must use the same ordinary route,
without salvaged_from/skip_build. Missing authority refuses before model work.
Test batch model selection never consults cohort cutover. Exercise modern stress
replay above two/eight retries. Existing diagnostic-exhaustion tests must still
pass; this increment does not distinguish stale diagnostic claims or regrant them. final_repair must refuse before model calls.
Existing non-batch compatibility tests and B legacy-retire regression must pass.
Run uv run --with numpy --with scipy python -B tests/run.py into a unique committed
log/record and request fresh diff review.

## Murphy rows

None close. Row 9 still needs lane 2 integration and item 8 live qualification;
row 39 needs genuine capped-submission evidence. Only the qualified-path allowance
checklist entry closes after tests and fresh review.

## Review resolutions and exact edit sites

The operator should be able to relaunch a modern checkpoint under the existing
batch commitment without old cohort rules or a new discretionary grant. This
is offline work with $0 model inference/cloud spend. Risks are drift in shared
non-batch behavior and accidentally changing diagnosis stop semantics; compatibility
and launch-level negative controls cover those risks.

* run.main: use a.batch_release_sha256 before installation to exclude saved
  max-total-calls inheritance and founder_ruling.context. Delete first_resume
  assignment, helper and its two obsolete test assertions/stub. This intentionally
  removes that unused expired-cohort check for non-batch resumes too; actual
  non-batch model cutover still validates its deadline in select_models.
  Move raised_limits import/explicit flag parsing into its non-batch resume block;
  keep authenticate_gates for all resumes. Exclude restore_gate_crash for batch
  work, retaining ordinary build/gate receipt processing. Assert scorecard and DONE.
* founder_decisions.record: retain freshness_archive_ruling, return before D1
  validation/recording when model_runtime.factory_job(c).
* model_runtime.select_models: call free_models.apply only for non-batch work.
* run.build: ruling_context only for non-batch. Before freshness_first, reject
  any modern attack-state final_repair flag as invalid_recovery_receipt. Use a
  small shared check also at write_and_attack entry after job_authority.for_case
  and before resume_provider_wait; no new module. This incompatible legacy marker
  is a refusal, NOT a diagnosis trigger. A modern operation never writes it.
  Test with public-match freshness rows and forbidden model/reviewer calls.
* run.build late_defect_needs_ruling: on modern work explicitly preserve the
  existing hold without loading founder/late-defect authorization. Diagnosis
  dispatch precedes build. A verified factory-bug continuation requires lane 2's
  outcome routing; this lane does not implement it. Test the hold before model
  work. Non-batch late-defect handling stays as is.
* run.write_and_attack: exclude feedback_allowed for modern work. Leave already
  exempt re-review bound calculations alone (no cosmetic refactor); test high
  historical counts rather than rewriting receipt bookkeeping.
* run.validate_and_repair: replace for-range with an attempt counter loop.
  For non-batch, retain max_repairs stop. For modern, do not inspect max_repairs;
  ordinary builder_rounds >= args.rounds calls existing stop_defect, which records
  the late-defect exhaustion consumed by diagnosis. A successful repair increments
  the actual author count in write_and_attack; the loop itself grants none.
  Existing unchanged-case repair_blocked remains a scientific no-change result,
  not an exhaustion allowance; no new stop label or diagnosis route is added.
  Test max_repairs=0 and >2 actual changed repairs reaching the ordinary round
  limit via run.main, retaining pending diagnosis instead of sealing on the old cap.
  The parser's nonnegative max_repairs syntax validation stays for compatibility.

Diagnostic boundary is unchanged: stream-d.md item 4 explicitly retains the
single optional execution claim, and item 8 scenario 2 demands exhausted diagnostic
work reach pending diagnosis without a new allowance. No edits to stress_progress,
bin/diagnostic_budget, diagnostic_env or attacker prompts. Automatic recovery of
that execution belongs to lane 2's diagnosis outcomes and item 8, not a hidden
claim reset here. A completed claimed-file does not by itself stop modern stress;
an incomplete/error/running diagnostic stays unscored exhaustion. Existing tests
cover that distinction. This resolves the ambiguity rather than asserting a stale
claim migration. The task removes legacy recovery allowances; it does not qualify
live diagnostic recovery or broaden the approved execution guard.

Keep the existing extension-mode refusal for salvaged_from (including historical
salvage) deliberately: it prevents nonordinary provenance entering a package.
It is not fresh recovery authority. No supported modern checkpoint emits salvage.
The historical fields preserved elsewhere are never a grant.
Row 9's two-late-repairs subproblem is addressed; row 9 itself remains open.

Implementation clarification: ordinary relaunches should not need an operator to
renew old grants. Final-repair refusal precedes author/stress/freshness work;
diagnosis dispatch remains earlier. An unchanged repair is a sealed gate failure
with repair_blocked, not diagnosis or an additional recorded repair. Diagnostic
row 13 remains open for outcome recovery and live qualification.
