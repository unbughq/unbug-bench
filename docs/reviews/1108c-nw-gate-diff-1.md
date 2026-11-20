# Diff review 1: 1108c-nw-gate hotfix (goldfish)

Mode: REVIEW. Personas: `zoom_out`, `implementation_readiness`. Standard: `implementation-readiness-standard.md`. Repo rules: `docs/ENGINEERING.md`.

## Scope

- **Branch:** `hotfix/1108c-nw-gate` at f0685e97. Its base is 3dfdde3c, 1108c's live source. The branch has 13 commits:
  - PR #207's own commits, 9 of them (db1e5aad..176be5d3, originals b8cec463..5d155d44);
  - the walled-gate commits 223ed35f, ab203bba and 122e3b77 (originals 3bc37499, 04416d93, 01c6f97e);
  - the pin commit f0685e97.
- **Design:** `docs/designs/neuralwatt-walled-gate.md`, including its "Gate identity" and "Deploy" sections. The coordinator's instruction is the bar.
- **What I ran:**
  - `git range-diff`, and tree comparisons against the originals;
  - `git diff` of the hotfix against `feat/neuralwatt-walled-gate` and against `origin/main` (616ad550, which already merges PR 208);
  - `ident.py`, which runs `myident.py` and `vcode.py`;
  - the nine named test files, plus `test_model_runtime.py`, because the branch touches it;
  - two scratch cross-version checks under `h1108c-review/`:
    - `xver.py`: the hotfix worker's own `_admit` payload sent to origin/main's router `Store`;
    - `maxcheck.py`: `route_maximum` for every chain route, hotfix against origin/main.
- I edited, committed and pushed nothing, and opened no network connection.

## 1. Fidelity

- **PR #207 commits.** 176be5d3's tree is byte-identical to 5d155d44's tree (`52dd9a90…`), and 5d155d44 was itself cut from 3dfdde3c. So all 9 commits are exact. The merges 9e3dda56 and 576901b1 (router-retry, cached-window, `capacity_protocol=2`) were not taken.
- **Walled-gate commits (range-diff).**
  - ab203bba and 122e3b77 are `=`.
  - 223ed35f differs from 3bc37499 only in the recorded conflict:
    - `openrouter_cached_tokens` is dropped from the import;
    - the cached-window hunk in `Allowance.amount` is not applied;
    - `openrouter_gate_cost` reads `incoming, _, outgoing` from `gate_profile(route)`.

    The test and fixture files are unchanged from the originals.
- **Hotfix against `feat/neuralwatt-walled-gate`, in `factory/`.** Every difference is main-only work:
  - **model_call_gate.py:** the paid_reserve retry loop, and cached-window in `Allowance.amount` and `OpenRouterUsage`;
  - **token_prices.py:** `openrouter_cached_tokens` and the cached floor;
  - **model_router.py:** router-retry (renew retry, `RouterRejected`, cached credit, `request_queue_size`), `no_route`, `capacity_protocol=2`;
  - **model_runtime.py:** diagnosis `--continue`, and the diagnosis XDG_DATA_HOME;
  - **other files:** engine.py, classify.py, stop_registry.py, diagnosis_invocation.py, diagnostics.py, run.py, run_artifacts.py, slot_state.py and the prompts;
  - **invalid-runs-compat.json:** the pin, intended.

  In the tests, the only difference under the walled-gate and Neuralwatt test files is that `cached-window-leases-20261119.json.gz` is absent, which is correct.
- **Conflict resolution, pricing.**
  - **OpenRouter:** `gate_profile(r)` returns `GATED_OPENROUTER.get(r)`. So every OpenRouter hold, cost, `empty_usage` value and `worst_request` is byte-for-byte 3dfdde3c's. Cached prompt tokens are priced at the full input rate and count wholly against `max_input_tokens`. That is 3dfdde3c's behaviour: never below the bill, and stricter than main.
  - **Neuralwatt:**
    - The hold uses `_nw_profile`: the twin's context and output at Neuralwatt's list.
    - GLM is $0.1736704, asserted in the test.
    - DeepSeek uses `NW_OWN_PRICES`.
    - Main computes the same values. On main, `openrouter_cached_tokens` returns 0 when `cost` is absent, and Neuralwatt usage never has `cost`, so main also prices every Neuralwatt prompt token at full price.
    - The Neuralwatt hold and settle are therefore identical between hotfix and main.
- **`Allowance.amount` on a Neuralwatt lease.**
  - It returns `(openrouter_gate_cost, prompt_tokens, completion_tokens)`.
  - With no `cost` key, the `cost <= amount` check is skipped, and the amount is the token-priced list.
  - A malformed `cached_tokens` is still refused in `OpenRouterUsage`, through the kept 3dfdde3c details loop.
  - Proven by `test_neuralwatt_walled_gate`:
    - `settled_usd == openrouter_gate_cost(...)` with `held_usd == 0` on real streams;
    - the held amount equals `amount(worst_request(GLM, 200))` and equals the formula;
    - a cached GLM request is priced at the full input price.
- **Do the tests prove the same things?** Yes. The files are identical to main's, and none of their assertions depends on cached-window. The cached-token test is about Neuralwatt, and it holds in both trees for the same reason.
- **Taken but not strictly needed by the gate:**
  - PR #207's DeepSeek Neuralwatt lane, `LATE_ROUTES`/`knows`, and the "callers send their chain" `_admit` change.
  - The gate's pricing (`_nw_profile`, `NW_OWN_PRICES`) and its tests come from these commits. Taking them whole and unedited is simpler and easier to prove than a partial backport. See N2 for what they bring.
- **Nothing missing.** 3dfdde3c already has:
  - `Ctx.router_accounts`;
  - `offered_accounts`;
  - the Neuralwatt budget rows (`open_steps`);
  - `neuralwatt_limit` in classify.py;
  - the Neuralwatt step in `bin/setup-secrets`;
  - `ordinary_retry`'s all-accounts `spent_routes` check.

## 2. Identity

- `ident.py … 3dfdde3c HEAD`: `cmp exit 0 IDENTICAL`, 166016 bytes on each side.

| Tree | Bench answers | Bench raw | Model answers | Model raw |
|---|---|---|---|---|
| 3dfdde3c | d4a7127a… | e50c8b74… | **60be464f…** | 60be464f… |
| HEAD f0685e97 | d4a7127a… | e50c8b74… | **60be464f…** | ff58ae63… |

- HEAD answers 3dfdde3c's model verdict code exactly.
- 3dfdde3c's own model pin (`802bfc8f→e1b82d17`, carried in by 223ed35f from main) never matched it, so `from = 60be464f` is right. `to = ff58ae63` is HEAD's raw digest. The bench pin is untouched, and no bench verdict file changed.

## 3. The verdict_code pin, per SHA

Saved state that 1108c made under 3dfdde3c:

- engine-checkpoint folders for G10, G11 and G17, keyed by `verdict_code(model)`;
- model-call receipts, keyed by request text, models, roles, root and ordinal, with no route, account or price;
- G10 helper try jobs (`release`, and so `try_key`);
- ordinary-retry state, whose binding has no route set;
- budget ledger rows.

| Hotfix SHA (original) | Verdict files | Change | Changes a saved verdict, receipt or checkpoint meaning? |
|---|---|---|---|
| 04a42329 (0890f9b3) | model_router.py, model_runtime.py | DeepSeek Neuralwatt lane added to its `CHAINS` row. `chain()` factored out. `_admit` sends `chain`. Router `LATE_ROUTES`/`knows`. `opencode_config` prices Neuralwatt by `runtime_prices(route)`, which gives the same numbers as the twin for GLM and MiMo. | No. `routes()` is a superset, so every saved `spent_routes` stays valid. `family` is untouched (identity identical). No receipt keys on route or chain. A DeepSeek ordinary retry that was "exhausted" may now continue on the new lane instead of resetting. That is a future lane, not a reread verdict. |
| c56373f5 (4d739f80) | model_runtime.py | Comment rewrap. | No. |
| f2e83c60 (5ba15c89) | model_call_gate.py | Comment only. | No. |
| 223ed35f (3bc37499, conflict-resolved) | model_call_gate.py, model_router.py, model_runtime.py | Walled Neuralwatt through the gate. `ungated_lanes` and `bounded_route` drop Neuralwatt. `_call` keeps Neuralwatt away from walled callers outside `WALLED_ROLES` (diagnosis). `NW_CONTEXT` constant. | No. The Claude and OpenRouter gate paths are behaviour-identical (`gate_profile` gives the OpenRouter pin). `_call`'s funding floor: for walled GLM, the minimum hold is still $0.1737; for DeepSeek it is still the twin's $0.1606. `empty_usage.max_request_output_tokens` changes for Neuralwatt routes, and nothing reads it. ordinary_retry for a walled role: `approved` gains the Neuralwatt lane, so a 3dfdde3c state with only the twin spent continues on Neuralwatt rather than resetting. No `completed` answer is invalidated. Science: a G10 verdict may mix GLM-on-OpenRouter tries with GLM-fp8-on-Neuralwatt tries. The founder accepted this on 2026-11-20. |
| f0685e97 | none of the ten (compat json) | Pin `60be464f → ff58ae63`. | It is the pin. |

The other 8 commits (db1e5aad, 40949f8a, 58893543, a19d0a7f, 7d677c90, 176be5d3, ab203bba, 122e3b77) touch only docs and tests.

The pin is sound. As a result, a hotfix case worker and a 3dfdde3c helper accept each other's jobs, and the reverse is true too (see N3).

## 4. Tests

All run in the hotfix tree with `uv run --with dbos==3.4.0 --with numpy --with scipy`. All OK.

| Test file | Tests |
|---|---|
| test_neuralwatt_walled_gate | 7 |
| test_neuralwatt_routes | 10 |
| test_neuralwatt_runtime | 8 |
| test_neuralwatt_budget | 15 |
| test_free_routes | 9 |
| test_model_call_gate_wall | 8 |
| test_model_router | 49 |
| test_router_paid_spend | 51 |
| test_stream_d_retries | 68 |
| test_model_runtime | 11 |

The logs are in `scratchpad/h1108c-review/logs/`. I did not repeat the full suite.

## 5. Release onto this hotfix

- **Router on main.** Main's router (origin/main 616ad550) answers the hotfix worker's own `_admit` payload (`capacity_protocol=1`, with `chain`) as follows:

  | Call | Lease from main's router |
  |---|---|
  | walled GLM `easy_calibrator` | `neuralwatt/glm-5.3-flash` on `neuralwatt-key` |
  | walled DeepSeek `strong_calibrator` | `neuralwatt/deepseek-v4.1-flash` |
  | unwalled MiMo `writer` | Go |

  - `route_maximum` agrees for all 17 chain routes (`maxcheck.py`: 0 differences), so `valid_lease` holds.
  - Main's router sends `no_route` only to `capacity_protocol == 2`.
  - The hotfix's single-shot `paid_reserve` uses fresh ids, so it never receives `duplicate`.
  - The Neuralwatt gate path makes no router RPC at all.
- **Acquire ids.** Acquire ids are a fresh `uuid4` per `await_lease`, so a released worker never replays a 3dfdde3c payload under an old id. That rules out `attempt id changed`.
- **Helpers.** Helpers are leased at the attempt's `plumbing_version`, so after the release they run the hotfix too. Their job `release` (60be464f) matches.
- **Keys and rollback.** See N1 and N3.

## Findings

No BLOCKING findings.

- **N1 (NIT, deploy precondition the repo cannot prove): `neuralwatt-key` must reach the G10 helper machines and the case worker.**
  - Under 3dfdde3c, no walled G10 try ever leased Neuralwatt, so helpers never needed the key. Now they do.
  - A helper without `SECRETS/neuralwatt-key` raises `credential_expiring` with `scope: account` (model_runtime.py:622). That marks `neuralwatt-key` unhealthy for every case on the router, not just 1108c.
  - Check the controller's `worker_credentials.accounts` before release. Also confirm that the live router is at neuralwatt-first or later: an older router rejects `chain` as `invalid admission fields`, and every acquire fails.
- **N2 (NIT, scope): the PR #207 commits bring 1108c the DeepSeek Neuralwatt lane for unwalled roles as well.**
  - This applies if 1108c has any DeepSeek role.
  - That lane bills at Neuralwatt's own list ($0.15/$0.60), above the twin ($0.14/$0.42), and comes before OpenRouter.
  - This is the founder's 11-20 "Neuralwatt first anyway" ruling, already on main. The gate's pricing code depends on it. Taking it is defensible, but it goes beyond "gate only", so say so in the release note.
- **N3 (NIT, rollback): rolling back to 3dfdde3c is safe for GLM and MiMo Neuralwatt spends, but not for a DeepSeek Neuralwatt spend.**
  - 3dfdde3c already accepts `open_steps` rows, Neuralwatt GLM and MiMo `spent_routes`, and `neuralwatt-key` in `router_accounts`.
  - Failure if 1108c has spent `neuralwatt/deepseek-v4.1-flash`:
    - after a rollback, `ordinary_retry` raises `ordinary_retry_state_invalid`, because the route is not in 3dfdde3c's DeepSeek `routes()`;
    - a lease on that route fails 3dfdde3c's `valid_lease`.
  - The design's rollback line names only "d038ab59 or older". For 1108c, the rule should read: "roll back to 3dfdde3c only if no DeepSeek Neuralwatt step was spent; otherwise withdraw the key".
  - The verdict code is the same on both trees, so receipts survive either way.
- **N4 (NIT, deploy): a release alone does not wake a case parked in `waiting_for_credit`.**
  - `_Case.wait_for_credit` loops on `credit_ready_step()`, which reads the router's paid-pool credit block. Releasing the hotfix does not lift it.
  - If 1108c is parked rather than running G10, it needs the operator's credit lift (`lift_credit`) before its calibrator can reach the Neuralwatt lane.
- **N5 (NIT, known ceilings, not regressions from 3dfdde3c):**
  - G10 calls that fall through to the OpenRouter twin have no renew or `paid_reserve` retry (router-retry was not taken).
  - Cached OpenRouter tokens count in full against `max_input_tokens` (412ba567's shape).
  - Each Neuralwatt 429 keeps a $0.17 hold, and about five of them end a walled call as `model_call_cap`.
  - Walled G10 tries now share Neuralwatt's 3 seats with every main case that runs Neuralwatt first.
- **N6 (NIT, record):**
  - On this branch, the design's "Gate identity" and "Deploy" text still says 1108c goes to main and loses its in-flight G10 receipts. This hotfix supersedes that.
  - f0685e97's message does not argue the pin by SHA. Save this review as that record and cite it in the release note.
  - The per-case branch leans against ENGINEERING §4 ("no rescue branches"). The coordinator made that call.

## Verdict

PASS

---

## Elephant's record

- No blocking finding. This file is the per-SHA pin argument for f0685e97 (N6).
- **N1, N4:** go to the coordinator as release preconditions: `neuralwatt-key` in the controller's worker credentials (helpers included); the router at neuralwatt-first or later; a case parked in `waiting_for_credit` may still need the credit lift.
- **N2:** accepted and stated in the release note: the PR #207 commits also give 1108c the DeepSeek Neuralwatt lane for unwalled roles (the founder's 11-20 Neuralwatt-first ruling, already on main); the gate's pricing depends on them.
- **N3:** the rollback rule for 1108c is: back to 3dfdde3c only if no `neuralwatt/deepseek-v4.1-flash` step was spent; otherwise withdraw the key. Recorded here and in the release note.
- **N5:** known ceilings, unchanged.
- **N6:** on this branch, this hotfix supersedes the design's note that 1108c moves to main and loses its in-flight G10 receipts: the pin keeps them (HEAD answers 60be464f…).
