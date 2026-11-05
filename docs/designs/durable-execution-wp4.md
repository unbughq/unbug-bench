# Durable execution WP4: failure classification

Status: design note for WP4 of `docs/designs/durable-execution.md` (wave 1). Branch
`de/wp4`, cut from `durable-execution` at `db13be8`.

## Problem

When a model call or a step ends without a result, the runner leaves a stop string:
the `BudgetError` text, or the card's `terminal_stop`. Examples are `opencode_error`,
`provider_limit:claude/claude-opus-5-5`, `stalled` and `Budget ledger stopped:
codex_error`. The engine needs exactly one `Outcome` for each attempt, and a reason
code that holds no case content.

Today, at least four places classify these strings, each in its own way:

- `calibration.interruption_label`;
- `recovery.HOLDER_STOPS`;
- `restart.py:94`, the provider-wait allowlist;
- `model_runtime._call`, which maps labels to router failure reasons.

The 50 non-dry-run scorecards in `sealed/` hold 511 stop strings in their
`continuation_budget` stop history (49 cards). More stop strings sit in card-level
`terminal_stop` fields (33 cards) and in one card's `error` field. None of today's
classifiers turns these strings into the engine's six outcomes.

## Change

`factory/durable/classify.py` is a pure module: no I/O, and its only import is the
frozen contract. It provides:

- `classify(stop, *, step, now, reset_at=None) -> Classified`, which implements the
  `Classifier` protocol. The `reset_at` keyword is optional. A caller that has a
  trusted reset time (the ledger's `claude_resets_at`, or `provider_failure.reset_at`)
  may pass it; a call through the protocol leaves it out. See contract finding 1.
- `REASONS`, the closed set of every reason that `classify` can return.
- `PUBLISHED_REASONS`, the allowlist of reasons safe for the public card. It includes
  the contract's own fixed engine and infra codes.
- `BACKOFF_S = 900` and `MAX_RESET_AHEAD_S`.

### Normalising the stop

1. If the stop is not a string, the result is `infra:unclassified_stop`.
2. Strip surrounding whitespace. Then strip one runner wrapper, `Budget stopped: ` or
   `Budget ledger stopped: `, the same prefixes `calibration.interruption_label`
   strips. The real card `Budget ledger stopped: codex_error` needs this.
3. The head is the text before the first `:`. Only the head picks the outcome. The
   only part after the `:` that is ever read is a `provider_limit` route's prefix
   (`claude/`, `codex/`, `opencode-go/`, `opencode/`, `openrouter/`), and it only
   picks one of five fixed codes.

Every reason comes from a fixed table, so no stop text can reach a reason. A test
feeds stops that carry file paths and secrets, and checks that each reason is a member
of `REASONS`.

### Mapping

The stage is `router` for a fault on the model or provider side, `infra` for a fault
in the runner or plumbing, and `batch` for the batch bound. For an EXHAUSTED case
limit, the stage is the step's own: `admit`, `writer`, `stress`, `diagnosis`, `seal`,
or `engine` for GATES. The grammar has no `gates` stage; see contract finding 2.

| Stop head | Outcome | Reason |
|---|---|---|
| `provider_limit` | PROVIDER_LIMIT | `router:claude_limit`, `router:codex_limit`, `router:opencode_limit`, `router:openrouter_limit`, or `router:provider_limit` for another route |
| `provider_wait`, `ProviderWait` | PROVIDER_LIMIT | `router:provider_wait` |
| `codex_login_expired`, `credential_expiring` | PROVIDER_LIMIT | `router:credential_expiring` |
| `opencode_error`, `codex_error`, `claude_error`, `process_error` | INFRA_ERROR | `router:<same>` |
| `zero_tokens` | INFRA_ERROR | `router:zero_tokens` |
| `refusal` | INFRA_ERROR | `router:refusal` (not published) |
| `provider_preflight_failed` | INFRA_ERROR | `router:preflight_failed` |
| `RouterUnavailable`, `router_unavailable` | INFRA_ERROR | `infra:router_unavailable` |
| `stalled` | INFRA_ERROR | `infra:stalled` |
| `timeout` | INFRA_ERROR | `infra:timeout` |
| `cancelled` | INFRA_ERROR | `infra:cancelled` |
| `PauseRequested`, `paused` | INFRA_ERROR | `infra:paused` |
| usage accounting (`missing_usage`, `invalid_usage`, `unpriced_usage`, `usage_monitor`, `invalid_usage_*`, `usage_*`) | INFRA_ERROR | `infra:usage_unknown` |
| ledger and reservation faults (`Invalid budget ledger…`, `resume_while_active`, `reservation_mismatch`, `invalid_money`, …) | INFRA_ERROR | `infra:ledger_error` |
| `cleanup_failed`, `cancellation_failed`, `containment_unavailable` | INFRA_ERROR | `infra:cleanup_failed` |
| `<cli>_cli_not_<version>` | INFRA_ERROR | `infra:cli_version` |
| `runner_error`, `seal_error` | INFRA_ERROR | `infra:runner_error` |
| a Python exception class name (`PermissionError`, `LookupError`, …) | INFRA_ERROR | `infra:runner_exception` |
| `complete`, `running`, empty | INFRA_ERROR | `infra:stop_without_failure` |
| `cost_limit`, `budget_exhausted` | EXHAUSTED | `<step stage>:money` |
| `call_limit`, `total_call_limit`, `model_call_cap` | EXHAUSTED | `<step stage>:call_limit`, `:total_call_limit`, `:call_cap` |
| `money_wait`, `retired_batch_bound` | EXHAUSTED | `batch:money_bound` |
| anything else | INFRA_ERROR | `infra:unclassified_stop` |

Why each choice:

- **Broken runs are INFRA_ERROR.** This covers model-CLI errors, stalls, timeouts,
  pauses, cancellations, accounting faults and runner exceptions. The policy retries
  them, never scores them, and settles them as waste. An unknown stop is also
  INFRA_ERROR: it is bounded by `max_infra_retries_per_step` and then goes to
  DIAGNOSE, and it is never scored (ENGINEERING section 3).
- **`timeout` and `stalled` are INFRA_ERROR, not EXHAUSTED.** They are a hung or
  silent model call. Today's recovery already treats both as operational stops
  (`recovery.HOLDER_STOPS`), and calibration labels them as interruptions. The
  engine's own attempt deadline is a separate code, `infra:deadline`.
- **Call limits and money limits are EXHAUSTED.** The design says EXHAUSTED is "the
  attempt reaches its `money_ceiling_usd_micros` or the runner's own limits".
  `money_wait` and `retired_batch_bound` are the batch bound, so they become
  EXHAUSTED with `batch:money_bound`. The policy then tells a money wait from a case
  outcome by the Grant label, as the design specifies.
- **A credential expiry is PROVIDER_LIMIT.** `model_router` already treats
  `credential_expiring` as a Wait. A renewal is external, so sleeping and retrying
  beats burning infra retries in seconds. The cost: a credential that is never renewed
  sleeps in 15-minute cycles instead of reaching DIAGNOSE. It holds no slot while it
  sleeps.
- **`refusal` is INFRA_ERROR** (the router switches route; it is never scored). Its
  reason is kept off the public card, because "a model refused this case" hints at the
  case's content.
- **`classify` never returns OK, GATE_FAILED or NEEDS_FOUNDER.** A stop string is
  never a verdict. Gate failures and escalations come from the GATES and STRESS step
  results. A "stop" of `complete` with no result is a broken attempt.

### retry_at

Every PROVIDER_LIMIT gets a finite `retry_at`:

- `reset_at` is used when it is finite, later than `now`, and no more than
  `MAX_RESET_AHEAD_S` (8 days, which covers a weekly window) after `now`;
- otherwise `retry_at = now + BACKOFF_S`, with `BACKOFF_S = 900`. That equals
  `model_router.retry_at(reason, now=now)` for a first failure. A test pins the two
  together, so the router and the engine back off alike.

The classifier knows no failure count, so its backoff is flat. Growth across repeated
limits belongs to the policy, which counts limits per step. A bad `now` or a bad
`step` is a caller bug and raises `ContractError`. The executor calls through
`guarded_run`, which contains it.

### Published-reason allowlist

`PUBLISHED_REASONS` holds every reason in `REASONS` except `router:refusal`, plus the
contract's fixed codes: `infra:deadline`, `infra:version_mismatch`,
`infra:attempt_busy`, `engine:executor_raised` and `engine:executor_bad_result`.
Gate reasons (`g5:…`) come from GATES results, not from WP4, so they are not on the
list. `report.py` (WP1) publishes only listed reasons. Any other reason shows as its
outcome alone.

## What it deletes

Nothing in wave 1. When WP5a and WP9 route every stop through `classify`, these become
redundant and can go in WP9: `calibration.interruption_label`, the label-to-reason
mapping in `model_runtime._call`, and the stop allowlists in `recovery.HOLDER_STOPS`
and `restart.py:94`.

## Tests

`tests/factory/test_durable_classify.py`:

- **Real stops.** It loads every non-dry-run `sealed/case-*.scorecard.json`; the test
  checks there are 50. It takes every stop string: `continuation_budget.previous_stops`,
  `continuation_budget.terminal_stop`, the card `terminal_stop`, and the card `error`.
  For every step kind, each must classify to exactly one valid `Classified`. It also
  checks:
  - the reason is in `REASONS` and passes `check_result_for` for that step;
  - nothing classifies as `infra:unclassified_stop`;
  - the per-kind counts equal the report's table.
- **Broken runs are never scored.** No real stop gives OK, GATE_FAILED or
  NEEDS_FOUNDER, and every model-CLI, stall, timeout, pause and exception stop is
  INFRA_ERROR.
- **Backoff.** Every real `provider_limit` stop gets `now + 900`, equal to
  `model_router.retry_at`. A real `claude_resets_at` from the cards is used when it
  is passed. A stale, non-finite or far-future `reset_at` falls back to the backoff.
- **No echo.** Stops carrying paths, digits and secrets give only reasons from
  `REASONS`, and the reason never contains the injected text.
- **Allowlist.** It is a subset of `REASONS` plus the contract codes, every entry
  matches `REASON`, and `router:refusal` is not on it.
- **Purity.** The same input gives the same output, and the module imports nothing
  but the contract and the standard library.

## Murphy rows

These are targets. The rows close only when the engine sleeps on these results in a
real run (WP1, WP5a), so this branch closes none:

- **Row 4**, the expiring quota observations. A provider limit gets an automatic,
  finite `retry_at` from `now`, with no operator observation.
- **Part of row 48.** Provider failures, refusals and outages get explicit
  classification. Outages wait or retry without consuming writer rounds, because
  INFRA_ERROR is never a round.

## Findings report

`docs/reports/durable-execution-wp4-stops.md`: counts of every stop kind and its
outcome, the allowlist, and the evidence on the 210 `opencode_error` stops.

## Contract findings (reported, not changed)

1. **The `Classifier` protocol has no reset-time input.** Real stops never carry a
   reset time: `provider_limit:<route>` has none. The real reset times live in the
   ledger (`claude_resets_at`, on 19 cards) and in `provider_failure.reset_at`. A
   call through the protocol therefore always gets the flat backoff. The optional
   `reset_at` keyword is compatible with the protocol, and lets WP5a pass the reset
   time it holds.
2. **`REASON` has no stage for the GATES step as a whole.** Only `g1`–`g17` are
   allowed, so a GATES-level EXHAUSTED that names no single gate (calibrators running
   out of calls) uses `engine:`. Adding `gates` to the stage list would fix this.
3. **Operator pauses cost infra retries.** They map to INFRA_ERROR, so under the
   current `policy.decide` a step paused more than `max_infra_retries_per_step` times
   goes to DIAGNOSE. There were 58 pauses in the 50 cards. Under the engine, pauses
   should become cancels that WP1 does not count. That is WP1's choice, not a contract
   change.
