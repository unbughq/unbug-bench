"""WP6: the money ledger, in the engine database (docs/designs/durable-execution-wp6.md).

Implements contract.Ledger exactly per its docstring. Every call runs in one
transaction that first locks the batch row, so reserves and settles of one batch are
serialized and concurrent cases can never overshoot the batch bound or a case's money.
Balances are sums over the attempt rows, never a second stored copy. Rows hold only
identifiers, enums and integers, with no timestamps, so replaying the same calls gives
an identical ledger.
"""
from __future__ import annotations

from typing import Optional

import sqlalchemy as sa

from durable.contract import (BATCH_ID, CASE_ID, ContractError, Grant, LimitedBy, Usage, _id, _nonneg_int)


class LedgerError(ValueError):
    """A call the ledger refuses. Messages are fixed text plus identifiers only."""


_META = sa.MetaData()

BATCHES = sa.Table(
    "durable_ledger_batch", _META,
    sa.Column("batch_id", sa.String(64), primary_key=True),
    sa.Column("bound_usd_micros", sa.BigInteger, nullable=False),
)

HELD, SETTLED, LOST = "held", "settled", "lost"

ATTEMPTS = sa.Table(
    "durable_ledger_attempt", _META,
    sa.Column("idempotency_key", sa.String(256), primary_key=True),
    sa.Column("batch_id", sa.String(64), sa.ForeignKey("durable_ledger_batch.batch_id"), nullable=False),
    sa.Column("case_id", sa.String(96), nullable=False),
    sa.Column("draws_case_money", sa.Boolean, nullable=False),
    sa.Column("requested_usd_micros", sa.BigInteger, nullable=False),
    sa.Column("case_limit_usd_micros", sa.BigInteger, nullable=False),
    sa.Column("granted_usd_micros", sa.BigInteger, nullable=False),
    sa.Column("limited_by", sa.String(16), nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("waste", sa.Boolean, nullable=False),
    sa.Column("calls", sa.BigInteger, nullable=False),
    sa.Column("paid_usd_micros", sa.BigInteger, nullable=False),
    sa.Column("list_usd_micros", sa.BigInteger, nullable=False),
    sa.Index("durable_ledger_attempt_case", "batch_id", "case_id"),
)


def _make_engine(url: str) -> sa.Engine:
    if sa.engine.make_url(url).get_backend_name() != "sqlite":
        return sa.create_engine(url, pool_pre_ping=True)
    engine = sa.create_engine(url, connect_args={"timeout": 60, "check_same_thread": False})

    # pysqlite's own transaction handling begins lazily, and a read that later writes can
    # fail or act on a stale read. Take the write lock up front instead (SQLAlchemy's
    # documented pysqlite recipe), so every ledger transaction is serialized.
    @sa.event.listens_for(engine, "connect")
    def _connect(dbapi_connection, _record):
        dbapi_connection.isolation_level = None

    @sa.event.listens_for(engine, "begin")
    def _begin(connection):
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def _key(value: str, case_id: Optional[str] = None) -> str:
    if not (type(value) is str and value.count("/") == 3 and len(value) <= 256):
        raise LedgerError("bad idempotency key")
    if case_id is not None and not value.startswith(case_id + "/"):
        raise LedgerError("idempotency key belongs to another case")
    return value


def _checked(fn, *args):
    try:
        return fn(*args)
    except ContractError as e:
        raise LedgerError(str(e)) from None


class SqlLedger:
    """contract.Ledger on SQLAlchemy. `url` is the engine's Postgres, or a SQLite file in tests."""

    def __init__(self, url: str):
        self._engine = _make_engine(url)
        try:
            _META.create_all(self._engine)
        except sa.exc.DBAPIError:
            _META.create_all(self._engine)   # another process created the tables first (Postgres race)

    def close(self) -> None:
        self._engine.dispose()

    def __repr__(self) -> str:
        return f"SqlLedger({self._engine.url.render_as_string(hide_password=True)!r})"

    # ---- internals ---------------------------------------------------------------------------

    @staticmethod
    def _lock_batch(conn, batch_id: str) -> int:
        bound = conn.execute(sa.select(BATCHES.c.bound_usd_micros).where(BATCHES.c.batch_id == batch_id)
                             .with_for_update()).scalar_one_or_none()
        if bound is None:
            raise LedgerError(f"batch {batch_id} is not open")
        return bound

    @staticmethod
    def _batch_sums(conn, batch_id: str) -> tuple[int, int, int]:
        """(held, spent, waste) of one batch."""
        a = ATTEMPTS.c
        held = sa.func.coalesce(sa.func.sum(sa.case((a.state == HELD, a.granted_usd_micros), else_=0)), 0)
        spent = sa.func.coalesce(sa.func.sum(sa.case((a.state == SETTLED, a.paid_usd_micros),
                                                     (a.state == LOST, a.granted_usd_micros), else_=0)), 0)
        waste = sa.func.coalesce(sa.func.sum(sa.case((sa.and_(a.state == SETTLED, a.waste), a.paid_usd_micros),
                                                     (a.state == LOST, a.granted_usd_micros), else_=0)), 0)
        row = conn.execute(sa.select(held, spent, waste).where(a.batch_id == batch_id)).one()
        return int(row[0]), int(row[1]), int(row[2])

    @staticmethod
    def _case_used(conn, batch_id: str, case_id: str) -> int:
        """The case's own money in use: holds and non-waste spend of steps that draw on it."""
        a = ATTEMPTS.c
        used = sa.func.coalesce(sa.func.sum(sa.case((a.state == HELD, a.granted_usd_micros),
                                                    (a.state == SETTLED, a.paid_usd_micros), else_=0)), 0)
        return int(conn.execute(sa.select(used).where(a.batch_id == batch_id, a.case_id == case_id,
                                                      a.draws_case_money, sa.not_(a.waste))).scalar_one())

    def _row(self, conn, key: str):
        return conn.execute(sa.select(ATTEMPTS).where(ATTEMPTS.c.idempotency_key == key)).one_or_none()

    def _attempt_batch(self, key: str) -> str:
        with self._engine.connect() as conn:
            batch_id = conn.execute(sa.select(ATTEMPTS.c.batch_id)
                                    .where(ATTEMPTS.c.idempotency_key == key)).scalar_one_or_none()
        if batch_id is None:
            raise LedgerError("no reservation for this idempotency key")
        return batch_id

    # ---- the protocol ------------------------------------------------------------------------

    def open(self, batch_id: str, bound_usd_micros: int) -> None:
        _checked(_id, batch_id, BATCH_ID, "batch_id")
        _checked(_nonneg_int, bound_usd_micros, "bound_usd_micros")
        with self._engine.begin() as conn:
            current = conn.execute(sa.select(BATCHES.c.bound_usd_micros).where(BATCHES.c.batch_id == batch_id)
                                   .with_for_update()).scalar_one_or_none()
            if current is None:
                conn.execute(BATCHES.insert().values(batch_id=batch_id, bound_usd_micros=bound_usd_micros))
            elif bound_usd_micros > current:
                conn.execute(BATCHES.update().where(BATCHES.c.batch_id == batch_id)
                             .values(bound_usd_micros=bound_usd_micros))

    def raise_bound(self, batch_id: str, bound_usd_micros: int) -> None:
        _checked(_id, batch_id, BATCH_ID, "batch_id")
        _checked(_nonneg_int, bound_usd_micros, "bound_usd_micros")
        with self._engine.begin() as conn:
            if bound_usd_micros > self._lock_batch(conn, batch_id):
                conn.execute(BATCHES.update().where(BATCHES.c.batch_id == batch_id)
                             .values(bound_usd_micros=bound_usd_micros))

    def reserve(self, batch_id: str, case_id: str, idempotency_key: str, requested_usd_micros: int,
                case_limit_usd_micros: int, *, draws_case_money: bool = True) -> Grant:
        _checked(_id, batch_id, BATCH_ID, "batch_id")
        _checked(_id, case_id, CASE_ID, "case_id")
        _key(idempotency_key, case_id)
        _checked(_nonneg_int, requested_usd_micros, "requested_usd_micros")
        _checked(_nonneg_int, case_limit_usd_micros, "case_limit_usd_micros")
        if type(draws_case_money) is not bool:
            raise LedgerError("draws_case_money must be a bool")
        with self._engine.begin() as conn:
            bound = self._lock_batch(conn, batch_id)
            row = self._row(conn, idempotency_key)
            if row is not None:
                if (row.batch_id, row.case_id, row.draws_case_money) != (batch_id, case_id, draws_case_money):
                    raise LedgerError("idempotency key reserved with other arguments")
                return Grant(int(row.granted_usd_micros), LimitedBy(row.limited_by))
            held, spent, _ = self._batch_sums(conn, batch_id)
            batch_left = max(0, bound - held - spent)
            amount = min(requested_usd_micros, batch_left)
            case_left = None
            if draws_case_money:
                case_left = max(0, case_limit_usd_micros - self._case_used(conn, batch_id, case_id))
                amount = min(amount, case_left)
            # The frozen tie rule: BATCH whenever the batch's remaining bound is at or below
            # the grant; otherwise CASE when the case's money cut the request short; otherwise
            # the whole request was granted.
            if batch_left <= amount:
                label = LimitedBy.BATCH
            elif case_left is not None and case_left < requested_usd_micros:
                label = LimitedBy.CASE
            else:
                label = LimitedBy.NOTHING
            conn.execute(ATTEMPTS.insert().values(
                idempotency_key=idempotency_key, batch_id=batch_id, case_id=case_id,
                draws_case_money=draws_case_money, requested_usd_micros=requested_usd_micros,
                case_limit_usd_micros=case_limit_usd_micros, granted_usd_micros=amount, limited_by=label.value,
                state=HELD, waste=False, calls=0, paid_usd_micros=0, list_usd_micros=0))
            return Grant(amount, label)

    def settle(self, idempotency_key: str, usage: Usage, *, waste: bool = False) -> None:
        _key(idempotency_key)
        if not isinstance(usage, Usage):
            raise LedgerError("usage must be a Usage")
        if type(waste) is not bool:
            raise LedgerError("waste must be a bool")
        self._finish(idempotency_key, SETTLED, waste, usage)

    def settle_lost(self, idempotency_key: str) -> None:
        _key(idempotency_key)
        self._finish(idempotency_key, LOST, True, Usage())

    def _finish(self, key: str, state: str, waste: bool, usage: Usage) -> None:
        batch_id = self._attempt_batch(key)
        with self._engine.begin() as conn:
            self._lock_batch(conn, batch_id)
            row = self._row(conn, key)
            wanted = (state, waste, usage.calls, usage.paid_usd_micros, usage.list_usd_micros)
            if row.state != HELD:
                if (row.state, row.waste, row.calls, row.paid_usd_micros, row.list_usd_micros) != wanted:
                    raise LedgerError("attempt already settled differently")
                return
            conn.execute(ATTEMPTS.update().where(ATTEMPTS.c.idempotency_key == key, ATTEMPTS.c.state == HELD)
                         .values(state=state, waste=waste, calls=usage.calls, paid_usd_micros=usage.paid_usd_micros,
                                 list_usd_micros=usage.list_usd_micros))

    # ---- reads -------------------------------------------------------------------------------

    def balance(self, batch_id: str) -> dict:
        """The batch's figures: bound, held, spent (waste included), waste, used and remaining."""
        _checked(_id, batch_id, BATCH_ID, "batch_id")
        with self._engine.begin() as conn:
            bound = self._lock_batch(conn, batch_id)
            held, spent, waste = self._batch_sums(conn, batch_id)
        used = held + spent
        return {"bound": bound, "held": held, "spent": spent, "waste": waste, "used": used,
                "remaining": max(0, bound - used)}

    def case_balance(self, batch_id: str, case_id: str, case_limit_usd_micros: int) -> dict:
        """The case's own money: used (holds plus non-waste spend) and remaining under the limit."""
        _checked(_id, batch_id, BATCH_ID, "batch_id")
        _checked(_id, case_id, CASE_ID, "case_id")
        _checked(_nonneg_int, case_limit_usd_micros, "case_limit_usd_micros")
        with self._engine.begin() as conn:
            self._lock_batch(conn, batch_id)
            used = self._case_used(conn, batch_id, case_id)
        return {"used": used, "remaining": max(0, case_limit_usd_micros - used)}

    def rows(self) -> dict:
        """Both tables in key order, as plain values (for replay comparison and audit)."""
        with self._engine.connect() as conn:
            return {"batches": [tuple(r) for r in conn.execute(sa.select(BATCHES).order_by(BATCHES.c.batch_id))],
                    "attempts": [tuple(r) for r in conn.execute(sa.select(ATTEMPTS)
                                                                 .order_by(ATTEMPTS.c.idempotency_key))]}
