# WP4 findings: real stops, their outcomes, and the `opencode_error` evidence

Branch `de/wp4`, from `durable-execution` at `db13be8`. Design:
`docs/designs/durable-execution-wp4.md`. Code: `factory/durable/classify.py`. Test:
`tests/factory/test_durable_classify.py`, which recomputes every count below from
`sealed/` on each run.

## Corpus and method

- **Cards.** The 50 cards in `sealed/case-*.scorecard.json` with `dry_run: false`, as
  committed at `db13be8`. One card (`case-20261014T205027Z-6d8046`) has no
  `continuation_budget`, so 49 cards have a stop history.
- **Stop strings**, with every occurrence counted:
  - **History** (511): every `continuation_budget.previous_stops` entry, plus
    `continuation_budget.terminal_stop`. This is the design's method.
  - **Card** (33): the card-level `terminal_stop`, when present.
  - **Error** (1): the card-level `error`. One card has `LookupError`.
- **Outcome and reason** come from `classify(stop, step=WRITER, now=…)`. The test runs
  every stop under all six step kinds. The outcome never changes with the step. Only the
  stage of an EXHAUSTED case limit does (`writer:` becomes `stress:`, `engine:` and so
  on).

### Difference from the design's table

My recount of the same files differs slightly from the Problem table in
`docs/designs/durable-execution.md`:

- the design totals 435 + 61 + 16 = 512 history stops; this recount finds 511;
- timeouts: design 23, recount 24;
- Codex errors: design 11, recount 12;
- call limits, cancellations and permission errors: design 9, recount 8;
- operator pauses: design 61, recount 58 (52 `PauseRequested` and 6 `paused`);
- non-stops: design 16, recount 17 (`complete`).

The test pins the recount (`test_counts_by_kind_and_outcome_match_the_report`).

## Every stop kind and its outcome

| Stop string | History | Card | Error | Outcome | Reason |
|---|---:|---:|---:|---|---|
| `opencode_error` | 210 | 0 | 0 | INFRA_ERROR | `router:opencode_error` |
| `stalled` | 74 | 1 | 0 | INFRA_ERROR | `infra:stalled` |
| `provider_limit:claude/claude-opus-5-5` | 68 | 3 | 0 | PROVIDER_LIMIT | `router:claude_limit` |
| `PauseRequested` | 52 | 0 | 0 | INFRA_ERROR | `infra:paused` |
| `paused` | 6 | 22 | 0 | INFRA_ERROR | `infra:paused` |
| `timeout` | 24 | 0 | 0 | INFRA_ERROR | `infra:timeout` |
| `complete` | 17 | 0 | 0 | INFRA_ERROR | `infra:stop_without_failure` |
| `provider_limit:openrouter/xiaomi/mimo-v2.6-pro` | 12 | 1 | 0 | PROVIDER_LIMIT | `router:openrouter_limit` |
| `provider_limit:openrouter/meta/muse-spark-1.3-contributor` | 9 | 4 | 0 | PROVIDER_LIMIT | `router:openrouter_limit` |
| `codex_error` | 12 | 0 | 0 | INFRA_ERROR | `router:codex_error` |
| `process_error` | 9 | 0 | 0 | INFRA_ERROR | `router:process_error` |
| `provider_limit:opencode-go/mimo-v2.6-pro` | 8 | 0 | 0 | PROVIDER_LIMIT | `router:opencode_limit` |
| `call_limit` | 2 | 1 | 0 | EXHAUSTED | `writer:call_limit` (the step's stage) |
| `total_call_limit` | 2 | 0 | 0 | EXHAUSTED | `writer:total_call_limit` (the step's stage) |
| `PermissionError` | 2 | 0 | 0 | INFRA_ERROR | `infra:runner_exception` |
| `cancelled` | 2 | 0 | 0 | INFRA_ERROR | `infra:cancelled` |
| `provider_limit:openrouter/z-ai/glm-5.3-flash` | 1 | 0 | 0 | PROVIDER_LIMIT | `router:openrouter_limit` |
| `provider_limit:opencode-go/muse-spark-1.3-contributor` | 1 | 0 | 0 | PROVIDER_LIMIT | `router:opencode_limit` |
| `Budget ledger stopped: codex_error` | 0 | 1 | 0 | INFRA_ERROR | `router:codex_error` |
| `LookupError` | 0 | 0 | 1 | INFRA_ERROR | `infra:runner_exception` |

Totals:

- **History (511):** 408 INFRA_ERROR, 99 PROVIDER_LIMIT and 4 EXHAUSTED.
- **Card (33):** 24 INFRA_ERROR, 8 PROVIDER_LIMIT and 1 EXHAUSTED.
- **Error (1):** 1 INFRA_ERROR.

No real stop gives OK, GATE_FAILED or NEEDS_FOUNDER. None falls through to
`infra:unclassified_stop`.

Every PROVIDER_LIMIT gets a finite `retry_at`. A stop string never carries a reset
time, so through the `Classifier` protocol the result is `now + 900` s, which equals
`model_router.retry_at` for a first failure. When the caller passes a trusted
`reset_at` (the ledger's `claude_resets_at` holds 1792511400 or 1792695600 on 19
cards), that time is used instead.

The real card text `Budget ledger stopped: codex_error` shows that a card's
`terminal_stop` can hold a raw `BudgetError` message. The classifier strips the
runner's two wrappers, as `calibration.interruption_label` does.

## Published-reason allowlist

`classify.PUBLISHED_REASONS` contains:

- every reason `classify` can return, except `router:refusal`, which hints at the
  case's content;
- the contract's fixed codes: `infra:deadline`, `infra:version_mismatch`,
  `infra:attempt_busy`, `infra:cancelled`, `engine:executor_raised` and
  `engine:executor_bad_result`.

The 55 entries:

```
admit:call_cap admit:call_limit admit:money admit:total_call_limit
diagnosis:call_cap diagnosis:call_limit diagnosis:money diagnosis:total_call_limit
engine:call_cap engine:call_limit engine:executor_bad_result engine:executor_raised
engine:money engine:total_call_limit
infra:attempt_busy infra:cancelled infra:cleanup_failed infra:cli_version infra:deadline
infra:ledger_error infra:paused infra:router_unavailable infra:runner_error
infra:runner_exception infra:stalled infra:stop_without_failure infra:timeout
infra:unclassified_stop infra:usage_unknown infra:version_mismatch
router:claude_error router:claude_limit router:codex_error router:codex_limit
router:credential_expiring router:opencode_error router:opencode_limit
router:openrouter_limit router:preflight_failed router:process_error
router:provider_limit router:provider_wait router:zero_tokens
seal:call_cap seal:call_limit seal:money seal:total_call_limit
stress:call_cap stress:call_limit stress:money stress:total_call_limit
writer:call_cap writer:call_limit writer:money writer:total_call_limit
```

Gate reasons (`g<n>:…`) come from GATES results, not from WP4. They are not on the
list, so `report.py` shows them as their gate and outcome only.

## The 210 `opencode_error` stops

### The repo cannot say what the errors were

- **No raw error text.** The label `opencode_error` is all a card records. No
  `provider_failure` record is kept for it, and no `last_process_error`, which exists
  only for `process_error`.
- **The raw OpenCode error events are not in the repo.** They are the
  `{"type":"error",…}` lines in each call's transcript (`c.work/transcripts/*.jsonl`).
  Transcripts travel only inside the encrypted checkpoint archives
  (`*.checkpoint.tar.gz.age`). `sealed/` holds only those archives' `.transfer.lock`
  files, never the archives. I found no transcript, runner log or OpenCode log for
  these cases anywhere in the repo or on this machine.
- **The runner code of the runs is not in the repo.** The runs were Oct 14–20, and
  this clone's history starts at 2026-10-31 (it is shallow). I cannot confirm which
  error events mapped to `opencode_error` at run time.
- **What today's code does.** In `factory/budget.py`, `consume()` raises
  `opencode_error` for an OpenCode `type: "error"` event that `diagnostic()` did not
  first classify as one of:
  - a credit failure (402);
  - a rate limit (429);
  - a quota failure (usage-limit text);
  - an outage (404, 5xx, or a model-unavailable or overloaded error type), which
    becomes `process_error`.

  So it is the catch-all for every other OpenCode error. I do not claim the
  Oct 14–20 runner behaved the same way.

### What the cards do show

All of these are counts from the public cards. The test does not pin them; the
scratch script that computed them read the same files.

1. **206 of the 210 (98%) are on cards with free MiniMax or DeepSeek Zen routes.**
   This is co-occurrence at card level, not attribution: stop history records no route,
   so no single stop is tied to a call on these routes.
   - 32 of the 49 cards gave `opencode/minimax-m3.1-flash-free` or
     `opencode/deepseek-v4.1-flash-free` to the writer, stress tester or reviewer
     (final `roles`). They hold 206 `opencode_error` stops in 466 stops, about 6.4 per
     card.
   - The other 17 cards used only `opencode-go/`, `openrouter/`, `claude/` and `codex/`
     routes in those roles (plus the free GLM easy calibrator, which 48 of the 49 cards have: all but `aeefd5`,
     which records no roles).
     They hold 4 `opencode_error` stops in 45 stops: one each in `86b100` and
     `ce4d82`, and two in `7d8a30`.
   - `openrouter/` and `opencode-go/` routes also run through the OpenCode CLI, so the
     correlation is with the free Zen route assignments, not with the CLI as such. It
     is confounded: the 32 cards average 14.6 stops per card and the 17 others 2.6, so
     the two groups ran very different amounts of work, and their role assignments
     differ too. The correlation does not show that the free routes caused the errors.
   - By role, among the 32 cards (a card can count under two roles): stress tester,
     26 cards and 178 stops; writer, 19 cards and 102 stops; reviewer, 19 cards and
     132 stops.
2. **The free GLM route is named directly 13 times.** Thirteen cards record
   `free_model_fallback: [{"from": "opencode/glm-5.3-flash-free", "to":
   "opencode-go/glm-5.3-flash", "why": "opencode_error"}]`. This is the runner's own
   attribution of an `opencode_error` to that free easy-calibrator route. Those 13
   cards hold 89 of the 210 stops. The card cannot show which history entry the
   fallback came from, so 13 is a lower bound on stops from that route, not a match
   to particular entries.
3. **On some cards the free routes produced nothing.** Three cards (`195b92`,
   `18681d` and `6a8a7d`) gave free Zen routes to the stress tester and reviewer, yet
   their usage ledgers show no events on those routes. They hold 18 `opencode_error`
   stops. That fits calls that failed before any model step finished, but the cards
   cannot prove it.
4. **Mostly isolated, with a few long runs.** Of the runs of consecutive
   `opencode_error` stops, 119 have length 1, 15 have length 2, 7 have length 3, and
   one each have lengths 4 and 5. Three have length 6, and one has length 13, at the
   end of `1ad7fa`'s history before an operator pause. The stops on either side are
   mostly provider limits (47 before and 48 after), stalls (32 and 36) and pauses
   (20 and 30).
5. **By launch day:** Oct 17, 67; Oct 18, 36; Oct 19, 97; Oct 20, 10; Oct 15, 0.

The only raw OpenCode error event in the repo is outside the 50 cards:
`tests/factory/fixtures/router-cheap-native.json.gz`, from 2026-10-30. It is an
`APIError` with `statusCode: 400` and message `model_call_cap`, from the factory's own
local model-call gate. Today's `budget.py` would label that event `opencode_error`,
because a 400 is not 402, 404, 429 or 5xx. It shows that one source of the label is
the factory itself, but it is no evidence about the 210.

### Top causes, as far as the repo supports

The repo supports correlations and one direct attribution, not causes. The real cause
of each `opencode_error` needs the error events in the encrypted transcripts.

| Rank | Signal | Stops on those cards | Evidence |
|---:|---|---:|---|
| 1 | Co-occurs with free Zen routes in writer, stress or reviewer roles (MiniMax M3.1 Flash, DeepSeek V4.1 Flash). Correlation only: those cards also ran 14.6 stops per card against 2.6. | 206 of 210, on 32 cards | card `roles` and `continuation_budget.events[].configured_model` |
| 2 | The free GLM easy-calibrator route `opencode/glm-5.3-flash-free`. 48 of the 49 cards (all but `aeefd5`, which records no roles) have it, so it is not a correlate. | ≥13 attributed by `free_model_fallback.why` (13 cards, which hold 89 of the 210 `opencode_error` stops) | `free_model_fallback` |
| 3 | No signal, on cards without free Zen routes in writer, stress or reviewer roles | 4, on 3 cards | `86b100`, `ce4d82`, `7d8a30` |

Rows 1 and 2 overlap: the 13 GLM attributions sit on cards also counted in row 1. The
repo cannot rank causes such as free-tier throttling without a 429, a model withdrawn
from the free tier, malformed or oversized requests, or the factory's own gate
refusing a call. That needs the error events from the encrypted transcripts.

**To get them,** someone holding the case keys would open the 33 affected cases'
checkpoint archives on the control VM and count the `error.name`, `statusCode` and
`message` values of the `type: "error"` lines. Better, the runner should record a
sanitized `{error_type, status_code}` beside `opencode_error` in the ledger, as it
already does for `process_error` (`last_process_error`), so future cards explain
themselves. That change belongs to WP5a or the router, not WP4.

## Contract findings

See the WP4 design note for detail.

1. The `Classifier` protocol has no reset-time input, and real stops carry none.
   `classify` takes an optional `reset_at` keyword, so WP5a can pass the ledger's
   reset time.
2. `REASON` has no stage for the GATES step as a whole, so a GATES-level EXHAUSTED
   uses `engine:`.
3. Operator pauses (58 in history, 22 more on cards) map to INFRA_ERROR. Under the
   current policy they would use up `max_infra_retries_per_step`. That is WP1's
   choice.

No real stop fails to fit an `Outcome`.
