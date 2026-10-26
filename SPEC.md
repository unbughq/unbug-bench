# Unbug bench — spec v0.1

The bench scores whether a protection keeps a plain-language business promise on real
open-source software, using a real bug. It is shared by every contestant and must be
built and frozen before any contestant is scored on it.

## First case: `medusa-oversell`

**Promise (contract):** *Never sell more stock than exists.* Units promised to customers on
live orders (placed, not canceled, not yet fulfilled) must never exceed stocked quantity
(backorder-allowed items excepted). Units stay promised until the order is fulfilled or
canceled: deleting the reservation of an order that is still live and reselling those units
counts as overselling. Canceling an order frees its stock legitimately.

**Software:** Medusa v2 back end, pinned to **2.19.0** (`@medusajs/medusa`,
`@medusajs/framework`, and all `@medusajs/*` packages resolved to 2.19.0). No storefront,
no admin UI (the admin API is served; setup creates one admin user). Postgres 17, Redis 7.

**Real bug:** medusajs/medusa#17032 (open). Inventory reservation validates each cart line
separately and never sums lines that draw on the same inventory item. Medusa's Locking
module serializes reservations per inventory item, so the outcome depends on **order**,
not on a database race: if cart A (5 units) reserves first, 5 remain and cart B's lines
(3 and 4 units) each pass separately, so 12 units are sold. If B reserves first, A
(5 > 3) is refused. Verified 2026-10-13 under `none`: A then B, one after the other,
oversold 6/6; B then A oversold 0/3. The original concurrent release oversold 14/30
(the A-first rate). **Do not modify Medusa core code** — the bug must be the one that ships.

### Scenario (one run)

1. Reset to the seeded snapshot.
2. Apply the guard under test (see Guards).
3. **Normal traffic:** 5 single-item orders for other products with ample stock
   (stock ≥ 100). Each must complete.
4. **Trigger:** product X has one inventory item with `stocked_quantity = 10` at a single
   stock location, `manage_inventory = true`, `allow_backorder = false`. Product X also has a
   "2-pack" variant whose inventory kit draws 2 units of the same inventory item.
   - Cart A: 5 × X (single unit variant).
   - Cart B: 3 × X (single unit variant) + 2 × 2-pack (= 4 units).
   - Combined demand 12 > 10. Complete both carts **at the same moment** via the store
     HTTP API, cart A on app instance 1 and cart B on instance 2. Cart B is dispatched
     0, 5 or 20 ms after A, chosen by run number (`(run − 1) mod 3`).
   - Correct outcome: exactly one cart placed (each fits alone).
5. **Sequential trigger:** product S, identical to X (stock 10, single + 2-pack). Cart A
   (5 × single) completes on instance 1, then cart B (3 × single + 2 × 2-pack) on
   instance 2. Correct outcome: A placed, B refused. Under `none` this oversells every
   run; it catches protections that only change ordering or timing, and protections that
   keep state in one process.
6. **Legitimate concurrent pair:** product Z (stock 16): cart C 4 × single + 2 × 2-pack
   (8 units) and cart D 2 × single + 3 × 2-pack (8 units), released like the trigger.
   Combined demand equals stock exactly; both must be placed.
7. **Backorder exception:** product BO (stock 4, `allow_backorder = true`): one cart of
   6 units must be placed and is not an oversell.
8. **Admin draft order** (product D, identical to X): a store order of 5 × single is
   placed. Then, via the admin API, a draft order of 3 × single + 2 × 2-pack (7 units) is
   created on instance 1 and converted to an order on instance 2
   (`POST /admin/draft-orders/:id/convert-to-order`). Correct outcome: conversion refused.
   Then a draft of 1 × single + 2 × 2-pack (5 units, exactly the rest) must convert.
9. **Admin order edit** (product E, identical to X): a store order of 5 × single is placed.
   An order edit adds 3 × single + 2 × 2-pack (`POST /admin/order-edits`, `…/items`,
   `…/request` on instance 1, `…/confirm` on instance 2). Correct outcome: confirmation
   refused; the open edit is then canceled (`DELETE /admin/order-edits/:id`). A second edit
   adding 1 × single + 2 × 2-pack (exactly the rest) must be confirmed. Both admin
   scenarios run sequentially and reach the same per-line availability check as checkout
   (via `reserveInventoryStep`). Under `none` both oversold (12 of 10) in 30/30 runs on
   2026-10-13.
10. **Resale** (product R, identical to X, stock 10), sequential: a store order of 4 × single
    + 3 × 2-pack (10 units) is placed and canceled via the admin API
    (`POST /admin/orders/:id/cancel`). A second identical order must be placed (canceling
    frees stock). Its reservations are then deleted via the admin API
    (`DELETE /admin/reservations/:id`, found by `GET /admin/reservations` on R's inventory
    item and the order's line IDs) while the order stays live. A third identical order must
    be refused. Under `none` the third order is placed (20 units promised of 10).
11. **Stress traffic (default, scored).** Steps 3–10 with every request group on a random
    instance, both concurrent pairs in random order with random 0–50 ms gaps, and the normal
    orders released together. In addition, a crowd of 6 × 4 units on product W (stock 24; all
    must be placed), and up to 10 bursts of 2–4 conflicting carts on product Y (stock 8). Each
    burst is released within 5 ms, and its placed orders are canceled before the next burst. The
    schedule comes from a recorded seed (README "Stress traffic"). `--normal` runs steps 3–10
    with the fixed instances and offsets only.
12. Run the checker.

The app runs as two Medusa server processes (ports 9000 and 9001) sharing Postgres and
Redis; the Redis locking provider is configured, as Medusa requires for multiple instances.

### Checker (the oracle)

- Reads Postgres **directly with read-only SQL**. Never calls Medusa APIs, never writes.
  `search_path` is `pg_catalog` only, so guard-created functions or operators cannot
  shadow the checker's. The checker role has `BYPASSRLS` (reasserted every reset), and
  every table it reads must be a plain table (`relkind = 'r'`), not a view.
- Reports JSON per run:
  - `units_sold_x` — units of inventory item X promised by live orders: current-version
    line quantity minus `fulfilled_quantity`, × kit `required_quantity`, on orders not
    deleted, canceled or draft. Counted from orders, never from reservations, so a deleted
    reservation cannot hide a promise. A guard cannot hide an oversell by canceling it: an
    API-confirmed order found canceled without an API cancel fails the cross-check.
  - `stocked_x`, `reserved_x`, `available_x` (= stocked − reserved).
  - `reservation_rows_sum_x` — sum of live `reservation_item` rows for X.
  - `normal_orders_placed` (expect 5).
  - `oversold` — true if units owed exceed stock on any non-backorder item: the kits with
    frozen factors, and since 2026-10-14 every other inventory item through its own variant
    links (`oversold_other_items` lists those). Owed units per line are clamped at 0.
  - `overreserved` — warning only: reserved above stock on a non-backorder item while no live
    order owes too much (founder decision 2026-10-14; was part of `oversold` before).
  - `bookkeeping_ok` — `reserved_x == reservation_rows_sum_x`.
  - `normal_ok` — all 5 normal orders placed.
  - `concurrent_oversold` (X), `sequential_oversold` (S); `oversold` covers X, S and Z.
  - `trigger_ok` — at least one concurrent trigger cart placed with its full quantity,
    and the first sequential cart placed.
  - `legit_concurrent_ok` — both Z carts placed with full quantities.
  - `backorder_ok` — the BO order placed with 6 units.
  - `draft_oversold` (D), `edit_oversold` (E), `resold_oversold` (R); `oversold` also covers
    D, E and R.
  - `resold_ok` — after the first R order is canceled, the 10-unit resale is placed.
  - `draft_ok` — the D store order and the fitting draft conversion are placed
    (`draft_store_placed`, `draft_fit_placed`). `edit_ok` — the E store order is placed
    and its latest version holds exactly 10 units, i.e. the fitting edit was confirmed
    (`edit_store_placed`, `edit_fit_placed`).
  - Units are counted from each order's current version (`order.version`; a confirmed
    edit raises it). Draft orders never converted (`is_draft_order` or status `draft`) are
    not sales.
  - `checker_ok` — BYPASSRLS and plain-table checks hold (part of `valid`).
  - `orders` — every order row with status and current-version quantities per variant.
  - `valid` — fixed seed product, variants and inventory item exist and are live,
    and `stocked_x == 10`; X inventory flags and live 1-unit/2-unit kit mappings
    must match the seed. Sales use fixed variant IDs and original kit factors. Seed IDs are read from the version-controlled manifest.
  - `crowd_oversold`, `crowd_ok` (stress only, computed by the runner from the checker's order
    rows and the API record against frozen stock Y 8, W 24): a burst or the crowd that places
    more units than stock, or live Y/W units above stock, is an oversell. A refused cart that
    would still fit the stock its group left is a false block (`crowd_ok = false`).
  - `pass` — `valid && !oversold && bookkeeping_ok && normal_ok && trigger_ok &&
    legit_concurrent_ok && backorder_ok && draft_ok && edit_ok && resold_ok &&
    confirmed_orders_ok` (and under stress `!crowd_oversold && crowd_ok`), with no
    guard-installation, traffic or checker errors. Errors are recorded per run;
    the checker is always attempted and run JSON is always written.
- The database is the primary oracle. The runner cross-checks it against the API: every
  order confirmed by a store `/complete`, an admin draft conversion or an admin order-edit
  confirmation must match its request, and must appear in the checker's `orders` with
  exactly its last confirmed quantities, unfulfilled (a confirmed edit replaces the order's
  expected items), not deleted or draft, and canceled exactly when the admin API confirmed
  its cancellation (`confirmed_orders_ok`). Units of every tracked kit are also summed from
  the last confirmation per order, excluding API-canceled orders (`api_units_sold`); `oversold`
  is true if either the database or the API count exceeds stock. A guard that deletes or
  rewrites an order after confirming it therefore fails.

### Guards

A guard is a directory `guards/<name>/` with an optional `db.sql` (applied to the database
after reset) and an optional `app.patch` (applied to the app before start). Calibration
guards live in the bench; contestant guards are supplied later from outside.

Database guards execute via `psql -c` as a non-superuser role, with public-schema
CREATE and application-table SELECT, REFERENCES and TRIGGER privileges (including
constraint triggers). Restored application tables are guard-owned **only while the guard
installs** (to permit ADD CONSTRAINT and similar DDL); afterwards the bench returns them to
the administrator and re-grants SELECT, REFERENCES and TRIGGER. Guard functions run as
the app role (SECURITY INVOKER, the default) or as the guard role (SECURITY DEFINER).
The checker invalidates seed tampering. The role cannot
modify bench objects or the template. Seed stock/product tampering invalidates the run. The serving app also
uses a separate non-superuser role. ALTER TABLE constraints on app tables and constraints on new guard tables are supported.

Calibration guards (bench-internal):
- `none` — vanilla Medusa 2.19.0.
- `refuse-all` — rejects every reservation (e.g. a trigger that always raises). Must fail
  because normal orders cannot complete.
- `reference` — a correct guard: Postgres `AFTER INSERT OR UPDATE` trigger on
  `reservation_item` that locks the inventory level row, sums live reservations for that
  item and location, adds the unfulfilled units still owed by live orders whose reserved
  lines lost their reservation (deleted or reduced), and raises if the total exceeds
  `stocked_quantity` (skip `allow_backorder` items). The reservation sum alone is the issue
  reporter's workaround; it misses resale after a reservation deletion.

### Reset

- Seed once, then snapshot (e.g. Postgres template database). Reset = recreate the
  database from the snapshot, flush Redis, restart the Medusa server. Target ≤ 30 s.
- A fresh reset followed immediately by the checker must report the identical baseline
  every time (stock 10, reserved 0, no orders).

### Calibration — the bench is done when

Run each calibration guard **30 times** (reset before every run):

| Guard | Required outcome |
|---|---|
| `none` | concurrent `oversold` in **at least 1** of 30 runs (report the rate per dispatch offset); sequential, draft, edit and resale rates reported |
| `refuse-all` | `normal_ok = false` in **30 of 30** runs → fails |
| `reference` | `pass = true` in **30 of 30** runs |

If `none` never oversells, the bench is not measuring the bug: stop and report what was
tried (timing, HTTP vs in-process, worker count) instead of changing the scenario to force
a result.

## Layout

```
unbug-bench/
  SPEC.md
  README.md                  bench-internal operation, versions, calibration
  CONTESTANT.md              promise, running the app, guard interface and limits
  projects/medusa/           Docker Compose (medusa, postgres, redis), pinned app, seed
  cases/medusa-oversell/     case.yaml (promise, version, limits), traffic/, checker/, probes/ (bench-internal probe guards)
  guards/{none,refuse-all,reference}/
  scenarios/dev/             dev change scenarios S0, S2–S11 (scenario.json, key.json, optional app.patch, admin.sql, hooks.mjs, judge.py)
  bin/                       reset, run-case <case> <guard> [runs], calibrate, verify-negative, replay,
                             checkpoint, score-claims (claims.py), stress-compare, fake-pass-check
  results/                   ignored runs/ and logs; only calibration-summary.json version-controlled
```

## Constraints

- Runs on one laptop with Docker; whole stack ≤ 4 GB RAM. No Kubernetes, no cloud.
- One command each: `bin/reset`, `bin/run-case medusa-oversell <guard> <runs>`,
  `bin/calibrate`.
- Pin every version (images by tag, npm via lockfile). Record them in README.
- Deterministic seed (fixed handles/SKUs and entity IDs; version-controlled seed-ids.json). Only the concurrency is
  nondeterministic.
- **Separation:** traffic scripts, checker, and calibration guards are bench internals.
  Contestants will receive only the promise, the app, and the guard interface. Do not put
  hints about the bug in anything a contestant would see.
- Keep it small and boring. No framework beyond what Medusa and the scripts need.


## Additional inventory writers (v2)

A scenario (including a case's `base/scenario.json`) declares independent channels:

```json
{"inventory_services":[{"name":"marketplace","project":"projects/marketplace"}]}
```

`name` is the Compose service name and becomes the judge path `service:<name>`.
Names must be unique and cannot replace Medusa, Postgres or Redis. `project` is an
absolute directory, a directory relative to the scenario, or a repository-relative
path. The directory contains code, a Dockerfile, `compose.yaml` (an overlay on the base
Medusa Compose project), and a trusted stdlib `adapter.py`. Compose overlays use the
base Compose file's path rules; the runner supplies an absolute build context for the
named service. Overlays must only add their own service/resources, preserve base
services, keep ports bound to localhost, and stay within the laptop's 4 GiB budget.
A case ships its own project code and declares it in its base scenario; the public
marketplace is practice material, not a required sealed-case service or bug.

`bin/setup --scenario <dir>` on fresh volumes and `bin/reset --scenario <dir>` prepare
these services; `bin/checkpoint` passes all applied scenarios to reset. Reset stops and
removes the previously declared services even when the next run declares none. After
Medusa's baseline is restored, it builds isolated service sources, starts the overlay,
waits for health, and calls each adapter's `reset`. Services may have their own database,
file or API: their reset adapter must clear all sales and restore their fixture before
traffic. The reference service uses tmpfs SQLite. A failed start/reset/check fails the
run; stale storage never supplies a successful verdict.

Adapter invocation is `python3 adapter.py <reset|check> <name> <compose-argv-json>`.
It runs on the host from the original project source, outside guard-patched runtime
code. The adapter uses the supplied Compose argv to reach its own storage. Both actions
return JSON with `{"orders":{}}` at baseline, or for a sale:

```json
{"orders":{"channel-1":{"units":{"s":2},"canceled":false}}}
```

Units are unfulfilled physical units of the existing frozen kit names (`x,s,z,d,e,r,y,w`).
The adapter fixes the catalog mapping/factors itself; it must not trust a runtime's
claimed stock, monitor view, or aggregate counters. Canceled orders remain identifiable.
Independent customer orders count once; a corresponding Medusa reservation is a hold,
not another sale. Mirroring a channel order as a Medusa customer order is unsupported:
the case must provide a trusted deduplication adapter before using such a design.

Drive services from existing `hooks.mjs` hooks. Record every attempted sale in
`ctx.record.services[name]` using the existing response wrapper:

```json
{"requested":{"s":2},"legitimate":true,
 "response":{"status":200,"data":{"order":{"id":"channel-1","units":{"s":2}}}}}
```

Only HTTP 200 with an order is a confirmation. If the traffic cancels it, add
`"canceled":{"status":200}` to that record. `legitimate:true` marks a required fitting
sale and contributes to checkpoint completion; hooks/judge checks must also test that
oversized orders fail and fitting orders succeed. Retried confirmations must be recorded
once. For windows that free stock before final checking (e.g. a canceled oversell), hooks
also record trusted observations in `ctx.record.inventory_windows`:

```json
[{"id":"before-cancel","medusa":{"s":5},"services":{"marketplace":{"s":7}}}]
```

These are physical units owed concurrently, read from each writer at that window.
The judge sums all writers against frozen stock and the scenario's rule; the observation
cannot raise the stock limit. A case that cancels sales between bursts must include such
windows, just as Medusa-only bursts use `ctx.group`. Hooks and adapters are trusted judge
inputs and must include every overlapping writer, not sampled subsets.

The generic judge checks confirmations against the service ledger, rejecting missing,
rewritten or silently canceled orders. For each service order/kit it takes the greater of storage and uncanceled API units,
then sums those orders and adds Medusa's greater database/API total. Distinct order IDs
are never merged just because their aggregate units happen to match.
An aggregate excess violates `service:<name>` for every service contributing units of
that kit; existing Medusa path verdicts continue to describe its own orders/groups.
Per-service bookkeeping checks are named `service:<name>:confirmed_orders_ok`. The judge
records individual and total units in `judge.facts.inventory_services`. `checkpoint.json`
receives service paths through the existing path-summary interface, ready for claims
scoring without changing `bin/checkpoint`. Backorder and safety-stock exceptions apply
to the shared stock, never to a channel's independent cached stock value.

A guard may additionally supply `services.patch`, applied with service names as the
first path component (`a/marketplace/service.py`). Patch only the runtime code: the
runner rejects changes to `adapter.py`, `Dockerfile` or `compose.yaml`, and builds temporary source
copies without editing `projects/medusa`. Guard hashing, saved guard copies and replay
include this patch. Service project sources, adapters and overlays are copied into the saved scenario; its
digest protects the complete baseline, including external or scenario-relative projects.
Replay resolves those frozen copies, so later baseline source changes cannot alter them.

Public development calibration: `scenarios/dev/S13-marketplace` with guards `none`,
`examples/tables-only`, and `examples/cross-service`. Both example guards protect Medusa's
tables. Only cross-service coordinates the channel's own SQLite promises with Medusa holds.
Its required result is safe, full legitimate completion; a table-only guard violates
`service:marketplace` despite every Medusa-only path remaining safe. The channel starts
with 2 units before Medusa's S sale, then attempts 7, 3, and 1 units: the safe statuses are
200, 409, 200, 409, totaling 5 channel + 5 Medusa units of the same 10.
