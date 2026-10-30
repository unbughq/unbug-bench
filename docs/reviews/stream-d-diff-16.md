Review 16 passes on `ad015d15a43a307bb4968ec63c4ed22caaa6baef`, with no blockers and no majors. The new test fixes review 15's Ma1: all three mutations that survived there now make the test fail. I changed nothing in the worktree and didn't write the doc into the repo. Your writer's full-suite log was still running when I finished, so no full-suite pass is claimed yet.

The full review is below. A copy is at `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/1cf23531-a17d-438d-bee4-895ff9dfc5a0/scratchpad/stream-d-diff-16.md`. The mutation results are in `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/1cf23531-a17d-438d-bee4-895ff9dfc5a0/scratchpad/mutations.txt`, and the scripts that ran them are `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/1cf23531-a17d-438d-bee4-895ff9dfc5a0/scratchpad/mut.py` (D) and `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/1cf23531-a17d-438d-bee4-895ff9dfc5a0/scratchpad/mutA.py` (stream A).

---

# Stream D diff review 16: Ma1 regression through `main`, and rebase onto router maxima

**Reviewed:** `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`, branch `t3/stream-d-implementation`, **HEAD `ad015d15a43a307bb4968ec63c4ed22caaa6baef`**. The tree is clean apart from the untracked `.stream-d-next/` folder, which is out of scope. `49b178b` is an ancestor of HEAD.
**Diff:** `c032cbf..ad015d1`, one commit (`ad015d1`): `tests/factory/test_stream_d_runtime.py`, +50 lines, test only.
**Also checked:**
- that rebasing the pending-diagnosis producer (`cfe616f..9aa72a1` → `49b178b..c032cbf`) kept the reviewed behavior;
- that A's `invocation_maximum` on `49b178b` validates the lease and ceiling-rounds `max_usd`, with no D change to it.

**Checked against:** `docs/designs/stream-d.md` (passed design); `interfaces.md` §8; `docs/reviews/stream-d-diff-14.md` and `-15.md`; `docs/ENGINEERING.md`; `implementation-readiness-standard.md`.
**Personas:** zoom-out and implementation-readiness goldfish, `Mode: REVIEW`, read-only.
**Out of scope:** `.stream-d-next` drafts, the diagnosis dispatcher, the held-outcome producer, extensions, money enablement, and closing any Murphy row. None is claimed.

## Verdict

**PASS on `ad015d15a43a307bb4968ec63c4ed22caaa6baef`.** No blockers, no majors. Review 15's Ma1 is fixed: all three of its surviving mutations are now killed. The rebase keeps the reviewed D behavior exactly. Two nits below; both are optional.

## Re-review of review 15 Ma1: fixed

`test_main_new_exhaustion_survives_handlers_and_final_accounting` runs the real `run.main()` in a separate `python -B -c` subprocess, so `main`'s fd redirection stays out of the test process.
- **Real artifacts:**
  - the practice case bytes (`self.case`, from `invalid-runs-practice.json.gz`), copied by the patched `build_fixture`;
  - the saved 5813be `continuation_budget` ledger (`self.ledger`), copied into `c.ledger`.
- **Authored inputs:** the prior completed `close_to_passing` diagnosis state, and the failure raised from `validate_and_repair`. The stubs are offline plumbing only: `Ctx` (with `job_money={}`, so `factory_job` is true), `sh`, `which`, `seal`, `bench_manifest`. `wipe` and `model_call` are stubbed to throw, which proves the stopped case checkpoints and does no model work.
- **The two modes:**
  - **`infrastructure`:** sets `exhaustion_occurred=True` and a G10 `infrastructure_gate` marker, then raises `KeyError`. So `main`'s `except Exception` branch (`factory/run.py:3071`) must keep the flag, and `finalize_accounting` (`:2793`) must pass it on.
  - **`budget`:** raises `BudgetError('budget_exhausted')`, which goes through the `BudgetError` branch (`:3059`).
- **Assertions on the sealed scorecard:**
  - the ID is not the previous one, and is a UUID4;
  - `status='pending'`;
  - `stop` is `infrastructure_exhausted` in infrastructure mode and `budget_exhausted` in budget mode;
  - `pending_projection(card)['replacement_eligible']` is `False` in infrastructure mode and `True` in budget mode.
- These match §8: "Only a later, distinct code-recorded exhaustion … creates a fresh ID", and an infrastructure stop gives a present, ineligible pending projection.

**Mutation evidence.** Each mutation was run on a `git archive ad015d1` export, against `test_stream_d_runtime` + `test_stream_d_projection`:

| Mutation | Result |
|---|---|
| (a) `except Exception`: `exhaustion_occurred = isinstance(error, InfrastructureExhausted)` (M1 reintroduced) | **killed**: new test fails |
| (b) `BudgetError` branch: `exhaustion_occurred = False` | **killed**: new test fails |
| (c) `finalize_accounting`: `new_exhaustion=False` | **killed**: new test fails, both subtests |
| (e) `BudgetError` branch: `or isinstance(error, BudgetError)` → `or False` | killed |
| (d) B1 marker revert: `stop = card.get('terminal_stop')` | killed: 3 failures, 1 error, across the B1 tests and the new test |
| (f) drop `if state and not new_exhaustion: return` | killed: `test_held_or_pending_extension_never_creates_a_new_diagnosis_id` |
| (g) drop `c.exhaustion_occurred = True` in `gate_pipeline.stop_infrastructure` | killed: G10 `finally` test |

The three mutations that survived in review 15, (a), (b) and (c), are now all killed.

## Rebase keeps the reviewed behavior

- `git range-diff cfe616f..9aa72a1 49b178b..c032cbf` shows commits 1–8 as `=`, meaning identical patches. Commit 9, `c032cbf`, adds only the review-15 record.
- The added/removed lines of `git diff cfe616f 9aa72a1 -- factory tools bin` and `git diff 49b178b c032cbf -- factory tools bin` are identical. The production D patch reviewed in 14 and 15 carried over unchanged.
- `factory/diagnosis.py` and `factory/gate_pipeline.py` are byte-identical at `9aa72a1` and `ad015d1`. `factory/run.py` differs between them only by the router-maxima merge lines (`model_call_cap` re-raises at `provider_preflight`, `early_probe` and the probe loop). Those are the same 3+/2− lines that `cfe616f..49b178b` brings in.
- **Focused suite on the export of `ad015d1`:** `test_stream_d_runtime test_stream_d_projection`, **33 tests, OK** (17.0 s). That is review 15's 32 plus the new test.

## A's `invocation_maximum` after the rebase: no D change

- `factory/model_runtime.py:71` `invocation_maximum(c, lease)` raises `BudgetError('route_maximum_unknown')` unless `model_router.valid_lease(lease, lease.route, c.router_accounts)` holds. It then returns `Decimal(str(lease.max_usd)).quantize(Decimal('.000000001'), rounding=ROUND_CEILING)`.
- Callers are `run.py:337` (attack path) and `model_runtime.py:357` (`reserve_invocation`).
- `git diff --quiet 49b178b ad015d1 -- factory/model_runtime.py factory/token_prices.py factory/budget.py factory/model_call_gate.py factory/model_router.py` reports no change. None of D's added or removed lines in `factory/` mention `maximum`, `max_usd`, `lease`, `reserve_invocation` or `model_call_cap`. **D does not change A's enforcement**, which matches the brief.
- `test_model_call_maxima` on the export: **17 tests, OK**. Mutation: skipping the `valid_lease` check is **killed** (6 failures).

## Findings

### Blocker
None.

### Major
None.

### Nits

- **N1. Stream A, not D, so not a D merge condition.** Mutating `ROUND_CEILING` to `ROUND_FLOOR` in `model_runtime.invocation_maximum` **survives** `test_model_call_maxima`. Every test lease uses `max_usd` values such as `50.0` that are already exact to 9 decimals, so the rounding direction is never tested. Ceiling-rounding is correct by inspection. If A wants it pinned, a lease with `max_usd` like `0.1234567891` should give `Decimal('0.123456790')`. Route this to stream A's owner; D needs no action.
- **N2.** In infrastructure mode the new test sets `c.exhaustion_occurred = True` and the marker directly, instead of reaching `stop_infrastructure` through `GatePipeline.run`. It also never asserts `terminal_stop == 'runner_error:KeyError'`. This is acceptable: mutation (a) being killed proves the `except Exception` branch runs, and the pipeline flag is pinned separately by mutation (g). An assertion on `terminal_stop` would make the scenario's intent explicit.
- **Carried from review 15:** N1 (the `model_call` patch proves nothing while there is no dispatcher) and N2 (a provider wait or pause drops an in-flight G10 marker, which is consistent with §8) still stand unchanged. They are noted again only so they aren't read as resolved.

## Zoom-out

- The change is one test, with no production code. It is the smallest change that covers the runner wiring review 15 flagged: it reaches `main`'s real handlers and `finalize_accounting` instead of factoring the flag lines out for testability.
- The subprocess harness is justified by `main`'s fd redirection. It follows the existing subprocess-isolation idiom and adds no new helper or fixture.
- No YAGNI or reinvention concerns.

## Implementation readiness

The test's scope, inputs and assertions match the guidance in review 15's Ma1 and its elephant resolution: completed state, then a fresh infrastructure exhaustion plus a runner error, and completed state then `budget_exhausted`, with new IDs and the right eligibility. Nothing is left to the implementer.

## Tests run (reviewer, export of `ad015d1` outside the worktree)

- `python3 -B -m unittest test_stream_d_runtime test_stream_d_projection`: 33 tests, OK.
- The new test alone: 1 test, OK (0.9 s).
- `python3 -B -m unittest test_model_call_maxima`: 17 tests, OK.
- **Mutations:** 7 D mutations, all killed. 2 A mutations: `valid_lease` skip killed, ceiling→floor survived (N1).
- **Full suite:** not run by this reviewer. The writer's `/tmp/stream-d-state-maxima-suite.log` is pinned on line 1 to `ad015d15a43a307bb4968ec63c4ed22caaa6baef`. When this review was written it was still running (last section `tests/bench/test-launch-guards.py`) with no failure summary yet. One line, `ERROR ClaudeUsageLimit`, is fake-harness output inside `test-factory-…` and was followed by `PASS`. **No full-suite pass is claimed here.** The parent must confirm the log finishes with a pass before merge, per ENGINEERING §1 step 4. The `703ba99` run is superseded.

No Murphy row closes in this review.

## Elephant resolution

PASS accepted. Review 15 Ma1 is closed by test_main_new_exhaustion_survives_handlers_and_final_accounting; all three prior surviving mutations fail. N1 forwarded to the parent for stream A: the rounding implementation is correct but a sub-nanodollar regression would pin ROUND_CEILING. No production change or additional gate is requested. N2 is optional; separate G10 and main tests cover both paths. No Murphy row closed. Full-suite result will be recorded after the SHA-pinned run finishes.


## Full-suite verification

The writer ran `uv run --with numpy --with scipy python -B tests/run.py`
on `ad015d15a43a307bb4968ec63c4ed22caaa6baef`, after rebasing onto
`49b178b`. Result: **145 test scripts run; 0 failed.**
Production code and tests remained byte-identical to that commit throughout the
run; only this review record and excluded drafts were written. The first log
line records the exact SHA. Log: `/tmp/stream-d-state-maxima-suite.log`.
SHA-256: `8f68b4c51f1f4127bcaad266610ab764c99894c8a8a025455108d170f97c280d`.
The earlier 703ba99 run is superseded and is not used as merge evidence.
No Murphy row closes.
