# Review: stream-d diagnosis-input design 4. PASS (no blockers, 1 major, 4 nits)

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`. I used the zoom_out, design_critic and implementation_readiness personas, with `heilmeier-standard.md` and `implementation-readiness-standard.md`.

**Scope:** commit `17cd006`, "Bind queued input generation to authenticated restore accounting". The diff `ebf3b1a..17cd006` changes only `docs/designs/stream-d.md` (+48/−5), in the section "Queued diagnosis inputs (review-17 follow-up)". I read `stream-d-diagnosis-input-design-3.md` verbatim and checked interfaces §8. I inspected these files only as supporting context: `factory/restore_ledger.py`, the `factory/launch.sh` restore boundary (lines 196–282 and 700–745), `factory/job_config.py`, `founder_ruling.context`, `RunArtifacts.seal` ordering, `run.py` `finalize_accounting` and the `prev_card`/`checkpoint_card` origin, and `carry_over.digest`. The `ebf3b1a` implementation (`diagnosis.py`, `test_stream_d_inputs.py`) is not reviewed and is not claimed ready. It still carries the old `checkpoint_card.sha256` check.

## The accepted correction holds

The code confirms the defect. `RunArtifacts.seal` writes `work/scorecard.json` (`run_artifacts.py:98`) before it tars and encrypts the archive. The archived card therefore can never name its own ciphertext digest. Its `sha256` is either absent (first seal) or the previous generation (later seals). `run.py:2962/2995` loads `c.checkpoint_card` from that archived `work/scorecard.json`. The old rule, "`card.sha256` equals initial `source_generation`", would refuse every legitimate input. Moving the generation off that field is correct.

## Feasibility of the receipt route (verified)

- **Producer chain.**
  - Host: `launch.sh:273–280` requires `card.sha256 == sha256(ciphertext)` and `== --checkpoint-sha256`.
  - Host: `job_config.host_check` (line 65) binds the config's `source_generation` to that same `checkpoint_sha`.
  - Worker: the batch-release path requires a wrapped case key (`restore_casekey` with `$batch_release`, lines 153–156 and 221). The worker then re-checks the ciphertext digest before extraction (line 712).
  - Worker: `launch.sh:731` passes `r2_sha` as `--generation` to `restore_ledger.py`.
  - `install` → `authenticate` → `_authenticated_source` requires `public_card.sha256 == generation`. It writes `SEALED/<case>.restore-accounting.json` under the ledger lock, and the runner starts only after that.

  As a result, `receipt.generation == source_generation` holds by construction on a correct launch. The design's description of this chain matches the code.
- **Path.** `c.ledger.parent` is `SEALED` (`run.py:28/2939`), which matches the `restore_ledger.main` target. `founder_ruling.context` already reads this same path, so this is a reuse of an existing reader, not a new channel.
- **Receipt shape.** The receipt has `version: 1`, `case`, `generation`, `public_card_sha256`, `ledger_sha256` and `accounting_authenticated: true`. It has `retained_ledger_sha256` only when a founder ruling is applied at this restore. `carry_over.digest` returns lowercase hex SHA-256, so the "validate as SHA-256" checks are well defined.
- **Ledger binding.**
  - No ruling: `_authenticated_source` requires `digest(public.continuation_budget) == digest(retained)`, and `ledger_sha256 = digest(imported)`. A present embedded archived budget must equal `retained`, so card budget == `ledger_sha256`.
  - Explicit ruling: `retained_ledger_sha256 = digest(retained)` == card budget.
  - Carried-forward ruling: no `retained_ledger_sha256`, and imported == retained.

  All three branches are consistent with the stated rule.
- **Live ledger growth.** It is correctly decoupled. `ledger.json` is frozen separately and is not hashed against the pre-settlement receipt.
- **Fail-closed.** A missing, malformed, wrong-case, unauthenticated, wrong-generation or mismatched receipt stops with `diagnosis_input_invalid` before publication.
  - Audit paths (`audit_g11`, `sealed_audit`) and fresh launches produce no receipt. Fresh launches are already excluded by the non-null `source_generation` requirement. Audit paths have no B job configuration, so diagnosis admission never gets that far.
  - A stale receipt on a reused worker is caught by the generation comparison.
- **Replay.**
  - The frozen receipt and card are validated against the manifest generation, never against the live receipt or the current binding. A later ordinary restore that rewrites the live receipt cannot invalidate the snapshot.
  - Changed frozen bytes refuse through the existing manifest digests.
  - This keeps design-3 resolution 1 (immutable replay) intact.
- **Scope.** No new public or RAM field, no producer change, no runtime activation, launcher or authority change, and no Murphy closure.

## Findings

### Blockers
None.

### Majors

**Ma1. The test plan does not cover the founder-correction branch of the ledger binding.**
- **Where:** the `restore-accounting.json` bullet ("must equal `retained_ledger_sha256` when that existing correction field is present, otherwise `ledger_sha256`") and the amended test paragraph.
- **Problem:** the named tests are "accepted through a real `restore_ledger.install` receipt", "missing/false/mismatched receipt refusals", "changed live receipt" and "frozen receipt corruption". None of them exercises a receipt produced by `install(..., ruling_path=..., ruling_sha256=...)`. That is the only case where `ledger_sha256 != digest(card.continuation_budget)`.
- **Consequence:** an implementation that always compares against `ledger_sha256` would pass every named test. It would then permanently stop every founder-ruled case with `diagnosis_input_invalid`, a terminal refusal with no automatic reset under design 3.
- **Fix:** add named tests that:
  - accept a receipt from a real `install` with an authenticated founder ruling, where the public ledger differs from the archived ledger, binding through `retained_ledger_sha256`;
  - refuse the same receipt when the archived budget is compared to `ledger_sha256`, or when `retained_ledger_sha256` is altered;
  - accept a carried-forward ruling receipt (`ruling_carried_forward: true`, no `retained_ledger_sha256`) that binds through `ledger_sha256`.

  `tests/factory/test_restore_ledger.py` already builds real `install` receipts and can supply both.

### Nits

**N1. An absent archived budget is unspecified.** `_authenticated_source` accepts an archived card with `continuation_budget` absent or `None` when `work/continuation-budget.json` exists (`embedded is None or ...`). The design's binding refuses that card, because `digest(None)` matches neither digest. That is fail-closed and fine for new-schema cards: `finalize_accounting` always embeds the ledger before seal. Still, state it explicitly ("an absent archived `continuation_budget` refuses input-invalid") so an implementer does not add a fallback to the work-tree file, which is not in the frozen input set.

**N2. Type strictness.** "integer `version: 1`" should say `type(version) is int` (rejecting `True`), as `job_config.install` already does for `schema`. "literal `accounting_authenticated: true`" should say `is True`.

**N3. List formatting.** The `card.json` entry still runs on from the `ledger.json` bullet without its own `- ` marker. This predates the amendment, but the amendment rewrote the entry. Split it so the input inventory reads as five items: case, ledger, card, receipt, work.

**N4. Missing rationale.** A reader may ask why the design doesn't take the generation directly from `c.source_generation`, which it is compared to anyway. Add one sentence: the receipt is the worker-side proof that this exact generation's archive was extracted and its accounting authenticated on this worker, and it is the only generation evidence that can be frozen for replay. `source_generation` is mutable current authority. This is what justifies carrying the extra file instead of a single field.

## Assessment of the named tests (excluding Ma1)

The amended list covers:
- acceptance of real archived cards with absent or older `sha256` through a real `install` receipt;
- missing, false and mismatched receipt refusals;
- unchanged replay after a later restore rewrites the live receipt;
- frozen-receipt corruption;
- the existing later-authenticated-source-generation replay;
- initial generation mismatch.

These match the real-artifact rule. Real seals produce exactly the absent-or-older `sha256` card shapes, and `install` does not need a ciphertext, so the tests are feasible without decryption. Live-ledger growth after restore needs no separate new case: design-3 test 1 ("append live usage and replay") together with the explicit statement that `ledger.json` is not hashed against the receipt covers it. The implementation should assert that this replay goes through a real receipt.

## Prior findings
Design-3 resolutions 1–6 still hold. The amendment changes only where the initial generation comes from and adds one frozen input. It does not touch the lifecycle, re-staging, producer-specific evidence or isolation rules.

## Validation boundary
PASS applies to design readiness only. Ma1 should be fixed in the design before implementation, because a terminal refusal is the failure mode. The `ebf3b1a` implementation still uses the old `checkpoint_card.sha256` check and needs its own diff review after it is changed. No files were written, no tests, suite, workloads, launches or decryption were run, no Murphy row closes, and no runtime activation or authority change is claimed.

## Elephant resolution

PASS accepted with Ma1 and all four nits accepted. Add explicit real-install
founder-correction and carried-forward ruling replays before implementation;
refuse missing embedded archived accounting, state strict version/boolean checks,
split the card inventory bullet, and explain the receipt's durable restore proof.
No finding is rejected. Review22's stale-cache major also requires a design
amendment and fresh design review before dispatcher wiring. No Murphy row closes.

