# Router: Claude account order and Neuralwatt burst (2026-11-21)

Two founder requests, in `factory/model_router.py` plus one word in `factory/model_runtime.py` (worker side,
see "The refused call"). Kept out of the top-level *.md files, which are part of the G8/G9 gate identity.
Neither file's gate-identity functions (`model_router.family`, `model_runtime.model_effort`) change.

## 1. Claude account order

**Problem.** Founder, 2026-11-21 ~00:00 UTC: "don't use the smaller claude account unless we run out of the
bigger one... some other work is going on on that account". The router leases `claude-factory-token-2` (small)
first and unlocks `claude-token` (big) only while the small one is rate or quota blocked. The small account
has no Mythos.

**Change.**
- `routes()`: Claude labels are `('claude-token', 'claude-factory-token-2')`. A route naming Mythos (any
  case) gets only `('claude-token',)`, so the small account can never be leased for it, whatever the health
  rows say. Every lease path goes through `routes()`. Mythos has no price profile on main, so it is not
  leasable at all yet; this keeps the guarantee when it lands.
- `eligible()`: mirrored. `claude-factory-token-2` is eligible only while `claude-token`'s health row is
  `rate`/`quota` with `blocked_until > now`. Spare capacity and caller preferences never unlock it.
- `_account_order()` (worker side): a Claude login whose secret file the worker does not have is not offered,
  for both logins (it was `claude-token` only). Otherwise the router would lease the missing small login as the
  big one's fallback and the call would stop on a fake credential fault instead of waiting for the reset (the
  2abb0a case of 14 November, mirrored).

Unchanged: `ACCOUNTS` (already big first; positions 2:4 are the Go accounts), the `provider_accounts` label map
(`claude: 1 -> claude-token, 2 -> claude-factory-token-2` is a mapping, not an order), and
`model_runtime`'s `other_login` check (symmetric). Lease validation on workers is set membership, so workers
on older releases accept leases from the new order.

## 2. Neuralwatt burst

**Problem.** Neuralwatt Basic guarantees 3 concurrent requests and bursts to 6 when it has room; a request
over 3 may get a 429. The pool is capped at 3 because any 429 blocks the whole `neuralwatt-key` pool for
900 s, doubling.

**Change.** New optional router config `burst_capacities` (pool -> int; the pool must be an approved
account and `capacities[pool] <= n <= 100`).
- A pool with a burst leases up to its burst, except during a burst cooldown, when it leases up to its
  floor (`capacities[pool]`).
- Every RPC samples each burst pool: while it holds more leases than its floor, `above_floor_at = now` on
  its health row. Every lease renews every 60 s, so a pool above its floor is sampled at least that often.
- `observe` of `rate`/`quota` on such a pool whose `above_floor_at` is within the last 300 s sets
  `burst_until = now + 300` on the pool's health row and nothing else: no `reason`, no `blocked_until`, no
  failure count. The pool is not blocked.
- Why a window and not the count when the worker observes: OpenCode retries a 429 before its final error
  event, and the worker writes receipts before it observes, so peers may finish in between. The count at
  observe time would see the floor and block the pool for a burst refusal (goldfish design review 1, B3).
  Clustered refusals from one burst all fall in the window too.
- A refusal after 300 s at or below the floor takes today's path (pool block, 900 s doubling).
- Deviation from the literal request, on purpose: a refusal with the floor or fewer held, but within 300 s
  of the pool being above its floor, takes the burst path (the race above). Only a refusal after a whole
  window at or below the floor blocks.
- Known ceiling: a real plan exhaustion (TPM) that starts during a burst takes up to one window of refused
  calls before the pool blocks. Worse, a call whose request can never succeed
  (`tpm_uncached_request_too_large`, a prompt between 1,000,000 tokens and the 1,048,560 context) can keep
  taking the burst path: each retry restarts its CLI, the cooldown ends, peers burst again, and the same
  request is refused again. Each retry re-spends the session's charged prefix. It is bounded by that role's
  duration and invocation funding inside the case's money, and it no longer blocks Neuralwatt for every
  case for 15-60 min as before (diff review 1, nit 1; Murphy row `new-nw-burst-2`).
- Only `rate` and `quota` take the burst path; `credit` and `outage` block as before. A block already on
  the row is kept (`dict(old, ...)`).
- `burst_capacities` is meant for providers with a documented guaranteed floor and best-effort burst
  (Neuralwatt only). Any approved account is accepted; putting a Claude account there would turn its
  quota into a 300 s cooldown, so don't.
- No `burst_capacities` key: `free()` uses `capacities` exactly as today, no row is sampled and `observe`
  never takes the burst path.

`burst_until` and `above_floor_at` are not blocks: `guard.router_clear` and the health reset ignore them;
`status` shows them.

**The refused call** (worker side, `model_runtime.go_quota_moves_on`). In production
(`UNBUG_PROVIDER_WAIT=1`, engine) a worker whose NW call ends `rate` deferred its own call to
`retry_at('rate')`, +900 s, because only NW `quota`/`credit` moved on. `rate` now moves on as well, so the
call goes straight back to the router: a floor seat if one is free, a `capacity` wait otherwise (up to 30
min in the worker, FIFO behind older requests), or, when the refusal blocked the pool, a `rate` wait that
parks as before. "Floor seat" holds only because no later lane of the NW chains is open in production:
`disabled_routes` has `openrouter/xiaomi/`, `openrouter/deepseek/`, `openrouter/z-ai/` and `opencode-go/`,
and `opencode-free` is 0. With a later lane open, acquire skips the full NW pool and leases that lane
instead, as for any full pool. Its money case is the same as `quota`'s: an NW call's tail is bounded by its open steps,
which `budget.py` counts for `rate` refusals already. This reverses neuralwatt-routes item 8's "`rate`
defers", which assumed every 429 blocks the pool. It reaches workers on new launches only.

**Config diff (not applied):** add `"burst_capacities": {"neuralwatt-key": 6}` next to
`"capacities"`, keeping `"neuralwatt-key": 3` there as the floor.

## 3. Lane config reload without a restart (coordinator request, 2026-11-21)

**Problem.** A router restart must wait for zero model calls in flight (it books cut calls as waste). With
12 live cases that has not happened in 8+ hours, so founder config changes (`disabled_routes`, and the
burst key above) are stuck behind it.

**Change.** `Store` keeps the config path (`main()` passes `--config`). Each RPC, inside its `BEGIN
IMMEDIATE` write transaction (so RPCs on other threads never see a half-applied config), stats the file;
when `(mtime_ns, ctime_ns, inode, size)` differs from the last one seen it re-reads the file. The whole file
must pass every check startup makes: `config_lanes()` (an object, no `database` key, approved `accounts`,
a parseable `paid_ceiling_usd`, valid lane keys), which `main()` now calls at startup too, plus Store's one
database check (a ceiling below retained spending). Only then are `capacities`, `disabled_routes` and
`burst_capacities` replaced, and `router config reloaded` is logged. Any error (unreadable, bad JSON, a
check that fails) logs one line to stderr with the error's kind only (no file content) and keeps the
running config whole; the file is tried again only after it changes. So the router never runs on a file
that could not start it (goldfish diff review 3, B1). A stat per
RPC is cheap and every held lease renews every 60 s, so a change applies within seconds while calls run.
Not reloaded (restart still needed): `accounts`, `paid_ceiling_usd`, the database. The reload code itself
needs one more drained restart to go live; after that, lane edits need none.

Tests: `test_an_edited_router_config_is_picked_up_without_a_restart`, on the live config file
(`fixtures/router-approved-config-20261121.json`): adding the burst key opens 3 more NW seats, adding
`neuralwatt/` to `disabled_routes` closes the lane, a floor change applies, seven kinds of edit startup
would refuse (including a bad `accounts`, ceiling or a `database` key beside valid lane keys) each log once
and keep the running config, a ceiling below booked spending is refused, a deleted file keeps the running
config, and restoring the live file logs a reload and returns to the floor.

## Rollout preconditions and steps

Checked read-only on the control VM, 2026-11-21:
- `router-approved-config.json` `capacities` has `claude-token: 100` (and `claude-factory-token-2: 100`),
  so the primary Claude pool keeps its seats. Without a `claude-token` entry it would default to 1 seat.
- `config.json` `worker_credentials.accounts` includes both `claude-token` and `claude-factory-token-2`.
  A worker without `claude-token` would get `credential_expiring` waits until claude-token is rate/quota
  blocked.

Steps (operator):
1. New source dir from the merged head.
2. One drained router restart (no model calls in flight) to load the new code. After it, replace
   `~/durable-first-case-20261106/router-approved-config.json` (the `--config` of the `ExecStart` in the
   drop-in `zzz-approved-ceiling.conf`) atomically, a temp file in the same directory then `mv`, with
   `burst_capacities` added. The router picks it up on the next RPC and logs `router config reloaded`
   (`journalctl -u unbug-model-router`). The router also logs that line once on its first RPC after any
   start, so look for a second one after the `mv`. `router config not reloaded` means the file was refused
   and the running config kept. A half-written read is only logged and retried on the next change.
3. `status`: the NW pool leases up to 6 (`capacity` on `neuralwatt/mimo-v2.6-pro`).
4. The stopgap health row for `claude-factory-token-2` (quota-blocked with `operator_hold`) is redundant
   after the restart and would block the fallback when claude-token runs out: let it lapse at its
   `blocked_until` or clear it with a healthy observe for that pool.
5. Worker-side pieces (`_account_order`, `go_quota_moves_on`) reach new launches only.

## Verdict-code pin

`model_router.py` and `model_runtime.py` are in `durable/checkpoints.MODEL_CODE`, so this change moves the raw
model verdict digest from `c464ced1…` to `a8c991fb…`. Nothing here changes what a finished model call or
gate produced, only which account, route or seat a call is admitted to and when it retries, so
`invalid-runs-compat.json` repins `model.to` to `a8c991fb…`, keeping `from: 802bfc8f…` (what 19b404be answers).
With the pin, live cases keep their model-stage receipt folders on the new release. The control VM's router and `source-current` run `source-19b404be`, which answers `802bfc8f…`
(checked read-only 2026-11-21). The bench digest is
unchanged (`9511baae…`, pinned to `d4a7127a…`). Recompute after any merge that touches these files.

## Deletes

Nothing; `free()`'s lease count is shared with `observe` as `occupied()`.

## Tests

`tests/factory/test_model_router.py`:
- the existing Claude order tests, mirrored (big first, small only on big's rate/quota, non-rate failures and
  allowlists never unlock the small account, a worker without the small login waits for the big one's reset);
- Mythos leases only `claude-token`, even with `claude-token` quota-blocked;
- `tests/factory/test_neuralwatt_routes.py`, on the real 11-19 router health rows: 6 seats, a 429 or quota
  above the floor caps at 3 for 300 s without blocking and the refused call retries on a floor seat; a
  peer finishing between the 429 and the observe still counts as the burst, and a refusal after a whole
  window at the floor blocks; a 429 at the floor blocks as before, with or without a burst key; invalid
  burst config is refused;
- `tests/factory/test_neuralwatt_runtime.py`: NW `rate` moves on;
- worker fixtures that gave a worker only the small login (`test_model_call_maxima`, `test_model_runtime`,
  `test_durable_call_budget`) now give it `claude-token`.

## Murphy rows

The register is not on main. New rows, to be numbered at merge:
- `new-router-claude-order-1`: the factory leases the small Claude account while the big one has quota,
  starving the founder's other work on it. Closed by the mirrored order tests.
- `new-nw-burst-1`: one Neuralwatt 429 above the guaranteed floor freezes the whole NW pool for 15+ min.
  Closed by the burst tests.
- `new-nw-burst-2` (open): a Neuralwatt request that can never succeed (`tpm_uncached_request_too_large`)
  during bursts retries on the burst path, re-spending its session prefix each time, until its role's
  duration or funding ends. Not closed by this change.
