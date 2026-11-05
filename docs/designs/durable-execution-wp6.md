# Durable execution WP6: the ledger

Status: design note for WP6 of `docs/designs/durable-execution.md` (wave 1).
Branch `de/wp6-wp7`, cut from `durable-execution` at `db13be8`.
Owns `factory/durable/ledger.py` and `tests/factory/test_durable_ledger*.py`.

## Problem

The engine needs one place that holds the batch's money bound and each case's own
money, grants every attempt its `money_ceiling_usd_micros` before the attempt starts,
and books what the attempt really spent. It has to be exact under concurrent cases,
survive a crash between any two calls, and give the same answers when the engine
replays a case and calls it again. Today this is spread over `batch_money.py`, the
holder's reservation receipts and per-card `case_budget`, which disagree after
crashes (design, "Problem").

## Change

`factory/durable/ledger.py` implements the frozen `Ledger` protocol (contract v5)
as `SqlLedger(url)`, stored through SQLAlchemy (which `dbos==3.4.0` already
installs). In production the URL is the engine's Postgres; tests use SQLite files.
It implements the contract seam `Ledger` and calls nothing else. WP1 calls it from
DBOS steps; `policy.draws_case_money` gives `draws_case_money`, and
`policy.settles_as_waste` gives `waste`.

### Tables

Two tables, created on construction if missing (`create_all`, idempotent):

- `durable_ledger_batch(batch_id PK, bound_usd_micros)`.
- `durable_ledger_attempt(idempotency_key PK, batch_id, case_id, draws_case_money,
  requested_usd_micros, case_limit_usd_micros, granted_usd_micros, limited_by,
  state, waste, calls, paid_usd_micros, list_usd_micros)`, where `state` is `held`,
  `settled` or `lost`.

Only identifiers, enums and integers are stored: nothing here can carry case
content. There are no timestamps or autoincrement ids, so two databases fed the
same calls hold identical rows.

Balances are not stored. They are sums over the attempt rows, computed inside the
same transaction that changes them, so there is no second copy that can drift:

- batch used = granted of `held` rows + paid of `settled` rows + granted of `lost` rows;
- batch waste = paid of `settled` rows with `waste` + granted of `lost` rows;
- case used = over that case's rows with `draws_case_money` and not `waste`:
  granted of `held` rows + paid of `settled` rows;
- remaining = max(0, limit − used).

Case money is keyed by `(batch_id, case_id)`. A case resumed in a later batch
(HOLD, wave 2) starts that batch's case money fresh; carrying lineage spend
across batches belongs to the planned `BatchSpec` change with WP10.

### Serialization

Every call runs in one transaction that first locks the batch row:

- Postgres: `SELECT ... FOR UPDATE` on `durable_ledger_batch`. Under READ
  COMMITTED, the sums that follow the lock see every commit that preceded it.
- SQLite: the engine issues `BEGIN IMMEDIATE` (the SQLAlchemy pysqlite recipe), so
  a transaction takes the write lock before its first read, and waits up to 60 s
  for it. `FOR UPDATE` compiles to nothing there.

So reserves and settles of one batch are serialized, and a grant is computed from
balances no other transaction can change before it commits. Concurrent cases can
never overshoot either limit.

### The calls

- `open(batch_id, bound)`: creates the batch row. If it exists, the bound becomes
  `max(current, bound)`, so a repeated `open` is a no-op and a replayed `open`
  never undoes a later `raise_bound`.
- `raise_bound(batch_id, bound)`: bound = `max(current, bound)`. Idempotent and
  order-independent. A figure below the current bound changes nothing (the ledger
  never lowers a bound the founder set; WP8's operator command validates input).
  An unopened batch raises `LedgerError`.
- `reserve(...)`: if a row with the key exists, return its stored Grant, unchanged
  even after `raise_bound` or `settle` (the request figure is ignored on a repeat,
  because a batch-only step's request is "the remaining bound", which moves). The
  repeat must name the same batch, case and `draws_case_money`, or `LedgerError`.
  Otherwise, with `B` the batch's remaining bound and `C` the case's remaining
  money (`case_limit − case used`):
  - `amount = min(requested, B, C if draws_case_money)`;
  - label: **BATCH** if `B <= amount`; otherwise **CASE** if `draws_case_money` and
    `C < requested`; otherwise **NOTHING**;
  - insert the row as `held`, and return `Grant(amount, label)`.
- `settle(key, usage, *, waste=False)`: books `usage.paid_usd_micros` (the paid
  figure is the money; calls and list price are kept for the record), marks the
  row `settled` and so frees the rest of the grant. With `waste=True` the row
  counts for the batch only, never against the case's money. Real usage above the
  grant is booked as it is (the worker stops at the ceiling, but its last call may
  overrun); the remaining figures clamp at zero.
- `settle_lost(key)`: marks the row `lost`. Its whole grant is booked to the batch
  as waste, never to the case.

### The tie cases of the label rule

The contract says: "BATCH whenever the batch's remaining bound is at or below the
granted amount; otherwise CASE whenever the case's remaining money capped the
grant; otherwise NOTHING". `LimitedBy.NOTHING` means "the whole request was
granted". Read together, the three ties (design review 4, N2) are:

| Tie | Example (request, C, B) | Label |
|---|---|---|
| request equals the batch's remaining bound | 30, 50, 30 | BATCH |
| case money equals the batch's remaining bound, both below the request | 50, 30, 30 | BATCH |
| request equals the case's remaining money, batch above it | 50, 50, 80 | NOTHING |

The third is NOTHING because the case's money did not cap anything: the whole
request was granted. A fresh ordinary step requests exactly `case_money_usd_micros`,
so this is the common case, and labelling it CASE would make every fresh step look
case-limited. `policy.decide` treats CASE and NOTHING alike today; WP1's minimum
grant rule ("a sub-minimum CASE grant diagnoses") depends on the difference, and
gets CASE only when the case's money really ran short.

### Idempotency and conflicts

Every call is idempotent on its key. A repeat with the same arguments changes
nothing. A repeat that contradicts the first call (a second `settle` with other
usage or another `waste`, `settle_lost` after `settle`, or `settle` after
`settle_lost`) raises `LedgerError` rather than silently choosing one: replay
always repeats the same arguments, so a contradiction is a caller bug. A settle
for a key that was never reserved raises too. `LedgerError` messages are fixed
text plus identifiers, never figures from case content.

### Reads

`balance(batch_id)` returns `{bound, used, held, spent, waste, remaining}` and
`case_balance(batch_id, case_id, case_limit)` returns `{used, remaining}`, for
WP1's minimum-grant check, `report.py`'s infra-waste line and the tests.
`rows()` returns both tables in key order, for the replay comparison.

## What it deletes

Nothing in wave 1. In WP9 it replaces the money booking in `batch_money.py`, the
holder's reservation receipts (`key_holder.py`, `batch_holder.py`) and the
in-process `case_budget` that WP5a turns off under the engine.

## Tests

`tests/factory/test_durable_ledger.py`, on real SQLite files through real
SQLAlchemy:

- **Concurrency:** 8 threads sharing one `SqlLedger`, and separately 4 processes
  each with its own `SqlLedger`, hammer one database file with reserves (random
  requests, several cases, ordinary and batch-only) and settles. Afterwards and at
  every step, the sum of all holds plus booked spend never exceeds the bound, and
  no case's non-waste use exceeds its money. A second run checks that two
  processes reserving the same key get the same Grant and one row.
- **Waste:** five INFRA_ERROR attempts that each spend money, settled with
  `waste=True`, lower the batch's remaining bound by their spend and leave the
  case's remaining money unchanged; a sixth ordinary reserve still gets the full
  case money. `settle_lost` does the same with the whole grant.
- **Labels:** the three ties above, plus a plain case of each label and a
  batch-only step that ignores case money.
- **raise_bound:** a reserve labelled BATCH, then `raise_bound`, then the same
  reserve returns the original Grant; a new key gets the raised figure.
- **Idempotency and replay:** a scripted sequence of every call is applied once to
  one database, and to a second database with every call repeated and then the
  whole sequence run again; the rows and every returned Grant are identical. A
  child process killed with `os._exit` partway through the sequence, then rerun
  from the start, also ends identical. Contradicting repeats raise.
- **Postgres** (optional): the concurrency test also runs against a Postgres URL
  given in `DURABLE_LEDGER_PG_URL`, and skips loudly without one.

## Murphy rows

The design assigns no Murphy row to WP6, and this note closes none. The ledger is
the money half of the engine's answer to row 9 (money exhaustion needs a human),
which WP10 targets: once the engine routes CASE exhaustion to diagnosis and
extensions draw on the batch, row 9's test runs there.
