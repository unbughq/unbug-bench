**Verdict: NOT PASS.** There is one blocker, plus three Major findings and four Nits.

Scope: I read the working diff of `docs/designs/status.md` (sections at lines 75, 186 and 192–213) and checked it against `factory/batch_status.py`, `tests/factory/test_batch_status.py`, `factory/diagnosis.py`, `tests/factory/test_stream_d_projection.py`, `factory/batch_service.py` `_enqueue`, and `interfaces.md` §8. I used the zoom-out, design-critic and implementation-readiness agents and the standards ENGINEERING.md names. I made no edits, paid calls or VM changes, and saved nothing.

### Blocker

**B1. Two designs claim the same D integration test, and this one names no file.**
- **Where:** `status.md:207-211`, and "Tests edit a saved real card" at line 204.
- **Problem:** This section requires an actual-D integration test. It checks that a pending false projection queues one same-owner exhaustion resume and no child. It checks that a completed `factory_bug_held` card with a None projection queues nothing. It checks that `unbug status` shows the finding action. But the section does not list any files it creates or changes, which the implementation-readiness standard requires.
- **Conflict:** The concurrent `batch-service.md` working diff claims this same test. It adds `tests/factory/test_batch_service_d.py` for the real D projection integration. It also says "Step2's status regression additionally asserts 'factory bug: see finding <id>'". So whoever implements this has to decide where the test lives, and the two increments can't merge independently.
- **Fix:** State the files: `factory/batch_status.py` and `tests/factory/test_batch_status.py`. Then say exactly one of these two things:
  - (a) This increment owns the D→B queue and status test, and names its own test file.
  - (b) This increment covers only status rendering plus one read of an authored snapshot. The D→B queue assertions stay with the accounting increment's `test_batch_service_d.py`.

  I prefer (b) because it keeps "separate" true and avoids writing the same test twice.

### Major

**M1. "Exactly" `factory bug: see finding <id>` is ambiguous when other rules also fire.**
- **Where:** `status.md:197-198` and `batch_status.py:160-163`.
- **Problem:** The `near limit` rule runs for every bucket except rejected, not collected and unreadable. A held case with spend or rounds at 80% or more would show two flags. One is `factory bug: see finding <id>` and the other is `near limit`. The text doesn't say whether "exactly" means the wording of the action or the only action for that case.
- **Fix:** Say whether `factory_bug_held` turns off `near limit` the way rejected cases do. Add a test with a held card at 80% or more spend.

**M2. The design describes a field that no other contract defines.**
- **Where:** `status.md:194-196`.
- **Problem:** The design says "D completes an infrastructure diagnosis with terminal_stop:factory_bug_held" and describes the public `factory_bug:{finding_id,gate_or_stage,summary_class}` field. Neither appears in `interfaces.md` or `stream-d.md`, and no code writes either one; my grep found them only in this diff and the concurrent `batch-service.md` diff. Meanwhile `interfaces.md:681` still says "factory_bug enters the existing coordinator maintainer queue". The new line "No maintainer queue… is added" reads as status adding nothing. It does not say that the ruling replaces the queue.
- **Fix:** Say the field is a D producer obligation from the parent ruling, not yet implemented, and that status tests author it. Also state field types: `finding_id` is a string, and `gate_or_stage` and `summary_class` are strings that status never shows. Then either update `interfaces.md` or name it as a required follow-up, so D doesn't write a different shape.

**M3. The "no child" checks pass trivially unless the test turns on replacement and diagnosis.**
- **Where:** `status.md:207-209`.
- **Problem:** `_enqueue` derives a child only when `record.replacement_policy.enabled` is true. `DIAGNOSIS_ENABLED` defaults to False, and while it is off `plan` returns `diagnosis_unavailable`. "No child" therefore holds trivially unless the test enables both. The design doesn't say how the known total is set up either, and the 5813be card has no `case_budget` key.
- **Fix:** If this increment keeps the test, require:
  - `replacement_policy.enabled` set to true;
  - `DIAGNOSIS_ENABLED` patched on, with the real `diagnosis` module;
  - an authored `case_budget.total_spent_usd`, labelled as authored;
  - the retained `infrastructure_gate` marker in the completed phase, so that `exhaustion()` stays true while the projection is None.

### Nits

- **N1.** The plain-word label in the per-case line for `factory_bug_held` isn't specified, for example "factory bug held". Add it to the `STOPS` wording. It must not echo any card text.
- **N2.** Typo at line 199: "at most128" should be "at most 128". Also, the token rule doesn't say whether matching uses `re.fullmatch`. It should, so a token with a trailing newline is refused.
- **N3.** Typo at line 211: "saved5813be" should be "saved 5813be". "ledger is retained" is unclear; say "continuation_budget unmodified".
- **N4.** The section's rule order matches the code: the `factory_bug_held` check comes before the `failed` and G12 branches, inside `phase == 'stopped'` only. Running and pending rows already skip stopped-case rules (`batch_status.py:110-136`), so the lifecycle precedence needs no new code, only the test. This is a confirmation, not a defect.

### What passes

- It adds no new module, command, data source, mutation or dependency, and the token check plus the "finding unreadable" fallback is the smallest safe design.
- Unscored status overriding a stale `failed_gate` or G12 is specified correctly. The sealed check already requires the stop to be null or `complete`.
- On the current `diagnosis.py`, a pending infrastructure state gives `replacement_eligible: false`, which `_enqueue` turns into one exhaustion resume and no child. A completed state gives a None projection, which queues nothing when the total is known. Both match the parent's ruling.

**To pass:** resolve B1 and M1–M3; the fixes are textual. Then run a fresh goldfish round.


## Elephant resolution

B1 and M1–M3 accepted. Named files and adopted option(b): this increment owns
rendering plus a snapshot read; accounting owns D-to-B queue assertions. Exact
means wording, near-limit coexists and is tested. D's producer/contract update
is an explicit activation prerequisite under the parent ruling, which replaces
the old maintainer queue. Nits fixed: label, fullmatch, spacing, unchanged ledger.
No findings rejected. Fresh round2 requested.
