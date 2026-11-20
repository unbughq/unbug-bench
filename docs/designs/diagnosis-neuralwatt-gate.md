# A walled diagnosis may use the Neuralwatt gate (2026-11-20)

Founder, 2026-11-20 ~10:40 UTC: "Let's fix them". Extends `neuralwatt-walled-gate.md` (PR 208) from the calibrators
to the diagnosis.

## Problem

- A diagnosis runs walled (`user='pilot'`) on the case's reviewer model (`diagnosis_dispatch.reviewer`), for example
  `openrouter/xiaomi/mimo-v2.6-pro`, whose chain is Go, then Neuralwatt, then OpenRouter.
- Go has no gate, so a walled caller cannot take it (`model_router.ungated_lanes`).
- `ModelRuntime._call` also excluded every Neuralwatt lane for a walled caller outside `WALLED_ROLES`, and
  `diagnosis_environment` withheld the Neuralwatt key: the walled gate was for the calibrators, and a diagnosis's
  `bound_reasoning` had no Neuralwatt form.
- The live router now refuses `openrouter/xiaomi/`, `openrouter/deepseek/` and `openrouter/z-ai/` (`disabled_routes`,
  the founder's "stop the spill"). A diagnosis then has no lane: the router answers `no_route`, and the case loops
  with 0 calls.

## Change

1. `model_runtime._call`: the diagnosis-only Neuralwatt exclusion is deleted. A walled caller excludes only what
   `ungated_lanes` returns (Go and free), the same as a calibrator.
2. `model_runtime.diagnosis_environment`: a `neuralwatt-key` lease passes `NEURALWATT_API_KEY` into the env given
   to `model_call_gate.enforce`. That is the same handoff as `OPENROUTER_API_KEY` for a paid lease. On the gate
   path, `enforce` reads the key as the upstream token and replaces the whole env with `openrouter_environment`,
   which holds only the per-gate token. The walled process never sees the key. `enforce` with `user` set is the
   only path a diagnosis takes, because a diagnosis always has `user='pilot'`.
3. `model_runtime._invoke`: a diagnosis on a Neuralwatt route gets the same treatment as one on a gated OpenRouter
   route: `gate.bound_reasoning = True` and `webfetch`/`websearch` denied in the inline config.
4. `model_call_gate.openrouter_body`: a Neuralwatt form of `bound_reasoning`. It sets
   `thinking_token_budget = max_tokens * 3 // 4`, the same room as OpenRouter's `reasoning.max_tokens`.
   - `thinking_token_budget` is vLLM's per-request reasoning bound. Neuralwatt serves vLLM 0.30.1.
   - Six real calls on 11-20 (fixture below) show that GLM, MiMo and DeepSeek each stop reasoning at exactly the
     budget and then answer. Without it, GLM and MiMo reason past it on the same prompt.
   - It is sent beside any `reasoning_effort`, because on vLLM effort is a chat-template hint, not a token bound.
     On OpenRouter, effort and `max_tokens` exclude each other, so that form is unchanged.
   - A caller can never send the field: it is not in the allowlist. Only the gate adds it, and only for a
     diagnosis.

The model and prompts are the same, and grading does not change. Holds, parser and prices are PR 208's.

## What it deletes

The diagnosis-only Neuralwatt exclusion in `_call`, and the "never its key" branch in `diagnosis_environment`.

## Tests (`tests/factory/test_diagnosis_neuralwatt.py`, real bytes)

- `neuralwatt-thinking-budget-20261120.json`: six real streaming answers from `api.neuralwatt.com`, captured
  11-20 on the trial key with one generic prompt, about $0.003 in all.
  - With the budget: `reasoning_tokens == 64` and a non-empty answer.
  - Without it: GLM and MiMo go above 64.
  - The gate's parser returns each answer's real usage.
- The body filter:
  - adds the bound only with `bound_reasoning`, clamped like OpenRouter's (`OPENROUTER_OUTPUT * 3 // 4`, and 300
    for `max_tokens=400`);
  - keeps `reasoning_effort`;
  - refuses a caller-sent `thinking_token_budget`;
  - leaves OpenRouter's form unchanged.
- End to end: the real `ModelRuntime._invoke` for `diagnosis-<lease>` as `pilot`, on a real `neuralwatt-key` MiMo
  lease, through the real `enforce` gate, with a loopback upstream that replays the real bytes.
  - The walled env holds no key or token, `webfetch`/`websearch` are denied, and EXA is off.
  - The upstream gets the key as bearer, `api.neuralwatt.com`, `/v1/chat/completions` and
    `thinking_token_budget = 24000`.
  - One request is validated and settled.
- `_call` for a walled diagnosis on MiMo and DeepSeek excludes no Neuralwatt lane, and only Go and free lanes.
  This flips `test_free_routes.test_a_walled_role_is_never_leased_a_free_route` for the diagnosis.
- `test_neuralwatt_runtime.test_diagnosis_hands_only_its_leases_neuralwatt_key_to_the_gate` flips the old "never
  a key".
- Failing first: with the code reverted, all five fail. With it, they pass, and so do
  `test_neuralwatt_walled_gate`, `test_router_cheap_maxima`, `test_durable_diagnosis_invocation`,
  `test_neuralwatt_routes` and `test_stream_d_retries`.

## Gate identity and verdict code

- The change touches `model_runtime.py` and `model_call_gate.py` only. Neither is a gate dependency file, and
  `model_runtime.model_effort` is untouched. `myident.py` on `git archive` trees of base and head must print
  identical JSON.
- Both files are in `durable.checkpoints.VERDICT_CODE`. The change adds a lane and a reasoning bound for the
  diagnosis, which has no gate-cache verdict, and it changes no saved verdict or model effect. So each tree repins
  `verdict_code_pins.model`: `from` is the digest its predecessor answers, `to` is the new raw digest. The pin is
  recomputed after the last commit on each branch.

## Murphy row

- `new-diag-nw-gate-1`: "A walled diagnosis has no lane once OpenRouter's MiMo/DeepSeek/GLM prefixes are disabled:
  Go is ungated, and Neuralwatt was excluded for a diagnosis. The router answers `no_route` and the case loops with
  0 calls (11-20)." Closed by `tests/factory/test_diagnosis_neuralwatt.py`.

## Deploy (operator)

- Worker-only plumbing. The router already leases Neuralwatt to a walled caller (PR 208).
- `neuralwatt-key` must be in each case's worker bundle, as for the calibrator.
- Live check: a diagnosis receipt shows `neuralwatt/<model>` and `cap_used.validated_requests > 0`.
- Walled diagnoses now share the 3 `neuralwatt-key` seats with G10.
