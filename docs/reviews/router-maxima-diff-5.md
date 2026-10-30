# router-maxima diff review 5: integration rebase and D Lease wiring (fresh goldfish, zoom-out + implementation readiness)

**Verdict: PASS (code review).** 0 Blockers, 0 Majors, 2 Nits. The full suite has not finished. `/tmp/router-maxima-full-81d064f.json` records `"status": "running"` (started 2026-10-30T04:28:15Z, tested_sha `81d064f…`, integration_base `cfe616f…`), and the log has reached `tests/bench/test-launch-guards.py`. This review does not claim the suite passed. Validation stays open until a terminal JSON and log exist with exit 0 and 0 failed scripts.

**Scope:** frozen HEAD `81d064f1413e8482231c98a68a25165a11815ab0`, new base `cfe616fabce8dafeb85c5e0c0c90c1d61b44d9b9`, old reviewed tip `c5a36e7`, old base `6abe169`. I worked only in the `t3/router-enforce-call-maxima` worktree and only read files. I made no edits, ran no tests, compiled nothing, launched nothing and read no secrets.

## Range-diff (`6abe169..c5a36e7` vs `cfe616f..81d064f`)

- **Patch-identical:** commits 1–5 and 8–12 (`=`).
- **Changed by conflict resolution:** commit 6 (`b727674`, runtime/token_prices/manifest) and commit 7 (`31d73ae`, invalid-runs test).
- **New:** commit 13 (`81d064f`), the D Lease wiring.

### Commit 6 conflict resolutions (checked line by line)

- **`factory/model_runtime.py:329-343`, the invalid-Lease branch.** A's `valid_lease` check replaces D's family-mismatch branch. The resolution keeps D's `release_uninvoked` (only when `factory_job(c)`) inside `try`. `model_router.finish(identity,'denied')` runs in `finally`, and `RouterUnavailable` is still tolerated. A's `unbounded_route` wait and `continue` are kept. A malformed `lease_id` skips both the release and the finish, which is correct: there is no reservation key to release.
- **`model_runtime.py:356-362`, ordering.** D's `reserve_invocation(...)` and the binding of `c.invocation_reservation` come before `with model_router.running(...)`. The one-use `model_router._start(lease)` and `_model_launch_permit` come next, and only then the secret check and environment setup. This matches the order the design note gives: reserve → start → setup.
- **`model_runtime.py:416-430`, the receipt.** The resolution keeps D's `booked_event_ids`, `usage_delta`, `complete_invocation` and reconciliation hook. It adds A's `MAXIMUM_FIELDS` and `cap_used`. `final_usage_known` now combines D's conditions with A's cap predicate (`closed`, no unknown requests, no in-flight requests). That is strictly more conservative than D alone, so it cannot make D under-settle.
- **`model_runtime.py:499-503`, the `_invoke` permit.** This is A's guard, and it sits before D's `case_budget_boundary(c, model, lease_id=…)`. The lease-aware boundary is unchanged.
- **`model_runtime.py:589-600`.** `run_budgeted` keeps all of D's `factory_kwargs` (`job_authority`, `invocation_id`, `lease_id`, `on_started`), `max_cost=None if factory_job(c)` and `concurrent=factory_job(c) or …`. The only changes are that it now runs inside `model_call_gate.enforce(...)` and passes `cancel=gate`. That is the union both sides intended.
- **`factory/token_prices.py:48-68`.** A's gate constants and functions now sit after D's `invocation_maximum`. D's `PAID_PRICES` and pricing helper are unchanged, and no price, route cap or multiplier changed: `CLAUDE_CALL_USD = 50`, rates come from `CLAUDE_PRICES`, factor 2.2.
- **`tests/tools/test_launch_manifest.py:82`.** Adds `model_call_gate.py` to D/B's worker set, which now includes `diagnosis.py`, `batch_service.py` and `batch_status.py`. `factory/launch_manifest.py` adds only `token_prices.py` and `model_call_gate.py`, once to each list.

### Commit 7 resolution: `tests/factory/test_invalid_runs.py:604-639`

At the tip, the test pins `current` to C's recorded `policy['current_*']` target. It then asserts, unconditionally:

- `assertNotEqual(actual, current)` and `assertFalse(compatible_identity(old, actual))`, at lines 621-622;
- for the panel, `assertNotEqual(actual_panel, panel)` and `assertFalse(compatible_panel(old_panel, actual_panel))`, at lines 636-637.

The intermediate commit-7 form made the identity rejection conditional (`if actual != current`). The tip removes that condition, which matches the router.md claim "unconditionally reject". Pinning the panel (`panel['cache']` and bench files set to C's `current_files`) is necessary now, because A adds `model_call_gate` to `gate_state.MODEL` and that changes the live panel cache. This is test scaffolding only. `factory/invalid-runs-compat.json` and `calibration.py` are byte-identical to the old reviewed tip, so C's classification is unchanged.

## New wiring (commit 13)

- **`factory/model_runtime.py:71-76`.** `invocation_maximum(c, lease)` raises `BudgetError('route_maximum_unknown')` unless `valid_lease(lease, lease.route, c.router_accounts|ACCOUNTS)` holds. That check covers:
  - the Lease type;
  - all four maximum fields, matched by exact type and value against the route policy;
  - the 32-hex ID;
  - an unexpired, finite `expires_at`;
  - the route/account/billing/family/pool tuple being among the allowed routes.

  If the check passes, the function returns `Decimal(str(lease.max_usd))` quantized upward to nine places, exactly as specified. The empty `ENFORCED_ROUTE_BOUNDS` and its lookup are deleted. Nothing in factory, tests, bin or tools references them any more.
- **Callers.** There are exactly two: `run.py:337` (pending writer/stress) and `model_runtime.py:357` (the wrapper). Both now reserve the same value, so `reserve_invocation`'s idempotent repeat check against the prior `maximum_usd` (budget.py:159) cannot raise `reservation_mismatch` between the pending reservation and the wrapper's reservation. A caller-supplied smaller maximum is impossible, which closes diff-3 N1's D2 duty for this route.
- **Unbounded routes still wait.** Updated `test_stream_d_runtime.py:205-215`: with `route_maximum → None`, `pending_call` raises `ProviderWait('unbounded_route')`, with no reservation, no attack-state and `builder_rounds == 0`.
- **New real-policy test, `test_model_call_maxima.py:292-354`.** It uses the actual `router.Store`, policy, gate and runtime, plus D's accountant. Only `run_budgeted`, `pinned_cli` and `SECRETS` are faked, and no CLI or network runs. It asserts:
  - `maximum_usd == '50.000000000'`;
  - `invocation_id` passthrough;
  - authority of $50;
  - `max_cost is None` and `concurrent`;
  - a loopback `ANTHROPIC_BASE_URL` gate;
  - `cancel` set.

  It then covers three outcomes:

  | Case | Outcome | Settlement |
  |---|---|---|
  | `done` | Settled, `final_usage_known` true | Gap 0 |
  | Interrupted by `model_call_cap` | Stays pending, unknown usage | Reconcile gap exactly 50; replay is byte-identical |
  | `denied` setup `OSError` before `on_started` | Settled | Known zero |

  In all three, the router ends with no leases. Six kinds of tampering raise `route_maximum_unknown`: each of the four maximum fields, expiry and account.
- **Byte identity, checked myself.**
  - Identical to `cfe616f`: `git diff cfe616f 81d064f` is empty for budget.py, job_authority.py, batch_money.py, batch_service.py, batch_status.py, diagnosis.py and job_config.py, and also for `docs/murphy-register.md` and `invalid-runs-compat.json`.
  - Identical to `c5a36e7`: `git diff c5a36e7 81d064f` is empty for model_router.py, model_call_gate.py, calibration.py and gate_state.py.
  - `run.py` differs from the base only by A's three `model_call_cap` propagation lines, which were already reviewed.
- **Synthetic D fixtures.** `test_stream_d.py` and `test_stream_d_runtime.py` add `synthetic_maximum('accounting-fixture-only')` or `synthetic_maximum(model)`, and patch `model_router.route_maximum` instead of the deleted dict. They are labelled as accounting/control-flow only and do not qualify any route. All of D's control-flow assertions are kept.

## Zoom-out

Wiring D to the Lease is the smallest correct change. It deletes the empty inventory instead of filling it, reuses `valid_lease`, and adds no new module or price source. Admission authority comes only from the route policy, and D accounting is untouched. The documented limitations still apply and are not re-reviewed here:

- the $50 ordinary threshold and single-invocation commitment;
- unbounded non-Claude roles;
- drained rollout;
- B's practice qualification.

The native Linux fixture is still marked historical in router.md (the last paragraph of the rebase note), not relabelled as a rerun. Murphy rows 2, 3, 4, 20, 47 and 48 remain open.

## Nits (optional)

1. **Stale docstring at `factory/token_prices.py:17-22`.** It says "Runtime dispatch accepts only the separately qualified enforcement inventory." That inventory (`ENFORCED_ROUTE_BOUNDS`) no longer exists, and production code no longer calls `token_prices.invocation_maximum`. Its only remaining caller is the synthetic fixture at `test_stream_d_runtime.py:77`. The design says D's pricing helper is intentionally kept, so do not delete it. Remedy: change the sentence to "Runtime admission uses only a `valid_lease`-checked `Lease.max_usd` (`model_runtime.invocation_maximum`); this helper grants no admission." The function body does not change, and neither do D's accounting modules.
2. **Historical wording at `docs/designs/stream-d.md:966`.** It says "This increment does not populate ENFORCED_ROUTE_BOUNDS". That is true for that increment, but a fresh reader could look for a symbol that has been deleted. Remedy: add one line to the router.md rebase note, or a one-line forward pointer in stream-d.md, saying that `ENFORCED_ROUTE_BOUNDS` was removed at `81d064f` and that admission now uses the Lease maximum. This is optional, and leaving it as is does not block anything.

## Handoff

The integration code review passes. Before merge:

- **Full suite:** wait for `/tmp/router-maxima-full-81d064f.json` to become terminal with exit 0 and a log ending in 0 failed scripts. Then archive the log `.gz` and JSON with SHA-256 the same way as earlier rounds, and record the result in the validation doc. If it fails, record the failure as it is and do not relabel the run.
- **Review records:** commit this review as `docs/reviews/router-maxima-diff-5.md`, and list every review file in the `Reviewed-by:` trailers.
- **Gates that remain:** do not merge or push without the founder. D2 enablement sizing and profile approval, and B's real practice-case qualification, are still prerequisites. No launch, price change, cap change or Murphy closure is authorised by this pass.

## Author response

PASS accepted; no blocking finding is open or rejected. Optional N1 is left as
historical helper wording to keep the reviewed/tested implementation frozen.
The new router.md integration note already records the deleted empty inventory
and its replacement with the validated Lease maximum (N2). The native Linux
fixture remains historical evidence at its recorded hashes. The required full
suite is still running on 81d064f; its terminal result and complete archival
evidence will be recorded before handoff. No merge, push or launch.


Terminal validation: the required full suite completed on the reviewed frozen
SHA `81d064f1413e8482231c98a68a25165a11815ab0` at
2026-10-30T04:45:03.690271Z, exit 0, **144 scripts and 0 failures**.
Complete log and SHA-256 metadata are `router-maxima-full-81d064f.log.gz` and
`router-maxima-full-81d064f.json`. Only documentation/review/evidence files
changed afterwards; this does not relabel the reviewer's earlier pending result.
