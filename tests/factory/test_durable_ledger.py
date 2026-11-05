"""WP6: the ledger (docs/designs/durable-execution-wp6.md), on real SQLite files through real
SQLAlchemy (installed by dbos==3.4.0; the suite runs with `--with dbos==3.4.0`).

Done when (durable-execution.md, WP6 row):
- concurrent reservations, from threads and from processes, never exceed either limit;
- five INFRA_ERROR settles that spent money (waste=True), and settle_lost, lower the batch's
  remaining bound and leave the case's money unchanged;
- the three tie cases of the label rule;
- a re-reserve after raise_bound returns the original Grant;
- every call is idempotent on its key, and replaying the same calls (also after a kill -9
  partway through) gives an identical ledger.

Set DURABLE_LEDGER_PG_URL (and run with a Postgres driver, e.g. `--with psycopg[binary]`) to
also run the concurrency test on Postgres.
"""
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory")]

from durable.contract import Grant, LimitedBy, Outcome, StepResult, Usage   # noqa: E402
from durable.ledger import LedgerError, SqlLedger                          # noqa: E402
from durable.policy import settles_as_waste                                 # noqa: E402

N, C, B = LimitedBy.NOTHING, LimitedBy.CASE, LimitedBy.BATCH
BATCH = "b-ledger-test"
M = 1_000_000   # one dollar in micros


def key(case, seq, attempt=1, step="writer:1"):
    return f"{case}/{seq}/{step}/{attempt}"


class Db:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.url = f"sqlite:///{self.tmp.name}/engine.sqlite"
        self.ledger = SqlLedger(self.url)

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()


# ---- concurrency ---------------------------------------------------------------------------

CASES = [f"case-c{i}" for i in range(5)]
BOUND, CASE_LIMIT = 1_000, 300   # micros: five cases' money (1500) exceeds the bound


def check_limits(test, grants, bound=BOUND, case_limit=CASE_LIMIT):
    """grants: (case_id, draws_case_money, Grant) of attempts that are all still held."""
    test.assertLessEqual(sum(g.amount_usd_micros for _, _, g in grants), bound)
    for case in {c for c, _, _ in grants}:
        test.assertLessEqual(sum(g.amount_usd_micros for c, d, g in grants if c == case and d), case_limit)
    # The test must have created real contention: the bound was used up, and a request was cut.
    test.assertEqual(sum(g.amount_usd_micros for _, _, g in grants), bound)
    test.assertTrue(any(g.limited_by is B for _, _, g in grants))


def hammer(ledger, worker, n, seed, out, barrier=None):
    rng = random.Random(seed)
    if barrier is not None:
        barrier.wait()
    for i in range(n):
        case = rng.choice(CASES)
        draws = rng.random() < 0.8
        g = ledger.reserve(BATCH, case, key(case, 1000 * worker + i + 1), rng.randint(1, 120), CASE_LIMIT,
                           draws_case_money=draws)
        out.append((case, draws, g))


PROC = textwrap.dedent('''
    import json, random, sys, time, pathlib
    sys.path.insert(0, sys.argv[1])
    from durable.ledger import SqlLedger
    url, worker, n, seed, go, mode = sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), sys.argv[6], sys.argv[7]
    ledger = SqlLedger(url)
    cases = [f"case-c{i}" for i in range(5)]
    rng = random.Random(seed)
    while not pathlib.Path(go).exists():
        time.sleep(0.001)
    out = []
    for i in range(n):
        if mode == "same":       # every process reserves the same keys
            case = cases[i % 5]; k = f"{case}/{i + 1}/writer:1/1"; draws = True; req = 40
        else:
            case = rng.choice(cases); k = f"{case}/{1000 * worker + i + 1}/writer:1/1"
            draws = rng.random() < 0.8; req = rng.randint(1, 120)
        g = ledger.reserve("b-ledger-test", case, k, req, 300, draws_case_money=draws)
        out.append([case, draws, g.amount_usd_micros, g.limited_by.value, k])
    print(json.dumps(out))
''')


def run_processes(url, mode, workers=4, n=60):
    with tempfile.TemporaryDirectory() as tmp:
        go = Path(tmp) / "go"
        procs = [subprocess.Popen([sys.executable, "-B", "-c", PROC, str(ROOT / "factory"), url, str(w), str(n),
                                   str(100 + w), str(go), mode], stdout=subprocess.PIPE, text=True)
                 for w in range(workers)]
        time.sleep(1.0)   # let every process import and connect, then release them together
        go.touch()
        outs = [p.communicate(timeout=300) for p in procs]
        for p in procs:
            assert p.returncode == 0, p.returncode
    return [json.loads(o) for o, _ in outs]


class Concurrency(Db, unittest.TestCase):
    def test_concurrent_first_open_keeps_largest_bound(self):
        from concurrent.futures import ThreadPoolExecutor
        gate = threading.Barrier(8)
        def first_open(bound):
            ledger = SqlLedger(self.url)
            try:
                gate.wait(timeout=30)
                ledger.open("b-concurrent-first", bound)
            finally:
                ledger.close()
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(first_open, range(1, 9)))
        self.assertEqual(self.ledger.balance("b-concurrent-first")["bound"], 8)

    def test_threads_never_exceed_either_limit(self):
        self.ledger.open(BATCH, BOUND)
        grants, threads = [], []
        barrier = threading.Barrier(8)
        for w in range(8):
            threads.append(threading.Thread(target=hammer, args=(self.ledger, w, 40, w, grants, barrier)))
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(len(grants), 320)
        check_limits(self, grants)
        self.assertEqual(self.ledger.balance(BATCH)["remaining"], 0)

    def test_processes_never_exceed_either_limit(self):
        self.ledger.open(BATCH, BOUND)
        outs = run_processes(self.url, "random")
        grants = [(c, d, Grant(a, l)) for out in outs for c, d, a, l, _ in out]
        self.assertEqual(len(grants), 240)
        check_limits(self, grants)
        self.assertEqual(len(self.ledger.rows()["attempts"]), 240)

    def test_processes_reserving_the_same_keys_get_one_grant_each(self):
        self.ledger.open(BATCH, BOUND)
        outs = run_processes(self.url, "same", n=30)
        for out in outs[1:]:
            self.assertEqual(out, outs[0])    # every process saw the same Grant for every key
        self.assertEqual(len(self.ledger.rows()["attempts"]), 30)
        self.assertEqual(sum(a for _, _, a, _, _ in outs[0]), self.ledger.balance(BATCH)["held"])

    def test_mixed_reserves_and_settles_keep_the_books(self):
        """Threads reserve and settle (ordinary, waste and lost). The ledger's balances equal the
        test's own bookkeeping, and neither limit is exceeded at the end."""
        self.ledger.open(BATCH, BOUND)
        book, lock = [], threading.Lock()

        def work(w):
            rng = random.Random(50 + w)
            for i in range(40):
                case = rng.choice(CASES); draws = rng.random() < 0.8; k = key(case, 1000 * w + i + 1)
                g = self.ledger.reserve(BATCH, case, k, rng.randint(1, 120), CASE_LIMIT, draws_case_money=draws)
                r = rng.random()
                if r < 0.3:
                    paid = rng.randint(0, g.amount_usd_micros); waste = rng.random() < 0.5
                    self.ledger.settle(k, Usage(1, paid, paid), waste=waste); end = ("settled", paid, waste)
                elif r < 0.4:
                    self.ledger.settle_lost(k); end = ("lost", g.amount_usd_micros, True)
                else:
                    end = ("held", g.amount_usd_micros, False)
                with lock:
                    book.append((case, draws, g, end))

        threads = [threading.Thread(target=work, args=(w,)) for w in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        used = sum(e[1] for *_, e in book)
        self.assertLessEqual(used, BOUND)
        bal = self.ledger.balance(BATCH)
        self.assertEqual(bal["used"], used)
        self.assertEqual(bal["waste"], sum(e[1] for *_, e in book if e[2]))
        for case in CASES:
            mine = sum(e[1] for c, d, _, e in book if c == case and d and not e[2])
            self.assertLessEqual(mine, CASE_LIMIT)
            self.assertEqual(self.ledger.case_balance(BATCH, case, CASE_LIMIT)["used"], mine)


@unittest.skipUnless(os.environ.get("DURABLE_LEDGER_PG_URL"), "DURABLE_LEDGER_PG_URL unset: Postgres run skipped")
class PostgresConcurrency(unittest.TestCase):
    def test_threads_and_processes_on_postgres(self):
        url = os.environ["DURABLE_LEDGER_PG_URL"]
        ledger = SqlLedger(url)
        import sqlalchemy as sa
        with ledger._engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM durable_ledger_attempt WHERE batch_id = :b"), {"b": BATCH})
            conn.execute(sa.text("DELETE FROM durable_ledger_batch WHERE batch_id = :b"), {"b": BATCH})
        ledger.open(BATCH, BOUND)
        grants, threads = [], []
        barrier = threading.Barrier(8)
        for w in range(8):
            threads.append(threading.Thread(target=hammer, args=(ledger, w, 20, w, grants, barrier)))
        for t in threads: t.start()
        for t in threads: t.join()
        # Raise the bound so the processes compete for a fresh 1000 on the same batch.
        ledger.raise_bound(BATCH, 2 * BOUND)
        # The process phase is independent contention, not a replay with changed
        # random arguments under the thread phase's existing idempotency keys.
        with ledger._engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM durable_ledger_attempt WHERE batch_id = :b"), {"b": BATCH})
        outs = run_processes(url, "random", n=40)
        grants += [(c, d, Grant(a, l)) for out in outs for c, d, a, l, _ in out]
        check_limits(self, grants, bound=2 * BOUND, case_limit=CASE_LIMIT)
        ledger.close()


# ---- waste -----------------------------------------------------------------------------------

class Waste(Db, unittest.TestCase):
    CASE = "case-waste"

    def test_five_spent_infra_errors_leave_the_case_money_unchanged(self):
        self.ledger.open(BATCH, 100 * M)
        for attempt in range(1, 6):
            k = key(self.CASE, 3, attempt, "writer:2")
            g = self.ledger.reserve(BATCH, self.CASE, k, 50 * M, 50 * M)
            self.assertEqual(g, Grant(50 * M, N))
            result = StepResult(Outcome.INFRA_ERROR, "infra:stalled", Usage(4, 3 * M, 5 * M))
            self.assertTrue(settles_as_waste(result))
            self.ledger.settle(k, result.usage, waste=settles_as_waste(result))
            self.assertEqual(self.ledger.case_balance(BATCH, self.CASE, 50 * M), {"used": 0, "remaining": 50 * M})
        bal = self.ledger.balance(BATCH)
        self.assertEqual((bal["spent"], bal["waste"], bal["held"], bal["remaining"]), (15 * M, 15 * M, 0, 85 * M))
        # The sixth attempt still gets the case's whole money.
        self.assertEqual(self.ledger.reserve(BATCH, self.CASE, key(self.CASE, 3, 6, "writer:2"), 50 * M, 50 * M),
                         Grant(50 * M, N))

    def test_spent_provider_limit_is_waste_too(self):
        self.ledger.open(BATCH, 100 * M)
        k = key(self.CASE, 1)
        self.ledger.reserve(BATCH, self.CASE, k, 50 * M, 50 * M)
        result = StepResult(Outcome.PROVIDER_LIMIT, "router:claude_limit", Usage(2, 2 * M, 2 * M), retry_at=1e9)
        self.ledger.settle(k, result.usage, waste=settles_as_waste(result))
        self.assertEqual(self.ledger.case_balance(BATCH, self.CASE, 50 * M)["remaining"], 50 * M)
        self.assertEqual(self.ledger.balance(BATCH)["remaining"], 98 * M)

    def test_settle_lost_books_the_whole_grant_as_waste(self):
        self.ledger.open(BATCH, 100 * M)
        k = key(self.CASE, 1)
        self.assertEqual(self.ledger.reserve(BATCH, self.CASE, k, 50 * M, 50 * M), Grant(50 * M, N))
        self.ledger.settle_lost(k)
        self.assertEqual(self.ledger.case_balance(BATCH, self.CASE, 50 * M), {"used": 0, "remaining": 50 * M})
        bal = self.ledger.balance(BATCH)
        self.assertEqual((bal["spent"], bal["waste"], bal["held"], bal["remaining"]), (50 * M, 50 * M, 0, 50 * M))

    def test_ordinary_settle_spends_case_money_and_frees_the_rest(self):
        self.ledger.open(BATCH, 100 * M)
        k = key(self.CASE, 1)
        self.ledger.reserve(BATCH, self.CASE, k, 50 * M, 50 * M)
        self.assertEqual(self.ledger.balance(BATCH)["remaining"], 50 * M)   # held while the attempt runs
        self.ledger.settle(k, Usage(9, 3 * M, 4 * M))
        self.assertEqual(self.ledger.case_balance(BATCH, self.CASE, 50 * M)["remaining"], 47 * M)
        bal = self.ledger.balance(BATCH)
        self.assertEqual((bal["spent"], bal["waste"], bal["held"], bal["remaining"]), (3 * M, 0, 0, 97 * M))

    def test_batch_only_steps_never_touch_case_money(self):
        self.ledger.open(BATCH, 100 * M)
        k = key(self.CASE, 1)
        self.ledger.reserve(BATCH, self.CASE, k, 50 * M, 50 * M)
        self.ledger.settle(k, Usage(1, 50 * M, 50 * M))                       # the case's money is spent
        self.assertEqual(self.ledger.reserve(BATCH, self.CASE, key(self.CASE, 2), 50 * M, 50 * M), Grant(0, C))
        d = key(self.CASE, 3, step="diagnosis")
        self.assertEqual(self.ledger.reserve(BATCH, self.CASE, d, 20 * M, 50 * M, draws_case_money=False),
                         Grant(20 * M, N))
        self.ledger.settle(d, Usage(1, 20 * M, 20 * M))
        self.assertEqual(self.ledger.case_balance(BATCH, self.CASE, 50 * M)["used"], 50 * M)
        self.assertEqual(self.ledger.balance(BATCH)["remaining"], 30 * M)


# ---- labels ------------------------------------------------------------------------------------

class Labels(Db, unittest.TestCase):
    def test_tie_request_equals_batch_remaining_is_batch(self):
        self.ledger.open(BATCH, 30)
        self.assertEqual(self.ledger.reserve(BATCH, "case-a", key("case-a", 1), 30, 50), Grant(30, B))

    def test_tie_case_money_equals_batch_remaining_is_batch(self):
        self.ledger.open(BATCH, 100)
        self.ledger.reserve(BATCH, "case-other", key("case-other", 1), 70, 70)   # leaves 30 of the bound
        self.assertEqual(self.ledger.reserve(BATCH, "case-a", key("case-a", 1), 50, 30), Grant(30, B))

    def test_tie_request_equals_case_money_is_nothing(self):
        self.ledger.open(BATCH, 80)
        self.assertEqual(self.ledger.reserve(BATCH, "case-a", key("case-a", 1), 50, 50), Grant(50, N))

    def test_plain_labels(self):
        self.ledger.open(BATCH, 100)
        a = "case-a"
        self.ledger.reserve(BATCH, a, key(a, 1), 20, 50)
        self.ledger.settle(key(a, 1), Usage(1, 20, 20))
        self.assertEqual(self.ledger.reserve(BATCH, a, key(a, 2), 50, 50), Grant(30, C))     # case money cut it
        self.assertEqual(self.ledger.reserve(BATCH, "case-b", key("case-b", 1), 5, 50), Grant(5, N))
        self.assertEqual(self.ledger.reserve(BATCH, "case-c", key("case-c", 1), 50, 50), Grant(45, B))
        self.assertEqual(self.ledger.reserve(BATCH, "case-d", key("case-d", 1), 50, 50), Grant(0, B))
        # A request equal to all three figures is BATCH: the batch rule comes first.
        self.ledger.raise_bound(BATCH, 130)
        self.assertEqual(self.ledger.reserve(BATCH, "case-e", key("case-e", 1), 30, 30), Grant(30, B))

    def test_batch_only_step_ignores_case_money_for_the_label(self):
        self.ledger.open(BATCH, 100)
        g = self.ledger.reserve(BATCH, "case-a", key("case-a", 1, step="diagnosis"), 60, 10, draws_case_money=False)
        self.assertEqual(g, Grant(60, N))


# ---- raise_bound and idempotency -------------------------------------------------------------

class Idempotency(Db, unittest.TestCase):
    def test_re_reserve_after_raise_bound_returns_the_original_grant(self):
        self.ledger.open(BATCH, 10 * M)
        k = key("case-a", 4, step="stress:2")
        self.assertEqual(self.ledger.reserve(BATCH, "case-a", k, 50 * M, 50 * M), Grant(10 * M, B))
        self.ledger.raise_bound(BATCH, 200 * M)
        self.assertEqual(self.ledger.reserve(BATCH, "case-a", k, 50 * M, 50 * M), Grant(10 * M, B))
        # Even with another request figure (a batch-only step requests the moving remaining bound).
        self.assertEqual(self.ledger.reserve(BATCH, "case-a", k, 190 * M, 50 * M), Grant(10 * M, B))
        self.assertEqual(self.ledger.reserve(BATCH, "case-a", key("case-a", 4, 2, "stress:2"), 50 * M, 50 * M),
                         Grant(40 * M, C))
        self.ledger.settle(k, Usage(1, 10 * M, 10 * M))
        self.assertEqual(self.ledger.reserve(BATCH, "case-a", k, 50 * M, 50 * M), Grant(10 * M, B))
        self.assertEqual(self.ledger.balance(BATCH)["used"], 50 * M)

    def test_every_call_is_idempotent(self):
        self.ledger.open(BATCH, 100)
        self.ledger.open(BATCH, 100)
        self.ledger.raise_bound(BATCH, 150)
        self.ledger.raise_bound(BATCH, 150)
        self.ledger.open(BATCH, 100)            # a replayed open never undoes a raise
        self.ledger.raise_bound(BATCH, 120)     # nor does a lower figure
        self.assertEqual(self.ledger.balance(BATCH)["bound"], 150)
        k = key("case-a", 1)
        g = self.ledger.reserve(BATCH, "case-a", k, 40, 50)
        self.assertEqual(self.ledger.reserve(BATCH, "case-a", k, 40, 50), g)
        self.ledger.settle(k, Usage(2, 7, 9), waste=True)
        self.ledger.settle(k, Usage(2, 7, 9), waste=True)
        k2 = key("case-a", 2)
        self.ledger.reserve(BATCH, "case-a", k2, 40, 50)
        self.ledger.settle_lost(k2)
        self.ledger.settle_lost(k2)
        self.assertEqual(self.ledger.balance(BATCH)["used"], 47)

    def test_contradicting_repeats_and_unknown_keys_raise(self):
        self.ledger.open(BATCH, 100)
        self.ledger.open("b-other", 100)
        k = key("case-a", 1)
        self.ledger.reserve(BATCH, "case-a", k, 40, 50)
        for bad in (lambda: self.ledger.reserve("b-other", "case-a", k, 40, 50),
                    lambda: self.ledger.reserve(BATCH, "case-a", k, 40, 50, draws_case_money=False),
                    lambda: self.ledger.reserve(BATCH, "case-b", k, 40, 50),       # key names another case
                    lambda: self.ledger.reserve("b-unopened", "case-a", key("case-a", 9), 1, 1),
                    lambda: self.ledger.reserve(BATCH, "case-a", "not-a-key", 1, 1),
                    lambda: self.ledger.reserve(BATCH, "case-a", key("case-a", 9), -1, 1),
                    lambda: self.ledger.raise_bound("b-unopened", 5),
                    lambda: self.ledger.settle(key("case-a", 9), Usage()),
                    lambda: self.ledger.settle_lost(key("case-a", 9))):
            with self.assertRaises(LedgerError):
                bad()
        self.ledger.settle(k, Usage(1, 5, 5))
        for bad in (lambda: self.ledger.settle(k, Usage(1, 6, 6)),
                    lambda: self.ledger.settle(k, Usage(1, 5, 5), waste=True),
                    lambda: self.ledger.settle_lost(k)):
            with self.assertRaises(LedgerError):
                bad()
        k2 = key("case-a", 2)
        self.ledger.reserve(BATCH, "case-a", k2, 10, 50)
        self.ledger.settle_lost(k2)
        with self.assertRaises(LedgerError):
            self.ledger.settle(k2, Usage())
        self.assertEqual(self.ledger.balance(BATCH)["used"], 15)


# ---- replay ------------------------------------------------------------------------------------

SCRIPT = [
    ("open", BATCH, 60),
    ("reserve", BATCH, "case-a", "case-a/1/admit/1", 50, 50, True),
    ("settle", "case-a/1/admit/1", (3, 40, 46), False),
    ("reserve", BATCH, "case-b", "case-b/1/admit/1", 50, 50, True),        # batch-limited: 20 left
    ("reserve", BATCH, "case-a", "case-a/2/writer:1/1", 50, 50, True),     # 0 left
    ("settle", "case-a/2/writer:1/1", (5, 0, 0), True),                   # infra error that spent nothing
    ("raise_bound", BATCH, 200),
    ("reserve", BATCH, "case-a", "case-a/2/writer:1/2", 50, 50, True),
    ("settle_lost", "case-b/1/admit/1"),
    ("reserve", BATCH, "case-b", "case-b/1/admit/2", 50, 50, True),
    ("settle", "case-a/2/writer:1/2", (12, 8, 9), True),                   # a spent infra error: waste
    ("reserve", BATCH, "case-a", "case-a/2/writer:1/3", 50, 50, True),
    ("settle", "case-a/2/writer:1/3", (8, 10, 12), False),
    ("reserve", BATCH, "case-a", "case-a/3/diagnosis/1", 80, 50, False),
    ("settle", "case-a/3/diagnosis/1", (2, 6, 6), False),
    ("settle", "case-b/1/admit/2", (1, 1, 1), False),
]


def apply(ledger, call):
    op, *args = call
    if op == "reserve":
        b, c, k, req, lim, draws = args
        return ledger.reserve(b, c, k, req, lim, draws_case_money=draws)
    if op == "settle":
        k, (calls, paid, lst), waste = args
        return ledger.settle(k, Usage(calls, paid, lst), waste=waste)
    return getattr(ledger, op)(*args)


REPLAY = textwrap.dedent('''
    import json, os, sys
    sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
    from durable.ledger import SqlLedger
    import test_durable_ledger as t
    ledger = SqlLedger(sys.argv[3]); stop = int(sys.argv[4])
    for i, call in enumerate(t.SCRIPT):
        if i == stop:
            os._exit(9)       # killed between two calls, after the previous one committed
        t.apply(ledger, call)
''')


class Replay(unittest.TestCase):
    def ledger(self, tmp, name):
        return SqlLedger(f"sqlite:///{tmp}/{name}.sqlite")

    def test_replaying_the_same_calls_gives_an_identical_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            once, twice = self.ledger(tmp, "once"), self.ledger(tmp, "twice")
            grants = [apply(once, c) for c in SCRIPT]
            again = []
            for c in SCRIPT:
                first = apply(twice, c)
                self.assertEqual(apply(twice, c), first)
                again.append(first)
            self.assertEqual(again, grants)
            self.assertEqual([apply(twice, c) for c in SCRIPT], grants)    # the whole case replayed
            self.assertEqual(twice.rows(), once.rows())
            self.assertEqual(twice.balance(BATCH), once.balance(BATCH))
            # The script exercised what it claims: a batch-limited grant replayed after the raise.
            self.assertEqual([grants[i] for i in (3, 4, 7, 9, 11, 13)],
                             [Grant(20, B), Grant(0, B), Grant(10, C), Grant(50, N), Grant(10, C), Grant(72, B)])
            self.assertEqual(once.balance(BATCH), {"bound": 200, "held": 0, "spent": 85, "waste": 28,
                                                   "used": 85, "remaining": 115})
            once.close(); twice.close()

    def test_kill_partway_then_replay_gives_an_identical_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            clean = self.ledger(tmp, "clean")
            for c in SCRIPT:
                apply(clean, c)
            for stop in (1, 4, 7, 9, 13, len(SCRIPT) - 1):
                url = f"sqlite:///{tmp}/killed-{stop}.sqlite"
                p = subprocess.run([sys.executable, "-B", "-c", REPLAY, str(ROOT / "factory"),
                                    str(Path(__file__).parent), url, str(stop)])
                self.assertEqual(p.returncode, 9)
                replayed = SqlLedger(url)
                for c in SCRIPT:
                    apply(replayed, c)
                self.assertEqual(replayed.rows(), clean.rows(), stop)
                replayed.close()
            clean.close()


if __name__ == "__main__":
    unittest.main()
