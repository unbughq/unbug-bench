# Diff review 1: diagnosis-neuralwatt-gate (goldfish)

## Scope

- **Diff:** commit 7a82a740 (code, design, fixture, tests) plus the pin commit f0eec9d9 (`factory/invalid-runs-compat.json`, shared with the worker-lost and credit-wake fixes). The base is 616ad550.
- **Checked against:**
  - the design, `docs/designs/diagnosis-neuralwatt-gate.md`;
  - the parent design, `docs/designs/neuralwatt-walled-gate.md`, and its diff review 1;
  - the founder's task statement and its hard constraints;
  - Murphy row `new-diag-nw-gate-1` in the local, untracked `docs/murphy-register.md`.
- **Personas:** `zoom_out` and `implementation_readiness`, Mode: REVIEW, against `implementation-readiness-standard.md` and ENGINEERING §1, §2 and §4.
- **Code read:**
  - **In `model_call_gate.py`:** `openrouter_body`, `Gate.token` and `bound_reasoning`, `_wall_access`, `openrouter_environment`, `free_environment` and all of `enforce`.
  - **In `model_runtime.py`:** `opencode_config`, `diagnosis_environment`, `diagnosis_loopback`, `bounded_route`, the exclusion block in `_call`, the key loading in `_call` (`:620-625`) and `_invoke` from the start through the gate block.
  - **In `model_router.py`:** `ungated_lanes`, `WALLED_ROLES` and how `disabled_routes` filters routes (`:473`).
  - **Elsewhere:** `durable/diagnosis_invocation.invoke` (the continuation loop), `budget.invocation_role`/`CALL_ROLES`, `durable/checkpoints.verdict_code` and `gate_state.model_science`.
- **Every walled caller of `_call`:** only two kinds of call pass `user=`.
  - Calibrators: `run.calibrate`, `early_probe` and the fairness replacement. Their call names start `strong-calibrator-` or `easy-calibrator-`, so their role is in `WALLED_ROLES`.
  - Diagnosis: `durable/diagnosis_invocation.py:119`.

  So the deleted exclusion at `model_runtime.py:541` only ever applied to diagnosis, and removing it widens no other walled caller. The router has no role-specific lane rules; the runtime's excluded list is the only control.
- **Fixture:** I decoded all six bodies of `neuralwatt-thinking-budget-20261120.json`.
  - Each body is real vLLM SSE: `system_fingerprint` `vllm-0.30.1rc1…` for GLM and MiMo, and `vllm-0.34.0…` for DeepSeek. Each ends with a usage frame, the `: energy` and `: cost` comments, then `[DONE]`.
  - Reasoning tokens:

    | Model | No budget | Budget 64 | Answer after the bound |
    |---|---|---|---|
    | GLM | 223 | 64 | yes |
    | MiMo | 147 | 64 | yes |
    | DeepSeek | 61 | 64 | yes |

  - The recorded requests are the generic prime-counting prompt, with no case content.
  - No `Authorization`, bearer, `sk-`, `api_key` or long secret-shaped string appears in the file or in the decoded bodies. The only long tokens are the `chatcmpl-…` ids. The `: cost` comment shows a trial allowance balance (~$4.999), which is not a secret.
- **What I ran** (in the worktree, `uv run -q --with dbos==3.4.0`):
  - `test_diagnosis_neuralwatt` (4), `test_free_routes` (9), `test_neuralwatt_runtime` (8), `test_neuralwatt_walled_gate` (7): all OK.
  - Neighbours: `test_durable_diagnosis_invocation` (19, 3 skipped), `test_neuralwatt_routes` (10), `test_stream_d_retries` (68), `test_router_cheap_maxima` (10), `test_model_call_gate_wall` (8), `test_neuralwatt_budget` (15), `test_model_runtime` (11): all OK.
  - **Mutations:** run on copies of `factory/`, `bin/`, `harbor/` and `tests/` in my scratchpad, never in the repo. The unmutated copy passed all four files first, as a control. All nine mutations were killed:

    | Mutation | Killed by |
    |---|---|
    | Restore the diagnosis Neuralwatt exclusion in `_call` | diagnosis_neuralwatt, free_routes |
    | `diagnosis_environment` withholds the Neuralwatt key | diagnosis_neuralwatt, neuralwatt_runtime |
    | No `bound_reasoning` for a Neuralwatt diagnosis (`:926`) | diagnosis_neuralwatt |
    | The gate never adds `thinking_token_budget` | diagnosis_neuralwatt |
    | The gate adds the budget without `bound_reasoning` | diagnosis_neuralwatt |
    | Budget = the full `max_tokens` instead of 3/4 | diagnosis_neuralwatt |
    | A caller may send `thinking_token_budget` (added to `OPENROUTER_FIELDS`) | diagnosis_neuralwatt |
    | `openrouter_environment` keeps `NEURALWATT_API_KEY` in the walled env | diagnosis_neuralwatt, neuralwatt_walled_gate |
    | `webfetch`/`websearch` not denied for a Neuralwatt diagnosis | diagnosis_neuralwatt |

  - **Identity** (digests computed from `git show <rev>:factory/…`):
    - Model verdict code:

      | Revision | Raw digest | Answers |
      |---|---|---|
      | 616ad550 (base) | `e1b82d17…` | `802bfc8f…` (through its pin) |
      | 7a82a740 alone | `01433a26…` | `01433a26…` (unpinned) |
      | f0eec9d9 (head) | `8fb314e4…` | `802bfc8f…` (pin `to` = `8fb314e4…`) |

    - The bench verdict code answers `d4a7127a…` at every revision.
    - 7a82a740 leaves both `family` and `model_effort` untouched, so the `model_science` inputs do not change. The branch's other `model_router.py` edit is `credit_ready`, not `family`.
  - **Hard constraints:** nothing in the diff touches `calibration.py`, `gate_state.py`, `bin/claims.py` or the delivery contract. There are no DBOS workflow or step changes, only runtime plumbing below the step, so replay cannot diverge.
  - `git status --short` is clean.
- **Not run by me:** the full suite. The host already has one running.

## Requirements check

- **The walled process never sees the Neuralwatt key. Met.**
  - `diagnosis_environment` (`model_runtime.py:289-291`) passes `NEURALWATT_API_KEY` only on a `neuralwatt-key` lease.
  - It is called only when `diagnosis` is true, and that requires `user == 'pilot'` (`:814-815`). So `enforce` always takes the walled gate path (`model_call_gate.py:876`, where `user is None` is false), not the ungated `free_environment` path that hands the key to the process.
  - `enforce` reads the key into `Gate.upstream_token` (`:920`) and replaces the whole env with `openrouter_environment` (`:921`, `:943`), an allowlist with no `*_KEY` or `*_TOKEN`. The walled process gets `Gate.token = secrets.token_urlsafe(32)` (`:752`).
  - If `enforce` raises (for example `credential_expiring`), no process has started, because `run_budgeted` runs inside the `with` block.
  - The `OPENCODE_CONFIG` file written at `:844-845` holds only `{env:NEURALWATT_API_KEY}`, and `enforce` drops it from the env anyway.
  - The end-to-end test checks the env the real `_invoke` hands to the process: no key value and no `_KEY`/`_TOKEN` name.
- **Neuralwatt is reached only through the gate. Met, as for the calibrators.**
  - `_wall_access` opens only loopback to the gate's port for the pilot UID.
  - The pilot wall otherwise leaves the public internet open (the comment on `diagnosis_loopback` says so for Codex). So the walled process could open a connection to `api.neuralwatt.com`, but with no credential it cannot use it. This is the same property the OpenRouter diagnosis and PR 208 rely on.
- **The reasoning bound really bounds Neuralwatt reasoning. Met.**
  - The fixture shows `reasoning_tokens == 64` exactly under `thinking_token_budget=64` on all three models, with a non-empty answer after it.
  - GLM (223) and MiMo (147) go past 64 without the budget, so the field cut them, not the prompt.
  - The gate sets `room = max_tokens * 3 // 4` after `max_tokens` is clamped to `OPENROUTER_OUTPUT`, the same headroom as OpenRouter's `reasoning.max_tokens`.
  - Only the gate can add the field. It is not in `OPENROUTER_FIELDS`, and a test proves a caller-sent value is refused.
- **Non-diagnosis and OpenRouter paths are unchanged. Met.**
  - The new branch runs only when `bound_reasoning and nw`, and `bound_reasoning` is set in exactly one place (`model_runtime.py:927`, diagnosis + opencode).
  - The OpenRouter `elif` is untouched, and the test pins OpenRouter's body form.
  - Calibrators never set `bound_reasoning`, so their Neuralwatt bodies are byte-identical to PR 208's.
- **Same model and prompts, no grading change. Met.** The lease route, prompt text and diagnosis validation are untouched. Only the lane set and the transport bound change.
- **Verdict-code pin. Met** (see Identity under Scope).
- **The Murphy row is proven. Met, with nit 1.** The runtime half of the row (diagnosis excluded Neuralwatt) is killed by two tests, and the router has no role-based lane rule to undo it.

## Findings

### 1. NIT: the Murphy test proves the runtime half of the row, not the router outcome under `disabled_routes`

- `test_a_walled_diagnosis_is_offered_the_neuralwatt_lane` (`tests/factory/test_diagnosis_neuralwatt.py:110-123`) stops at `await_lease` and checks only `router_excluded`.
- The row's live symptom is "router answers `no_route`" with the `openrouter/xiaomi/`, `openrouter/deepseek/` and `openrouter/z-ai/` prefixes disabled.
- No test pairs the diagnosis exclusion with a real `Store(disabled_routes=…)` and shows that a lease comes back on `neuralwatt-key`. Today this holds because the router has no role rule, but nothing pins it.
- **Fix:** add one subtest to `test_neuralwatt_routes.py`, next to `test_walled_roles_take_the_neuralwatt_lane_first…` (`:145`). Build the 11-19 real state with `disabled_routes=('openrouter/xiaomi/', 'openrouter/deepseek/', 'openrouter/z-ai/')`, take `excluded = router.ungated_lanes(model, ACCOUNTS)`, run `acquire(model, role='reviewer', excluded=excluded)` for MiMo and DeepSeek, and assert `('lease', 'neuralwatt/…', 'neuralwatt-key')`.

### 2. NIT: once Neuralwatt credit runs out, the row's symptom comes back

- **Failure scenario:** after a Neuralwatt `credit` observation, a walled acquire waits on the OpenRouter twin (PR 208). With those twin prefixes disabled, the diagnosis is back to having no lane.
- Diagnoses are heavy (MiMo re-reads large contexts). The fixture's `: cost` comment shows the key is on a ~$5 trial allowance, and diagnoses now share it and the 3 seats with G10.
- **Fix (docs only):** in the design's Deploy section (`docs/designs/diagnosis-neuralwatt-gate.md:88-93`), add: "Neuralwatt credit or quota exhaustion puts walled diagnoses back on `no_route` (twin prefixes disabled); watch the Neuralwatt balance alongside G10." The row's `Closed by` stays valid.

### 3. NIT: a diagnosis continuation can now switch provider in the middle of a session (untested)

- `durable/diagnosis_invocation.py:111-117` runs up to `1 + CONTINUATIONS` turns. Each turn is a fresh `_call` and lease, with `--continue` on the same OpenCode session (pilot `XDG_DATA_HOME`).
- Before this change, a diagnosis for these models was always on OpenRouter. Now turn 1 can run on `neuralwatt` (openai-compatible) and a later turn on the OpenRouter twin, or the other way round, once the twin prefixes are enabled again.
- The two gate allowlists differ (`reasoning_content` against `reasoning`/`reasoning_details`, `model_call_gate.py:452-453`). A replayed history in the other provider's shape would fail with `unsupported message` and look like a process error.
- This cannot happen while the prefixes are disabled.
- **Fix:** add one line to the design's Deploy notes. When the twins are re-enabled, either capture a real cross-provider `--continue` body, or make continuations reuse the first turn's provider.

### 4. NIT: small inaccuracies in the design text

- `docs/designs/diagnosis-neuralwatt-gate.md:31` says "Neuralwatt serves vLLM 0.30.1". DeepSeek's real answers carry `vllm-0.34.0-tp4-…`.
- DeepSeek's unbudgeted call reasoned only 61 tokens. So the fixture shows DeepSeek accepting the field and stopping at it, not being cut by it. Line 50 is accurate, but line 32 ("each stop reasoning at exactly the budget") reads stronger for DeepSeek than the evidence.
- The parent design `docs/designs/neuralwatt-walled-gate.md:160` still says "the diagnosis still excludes Neuralwatt".
- **Fix:** change line 31 to "vLLM (0.30.1 for GLM/MiMo, 0.34.0 for DeepSeek)". Optionally add a line to the parent design: "superseded for diagnosis by diagnosis-neuralwatt-gate.md".

### Process note (not a finding)

7a82a740 on its own answers an unpinned model verdict code (`01433a26…`). Only f0eec9d9 restores `802bfc8f…`. The branch must merge as a unit and must never be cherry-picked commit by commit. The design already says the pin is recomputed after the last commit, so this is consistent.

## Zoom-out

- The change is the smallest that fits. It deletes the special exclusion and the "never its key" branch, reuses PR 208's gate, allowlist, holds, parser and env replacement unchanged, and adds one five-line branch in `openrouter_body`. There is no new abstraction, configuration or helper.
- The design is actionable. It names the exact files, functions, the bound formula, each test and the identity steps. No design decision is left to the implementer.

## Verdict

**PASS.** No blocking finding is open. Nits 1–4 are optional. The usual merge condition still applies: the full suite on head f0eec9d9 must be green. I did not see that run's result.

## Elephant response

- Nit 1 (router outcome under `disabled_routes` untested): not taken. The router has no role-specific lane rule, and `test_neuralwatt_routes.py` already pins the walled acquire on real 11-19 health.
- Nit 2 (Neuralwatt exhaustion brings `no_route` back): added to the design's Deploy notes.
- Nit 3 (cross-provider continuation): added to the design's Deploy notes.
- Nit 4 (design text): fixed (vLLM versions, DeepSeek acceptance rather than a cut, parent design marked superseded).
