# Diff review 1: cb5e26-nw-gate hotfix (goldfish)

Mode: REVIEW. Personas: `zoom_out`, `implementation_readiness`. Standard: `implementation-readiness-standard.md`. Repo rules: `docs/ENGINEERING.md`.

## Scope

- **Branch:** `hotfix/cb5e26-nw-gate` at 1102afc0, base d038ab59 (cb5e26's live source). That is 32 commits: PR #197 (16), PR #198 (5), PR #207's own commits (9), the walled-gate commits 1c5f4b3c and e0a81dbe, and the pin commit 1102afc0.
- **Design:** `docs/designs/neuralwatt-walled-gate.md`, including its "Gate identity" and "Deploy" sections. The coordinator's instruction is quoted in the review request.
- **What I ran:**
  - `git range-diff` for each source PR.
  - `git diff` of the hotfix against `feat/neuralwatt-walled-gate`.
  - `git show --remerge-diff` of the merges 576901b1 and 9e3dda56.
  - `ident.py`, `myident.py` and `vcode.py`.
  - The ten named test files.
  - A scratch cross-version check, `scratchpad/hotfix-review/xver.py`. It sends the hotfix worker's own `acquire` payload to the `feat/neuralwatt-walled-gate` (main-side) router `Store`.
- Nothing was edited, committed or pushed.

## 1. Fidelity

- **Range-diff:** every backported commit is `=` to its original, with two exceptions, and both are hunk context only:
  - 0a98bce5 vs dafec806: the recorded token_prices.py conflict. `_request_worst` and `openrouter_cached_tokens` are both kept, and the function bodies are identical.
  - 1c5f4b3c vs 3bc37499: the same token_prices.py context.

  PR #198 and PR #207 are `=` throughout.
- **Merges not taken:** 9e3dda56 has no remerge conflict. 576901b1's only resolution is `capacity_protocol=2, chain=chain(model)` in `_admit`. Skipping it leaves the hotfix at `capacity_protocol=1, chain=...`, which is exactly what PR #207's own commit cd3ad4bb sent.
- **Hotfix vs `feat/neuralwatt-walled-gate`, `factory/` and `bin/`:** every model-path difference is main-only work the hotfix should not carry:
  - router-retry: `PAID_RESERVE_RETRY_*`, `RENEW_RETRY_*`, `RouterRejected`, the cached credit balance, `refresh_credit`, `request_queue_size`;
  - `no_route`, in classify.py, stop_registry.py and `REASONS`;
  - `capacity_protocol=2`.

  The other differences are unrelated main work: engine.py, admit.py, run_artifacts.py, slot_state.py, prompts, fake-pass-check, diagnostics.py, ordinary_freshness.py, and run.py beyond `Ctx.router_accounts`. Of the test files the hotfix touches, only `test_model_router.py` and `test_router_paid_spend.py` differ from the branch, and the differences are router-retry tests only.
- **Nothing non-Neuralwatt slipped in.** `d038ab59..HEAD` touches only Neuralwatt files: budget.py; classify.py and stop_registry.py (`neuralwatt_limit`); model_call_gate.py, model_router.py and model_runtime.py; ordinary_retry.py; run.py (`router_accounts` only); token_prices.py; `bin/setup-secrets` (new `neuralwatt` step); tests, fixtures, designs and reviews. `durable/helpers.py` nets to zero: 16ee81d6 is reverted by 1609996e.
- **Skipping router-retry and 576901b1 is consistent:**
  - A `capacity_protocol=1` worker is never sent `no_route`. Main's router sends it only when `capacity_protocol == 2`, so the hotfix's lack of `no_route` in classify.py is consistent.
  - Main's router accepts `chain` together with protocol 1.
  - The hotfix gate's single-shot `paid_reserve` never sees `duplicate`, because each request uses a fresh id.
  - The Neuralwatt gate path makes no `paid_reserve` at all.
  - **Checked on code:** `xver.py` builds payloads with the hotfix's own `_admit` and sends them to main's `Store.rpc('acquire')`:

    | Call | Lease from main's router |
    |---|---|
    | walled GLM `easy_calibrator` | `neuralwatt/glm-5.3-flash` on `neuralwatt-key` |
    | walled DeepSeek `strong_calibrator` | `neuralwatt/deepseek-v4.1-flash` |
    | unwalled MiMo `writer` | `opencode-go/mimo-v2.6-pro` |

## 2. Identity

- **Output of `ident.py ... d038ab59 HEAD`:** `cmp exit 0 IDENTICAL`, 165732 bytes each side.
- **verdict codes:**

  | Tree | Bench answers | Bench raw | Model answers | Model raw |
  |---|---|---|---|---|
  | d038ab59 | d4a7127a… | e50c8b74… | 73aa880a… | 73aa880a… |
  | HEAD | d4a7127a… | e50c8b74… | 73aa880a… | aaa935cb… |

- **What `myident.py` covers:**
  - `gate_state.model_science()`, which is `family` and `model_effort` traced transitively;
  - `sealed_audit.delivery_contract()`;
  - `runner_inputs` for every gate in `STAGE_DEPENDENCIES`;
  - `dependency_files(..., include_pool=True)` plus `case_contract.py`. This catches `durable/helpers.py` and `durable/helper_link.py` as dependencies of G5, G6, G7 and G10. Both are unchanged;
  - the calibration and stress judge `source_inputs`;
  - every prompt file;
  - `release_pins()`.
- **What it does not hash:** `run.prompt()`'s code, `environment()`, and the card and model inputs.
  - run.py's only edit is in `Ctx.__init__`. `prompt()` and `select_models` are unchanged, and the card does not move.
  - So the identity is proved for this tree (gap noted as N5).

## 3. The verdict_code pin

- **The values are right.** d038ab59's own pin (`3429db4f→898b3f9d`) is stale, so d038ab59 answers its raw digest, 73aa880a. The hotfix pin is `from 73aa880a, to aaa935cb`, and aaa935cb is HEAD's raw digest. The bench pin is unchanged.
- **What the pin keeps:**
  - The model-stage engine-checkpoint folder: G10, G11 and G17 gate entries, and every model-effect receipt.
  - Helper job `release`, so `try_key`s, and with them the saved G10 try results, are unchanged.
- **Why that is sound:**
  - Model-effect receipts are keyed by request text, models, roles, root and ordinal, and replayed against the workspace pre-image. No route, account or price enters the key.
  - Gate entries are keyed by `gate_state.inputs`, which is identical.
  - ordinary-retry state lives outside the pinned folder. Its binding is unchanged, and its spent-route check now accepts a superset.
  - Budget ledger rows gain one optional key, `open_steps`.
- **On neuralwatt-first-design-3 (finding 3):**
  - It was a NIT. It asked for either a stated cost or a pin argued in the diff review.
  - Its reason, that "model_runtime.py and model_router.py change model effects", is about which lane serves **future** calls. No saved receipt or verdict is reread or reinterpreted by these edits.
  - I side with the pin.
  - Science caveat: a G10 verdict may combine earlier tries (GLM on OpenRouter's fp4/fp8 endpoints) with later ones (GLM fp8 on Neuralwatt). The founder accepted that note for walled roles on 2026-11-20, and OpenRouter tries were already a mix of endpoints.

| Hotfix SHA (original) | Verdict files | Change | Changes a saved verdict, receipt or checkpoint meaning? |
|---|---|---|---|
| 0a98bce5 (dafec806) | model_router.py | `neuralwatt-key` appended to `ACCOUNTS` (the `[2:4]` slice is unchanged). Neuralwatt lanes inserted into the MiMo and GLM `CHAINS`. `route_maximum` for Neuralwatt. `ungated_lanes` + Neuralwatt, later reverted by 1c5f4b3c. | No. Every old route name is still in `routes()`, so saved `spent_routes` stay valid. `family` is untouched (`model_science` identical). Receipts carry no route in their key. |
| 6d81e63c (1ce69658) | model_call_gate.py, model_runtime.py | Unwalled Neuralwatt branch in `enforce` and `free_environment`. `offered_accounts`. Neuralwatt provider in `opencode_config` (added only when `model in NW_ROUTES`). `go_quota_moves_on` for Neuralwatt credit and quota. `NEURALWATT_API_KEY` env. `valid_lease` takes the accounts. | No. Each non-Neuralwatt lease takes its old path byte for byte. This adds future lanes only. |
| 16ee81d6 + 1609996e (67b6d99d + 1f9a704e) | durable/helpers.py | Edit, then revert. | No. The file is byte-identical to d038ab59, as the identity also proves. |
| 2ce494a4 (afca11c6) | model_runtime.py | `diagnosis_environment` gives a Neuralwatt lease no key. | No. |
| 09287038 (66570209) | ordinary_retry.py | `spent_routes` checked against all of `ACCOUNTS`, not just the offered ones. | No. Everything that was valid stays valid, and the binding and directory key are unchanged. |
| cd3ad4bb (0890f9b3) | model_router.py, model_runtime.py | DeepSeek Neuralwatt lane. `chain()` factored out. Acquire sends `chain`. Router `knows`. Neuralwatt's own list price. | No. These are wire and lane changes. No saved state carries a chain. |
| 4f266bbc (4d739f80) | model_runtime.py | Comment only. | No. |
| 4b850e19 (5ba15c89) | model_call_gate.py | Comment only. | No. |
| 1c5f4b3c (3bc37499) | model_call_gate.py, model_router.py, model_runtime.py | Walled Neuralwatt through the gate. `gate_profile` returns `GATED_OPENROUTER[route]` for OpenRouter routes, so OpenRouter holds and prices are unchanged. The `paid` path is unchanged. `ungated_lanes` and `bounded_route` drop Neuralwatt. A walled caller outside `WALLED_ROLES` still excludes Neuralwatt. | No. It only adds a lane a walled call may lease next. The Claude and OpenRouter gate paths are behaviour-identical (tests below). |

## 4. Tests (hotfix tree, `uv run --with dbos==3.4.0 --with numpy --with scipy`)

All OK:

| Test file | Tests |
|---|---|
| test_neuralwatt_walled_gate | 7 |
| test_neuralwatt_routes | 10 |
| test_neuralwatt_runtime | 8 |
| test_neuralwatt_budget | 15 |
| test_free_routes | 9 |
| test_cached_window | 5 |
| test_model_call_gate_wall | 8 |
| test_model_router | 49 |
| test_router_paid_spend | 51 |
| test_stream_d_retries | 68 |

Logs are in `scratchpad/hotfix-review/*.log`. The full suite is the coordinator's run and was not repeated.

## Findings

No BLOCKING findings.

- **N1 (NIT, deploy): a plumbing release alone may not wake cb5e26.**
  - If cb5e26 is parked in the engine's `wait_for_credit`, it loops on `credit_ready_step()`, which reads the router's paid-pool credit block. A plumbing release does not break that loop.
  - `lift_credit` lifts the block only when the balance covers the holds in flight, plus the dearest gated OpenRouter hold, plus a margin. It also refuses inside backoff or past the cap.
  - At $2.50 it may answer `short_by` or `capped`, and then the operator needs `--lift-credit`.
  - The Deploy section of the walled-gate design does not cover this. Check the case's engine status before relying on the release.
- **N2 (NIT, rollback): once cb5e26 runs a Neuralwatt step, never move it back to d038ab59.** The design's rollback rule names only 3dfdde3c. At d038ab59:
  - `budget.usage_coverage` rejects ledger rows that carry `open_steps`;
  - `ordinary_retry` rejects Neuralwatt `spent_routes`;
  - `model_router.routes` raises `unapproved account` for a `router_accounts` list that includes `neuralwatt-key`. This also applies to any d038ab59 helper, which the pin lets accept hotfix jobs.

  Withdrawing the key is the only rollback.
- **N3 (NIT, preconditions this repo cannot prove):**
  - The live router must be at neuralwatt-first or later. An older router refuses `chain` as `invalid admission fields`, and every acquire fails.
  - The controller's `worker_credentials.accounts` must include `neuralwatt-key`, so the case worker and its G10 helpers (same bundle) hold the key. Otherwise a keyless walled try reports `credential_expiring` account-wide and blocks the Neuralwatt pool for every case (design N8).

  The design asserts both. Neither is visible from the repo.
- **N4 (NIT): no router-retry on the worker side.**
  - G10 calls that fall through to the OpenRouter twin still have no renew or `paid_reserve` retry, so they are exposed to the 19 November lost-reply losses. That is not a regression from d038ab59, and it follows the instruction.
  - Neuralwatt 429s each keep a $0.17 hold. About five end a walled call as `model_call_cap` (the design's own ceiling). Walled G10 tries now share Neuralwatt's 3 seats with every main case that runs Neuralwatt first.
- **N5 (NIT): gaps in `myident.py`.** It does not hash `run.prompt()`'s code, `environment()`, or the card and model inputs. That is harmless here, because run.py changes only `Ctx.__init__`. Note it if the script is reused for a run.py edit.
- **N6 (NIT, record):** 1102afc0 carries the pin, but no review file on the branch argues it SHA by SHA. Save this review as that record and cite it in the release note. A per-case branch also leans against ENGINEERING §4 "no rescue branches". The design acknowledges this and leaves it to the coordinator.

## Verdict

PASS

---

## Elephant's record

- No blocking finding. This file is the per-SHA pin argument for 1102afc0 (N6).
- **N1, N2, N3:** added to the walled-gate design's deploy notes (cherry-picked onto this branch); N3's two preconditions (router at neuralwatt-first or later; `neuralwatt-key` in the controller's worker credentials) go to the coordinator.
- **N4:** accepted as instructed (no router-retry on this branch).
- **N5:** noted; run.py changes only `Ctx.__init__` here.
