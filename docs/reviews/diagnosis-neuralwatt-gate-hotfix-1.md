# Hotfix review 1: diagnosis-neuralwatt-gate ports (goldfish)

## Scope

- **Branches reviewed:**
  - `hotfix/diag-nw-01c6f97e` (commits 3c6dec2d and 0321124b) on base `01c6f97e`
  - `hotfix/diag-nw-cb5e26` (commits f2f6cd4f and 2250f606) on base `5cb5b02c`
  - `hotfix/diag-nw-1108c` (commits 35fa3016 and de120e8c) on base `56252d30`, which is the head of the precedent branch `hotfix/1108c-nw-gate`
- **Reference:** commit `7a82a740`. There is no separate design for these ports, so I reviewed them against that commit and its design doc.
- **How I checked:**
  - Compared each branch diff to `git show 7a82a740` after stripping index lines and hunk offsets.
  - Compared the base code that differs from main in `model_runtime.py`, `model_call_gate.py`, `model_router.py`, `run.py`, `token_prices.py`, `durable/classify.py` and `durable/stop_registry.py`.
  - Built `git archive` trees of each base and branch and ran `myident.py`, `vc.py`, `cmp`, and the related tests.

## Findings that apply to all three branches

- **The port matches the reference exactly.**
  - After normalising, each branch diff is byte-identical to `7a82a740`, apart from the pin hunk.
  - It covers the design doc, the `model_call_gate.openrouter_body` addition (`thinking_token_budget = room`), and the three `model_runtime.py` changes: the diagnosis key in `diagnosis_environment`, deleting the Neuralwatt exclusion in `_call`, and the Neuralwatt branch in `_invoke`.
  - It also brings the fixture, the new test, and both flipped tests.
  - It touches none of the forbidden files (`calibration.py`, `gate_state.py`, `bin/claims.py`, the sealed delivery contract).
- **No base needs the change somewhere the reference didn't touch.**
  - On `01c6f97e`, `model_runtime.py`, `model_call_gate.py` and `model_router.py` are identical to the reference tree.
  - On `5cb5b02c` and `56252d30`, `model_call_gate.py` differs only in the paid_reserve retry loop. `56252d30` also differs in cached-token counting. Neither is near `openrouter_body`, whose `bound_reasoning` and `nw` code is the same shape as the reference, so the 5-line addition lands correctly.
  - `56252d30`'s `model_runtime.py` differs only in diagnosis `--continue` and the XDG data home.
  - A search of `factory/` and `bin/` for `WALLED_ROLES`, `NW_ROUTES` or `neuralwatt` on lines mentioning diagnosis or the wall gives the same hits on every tree. No base has another diagnosis-specific Neuralwatt exclusion. `bounded_route` (`model_runtime.py:199`) excludes free and Go routes only for `WALLED_ROLES`, the same as the reference.
- **Gate identity is identical on every branch.** `myident.py` output is byte-identical between base and branch (`cmp` reported no difference for all three pairs).
- **The model verdict code is unchanged on every branch.** `vc.py` gives the same answered `model` and `bench` digests on base and branch. Only `raw_model` moves, and it equals the new pin `to`.
- **The pin edits are correct.** Only `verdict_code_pins.model.to` changed, and `from` is the digest the base already answers. The `bench` pin and everything else in `factory/invalid-runs-compat.json` match the base.

| Branch | `from` (answered digest, unchanged) | old `to` | new `to` (branch raw digest) |
|---|---|---|---|
| `01c6f97e` | 802bfc8f | e1b82d17 | 01433a26 |
| `cb5e26` | 73aa880a | aaa935cb | 504b65fd |
| `1108c` | 60be464f | ff58ae63 | 34a64d6c |

  The `01c6f97e` result matches main's own repin (raw 01433a26, answers 802bfc8f), as it should: that base's two changed files are identical to the reference tree.
- **The new test fails first.** I copied `test_diagnosis_neuralwatt.py` and its fixture into each base tree. Three of its four tests fail there (1 failure, 2 errors).
- **The related tests pass on each branch tree.** `test_diagnosis_neuralwatt`, `test_free_routes`, `test_neuralwatt_runtime`, `test_neuralwatt_walled_gate`, `test_router_cheap_maxima`, `test_durable_diagnosis_invocation`, `test_neuralwatt_routes` and `test_stream_d_retries` all pass. `test_durable_diagnosis_invocation` skipped 3 tests that need a Linux pilot user, so the walled `sudo` path wasn't run end to end on this Mac.
- **I did not run the full suite** (`tests/run.py`) on these heads. That is the author's step-4 job, and it is still owed if it hasn't been done.

## Per-branch findings

### `hotfix/diag-nw-01c6f97e`
- No blocking findings and no nits.

### `hotfix/diag-nw-cb5e26`
- **NIT** in `docs/designs/diagnosis-neuralwatt-gate.md`, Problem section ("the router answers `no_route`").
  - This base's worker sends `capacity_protocol=1` (`factory/model_router.py`, `admission` data), so on this lineage a diagnosis with no lane sees `outage` rather than `no_route`.
  - The doc was copied verbatim from main, and the fix itself is not affected.
  - Fix: add one line to this branch's copy saying that on this base the no-lane wait shows as `outage`.

### `hotfix/diag-nw-1108c`
- **NIT**: the same `no_route` versus `outage` wording, for the same reason (`capacity_protocol=1`). Same fix.

## Verdict

- `hotfix/diag-nw-01c6f97e`: **PASS**
- `hotfix/diag-nw-cb5e26`: **PASS**
- `hotfix/diag-nw-1108c`: **PASS**

I removed my temporary archive directories (`gf-*`) from the scratchpad.

## Elephant response

- `hotfix/diag-nw-cb5e26` and `hotfix/diag-nw-1108c` nit (`no_route` against `outage`): fixed, one note in each branch's design copy. Identity and verdict code re-proved on the final heads (eb87133a, 625ce7e0).
