# Diff review 1: neuralwatt-walled-gate (goldfish)

## Scope

- **Diff:** `git diff 77f25170 04416d93`. I reviewed the code commit 3bc37499 first. Then I reviewed the follow-up 04416d93, which changes only tests and docs. I confirmed that 04416d93 touches nothing under `factory/`, `bin/` or `harbor/`.
- **Checked against:**
  - the design, `docs/designs/neuralwatt-walled-gate.md`;
  - the parent spec, `docs/designs/neuralwatt-routes.md` §"Walled roles (easy_calibrator) and Neuralwatt";
  - the first design review, `docs/reviews/neuralwatt-walled-gate-design-1.md`;
  - the coordinator's task requirements.
- **Personas:** `zoom_out` and `implementation_readiness`, in Mode: REVIEW, against `implementation-readiness-standard.md` and ENGINEERING §1, §2 and §4.
- **Code read:**
  - all of the changed code in `factory/model_call_gate.py`, `model_router.py`, `model_runtime.py`, `token_prices.py` and `invalid-runs-compat.json`;
  - the callers around it: `budget.py` (`_gate_bound`, `_settle_leaf`, the Neuralwatt stop in `check_limits`, `open_steps`, Neuralwatt error handling), `ordinary_retry.py`, `run.py` preflight dedupe, `durable/runtime.py` `largest_call_hold`, `durable/helper_link.py`, `model_runtime._invoke`, `diagnosis_environment` and `opencode_config`;
  - `gate_state.model_science` and `durable/checkpoints.verdict_code`.
- **Fixtures:** I decoded both new fixtures.
  - The streams fixture holds seven real answers, each with a usage frame of `choices: []`, then `: energy` and `: cost` comments, then `[DONE]`. None has `cost` inside usage.
  - The OpenCode fixture has two bodies, both sent with the gate token. The second carries `reasoning_content`, `tool_calls` and a tool message.
  - Neither fixture contains anything that looks like a key or a bearer token.
- **What I ran:**
  - **Touched tests on 04416d93:** `test_neuralwatt_walled_gate` (7), `test_neuralwatt_routes` (10), `test_neuralwatt_runtime` (8), `test_free_routes` (9), `test_model_call_gate_wall` (8), `test_neuralwatt_budget` (15) and `test_stream_d_retries` (68). All OK.
  - **Neighbouring tests on 3bc37499 that use the changed functions:** `test_cached_window`, `test_codex_route`, `test_durable_admit`, `test_durable_call_budget`, `test_durable_classify`, `test_durable_diagnosis_invocation`, `test_durable_runtime`, `test_g10_money`, `test_guard_preflight`, `test_helper_g10_and_checks`, `test_model_call_maxima`, `test_model_runtime`, `test_opencode_continue_linux`, `test_resume_role_swap`, `test_router_cheap_maxima` and `test_router_item8_profiles`. All OK.
  - **Retry tests on 3bc37499:** `test_stream_d_retries` failed 3 tests. The same file passes on 77f25170 (finding 1 below, fixed in 04416d93).
  - **Mutations:** 14 of them, run on a `git archive` copy in my scratchpad, never in the repo. Each mutation and the test that killed it:

    | Mutation | Killed by |
    |---|---|
    | gate token is the real key | walled_gate |
    | `provider` added for Neuralwatt | walled_gate |
    | Neuralwatt 4xx refunded | walled_gate |
    | account check removed | walled_gate |
    | `usage_reservation_exceeded` → `model_call_cap` mapping removed | walled_gate |
    | message-level `reasoning_details` allowed | walled_gate |
    | top-level `usage` allowed | walled_gate |
    | `ungated_lanes` re-includes Neuralwatt | routes, free_routes |
    | `ungated_lanes` drops Go | routes, free_routes |
    | diagnosis may take Neuralwatt | free_routes |
    | walled Neuralwatt takes the ungated branch | walled_gate |
    | hold context shrunk | walled_gate |
    | parser ignores the model | walled_gate |
    | OpenRouter path accepted on a Neuralwatt gate | walled_gate |

  - **Identity:**
    - `gate_state.model_science()` gives the same digest on the 77f25170 and HEAD archives (`67de849c…`).
    - `verdict_code(True)`: 77f25170 answers `802bfc8f…` (its raw digest). HEAD's raw digest is `e1b82d17…`, and HEAD answers `802bfc8f…` through the repinned `from`/`to`.
    - 04416d93 changes no file that `verdict_code` digests.
    - No edits to `factory/calibration.py`, `factory/gate_state.py`, `bin/**`, `harbor/**`, top-level `*.md`, `run.py` or `budget.py`.
    - `model_router.family` and `model_runtime.model_effort` are unchanged. `family` references no changed names, and `model_effort` references only `family`.
  - `git status --short` is clean.
- **Not run by me:** the full suite on 04416d93. The elephant says that run is in progress. A full suite I started on 3bc37499 was overtaken when the branch moved, so I am not counting it.

## Requirements check

- **Walled roles get Neuralwatt first, then the OpenRouter twin. Met.**
  - `ungated_lanes` now returns Go and free lanes only (`model_router.py:209`).
  - `bounded_route` was changed the same way.
  - `test_neuralwatt_routes` runs on real 11-19 router state. A walled GLM or DeepSeek acquire is leased Neuralwatt. After a `credit` observation it waits on the twin.
- **Fixed upstream. Met.**
  - The host is `api.neuralwatt.com` (`model_call_gate.py:677`).
  - The path must be exactly `/v1/chat/completions`, with no override.
  - The lease must be on `neuralwatt-key` (`:914`).
  - Upstream TLS verifies the certificate, because `HTTPSConnection` uses its default context.
- **Key custody. Met.**
  - The gate keeps the real key in `upstream_token`.
  - The walled process gets a random `secrets.token_urlsafe(32)` instead (`:747`).
  - `openrouter_environment` (`:797`) copies only an allowlist of environment variables. No `*_KEY` or `*_TOKEN` variable crosses.
  - The inline config's `apiKey` is the gate token.
  - argv carries no key.
  - The runtime's `OPENCODE_CONFIG` file holds only `{env:NEURALWATT_API_KEY}`, and enforce drops that file from the walled env.
  - The handler suppresses its logs, and `cap_used` holds no token.
  - The test asserts that the key is absent from the whole walled env and that `Gate.token != key`.
- **Body allowlist. Met.**
  - Top-level `usage`, `reasoning` and `include_reasoning` are refused. So are message-level `reasoning` and `reasoning_details`.
  - `usage` and `provider` are never added (`:499` returns before the provider block).
  - `reasoning_content` must be a string.
  - `max_tokens` is clamped, and `stream_options` is forced on a stream.
- **Hold and refund. Met.**
  - The `Allowance.reserve` hold uses `gate_profile`. The twin's context is used for the input side, so the hold is never below Neuralwatt's real `max_model_len`.
  - A hold is refunded only by `OpenRouterUsage.final()` on a 200 response with a validated terminal usage frame.
  - A Neuralwatt 4xx or 5xx response keeps its hold; the `not openai` guard is at `:707`.
  - The parser is tested on real Neuralwatt bytes, whole and in 1-byte and 7-byte chunks, plus ten altered streams.
- **No router `paid_reserve`. Met.** `paid` is still `GATED_OPENROUTER` only, and the test makes `model_router._rpc` raise if it is called.
- **Ungated providers never reach a walled role. Met.**
  - Go with `user` set is still refused in `enforce`.
  - `bounded_route('easy_calibrator', Go-only)` is False.
  - `test_free_routes` pins the exact excluded-lane tuples.
  - A diagnosis keeps Neuralwatt excluded (`model_runtime.py:541`).
- **Money stop, not infra. Met.** The gate path maps budget.py's Neuralwatt `usage_reservation_exceeded` to `model_call_cap` (`:936`). Neuralwatt 402 and 429 bodies pass through unchanged, so budget.py's terminal Neuralwatt error handling classifies them exactly as on the ungated lane.
- **Verdict-code repin. Met.** HEAD answers what 77f25170 answers, as listed under Scope. The pin's reasoning holds: the change adds a lane a walled call may lease next and changes no saved verdict or model effect.

## Findings

### 1. BLOCKING, fixed in 04416d93: three cae763 retry tests failed on the code commit

- **Evidence:**
  - On 3bc37499, `tests/factory/test_stream_d_retries.py` fails three tests with "BudgetError not raised":
    - `test_cae763_walled_role_exhausts_its_one_gated_route_and_resets_next_attempt`;
    - `test_a_spent_neuralwatt_route_survives_the_key_being_withdrawn`;
    - `test_cae763_saved_stuck_pending_judgment_resets_on_the_next_attempt`.
  - The same file passes on 77f25170.
  - The cause is that a walled role's leasable set in `ordinary_retry.answer` grew. Base: `[openrouter/z-ai/glm-5.3-flash]`. Head: `[neuralwatt/glm-5.3-flash, openrouter/z-ai/glm-5.3-flash]`.
  - So one spent lane no longer exhausts it (`ordinary_retry.py:202`).
  - The design's statement that `ordinary_retry` "need[s] no edit" was true of the code, not of its tests.
- **Failure scenario:** the full suite is red on the head handed back. That breaks ENGINEERING §1 step 4, and the cae763 Murphy tests stop proving their row.
- **Resolution:** 04416d93 rewrites the three tests for the two-lane reality:
  - empty answers spend Neuralwatt, then the twin;
  - the call then counts as exhausted and resets on the next engine attempt;
  - with the key withdrawn, the spent Neuralwatt route is still accepted.

  The file passes on 04416d93 (68 OK). The tests still prove the cae763 row ("exhausted over the leasable set, then reset"). **Closed.**

### 2. NIT: after one malformed Neuralwatt answer, an ordinary-retry call moves to the OpenRouter twin, which is out of credit

- `ordinary_retry.py:213` excludes spent routes from the next try. Take the easy-calibrator dedup (`retained_answer`): it gets one malformed answer on Neuralwatt, and its next judgment leases the twin.
- With OpenRouter at $2.50 and no top-up, that try parks waiting on `credit`. It resets only after the twin is also spent, which cannot happen while OpenRouter has no credit.
- This is ordinary chain semantics; unwalled roles behave the same way. It is not worse than before, when the walled role was on the twin from the start.
- The updated tests use a stub where the twin answers, so they do not show this shape.
- Suggestion: say it in the design's deploy notes ("a malformed Neuralwatt dedup answer parks on OpenRouter credit"), so an operator recognises it.

### 3. NIT: `openrouter_body`, `OpenRouterUsage` and `openrouter_environment` now also serve Neuralwatt

- The `nw` switches are small and well commented, so reuse was the right call over a parallel copy.
- The names now mislead a 3am reader. Rename them when the files are next touched, for example `openai_body`, `OpenAIUsage` and `walled_opencode_environment`.

### 4. NIT: the cached-token pricing depends on Neuralwatt never sending `usage.cost`

- `token_prices.py:149` prices cached tokens at the cache-read rate only when `cost` is present in usage. It then floors the amount at that `cost`.
- If Neuralwatt ever adds a `cost` field with different semantics (another unit, or energy-adjusted), the gate would start using it as the floor without anyone noticing.
- Optional hardening: for a Neuralwatt route, ignore `cost` or treat it as invalid until a real cached request is captured. This matches the design's own upgrade note.

### 5. NIT: the diagnosis backstop changed shape

- Before this change, `enforce` refused any walled Neuralwatt lease with `route_feature_unsupported`.
- Now a walled Neuralwatt lease takes the gate path. If `_call`'s diagnosis exclusion (`model_runtime.py:541`) ever regressed:
  - `diagnosis_environment` strips the key (`:290`), so the call fails `credential_expiring`;
  - that failure is observed account-wide and blocks the Neuralwatt pool, where before it was a per-call refusal.
- This is only reachable through a regression, and `test_free_routes` kills that regression.
- Optional: in `enforce`, refuse `nw and gate.bound_reasoning`, or pass the role through, so the backstop stays local.

### 6. NIT (process): the Murphy row cannot be closed as ENGINEERING §2 describes

- `docs/murphy-register.md` is untracked (it was removed from git in 33d45fc1).
- So `Closed by` cannot land "in the same commit as the fix". The design says the parent appends the row locally.
- Record that in the merge commit, so the closure has a trace.

## Verdict

**PASS.** The only blocking finding (1) is fixed in 04416d93, and no blocking finding is open. The usual merge condition still applies: the elephant's full suite on 04416d93 must be green before merge. I did not see that run's result.

---

## Elephant's record: what was fixed

- **Finding 1 (BLOCKING):** fixed in 04416d93 before this review finished; the elephant's full suite on 3bc37499 found the same three tests. The full suite on 04416d93 is the merge condition (see the PR).
- **N2:** added to the design's deploy notes (a malformed Neuralwatt dedup answer moves to the twin and parks on OpenRouter credit).
- **N3:** not done; rename when the files are next touched.
- **N4:** not done; the design's `: cost` upgrade note already requires capturing a real cached request first.
- **N5:** not done; `test_free_routes` kills the regression it guards.
- **N6:** the PR body and merge commit carry the Murphy row text for the local register.
