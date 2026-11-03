# Bounded roles for the three-case pilot

## Problem and objective

The planned pilot must discover an unsupported model before creating a worker.
A real `ModelRuntime.call` with authenticated batch money and the real router
store returns `ProviderWait('unbounded_route')` for `codex/gpt-6.1-sol`, before
any CLI. `tests/factory/test_model_call_maxima.py` contains the offline probe.
The parent chose the pilot workaround: do not enable Codex's unbounded CLI.
The reviewed Codex transport/gate is a separate follow-up after the pilot.
This makes the one proposed pilot configuration reviewable; it does not activate
the holder, diagnosis, paid routes, or a live batch.

## Pin and admission

Name the proposed three-job batch `b-real-pilot`. Future pilot activation must
allow only that exact manifest ID; the existing global holder switch stays off.
The real `batch_holder._admit` decision validates each resolved job before any
money authority or operation is written. For that ID require exactly one each:

| Flag | Exact route | Existing invocation maximum |
| --- | --- | ---: |
| `--builder` | `openrouter/minimax/minimax-m3.1-flash` | $0.690001 |
| `--attacker` | `openrouter/deepseek/deepseek-v4.1-flash` | $1.17440612 |
| `--reviewer1` | `openrouter/xiaomi/mimo-v2.6-pro` | $1.7104906 |
| `--strong-calibrator` | `claude/claude-opus-4-5-20251101:compact` | $3 |
| `--easy-calibrator` | `openrouter/minimax/minimax-m3.1-flash` | $0.690001 |

These are the already-reviewed routes from the practice manifest; no new route,
fallback, tariff, maximum or account rule. `--reviewer2` is forbidden. G16 and
G17 use the strong calibrator; diagnosis uses reviewer1. Effort, source, slot,
seeds and non-role options retain their existing behaviour. The future manifest
must pass all five flags explicitly in every job, plus its other required args.

Check flag tokens rather than reimplementing the whole runner parser. Require
the literal `--flag`, followed by its exact route, once per flag. For all five
role flags and `--reviewer2`, reject `--flag=value`, duplicates, abbreviations,
and aliases that argparse could interpret as one of these flags. Other options,
including the five `--*-effort` options, remain legal. Reject extra `--reviewer2`
in all forms. Also require the actual `model_router.route_maximum` for each
chosen route to remain non-null. Fail with the fixed public-safe label
`pilot roles must use pinned bounded routes`. `qualify-batch-inputs.qualify`
preserves its existing result shape and reports that label in `observation`
only for this exact error. Other failures keep the existing generic label.
The guard executes on new, replay and resume admissions. It does not modify
existing non-pilot or practice manifests. Future code that activates a pilot
under another ID must add an equivalent reviewed admission contract first.

This is the existing B admission path, not another launcher or ledger. Remove
no path: the problematic default is overridden only for the pilot, not deleted
from existing non-pilot rotations. The old Codex batch refusal remains. The
pilot plan document must list these flags and the required preflight. Preserve
the $20/case and $60/batch proposal, shared paid cap, infrastructure cap, and
all other live prerequisites. Paid MiniMax, DeepSeek and MiMo use OpenRouter;
the existing shared-credit rules apply. No live affordability, quality, or
provider availability is claimed.

## Cost evidence and limits

The expected whole-case cost delta cannot be estimated from the retained data:
the available Codex card does not identify all role invocations, and different
models may use different tokens/turns. The $20 case/$60 batch list-equivalent
ceilings do not increase. Actual subscription billing may be $0 within plan;
the three selected OpenRouter routes can consume the existing shared cash cap.

For scale only, the saved real `canary6-round8-collected-card.json` has one
Codex strong-calibrator preflight event with 10,733 input tokens (9,088 cached)
and 5 output tokens. Its stored Codex list-equivalent estimate is $0.0042488.
At the code-pinned Opus 4.5 rates ($5 uncached/$0.50 cached/$25 output per
million), the *same token counts* imply $0.012894, a +$0.0086452 difference
for that one preflight invocation. This is not an expected case delta, a live
quote, or proof that the replacement performs the same work. Other substituted
roles change too; the full incremental case cost and cash spend are unknown.

## Files and validation

Change only `factory/batch_holder.py` and `tools/qualify-batch-inputs.py`, the
pilot plan, and their tests/reports. Test the actual runner's parser and
`model_runtime.select_models` on all five pinned flags, four independent families,
and real router store leases/maxima. Test real `_admit`/qualifier with each role
changed to Codex, duplicate/abbreviated/equals forms, an extra reviewer, missing
flags, and a removed bounded maximum: each must refuse before state changes,
with the fixed label for the qualifier. Test a valid proposed pilot and an
unrelated batch; do not claim live qualification. Check diagnosis reviewer and
G16/G17 role mapping. Use the saved Codex receipt for the price illustration.
All provider and job bindings in these tests are explicitly synthetic except
the retained public receipt. No workers, provider calls or secrets.

Murphy 30 remains open: this pins just this future pilot, not all batches.
No Murphy row closes. Before live pilot, settlement, activation, diagnosis,
worker containment, actual funding/credit and all pilot prerequisites remain.
Offline cost $0; timeline one design/review, implementation and suite cycle.
