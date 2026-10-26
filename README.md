# Unbug bench — bench-internal

Local regression harness for Medusa inventory consistency. Bench internals are
`cases/`, `guards/`, `bin/`, and `results/`; distribute contestants only the promise,
application and guard interface. No Medusa package source is patched. The contestant-facing document is
[CONTESTANT.md](CONTESTANT.md); do not distribute this README or SPEC.md.

Requirements: Docker Compose, Python 3, Node.js 22 or newer, npm. From this directory:

```sh
cd projects/medusa
npm ci --no-audit --no-fund
node verify-lock.mjs
cd ../..
bin/setup
bin/reset
bin/check
bin/run-case medusa-oversell none 30          # stress traffic (default); --normal for the fixed schedule
bin/calibrate
bin/verify-negative
bin/replay results/runs/<run-directory> [--runs 1,2,3]
bin/checkpoint --scenario scenarios/dev/S9-cleanup-job --guard reference --runs 3 [--claims claims.json]
bin/score-claims <checkpoint.json> <claims.json>
bin/stress-compare [--runs 30]
bin/fake-pass-check <guard> [<guard> ...] [--runs 5]
```

`bin/setup` builds, migrates and seeds once on a fresh bench volume. It records IDs
as fixed entity IDs in version-controlled `projects/medusa/seed-ids.json`, creates the
local admin user from that manifest's `admin` login (`medusa user`), and creates the disconnected `medusa_seed`
template. Do not run setup again on an already seeded volume. `bin/reset` stops
both Medusa instances, recreates the database, flushes the dedicated Redis instance and
restarts them. Both before and after startup it checks the seeded stock, reserved-0,
no-orders baseline. Results contain reset duration and database verdicts. A file
lock prevents simultaneous bench commands. The checker has SELECT-only grants
and executes a read-only, repeatable-read transaction with `search_path` fixed to
`pg_catalog` only and schema-qualified table names. Kit products X (concurrent trigger,
stock 10), S (sequential trigger, stock 10), Z (legitimate concurrent pair, stock 16)
backorder product BO (stock 4, `allow_backorder`), and D (admin draft order), E (admin
order edit) and R (cancel/resale and reservation deletion), all shaped like X (stock 10), are
identified by fixed seed IDs; the original kit factors and inventory flags are validated and
sales use frozen seed factors; missing/deleted seed objects or changed stock invalidate the
run.

**Promise as scored:** units promised to customers on live orders (not deleted, canceled or
draft) that are not yet fulfilled must never exceed stocked quantity (backorder items
excepted). Deleting the reservation of a live order and reselling its units counts as
overselling; canceling an order frees its units. The checker counts sales from orders, never
from reservations: current-version line quantity minus `fulfilled_quantity`, so a confirmed
order edit counts and a canceled order does not. Unused kit products Y and W (stock 8 and 24) remain.

## What one run checks

Traffic has two modes. **Stress is the default and the scored mode since 2026-10-14** (see
[Stress traffic](#stress-traffic)); `--normal` runs the fixed schedule below, which the earlier
calibrations and `bin/verify-negative` use.

The bug (#17032) is a summing bug plus ordering, not a database race. Medusa checks
each reservation line against availability separately, and its Locking module
serializes reservations per inventory item. If the 5-unit cart A reserves first, 5
remain and cart B's 3-unit and 4-unit lines each pass, so 12 of 10 are sold. If B
reserves first, A is refused. Measured 2026-10-13 under `none` with one instance:
A then B, one after the other, oversold 6/6; B then A 0/3. The concurrent trigger's
oversell rate is the rate at which A wins the lock.

Traffic, in order (`cases/medusa-oversell/traffic/run.mjs`):

1. Five normal orders, alternating between the two app instances.
2. Concurrent trigger on X, unchanged carts: A (5 single) on instance 1, B (3 single +
   2 × 2-pack) on instance 2. B is dispatched 0, 5 or 20 ms after A by run number
   (`(run − 1) mod 3`); 0 ms keeps the original same-synchronous-turn release.
3. Sequential trigger on S: the same carts, A completes on instance 1, then B on
   instance 2. It is deterministic; it catches fixes that only change order or timing,
   and fixes that keep state inside one process.
4. Legitimate concurrent pair on Z: 8 + 8 units (stock 16, exactly full), released like
   the trigger. Both must be placed.
5. Backorder: 6 units of BO (stock 4). It must be placed and is not an oversell.
6. Admin draft order on D, sequential: store order 5 × single, then a draft of 3 × single
   + 2 × 2-pack created on instance 1 and converted on instance 2 (must be refused), then
   a draft of 1 × single + 2 × 2-pack, exactly the rest (must convert).
7. Admin order edit on E, sequential: store order 5 × single, then an edit adding 3 ×
   single + 2 × 2-pack (begin, add items, request on instance 1; confirm on instance 2;
   must be refused, and the open edit is then canceled), then an edit adding 1 × single +
   2 × 2-pack, exactly the rest (must be confirmed).
8. Resale on R, sequential: store order 4 × single + 3 × 2-pack (all 10 units) on instance
   1, canceled with `POST /admin/orders/:id/cancel` on instance 2; the same order again
   must be placed. Its reservations (found by `GET /admin/reservations` on R's inventory item,
   matched to the order's line IDs) are deleted with `DELETE /admin/reservations/:id` on
   instance 2 while the order stays live; a third such order on instance 2 must be refused.

Both admin paths reach the same per-line check through `reserveInventoryStep`
(`convertDraftOrderWorkflow`, `confirmOrderEditRequestWorkflow`); a protection placed only
on the store checkout route does not cover them. Verified over HTTP on 2026-10-13: draft
creation needs no shipping method; the request step is optional (confirm also works from
`pending`); a draft may carry the same variant on two lines; draft creation and adding
edit items run Medusa's own per-line availability check, which also passes the 3 + 4 mix.
Admin calls use `POST /auth/user/emailpass` and a bearer token. A refusal under the
reference guard surfaces as HTTP 500 and Medusa compensation reverts it: the draft stays
a draft, and the refused edit's version-2 items are soft-deleted.

`pass` requires `valid`, no oversell (units owed above stock on X, S, Z, D, E, R, every other product, and under stress the crowd and bursts; more reserved than stocked is only the `overreserved` warning), `bookkeeping_ok` on every tracked
item, `normal_ok`, `trigger_ok` (at least one X cart placed with full quantity, and
sequential cart A placed), `legit_concurrent_ok`, `backorder_ok`, `draft_ok` (D store
order and fitting conversion placed), `edit_ok` (E store order placed, latest version
exactly 10 units), `resold_ok` (the R resale after the cancel placed) and
`confirmed_orders_ok`, under stress also `crowd_ok`, with no errors. Per-path fields: `concurrent_oversold`,
`sequential_oversold`, `draft_oversold`, `edit_oversold`, `resold_oversold` (R).

## Stress traffic

Stress traffic runs every step of the fixed schedule, plus:

- **Randomised placement and order.** Every request group (cart preparation, completion, each
  admin step) goes to a random instance; both concurrent pairs (X, Z) are released in random
  order with a random 0–50 ms gap; the five normal orders are released together with 0–50 ms
  jitter.
- **W crowd.** 6 carts of 4 units on W (stock 24, exactly the stock), released together with
  the first burst. All must be placed.
- **Y bursts.** Up to 10 independent conflict trials on Y (stock 8). Each burst releases 2–4
  carts that each fit alone (mostly multi-line), within 0–5 ms. Placed orders are then
  canceled through the admin API to restore stock. Bursts stop at the first one that sells more
  than 8, so the oversell stays in the database.
- **Judge** (`bench.py` `crowd_check`). Groups are the W crowd and each burst. A group that
  places more units than stock is an oversell. So are live crowd and burst orders in the
  database, or API confirmations, above frozen seed stock (Y 8, W 24) with frozen kit factors.
  A refused cart that would still fit the stock its group left is a **false block**
  (`crowd_ok = false`): with a correct guard, stock only falls within a group, so a refused
  cart was too big when refused and still is. A refused admin cancel is also a false block.
  Y and W are judged in Python from the checker's order rows, and since 2026-10-14 also by
  `check.sql`, which judges every product.
- **Refusals are outcomes, not errors** (2026-10-14, all traffic modes). A cart Medusa refuses
  to create for lack of stock (HTTP 400 `insufficient_inventory`) is recorded as a refused
  sale, and a request with no answer within 30 s as a refusal (status 504, listed in
  `traffic.timeouts`, counted in `checker.timeouts`). So a guard that over-blocks or hangs a
  workflow gets a scored FAIL (false block, refused cancel), never a harness error. Other
  failures of required setup steps are still traffic errors. A failed reset or image build
  makes the run invalid with no verdict; if it failed before the run's database was created,
  the checker is not run at all (it would read the previous run's state).
- **Seed.** The whole schedule is drawn from a seeded PRNG (mulberry32) before the first
  request, so it depends only on the seed, never on responses. Per-run seed =
  (base × 1,000,003 + run) mod 2³¹, base 1 by default (`--seed`). It is recorded in every run
  JSON (`traffic_options.seed`, `traffic.plan`), and `bin/replay` reuses it.

**Why stress is part of `pass`.** The fixed schedule already fails delay-only and
process-local guards in every run, through the sequential paths. What it misses is a guard that
is correct one order at a time but takes no lock. Measured with `bin/stress-compare` on
2026-10-14 (Wilson 95% intervals):

| Probe guard | Traffic | Pass | Wilson 95% | Oversold runs | Error runs |
|---|---|---:|---|---:|---:|
| Race window: counts units owed by live orders, no lock (`cases/medusa-oversell/probes/order-sum-no-lock`) | normal | 28/30 | 78.7%–98.2% | 2 | 0 |
| Race window | stress | 3/30 | 3.5%–25.6% | 27 | 17 |
| Race window, rerun after the refusal fix (2026-10-14) | stress | 2/30 | 1.8%–21.3% | 28 | 0 |
| Delay only: single-line carts wait 300 ms (verify-negative `ORDER_ONLY`) | normal | 0/10 | 0.0%–27.8% | 10 | 0 |
| Delay only | stress | 0/10 | 0.0%–27.8% | 10 | 0 |
| Lock in one instance: per-process ledger (verify-negative `LEDGER`) | normal | 0/10 | 0.0%–27.8% | 10 | 0 |
| Lock in one instance | stress | 0/10 | 0.0%–27.8% | 10 | 0 |

Under stress, the race-window guard's 17 error runs were 30 s timeouts of the admin cancel after
a burst. The guard's trigger also fires on Medusa's compensation, so a refused burst cart's
order could not be rolled back: it answered HTTP 400 while its order stayed live, live Y
orders exceeded stock, and the next cancel hung. That is the guard's failure, not the bench's,
but it was recorded as a traffic error. Since 2026-10-14 a timeout is a refused cancel (scored
false block); the rerun had 12 such timeouts, 0 errors, 2/30 passes
(`results/stress-comparison-20261014T092445Z.json`). A guard passing
3/30 per run passes a 30-run checkpoint with probability ≈ 0. Stress keeps `reference` at
30/30 with no false blocks (calibration below), so it is fair enough to score. Run-to-run
randomness stays in which cart wins Medusa's lock, not in what a correct guard must allow.
Host load is recorded per run (`host_load_average`). The health wait is 180 s because Medusa
startup took 49 s at load average 175 on 2026-10-14.

## Replay

`bin/replay <run-directory | NN.json> [--runs …]` re-applies the stored guard on a fresh
reset, with the stored run number (dispatch offset), traffic options (stress seed) and change
scenarios, then compares verdicts. Since 2026-10-14 every run directory stores `guard/`
(checked against `guard_sha256`), `scenarios/` copies (checked against their hashes) and
`bench_sha256` of the checker, traffic, `bench.py` and seed manifest. A replay notes any bench
file that changed since the run. Older runs fall back to `guards/<name>` and are marked
unverifiable. The verdict (`pass`, `valid`, and the presence of errors) must match, or the
command exits 1. Other differing booleans are listed, and race-driven fields are labelled
stochastic. Reports: `results/replays/`.

## Change scenarios and claims

`bin/checkpoint --scenario <dir> [--scenario <dir> …] --guard <guard>` applies change scenarios
in order to a fresh bench in every run, runs traffic and the judge, and writes `checkpoint.json`
into the run directory. It records violated runs per path with Wilson intervals, scenario
checks, legitimate completion, and whether the observed result matches the answer key's
`expected_judge` for this guard. A scenario directory can change the app (`app.patch`, applied
before the guard's patch), the database (`admin.sql`, as administrator after the guard), traffic
options (`lb: round-robin`), the rule the judge applies (`safety_stock`, `final_stock`,
`backorder`, variant factors recorded by hooks), and traffic itself (`hooks.mjs` before/after).
`judge.py` adds read-only database facts. The machinery takes any directory path. Dev
scenarios live in `scenarios/dev/` (format in its README); sealed scored variants use the same
format. `--claims claims.json` scores an arm's claims against the last scenario's key
(`bin/claims.py`, PROTOCOL.md section 5):

- `protected` or `withdrawn-safe-fallback` on a path the oracle saw oversold, or `protected`
  where the key says the arm cannot know (S11), is **false assurance**.
- A non-protected claim where the key accepts only `protected` is a **false alarm**.
- A claim is **correct** if the key accepts it.
- The response is correct only if it is in the key's set, the checkpoint is safe, and
  legitimate completion is at least 95%.

`tests/bench/test_claims.py` covers the cases with hand-written claims.

## Fake-pass check

`bin/fake-pass-check <guard> …` reviews a passing guard beyond the known probes. It runs:

- **Static scan.** Roles, ownership, grants, RLS, search_path, views, rules and renames,
  operators and casts, database settings, writes or drops on application tables, trigger
  disabling, sleeps, conditions on the reader's identity, conditions on bench test data or seed
  IDs. Review items: SECURITY DEFINER, time or randomness, refusing on a read without a lock,
  process-local state, store-route-only hooks.
- **Catalog diff.** Run after install, against a no-guard reset.
- **Data diff against the seed.** Run at install and after traffic. Every table that traffic
  leaves unchanged under `none` and `refuse-all`, plus every stocked quantity, must still match.
- **Re-runs.** Stress runs with a fresh, recorded seed, plus one normal run. Every run must pass.

Verdict: `clean`, `review` (review items only) or `flagged`. Evidence goes to
`results/fake-pass/`.

## Checker integrity

- **API cross-check.** The runner (`bench.py` `cross_check`) takes every order confirmed
  by a store `/complete` (`{type: "order", order}`), an admin draft conversion
  (`{order}`) or an admin order-edit confirmation (`{order_preview}`). The confirmed
  items must equal the request; the last confirmation per order (an edit replaces the
  store order's expected items) must appear in the checker's `orders` with those
  per-variant unfulfilled quantities (traffic fulfils nothing), not deleted or draft, and
  canceled exactly when an admin cancel for it returned 200. Units of X/S/Z/D/E/R are also
  summed from those last confirmations, minus API-canceled orders (`api_units_sold`);
  `oversold` is true if either source exceeds stock. Deleting, canceling, marking fulfilled
  or rewriting an order after it was confirmed therefore fails the run.
- **RLS.** `bench_checker` has `BYPASSRLS`, set by the administrator on every reset;
  the checker verifies it (`checker_ok`, part of `valid`).
- **Shadowing.** `search_path = pg_catalog` only. Under the old `pg_catalog, public`, a
  guard-owned `public.*(numeric, integer)` operator beat pg_catalog's implicit-cast
  match and turned `5 * 2` into 0 (verified 2026-10-13); now it cannot be found.
- **Views and rules.** Every table the checker reads must be a plain table
  (`relkind = 'r'`), so a renamed table behind a same-named view invalidates the run.
  PostgreSQL 17 rejects ON SELECT rules on tables. Rules and triggers act only on
  writes, which Medusa and the checker see alike; write tampering is caught by the
  cross-check.
- **Ownership.** App tables are guard-owned only while `db.sql` runs. Afterwards the
  bench returns them to the administrator and re-grants SELECT, REFERENCES and TRIGGER.
  Guard objects can then no longer ALTER, DROP, re-own or (as the guard role) write
  app tables during traffic. Verified: `bench_guard` gets "must be owner" for
  `ALTER TABLE … ENABLE ROW LEVEL SECURITY` and "permission denied" for DELETE. FK
  cascades run as the new owner, and the app role keeps its DML grants, so Medusa
  compensation is unchanged; calibration below passes with it. It does not remove
  DML through SECURITY INVOKER triggers, which run as the app role; the API
  cross-check covers that path.

Versions: Medusa backend 2.19.0, TypeScript 5.8.3, pg 8.16.3;
Docker tags `node:22.22.2-bookworm-slim`, `postgres:17.11-bookworm`,
`redis:7.4.8-bookworm`. Transitive npm versions and integrity hashes are frozen
in `projects/medusa/package-lock.json`. The admin UI is disabled (the admin API is
served); no storefront is built.

Version deviation from SPEC.md: all 70 backend/tooling `@medusajs/*` packages
resolve to 2.19.0; the upstream admin dependency `@medusajs/ui` resolves to 4.2.1.
There is no published UI 2.19.0. Keeping the upstream dependency avoids modifying
Medusa source. `verify-lock.mjs` enforces this single explicit exception.

Memory limits: two Medusa instances at 1,280 MiB each (2,560 MiB, the previous
single-instance budget), Postgres 768 MiB, Redis 128 MiB, total 3,456 MiB (3.375 GiB).
Each instance's V8 heap limit is 768 MiB. Both instances share the database and Redis;
`medusa-config.ts` configures the Redis locking provider (`@medusajs/locking-redis`
2.19.0, already in the lockfile), because the default in-memory provider is per process
and would let two instances lose `reserved_quantity` updates. Only the bench's own
Docker resources are used; the instances listen on localhost ports 9000 and 9001.

Guard interface: `guards/<name>/db.sql` is applied after database restore and
before startup as `bench_guard`, a non-superuser with CREATE on public and
SELECT, REFERENCES and TRIGGER on app tables. The role owns restored app tables
while its SQL runs, so it can add constraints; ownership then returns to the
administrator (see Checker integrity). The checker rejects seed tampering.
SQL is sent via `psql -c` with backslash lines rejected, so client meta-commands
cannot execute. Guard/app role defaults are reset before every guard. The role cannot
own or alter bench objects, privileged/other roles, or the disconnected template. Medusa serves
requests as the separate non-superuser `medusa_app`; migration/seeding use the
administrator. Alternatively pass an absolute guard-directory path. Optional
`app.patch` paths are relative to `projects/medusa`; patches are checked and
applied in a temporary copy, then built as a separate image before starting it.
Database guards and application patches may coexist. Application image build
time is excluded from reset timing. Calibration uses database guards only.

Per-run JSON and run-case summaries live under ignored `results/runs/`; other
verification artifacts and logs under `results/` are also ignored.
Only `bin/calibrate` writes the version-controlled
`results/calibration-summary.json`. Setup/traffic/checker failures are recorded
per run, the checker is always attempted, and a run with errors always fails.
Failed calibration must not be treated as a valid benchmark.

## Calibration 2026-10-14, after the four judge fixes (current)

Same stress traffic (base seed 1). Judge: units owed only (over-reservation is the
`overreserved` warning), owed units clamped at 0, custom lines skipped, every product judged;
traffic records refused cart creation and 30 s timeouts as refusals.

| Guard | Runs | Pass | Oversold (any) | Other products oversold | Overreserved warning | Crowd OK | Normal OK | Errors | Invalid |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| none | 30 | 0 | 30 | 30 (Y) | 30 | 30 | 30 | 0 | 0 |
| refuse-all | 30 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| reference | 30 | 30 | 0 | 0 | 0 | 30 | 30 | 0 | 0 |

Reset 9.7–32.0 s; no request timed out. Log: `results/calibration-2026-10-14-judgefix.log`.

## Calibration 2026-10-14, stress traffic (superseded)

Stress traffic (base seed 1, so run *n* has the same schedule for every guard). Products,
checker and seed are unchanged from the resale calibration below. A first attempt the same day
had `reference` 30/30 and `none` 0/30 with no errors, but one `refuse-all` run failed with
"socket hang up". A pooled keep-alive socket was reused just as Medusa closed it after 5 s
idle. The traffic runner now honours the server's keep-alive hint (agent `timeout`) and resends
once only when a reused socket is reset before any response (Node's documented pattern). The
full calibration was then rerun (`results/calibration-summary-2026-10-14-stress-attempt1.json`
keeps the first attempt).

| Guard | Runs | Pass | Oversold (any) | Concurrent X | Sequential S | Draft D | Edit E | Resale R | Crowd/burst oversold | Crowd OK | Normal OK | Legit pair OK | Draft OK | Edit OK | Resold OK | Confirmed orders OK | Errors | Invalid |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| none | 30 | 0 | 30 | 15 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 0 | 0 | 30 | 30 | 0 | 0 |
| refuse-all | 30 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 30 | 0 | 0 |
| reference | 30 | 30 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 0 | 0 |

Reset 7.6–11.0 s. Host load average (1 min) stayed at or below 9.4.

- **none.** The X pair oversold in 15/30 runs: in the other 15, cart B was released first and
  cart A was refused, which random order allows. Bursts exposed the oversell in every run: the
  first oversold burst was burst 1 in 9 runs, 2–6 in 20, and 9 in one.
- **reference.** All 1,101 crowd and burst carts were placed or correctly refused: 0 false
  blocks, all 6 W carts placed in every run, 10 bursts in every run. The X pair placed A 17
  times and B 13 times. Across both attempts, `reference` passed 60/60 stress runs with no
  false block.
- **refuse-all.** Every crowd cart was refused (1,101 false blocks).

## Calibration 2026-10-13/14, resale after cancel and after reservation deletion (normal schedule)

Founder decision 2026-10-13: deleting the reservation of a live order and reselling its
units breaks the promise. Added product R and traffic step 8. The checker previously counted
every placed order, **including canceled ones**, so a legitimate cancel-then-resale would
have scored as an oversell; it now counts live (not deleted, canceled or draft) orders'
unfulfilled current-version units, still never reservations. The cross-check accepts a
canceled order only when the admin cancel returned 200. Fresh reseed (product R added; all
earlier IDs unchanged, verified field by field against the previous manifest); a second
fresh reseed produced a byte-identical `seed-ids.json` (sha1 9ace6aaa…).

| Guard | Runs | Oversold (any) | Concurrent X | Sequential S | Draft D | Edit E | Resale R | Normal OK | Trigger OK | Legit pair OK | Backorder OK | Draft OK | Edit OK | Resold OK | Bookkeeping OK | Confirmed orders OK | Pass |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| none | 30 | 30 | 28 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 0 | 0 | 30 | 30 | 30 | 0 |
| refuse-all | 30 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 30 | 30 | 0 |
| reference | 30 | 0 | 0 | 0 | 0 | 0 | 0 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 |

Zero errors and zero invalid runs across all 90. Reset 6.98–24.05 s (one `none` reset at
24.05 s; all others ≤ 12.19 s). Under `none` the third R order was placed in every run (20
units owed of 10). The concurrent X pair oversold 28/30: at offsets 0 ms and 20 ms one run
each placed only cart B. Under `reference` the X pair placed A 28 times and B twice (both
at 5 ms). Sampled peak memory over all 90 runs (869 `docker stats` samples): Medusa
401 + 396 MiB (pair peak 794), Postgres 138, Redis 16, total 941 MiB against the 3,456 MiB limit
(`results/resources-summary-2026-10-13-resale.json`).

Reference guard change: the trigger still sums live reservations, then adds, for every
order line ever reserved at that item and location whose order is live, the unfulfilled
units its live reservations no longer hold. Deleting a reservation is allowed; the resale
is refused. Blocking the deletion instead is not workable at the database level: Medusa's
cancel deletes reservations before it marks the order canceled, and order edits delete
then re-reserve, each in separate transactions, so a legitimate deletion looks like an
illegitimate one at that moment. Lines never reserved are skipped because Medusa creates the
order before reserving it; counting them would make the concurrent X carts block each
other. Known limit: Medusa soft-deletes reservations on every path except compensation; a
raw hard `DELETE` leaves no row and is not covered.

## Calibration 2026-10-13, admin paths added (superseded)

Same store traffic as below, plus the sequential admin draft-order (D) and order-edit (E)
scenarios. Fresh reseed on 2026-10-13 (products D and E and the admin user added; all
earlier IDs unchanged); a second fresh reseed produced a byte-identical `seed-ids.json`
(sha1 a67d62d2…).

| Guard | Runs | Oversold (any) | Concurrent X | Sequential S | Draft D | Edit E | Normal OK | Trigger OK | Legit pair OK | Backorder OK | Draft OK | Edit OK | Bookkeeping OK | Confirmed orders OK | Pass |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| none | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 0 | 0 | 30 | 30 | 0 |
| refuse-all | 30 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 30 | 30 | 0 |
| reference | 30 | 0 | 0 | 0 | 0 | 0 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 |

Zero errors and zero invalid runs across all 90. Reset 6.57–12.94 s. Under `none` the
draft conversion and the order edit each sold 12 of 10 in every run; the fitting draft
and edit are then refused by Medusa's own check because stock is already gone, so
`draft_ok`/`edit_ok` are false there by construction. Under `reference` the concurrent X
pair placed A in 27 runs and B in 3 (offset 0 ms: A 8, B 2; 5 ms: A 9, B 1; 20 ms: A 10).
Memory was not re-sampled.

## Calibration 2026-10-13, store paths only (superseded)

Two instances, Redis locking, dispatch offsets 0/5/20 ms (10 runs each), sequential
trigger, legitimate pair, backorder and API cross-check. Fresh reseed on 2026-10-13
(products S and BO added; all earlier IDs unchanged); a second fresh reseed produced a
byte-identical `seed-ids.json` (sha1 6a1e35e6…).

| Guard | Runs | Oversold (any) | Concurrent X | Sequential S | Normal OK | Trigger OK | Legit pair OK | Backorder OK | Bookkeeping OK | Confirmed orders OK | Pass |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| none | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 0 |
| refuse-all | 30 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 30 | 30 | 0 |
| reference | 30 | 0 | 0 | 0 | 30 | 30 | 30 | 30 | 30 | 30 | 30 |

Zero errors and zero invalid runs across all 90. Reset 6.50–8.14 s. Sampled peak
memory: 905 MiB total (Medusa 360 + 380, Postgres 177, Redis 21) against the
3,456 MiB limit. The concurrent X trigger oversold under `none` in 30/30 runs at every
offset, versus 14/30 with one instance on 2026-10-11. With two instances and Redis
locking, cart A won the lock in every run, so the reference guard placed A 30/30.
No timing variation stopped the oversell. The concurrent trigger therefore no longer
exercises B-first ordering; the sequential trigger is the deterministic check.

## Calibration 2026-10-11 (previous scenario, one instance)

Verified on 2026-10-11 using host Node 23.11.1 (traffic runner), Python 3.14.6,
Docker 29.7.2 and Compose 5.4.0; Medusa runs in the pinned Node 22.22.2 image.
All 90 trials used HTTP, one backend process and two warmed keep-alive sockets
released in the same synchronous turn. No scenario or timing variation was needed.

| Guard | Runs | Oversold | Normal OK | Bookkeeping OK | Pass |
|---|---:|---:|---:|---:|---:|
| none | 30 | 14 | 30 | 30 | 16 |
| refuse-all | 30 | 0 | 0 | 30 | 0 |
| reference | 30 | 0 | 30 | 30 | 30 |

The updated calibration has zero harness errors and zero invalid seed states
across all 90 runs. Reset durations ranged from 5.81 to 10.71 seconds.
Stock inflation, soft-deletion, kit tampering, checkout setup errors, template/role
attacks and psql commands were exercised by `bin/verify-negative`. A second fresh
seed produced a byte-identical ID manifest.

Negative probes (`bin/verify-negative`, normal schedule, last run 2026-10-14 after the stress changes: 19 probes plus the role-settings check) must all score `pass=false` for
the stated reason: seed tampering, template/role/psql attacks and checker errors (as
before); a view swapped in for `inventory_level` (`checker_ok=false`); RLS hiding
orders from the checker (the checker still sees every order and the oversell); a
shadowing `public.*` operator (units still counted); hard-deleting the
confirmed overselling order and scrubbing its reservations after confirmation
(`confirmed_orders_ok=false`, API count 12 > 10); refusing reservations for low-stock
items (`trigger_ok=false`, `legit_concurrent_ok=false`); the reference guard with an
off-by-one `>=` (`legit_concurrent_ok=false`, and the fitting draft and edit refused); the
previous reference guard that sums reservation rows only (added 2026-10-14: every other check
holds, including the resale after the cancel, but after the live R order's reservations are
deleted its 10 units are sold again, `resold_oversold=true`, R sold 20 of 10); an
app patch that guards only `/store/carts/:id/complete` by summing cart lines against
stock minus reservations under a Redis lock (every store check holds, including the
concurrent pair; draft and edit each sell 12 of 10, so it would have passed before the
admin scenarios existed); an app patch delaying single-line
carts by 300 ms (concurrent trigger looks fixed, sequential oversells); and an app
patch with a per-process units ledger (sequential oversells across two instances).
Control: the same ledger with both carts on one instance passed 3/3
(`results/ledger-single-instance-control.json`).

The latest counts and reset durations are in
[calibration results](results/calibration-summary.json). Negative tests and local
verification artifacts are under ignored `results/`; they are not calibration.
The literal all-`@medusajs/*` 2.19.0 pin remains impossible because upstream UI
has no such release; the explicit lock verification exception is unchanged.
