# Goldfish review: resume role swap (diff 1)

- Branch: feat/resume-role-swap, commits e003567f and 0cba67be on main 018a8fe6
- Mode: REVIEW (personas: zoom_out, implementation_readiness). No design doc; reviewed against the commit messages.
- Reviewer: goldfish, read-only. No code changed.

## What I checked

- Family rules: FACTORY.md section 3 (four distinct families; strong calibrator on a subscription, never the writer family; easy calibrator not a contestant family; explicit role flags still satisfy separation). docs/ENGINEERING.md section 4 is design rules (one launch path, real artifacts, delete before adding), not family rules. AGENTS.md has no family rules.
- Whether a swap can reuse the old role holder's evidence.
- DBOS replay of already-recorded workflows.
- Merge against origin/opt/integration (`git merge-tree`).
- Targeted tests: test_resume_role_swap (16 OK), test_durable_runtime (29 OK), test_durable_admit (34 OK), test_durable_engine filtered to swap/resume (see the end).
- Real artifact: sealed/case-20261019T065843Z-22e434.scorecard.json.

## Evidence reuse: holds

Every place that reuses work done by a swappable role is keyed on that role's model, so a swap cannot carry the old holder's verdicts forward:

- G2 identity names attacker and stress_tester (factory/gate_state.py:176-183). Stress-stage identity names the attacker model and role (gate_state.py:203-208). Stress category state lives under `digest(attack_binding)` (stress_progress.py:50-52; run.py:966-973 binds `c.models["attacker"]`). A swapped attacker gets a fresh directory.
- G10/G16/G17/G11 identities name strong_calibrator (gate_state.py:176-177). Calibration attempts and the early-probe reuse are keyed on `calibration_identity`, which holds `c.models[role]` (run.py:2084, calibration.py:351-356). No try from the old calibrator is reused.
- opt/integration's resume-reuse work (54160930: `strong_attempts_exist`, the G7 cache, slot-tolerant `compatible_identity`) and narrow fingerprints (gate_state inputs) still keep attacker and strong_calibrator in the identities. The swap does not open a reuse hole there.

## Findings

### 1. should-fix (blocking for the merge into opt/integration): the five-family reviewer rule must move into `check_role_families`
- factory/model_runtime.py:127 and :139-154. `git merge-tree origin/opt/integration 0cba67be` conflicts in factory/model_runtime.py (and tests/factory/test_durable_engine.py).
- opt/integration's select_models always adds reviewer2 (`second_reviewer`) and requires five distinct families: reviewer2 differs from writer, stress tester, strong calibrator and reviewer. This branch moved the rules into `check_role_families` using main's older rule: reviewer2 only differs from writer and stress tester.
- Failure scenario: someone resolves the conflict by keeping this branch's one-line `check_role_families(...)` call. Then select_models loses the five-family rule. A swap of the strong calibrator into reviewer2's family also passes. In opt/integration, `context_for_step` runs `with_second_reviewer` (run.py ~3112 there) before `swap_roles`. reviewer2 is picked against the old stress tester and strong calibrator, then the swap can move the strong calibrator into reviewer2's family, and the old rule does not see it.
- Weakens the exam: yes, if resolved that way. G8/G9 lose an independent second reviewer.
- Fix at merge: put the five-family check, with reviewer2 required whenever present, inside `check_role_families`. Keep `second_reviewer` insertion in select_models before the call. Add one swap test: strong_calibrator swapped into reviewer2's family must be refused.

### 2. should-fix: select_models now enforces the rotation `refused` list on explicit pins (a policy change, and it can block the swap at ADMIT)
- factory/model_runtime.py:152-154, called from :127. ADMIT order is at factory/durable/steps/admit.py:797-799 (`_pin_models` then `swap_roles`).
- Before this change, explicit role flags bypassed `refused` (only rotation rows were checked, model_runtime.py:203-204). A Codex attacker like the one in the commit's motivating case can only come from an explicit pin, because both rotation tables refuse openai as stress_tester.
- Failure scenario 1: any batch whose INPUTS pin `attacker: codex/...` now fails every ADMIT attempt. A ValueError becomes `admit:processing_failed`, which is INFRA_ERROR, so it is retried and then diagnosed.
- Failure scenario 2: a case that stopped in ADMIT with a Codex attacker pinned is resumed with `--roles stress_tester=<non-openai>`. `_pin_models` → select_models raises on the old pin before `swap_roles` runs, so the swap that would fix it never applies.
- Weakens the exam: no. It is stricter. But it is a founder-facing policy change: FACTORY.md says explicit flags must only "satisfy family separation". It was bundled into a review-fix commit.
- Ask: get founder sign-off and say it in FACTORY.md section 3. Otherwise keep `refused` for the swap only. Either way, apply the swap to the INPUTS roles before the families are checked at ADMIT, or check the refused list after the swap.

### 3. should-fix: a stress tester swap is accepted at SEAL (and after G2 passed) for no use, and it makes the sealed record disagree with its evidence
- factory/run.py:2703 restricts only the strong calibrator. A stress_tester swap is applied on GATES and SEAL steps too (run.py:2770-2771).
- The attacker does no work at SEAL (engine_seal, run.py:3133). Swapping there rewrites `card.roles.stress_tester` and `card.models.attacker` in the sealed scorecard. The G2 record and the stress-stage `scientific_version` were made with the old attacker, so they no longer match the card's identity. extension_compare (extension_compare.py:42-57,123) and any recertify then see them as stale or mismatched. The scorecard names a stress tester that never stressed the case. `role_swaps` records it, but nothing that reads `roles` reads `role_swaps`.
- Weakens the exam: no, but the reported per-role models (FACTORY.md section 3: "Exact model IDs ... recorded per role") become misleading.
- Fix: refuse a stress_tester change on a SEAL step, as is done for the strong calibrator. Optionally, also refuse it once `card.gates` holds a G2 result.

### 4. should-fix: refusals the worker finds by reading the case card burn infra attempts before the diagnosis
- factory/run.py:2687-2720 raises ValueError from `context_for_step`. The commit says each attempt then fails `infra:context_failed` until the infra allowance runs out.
- These refusals are deterministic (family collision, G10 rule), so every retry is a pit stop that cannot succeed.
- Real artifact: on sealed/case-20261019T065843Z-22e434.scorecard.json (writer deepseek, stress minimax, strong anthropic, reviewer openai), the brief's example `stress_tester=claude/claude-opus-5-5,strong_calibrator=codex/gpt-6.1-sol` is refused. So are `stress_tester=claude/...` alone and `stress_tester=codex/...` alone. I ran `check_role_families` against that card's roles. The live 22e434 card may differ, since the brief says its attacker is Codex, but this shows the realistic outcome: the operator learns about the refusal only after N wasted worker attempts.
- Weakens the exam: no.
- Fix: return a non-retryable result for a refused swap, such as EXHAUSTED with a `roles_refused` reason, instead of letting it be classified as infra.

### 5. nit: stale early-probe label after a strong calibrator swap
- The early probe runs at G5 inside the writer round's early checks (run.py:936-937, EARLY_GATES at run.py:38), which is before the first GATES step. So `card["early_probe"]` (`likely_hard`/`solvable`) can come from the old calibrator. A later swap is allowed, and an unchanged G5 is reused, so the probe is not rerun.
- It is only a label and G10 does not reuse it (the identity differs), so the exam is not weakened. The board or label would show the old model's result. Fix: pop `early_probe` when the strong calibrator changes.

### 6. nit: `check_swap_models` uses the default accounts
- factory/model_runtime.py:157-166 calls `bounded_route(role, model)` with `model_router.ACCOUNTS`. require_bounded_models uses `c.router_accounts` (model_runtime.py ~183). In the worker path (run.py:2714) the case's accounts are known and should be passed.

### 7. nit: duplication
- `SWAP_MODEL_KEYS` (run.py:2684) restates the role-to-models-key map that already exists as `RECERTIFY_ROUTE_KEYS` (admit.py:238, inverted) and in select_models' `flags`.
- `resume_point` (engine.py:465-467) re-lists the lineage that `_resume_point` already lists and reads `resume` from (engine.py:500-501, :531).
- Small, but the repo's rule is to reuse what is there.

### 8. nit: the swap invalidates in-flight call checkpoints of unswapped roles once
- checkpoints.py:198 puts all of `card.roles` in each call checkpoint identity. A partly done writer or reviewer call checkpoint from before the swap is not reused. This is one-time waste, not correctness.

## DBOS replay: safe

- `StepInput.roles` is `omit_none`. `to_record` drops it when None (contract.py:719-720), and `_exact` accepts its absence (contract.py:728-735). Old recorded jobs and step inputs stay byte-identical. `idempotency_key` does not include roles (contract.py:270-272).
- `case.roles` comes only from the recorded job (`resume.get("roles")`, engine.py:1468). `_Batch.start_case` copies it from the recorded batch job (engine.py:1558-1559). Both are deterministic on replay.
- `resume_point`'s `DBOS.list_workflows` runs in `Engine.start_batch` (engine.py:2026), outside any workflow. Its result is frozen into the batch job input.
- The worker re-applies the swap idempotently. `changed` is empty once the snapshot holds it (run.py:2699-2701).
- Operational caveat (nit): the swap reaches only workers whose plumbing release has this contract. An older release's `_exact` rejects a StepInput that carries `roles`. Releases roll forward, so this only bites if a resume pins an older plumbing release.

## Zoom-out

- One launch path holds: the swap is a resume argument carried in the resume record, not a rescue branch.
- The scope fits the founder's ask (two roles). History lives in `role_swaps`. Undo is "resume naming the old model", with no new verb. That is the lazy, right shape.
- The strong-calibrator rule ("before the first GATES step") is a reasonable proxy, but it is not exact: see finding 5. It is checked in one place.

## Verdict

**Approve for main after findings 2-4 are addressed or explicitly accepted by the founder.** Finding 1 must be handled in the opt/integration merge: the resolution must move the five-family reviewer rule into `check_role_families`, or the exam gets weaker. No evidence-reuse hole and no DBOS replay hazard was found.

Tests: test_resume_role_swap 16 OK, test_durable_runtime 29 OK, test_durable_admit 34 OK; test_durable_engine (filtered -k role_swap -k swap -k resume) 31 OK.
