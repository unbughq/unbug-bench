# Diff review 1: 18681d Neuralwatt hotfix (goldfish)

Mode: REVIEW. Personas: `zoom_out`, `implementation_readiness`. Standard: `implementation-readiness-standard.md`.
Branch `hotfix/18681d-nw-3dfdde3c` at 4f77a47d (merge of hotfix/diag-nw-1108c 625ce7e0 into 491b3dca). No design step: reviewed against the commit message, the operator's requirement and the designs it brings in.

VERDICT: PASS

(Report text reflowed into fewer lines by the elephant; findings, numbers and wording of verdict and nits unchanged.)

**Blocking findings:** none.

**Checks against the requirement**

1. Merge clean and faithful. Parents 491b3dca and 625ce7e0, merge-base 3dfdde3c; the two sides touch disjoint files. Diff 3dfdde3c→625ce7e0 vs 491b3dca→4f77a47d (index lines stripped): byte-identical. Diff 3dfdde3c→491b3dca vs 625ce7e0→4f77a47d: byte-identical. Head = 491b3dca plus exactly 625ce7e0's changes; G2 ruling intact (`test_g2_blocked_source` 13 tests pass).
2. Gate identity IDENTICAL, verdict codes unchanged: `491b3dca vs 4f77a47d: identity IDENTICAL (1698 lines) | vc base: 60be464f… d4a7127a… | vc new: 60be464f… d4a7127a…`. Model verdict-code files changed (raw digest 34a64d6c); `invalid-runs-compat.json` pins it back to 60be464f, the code 491b3dca answers. No other verdict-code files touched.
3. Protected files untouched: calibration.py, gate_state.py, bin/claims.py not in the diff.
4. Cross-version, head worker vs origin/main router (19b404be). CHAINS, LATE_ROUTES, chain(), knows(), acquire field allowlist and chain validation, ungated_lanes and token_prices lines 1-141 (all NW profiles, NW_OWN_PRICES, nw_maximum, _nw_profile) match main exactly; NW gate code in model_call_gate matches main (main differs only in OpenRouter cached pricing and paid_reserve retry). Ran the head's real `_admit` piped into main's `Store.rpc` in a separate process, router config: Go disabled, openrouter/deepseek/ disabled, free DeepSeek disabled, Go pools capacity 0, neuralwatt-key capacity 3, funding $12.50. Head worker validated each lease (`allowed`, `valid_maximum`, funding cap, `Lease(**)`). Every case got a neuralwatt-key lease, max_usd 12.5, valid_maximum True, request carried `chain=chain(model)` and `capacity_protocol=1`:

   | Role (walled?) | Model sent | Lease route |
   |---|---|---|
   | stress_tester | opencode/deepseek-v4.1-flash-free | neuralwatt/deepseek-v4.1-flash |
   | stress_tester | openrouter/deepseek/deepseek-v4.1-flash | neuralwatt/deepseek-v4.1-flash |
   | stress_tester | opencode-go/deepseek-v4.1-flash | neuralwatt/deepseek-v4.1-flash |
   | easy_calibrator (walled; ungated_lanes excluded) | DeepSeek free | neuralwatt/deepseek-v4.1-flash |
   | strong_calibrator (walled) | OpenRouter DeepSeek | neuralwatt/deepseek-v4.1-flash |
   | reviewer | MiMo | neuralwatt/mimo-v2.6-pro |
   | easy_calibrator (walled) | MiMo | neuralwatt/mimo-v2.6-pro |
   | easy_calibrator (walled) | GLM free | neuralwatt/glm-5.3-flash |
   | writer | GLM free | neuralwatt/glm-5.3-flash |

   opencode_config(route) cost matches the leased price (DeepSeek {0.15, 0.6, 0.015} = NW_OWN_PRICES; MiMo/GLM twin pins). Walled roles go through the gate (`enforce` with `user`), covered by test_neuralwatt_walled_gate and test_diagnosis_neuralwatt.
   capacity_protocol 1 vs live router: with 2 NW seats and 3 DeepSeek acquires the third got `Wait(reason='capacity')`, in the head's REASONS, accepted. With NW also disabled the wait is `outage` (main sends no_route only for protocol 2); accepted and documented in docs/designs/diagnosis-neuralwatt-gate.md line 18.
   Keys: NW account offered only when its secret file exists (model_runtime.py:75); ungated path `enforce` requires NEURALWATT_API_KEY and neuralwatt-key; walled process gets only the gate's random token; diagnosis always walled.
5. Nothing found that would stall or misbook a call on this lineage. 3dfdde3c workers unaffected (main's knows() still withholds NW DeepSeek from chainless callers; covered by test_a_caller_without_a_chain_never_gets_a_lane_it_does_not_know). NW tail booked with nw_request_worst using NW's own DeepSeek profile.

**Nits (optional)**
- N1. Merge commit 4f77a47d has no `Reviewed-by:` trailers and no review record in the tree yet.
- N2. On this lineage, when no lane is eligible at all, the wait shows as `outage` (short rechecks) rather than `no_route`. Harmless while the NW lane is live; status reads should know `outage` on 18681d can mean "no lane configured".
- N3. Neuralwatt has 3 Basic seats; with all DeepSeek/MiMo/GLM roles failing over, `capacity` waits will be common. Clean retries, not a defect.

**What I ran** (read-only): ENGINEERING section 1, personas, standard; git log/diff/cat-file; the two-diff faithfulness check; idproof.sh (after reading it and myident.py); git archive origin/main factory into scratch and diffs vs head; head `_admit` against main `Store` in separate processes; tests in the worktree, all rc=0: test_neuralwatt_routes (10), test_neuralwatt_runtime (8), test_neuralwatt_walled_gate (7), test_diagnosis_neuralwatt (4), test_model_router (49), test_model_runtime (11), test_free_routes (9), test_stream_d_retries (68), test_g2_blocked_source (13). Not run: full suite.

## Elephant's record
- Fixed: N1, this file plus Reviewed-by trailers on the record commit.
- N2, N3: no change (documented behaviour; capacity is the founder's NW plan).
