# Goldfish diff review 1: `stream-d-admitted-execution`, diff `80d16ea..0d3259f`

**Mode:** REVIEW. **Personas:** zoom_out, implementation_readiness. **Standards:** zoom-out-standard.md, implementation-readiness-standard.md.

I reviewed read-only at commit `0d3259f`. I read the design, both design reviews and their elephant responses, the suite record, and the whole code and test diff. I also read the surrounding code in context:
- `run.py`: `write_and_attack`, `main`, `loop_freshness`, `confirm_hits`, `pending_call`, `complete_writer`, `resume_provider_wait`, `write_provider_wait`;
- `extensions.py`: `writer_receipt`, `retain_writer`, `writer_continuation`, `_WRITER_MUTABLE`;
- `diagnosis_dispatch.py`: `apply`, `replay`, `_dispatch`, `dispatch`, `CARRY`;
- `sealed_audit.prepare`.

The suite log's SHA-256 matches the record (`a167f7da…`). It ends with "159 test scripts run; 0 failed." The design was not skipped.

**Verdict: does not pass yet. One blocking finding is open**, and it is a missing test, not a code defect. Every code path I traced matches the design.

---

## Requested checks

### 1. Exact admitted authority: sound
- **The decision must match the active row.** In `apply`, `row['exhaustion_id'] != manifest['exhaustion_id']` raises `InputVerificationError`, which becomes `diagnosis_input_invalid`.
- **Only replay can execute.** Execution is returned only when `resume=True` and `DIAGNOSIS_ENABLED is True`, and only `replay` passes `resume=True`. `invoke` and the second `apply` call in `_dispatch` still stop unconditionally.
- **The identity is a strict integer.** `_dispatch` and `main` both check `type(...) is int`, so `False` (no diagnosis) can never be mistaken for identity 0.
- **`write_and_attack` re-checks everything before any model call.** It verifies:
  - the modern job, `job_authority.for_case`, and the integer identity;
  - that `active()['extension_id']` equals the identity;
  - `writer_receipt(c)`;
  - the receipt's `schema_version == 2`, actor, phase, `round == row.round` and `round_limit == row.round`.
- **`round_limit` is enforced in two places.** `retain_writer` checks it against `receipt['round']`, and `writer_receipt` checks it against `row['round']`.

### 2. One writer and one stress round: sound
- **No second writer.** `round_limit` comes from the history row at both the initial assignment and the receipt-parse override, and `args.rounds` is never changed. Writer validation failure (`continue`) and stress findings at the ceiling both end in the post-loop `exhausted=True` / `rounds_exhausted`. The modern path raises before the final-repair `builder-precheck`.
- **No reselection or prototype.** The whole `complete`/prototype/reselect block sits under `extension is None`.
- **No G1 heuristic.** `skip_writer` short-circuits on `extension is None` before `g1` is evaluated.
- **Stripping `failed_gate` is necessary, and a test proves it.** Without the strip, `test_pending_stress_from_gate_failure_resumes_without_writer` would take the `report = None` branch and finish with an empty `range(n+1, n+1)`.
- **The writer intent stays immutable on replay.** `copy.deepcopy(resume_unit)` keeps the intent unchanged. The later `.update(...)` fields that are outside `_WRITER_MUTABLE` (`before_repair_sha256`, `repair_requested`, `findings_report`, `input_problems`) are re-derived from the same receipt, so they compare equal. The test confirms this.
- **The binding hash now stays consistent.** `binding_sha256` is updated with `binding` at the `resume_writer_validation` site. The in-loop site already went through `complete_writer`.

### 3. Terminal markers prevent repeat work: sound
- **All three success sites are covered.** The pre-loop recovery, the freshness-cleared recovery and the in-loop site each publish `phase=validated, next_phase=extension_comparison`. `early_review` is skipped at all three of its call sites, and there are no others in the function.
- **The marker's evidence survives freshness.** `loop_freshness` writes `round-N-writer.json` and leaves the original `round-N.json` unchanged. So `review_completed.report_sha256` still verifies on re-entry.
- **The re-entry check comes before any paid work.** It runs after `resume_provider_wait` and identity validation, and before every freshness, G1, `early_checks`, writer or stress call. Tampered terminal evidence refuses (`extension_reservation_mismatch`), and a test covers it.

### 4. `main` refuses other modes and stops before final gates: sound
- **Modes.** All eight modes in the design are refused with `extension_execution_mode_invalid`, and a test covers each one.
- **Repair policies.** `raised_limits` and `restore_gate_crash` are skipped for this route.
- **Stop.** `extension_comparison_pending` is raised unconditionally after `write_and_attack`, so `build`, `validate_and_repair` and `seal` cannot be reached.
- **Labels.** `write_provider_wait` overwrites `terminal_stop` with `provider_wait`, so the pending label that `apply` published early cannot hide a provider wait.

### 5. Tests use saved artifacts: mostly
`test_stream_d_execution.py` runs real admission, real `pending_call` reservations against the saved runtime/5813be ledger fixtures, the real receipt machinery and the real loop. It substitutes authored model outputs, G1 results and freshness results, as the design declares. Gaps are listed below.

No Murphy row is claimed closed. Row 9 is only cited as supported, which matches the design.

---

## Blocking findings

### B1. The design's provider-wait and infrastructure-interruption tests through execution are missing
- **Severity:** Blocker (implementation readiness: a required test from the standard is absent)
- **Scope:** design line 117 ("Exercise provider wait and infrastructure interruption through the real admission/receipt machinery") and lines 90–92; `tests/factory/test_stream_d_execution.py`
- **Finding:** The new execution tests only exercise a `Killed` crash. None runs an admitted writer or stress call that ends in `ProviderWait` or `InfrastructureExhausted`, then resumes through `write_and_attack`.

  This path is new behaviour, not only an existing one. After `resume_provider_wait` clears `lease_id` and `invocation_id` and sets `resumed_from_wait`, the admitted writer now replays a deep copy of that receipt. It then relies on `writer_continuation` → `provider_continuation` to authorise a new lease under the same `writer_operation_id`. I traced it and believe it works, but nothing checks it. `test_settled_provider_wait_continues_extension` only covers the `pending_call` layer, not the loop.

  The stop labels the design protects (`provider_wait`, `infrastructure_exhausted`, `runner_error:<type>`, never a scientific failure) are not asserted anywhere for admitted execution.
- **Guidance:** Add two tests in `test_stream_d_execution.py`:
  1. **Writer provider wait.** The admitted writer raises a provider wait. `write_provider_wait`, then `resume_provider_wait`. Re-execute. Assert:
     - exactly one more `builder-9` call;
     - the intent's fields outside `_WRITER_MUTABLE` are unchanged;
     - a terminal marker on success.
  2. **Stress infrastructure failure.** The stress call raises `InfrastructureExhausted`. Assert:
     - the stop label is `infrastructure_exhausted` (via `main`, or by asserting the exception type);
     - re-entry reruns only `attacker-9`.

---

## Non-blocking findings

### M1. Admitted execution loses the scorecard-retained freshness verdict path
- **Severity:** Major (non-blocking)
- **Scope:** `diagnosis_dispatch.apply`, which now writes `scorecard.json` and then returns into execution; `run.loop_freshness`, which reads `scorecard.json` for `loop_freshness.verdict_path`; `CARRY`, which has no `loop_freshness` key
- **Finding:** Before this diff, `apply` rewrote `scorecard.json` and then stopped. Now execution continues after that rewrite. `loop_freshness` reads its retained `verdict_path` from `scorecard.json`, so for admitted work it always finds `None`.

  The primary retention, the binding-keyed `freshness-verdict.json` receipt, is unaffected. But the secondary recovery is lost. That recovery covers a kill after `review-completed.json` but before the receipt write. In that window, one extra paid freshness reviewer call is possible, bounded only by batch money. The design says freshness "uses existing durable freshness machinery".
- **Guidance:** Do one of these:
  - pass `prev_card`'s `loop_freshness` into `c.card` (or add it to `CARRY`);
  - state the narrower guarantee in the design.

### N1. `run.py` reaches into a private helper
`write_and_attack` calls `extensions._writer_json`. Expose a public reader, or have `writer_receipt` return what the entry check needs.

### N2. The terminal-evidence check duplicates existing logic
It re-implements, inline, the same four-condition `review_completed` authentication used by the pre-loop path (~line 1347). The `sha256(json.dumps(binding, sort_keys=True))` expression now appears about 8 times in `write_and_attack`. Extract one small helper so the two authentications cannot drift apart.

### N3. "Lagging scorecard" is only simulated in memory
`terminal_replays` pops `stress_review` from the in-memory `c.card`. It never re-enters through `dispatch`/`apply` with an on-disk checkpoint whose card predates the receipt. An end-to-end `main_resume` after a real terminal receipt would prove the whole stop path. That path is `apply` → `writer_receipt` (stress actor returns `None`) → entry check → same label.

### N4. The mismatched-row test uses a patched row
`test_replay_rejects_active_row_from_other_decision` patches `extensions.active` with a mismatched row. That is acceptable as a control, but it is not a saved artifact.

### N5. Two design-listed tests are not visibly new
I could not find new tests for "missing authority" (only stale authority is tested) or for "corrupted decision" with the flag enabled. Either point to the existing tests that cover them, or add them.

### N6. Audit-mode setup runs before the refusal
`audit_fairness`/`rehearse_only` run `sealed_audit.prepare` before `dispatch`, so the refusal comes after that setup step, not "before any setup". This is harmless: it copies into a fresh audit workspace and makes no model call. Note it in the design.

---

## Zoom-out
The change is proportionate. It reuses the existing loop, receipt fields (`next_phase`, `exhausted`, `stop_reason`) and the reservation and continuation machinery. It adds no new file, schema, ledger or money authority. The deletions the design promised are present: the unconditional replay stop, the round clamp for admitted work, and the replay overwrite of the writer intent.

**To pass:** add the B1 tests and re-run the full suite to a fresh log. M1 and N1–N6 are optional, but M1 should at least be recorded in the design.

## Elephant response

B1 accepted: add real loop provider-wait and infrastructure-exhaustion replays, rerun the full suite, and request fresh verification. M1 accepted as a documented narrower guarantee for this increment: binding-keyed freshness receipts remain retained, but the scorecard-only fallback can be lost across apply; full package integration must preserve it. N6 clarified in the design. N1–N5 remain nonblocking suggestions; no blocker is rejected.

