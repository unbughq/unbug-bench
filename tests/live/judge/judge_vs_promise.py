#!/usr/bin/env python3
"""Test the ruler: compare check.sql's oversell verdict with a plain reading of the
promise in CONTESTANT.md, on thousands of random small shop states.

Starts its own throwaway Postgres (same image as the bench, no published port, unique
name), loads only the 9 tables check.sql reads, then for each random state: writes the
rows, runs check.sql unchanged as bench_checker, and compares with reference() below.
Never touches the bench's own Docker stack. Standard library only.

Usage: python3 tests/live/judge/judge_vs_promise.py [states=5000] [seed=20261014]
Exit code 0 = no disagreements, 1 = disagreements (minimal examples printed), 2 = harness error.
"""
import collections, copy, json, os, pathlib, random, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[3]
CHECK_SQL = (ROOT / "cases/medusa-oversell/checker/check.sql").read_text()
IDS = json.loads((ROOT / "projects/medusa/seed-ids.json").read_text())
for key in ("inventory_x", "product_x", "variant_single", "variant_pack"):  # same substitution as bench.py checker()
    CHECK_SQL = CHECK_SQL.replace("{{" + key + "}}", "'" + IDS[key].replace("'", "''") + "'")
IMAGE = "postgres:17.11-bookworm"  # projects/medusa/compose.yaml
CONTAINER = f"unbug-judge-test-{os.getpid()}"

# Seed shape (bench.py STOCK + BO, plus Y: a product outside the 7 kits, judged through the
# catalog's own links since 2026-10-14). kit: (stock, allow_backorder, has 2-pack)
KITS = {"x": (10, False, True), "s": (10, False, True), "z": (16, False, True), "bo": (4, True, False),
        "d": (10, False, True), "e": (10, False, True), "r": (10, False, True), "y": (8, False, True)}
JUDGED = ("x", "s", "z", "bo", "d", "e", "r")  # kits with per-kit facts in check.sql
PER_KIT_FIELD = {"x": "concurrent_oversold", "s": "sequential_oversold", "d": "draft_oversold",
                 "e": "edit_oversold", "r": "resold_oversold"}  # z and bo only appear in `oversold`
item = lambda k: f"iitem_bench_{k}"
single = lambda k: f"variant_bench_{k}_single"
pack = lambda k: f"variant_bench_{k}_2pack"
LOC, LOC2 = "sloc_bench", "sloc_two"

# Catalog rows as seeded; the random states never change them (kit tampering only
# invalidates a run, see README). The reference reads these rows, not KITS.
VARIANTS = []   # (variant_id, product_id, allow_backorder)
LINKS = []      # (variant_id, inventory_item_id, required_quantity)
for k, (stock, bo, has_pack) in KITS.items():
    VARIANTS.append((single(k), f"prod_bench_{k}", bo)); LINKS.append((single(k), item(k), 1))
    if has_pack:
        VARIANTS.append((pack(k), f"prod_bench_{k}", bo)); LINKS.append((pack(k), item(k), 2))

# ---------------------------------------------------------------- reference rule
def reference(state):
    """The promise, read plainly. Per inventory item: units owed on live orders must not
    exceed the stock that exists, unless the item allows backorders.
    live order  = not soft-deleted, not canceled, not a draft (is_draft_order or status draft)
    owed units  = for each line on the order's current version: max(0, ordered - fulfilled)
                  x the variant's kit factor (required_quantity) for that item
    stock       = sum of stocked_quantity over live inventory levels of the item (all locations)
    Reservations are deliberately ignored: they neither add nor free promised units."""
    factor = {v: (i, q) for v, i, q in LINKS}
    backorder = collections.defaultdict(bool)
    for v, _, bo in VARIANTS:
        backorder[factor[v][0]] |= bo
    owed, stocked = collections.Counter(), collections.Counter()
    for o in state["orders"]:
        if o["deleted"] or o["status"] in ("canceled", "draft") or o["draft"]:
            continue
        for line in o["lines"]:
            if line["deleted"] or line["variant"] not in factor:
                continue
            inv, q = factor[line["variant"]]
            for version, ordered, fulfilled, deleted in line["rows"]:
                if version == o["version"] and not deleted:
                    owed[inv] += max(0, ordered - fulfilled) * q
    for k, levels in levels_of(state).items():
        stocked[item(k)] += sum(s for _, s, _, deleted in levels if not deleted)
    return {k: {"owed": owed[item(k)], "stocked": stocked[item(k)],
                "oversold": not backorder[item(k)] and owed[item(k)] > stocked[item(k)]} for k in KITS}

def levels_of(state):
    """Inventory levels per kit: (location, stocked, reserved, deleted). Unlisted kits keep the seed level."""
    return {k: state["levels"].get(k, [(LOC, KITS[k][0], 0, False)]) for k in KITS}

# ---------------------------------------------------------------- SQL
SCHEMA = """
CREATE TYPE public.order_status_enum AS ENUM ('pending','completed','draft','archived','canceled','requires_action');
CREATE TABLE public."order" (id text PRIMARY KEY, version integer NOT NULL DEFAULT 1,
  status public.order_status_enum NOT NULL DEFAULT 'pending', is_draft_order boolean NOT NULL DEFAULT false,
  email text, deleted_at timestamptz);
CREATE TABLE public.order_line_item (id text PRIMARY KEY, variant_id text, variant_sku text, deleted_at timestamptz);
CREATE TABLE public.order_item (id text PRIMARY KEY,
  order_id text NOT NULL REFERENCES public."order"(id) ON UPDATE CASCADE ON DELETE CASCADE, version integer NOT NULL,
  item_id text NOT NULL REFERENCES public.order_line_item(id) ON UPDATE CASCADE ON DELETE CASCADE,
  quantity numeric NOT NULL, fulfilled_quantity numeric NOT NULL, deleted_at timestamptz);
CREATE TABLE public.product (id text PRIMARY KEY, deleted_at timestamptz);
CREATE TABLE public.product_variant (id text PRIMARY KEY, product_id text, manage_inventory boolean NOT NULL DEFAULT true,
  allow_backorder boolean NOT NULL DEFAULT false, deleted_at timestamptz);
CREATE TABLE public.inventory_item (id text PRIMARY KEY, deleted_at timestamptz);
CREATE TABLE public.inventory_level (id text PRIMARY KEY, inventory_item_id text NOT NULL, location_id text NOT NULL,
  stocked_quantity numeric NOT NULL DEFAULT 0, reserved_quantity numeric NOT NULL DEFAULT 0, deleted_at timestamptz);
CREATE TABLE public.reservation_item (id text PRIMARY KEY, line_item_id text, location_id text NOT NULL,
  quantity numeric NOT NULL, inventory_item_id text NOT NULL, deleted_at timestamptz);
CREATE TABLE public.product_variant_inventory_item (id text NOT NULL, variant_id text NOT NULL, inventory_item_id text NOT NULL,
  required_quantity integer NOT NULL DEFAULT 1, deleted_at timestamptz, PRIMARY KEY (id, variant_id, inventory_item_id));
-- bench.py setup(): the checker role
CREATE ROLE bench_checker LOGIN BYPASSRLS; ALTER ROLE bench_checker SET default_transaction_read_only = on;
GRANT USAGE ON SCHEMA public TO bench_checker; GRANT SELECT ON ALL TABLES IN SCHEMA public TO bench_checker;
"""

def lit(v):
    return "NULL" if v is None else "true" if v is True else "false" if v is False else str(v) if isinstance(v, int) else "'" + str(v).replace("'", "''") + "'"

def insert(table, rows):
    return f"INSERT INTO public.{table} VALUES " + ",".join("(" + ",".join(map(lit, r)) + ")" for r in rows) + ";\n" if rows else ""

def catalog_sql():
    return (insert("product", [(f"prod_bench_{k}", None) for k in KITS])
            + insert("inventory_item", [(item(k), None) for k in KITS])
            + insert("product_variant", [(v, p, True, bo, None) for v, p, bo in VARIANTS])
            + insert("product_variant_inventory_item", [(f"pvitem_{n}", v, i, q, None) for n, (v, i, q) in enumerate(LINKS)]))

def state_sql(state):
    dead = lambda d: "2026-01-01" if d else None
    levels = [(f"ilev_{k}_{n}", item(k), loc, s, r, dead(d))
              for k, ls in levels_of(state).items() for n, (loc, s, r, d) in enumerate(ls)]
    orders, lines, items, res = [], [], [], []
    for n, o in enumerate(state["orders"]):
        oid = f"order_{n}"
        orders.append((oid, o["version"], o["status"], o["draft"], f"o{n}@bench.test", dead(o["deleted"])))
        for m, line in enumerate(o["lines"]):
            lid = f"ordli_{n}_{m}"
            lines.append((lid, line["variant"], None, dead(line["deleted"])))
            items += [(f"orditem_{n}_{m}_{j}", oid, v, lid, q, f, dead(d)) for j, (v, q, f, d) in enumerate(line["rows"])]
            inv = next((i for v, i, _ in LINKS if v == line["variant"]), None)
            res += [(f"resitem_{n}_{m}_{j}", lid, LOC, q, inv, dead(d)) for j, (q, d) in enumerate(line["res"]) if inv]
    res += [(f"resitem_manual_{j}", None, LOC, q, item(k), dead(d)) for j, (k, q, d) in enumerate(state["manual_res"])]
    return ('TRUNCATE public."order", public.order_item, public.order_line_item, public.reservation_item, public.inventory_level;\n'
            + insert("inventory_level", levels) + insert('"order"', orders) + insert("order_line_item", lines)
            + insert("order_item", items) + insert("reservation_item", res))

def psql(sql):
    p = subprocess.run(["docker", "exec", "-i", "-e", "PGPASSWORD=medusa", CONTAINER, "psql", "-h", "127.0.0.1", "-Xq",
                        "-v", "ON_ERROR_STOP=1", "-At", "-U", "medusa", "-d", "medusa"], input=sql, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(f"psql failed ({p.returncode}): {p.stderr.strip()[-2000:]}")
    return p.stdout

def judge(states):
    """Run check.sql, unchanged, as bench_checker once per state; one JSON line per state."""
    out = psql("".join(state_sql(s) + "SET ROLE bench_checker;\n" + CHECK_SQL + "\nRESET ROLE;\n" for s in states)).splitlines()
    if len(out) != len(states):
        raise RuntimeError(f"expected {len(states)} checker rows, got {len(out)}: {out[:3]}")
    return [json.loads(line) for line in out]

# ---------------------------------------------------------------- comparison
def overreserved(state):
    """Warning, not part of the promise: reserved_quantity above stock on a non-backorder item."""
    return any(not KITS[k][1] and sum(r - s for _, s, r, d in ls if not d) > 0 for k, ls in levels_of(state).items())

def compare(state, j):
    """Fields compared: kits[k].sold vs owed, kits[k].stocked vs stock (k in x s z bo d e r),
    the per-path *_oversold fields (x s d e r), the overall `oversold` (every product, Y
    included), `oversold_other_items` and the `overreserved` warning.
    Returns a sorted tuple of disagreement kinds (empty = agreement)."""
    ref, kinds = reference(state), set()
    for k in JUDGED:
        if float(j["kits"][k]["sold"]) != ref[k]["owed"]: kinds.add("sold differs")
        if float(j["kits"][k]["stocked"]) != ref[k]["stocked"]: kinds.add("stocked differs")
    verdicts = [(j[f], ref[k]["oversold"]) for k, f in PER_KIT_FIELD.items()]
    verdicts.append((j["oversold"], any(ref[k]["oversold"] for k in KITS)))
    for jv, rv in verdicts:
        if jv and not rv: kinds.add("judge says oversold, promise does not")
        if rv and not jv: kinds.add("promise says oversold, judge does not")
    if j["oversold_other_items"] != ([item("y")] if ref["y"]["oversold"] else []): kinds.add("oversold_other_items differs")
    if j["overreserved"] != overreserved(state): kinds.add("overreserved warning differs")
    return tuple(sorted(kinds))

# ---------------------------------------------------------------- random states
STATUS = [("pending", False, 50), ("completed", False, 8), ("archived", False, 4), ("requires_action", False, 4),
          ("canceled", False, 14), ("draft", True, 12), ("pending", True, 1.5), ("draft", False, 1.5)]
CONVERTED_DRAFT = 5  # weight of a converted draft: status pending, is_draft_order false (same rows as a store order)

def gen_state(rng):
    kits = rng.sample(list(KITS), rng.randint(1, 3))
    state = {"levels": {}, "orders": [], "manual_res": []}
    for k in kits:
        stock = KITS[k][0] if rng.random() < .6 else rng.randint(0, 12)
        shape = rng.random()
        if shape < .8: levels = [[LOC, stock, 0, False]]
        elif shape < .95: a = rng.randint(0, stock); levels = [[LOC, a, 0, False], [LOC2, stock - a, 0, False]]
        else: levels = [[LOC, stock, 0, False], [LOC2, rng.randint(1, 6), 0, True]]  # soft-deleted level
        state["levels"][k] = levels
    for _ in range(rng.randint(0, 5)):
        status, draft, _ = rng.choices(STATUS + [("pending", False, 0)], [w for *_, w in STATUS] + [CONVERTED_DRAFT])[0]
        version = rng.choice([1, 1, 1, 2, 3])
        o = {"status": status, "draft": draft, "deleted": rng.random() < .08, "version": version, "lines": []}
        live = not (o["deleted"] or status in ("canceled", "draft") or draft)
        for _ in range(rng.randint(1, 3)):
            k = rng.choice(kits)
            r = rng.random()
            variant = single("y") if r < .1 else pack(k) if KITS[k][2] and r < .45 else single(k)
            start = rng.choice([1] * 3 + list(range(1, version + 1)))  # lines added by a later edit start later
            rows, qty = [], rng.randint(1, 5)
            for v in range(start, version + 1):
                qty = max(0, qty + rng.choice([0, 0, 0, -1, 1, 2])) if v > start else qty
                f = rng.randint(0, qty) if rng.random() < .15 else 0
                if rng.random() < .02: f = qty + 1  # impossible in Medusa: fulfilled > ordered
                rows.append([v, qty, f, rng.random() < .04])
            if rng.random() < .15:  # rows of an unconfirmed or refused edit at version + 1
                rows.append([version + 1, qty + rng.randint(1, 4), 0, rng.random() < .7])
            factor = 2 if variant and variant.endswith("2pack") else 1
            owed = max(0, rows[-1][1] - rows[-1][2]) * factor
            r = rng.random()
            if live: res = ([[owed, False]] if r < .6 else [] if r < .75 else [[owed, True]] if r < .9
                            else [[owed // 2, False], [owed - owed // 2, False]])
            else: res = [[owed, False]] if r < .1 else []  # stale reservation left on a canceled/draft order
            o["lines"].append({"variant": variant, "deleted": rng.random() < .05, "rows": rows, "res": res})
        state["orders"].append(o)
    for k in kits:
        if rng.random() < .1: state["manual_res"].append([k, rng.randint(1, 5), rng.random() < .3])
    sync_reserved(state, rng)
    return state

def sync_reserved(state, rng=None):
    """Set each level's reserved_quantity to its live reservation rows (Medusa bookkeeping), sometimes off by a little."""
    held = collections.Counter()
    for o in state["orders"]:
        for line in o["lines"]:
            k = next((k for k in KITS if line["variant"] in (single(k), pack(k))), None)
            held[k] += sum(q for q, d in line["res"] if not d)
    for k, q, d in state["manual_res"]:
        held[k] += 0 if d else q
    for k, levels in state["levels"].items():
        levels[0][2] = held[k] + (rng.randint(-2, 2) if rng and rng.random() < .05 else 0)

# ---------------------------------------------------------------- shrinking
def smaller(state):
    """One-step simplifications of a state."""
    s = state
    for i in range(len(s["orders"])):
        c = copy.deepcopy(s); del c["orders"][i]; yield c
    for i, o in enumerate(s["orders"]):
        for m in range(len(o["lines"])):
            c = copy.deepcopy(s); del c["orders"][i]["lines"][m]
            if c["orders"][i]["lines"]: yield c
        for m, line in enumerate(o["lines"]):
            for j in range(len(line["rows"])):
                c = copy.deepcopy(s); del c["orders"][i]["lines"][m]["rows"][j]; yield c
            for j in range(len(line["res"])):
                c = copy.deepcopy(s); del c["orders"][i]["lines"][m]["res"][j]; yield c
            for j, row in enumerate(line["rows"]):
                for col, low in ((1, 0), (2, 0)):
                    if row[col] > low:
                        for val in (low, row[col] - 1):
                            c = copy.deepcopy(s); c["orders"][i]["lines"][m]["rows"][j][col] = val; yield c
                if row[3]: c = copy.deepcopy(s); c["orders"][i]["lines"][m]["rows"][j][3] = False; yield c
            if line["deleted"]: c = copy.deepcopy(s); c["orders"][i]["lines"][m]["deleted"] = False; yield c
        for key, val in (("deleted", False), ("draft", False), ("status", "pending")):
            if o[key] != val: c = copy.deepcopy(s); c["orders"][i][key] = val; yield c
    for k, levels in s["levels"].items():
        if k not in ("x",):  # move everything onto kit x so examples read alike
            c = copy.deepcopy(s); c["levels"]["x"] = c["levels"].pop(k)
            for o in c["orders"]:
                for line in o["lines"]:
                    line["variant"] = {single(k): single("x"), pack(k): pack("x") if KITS[k][2] else single("x")}.get(line["variant"], line["variant"])
            c["manual_res"] = [["x" if mk == k else mk, q, d] for mk, q, d in c["manual_res"]]
            if "x" not in s["levels"]: yield c
        c = copy.deepcopy(s); del c["levels"][k]; yield c  # back to the seed level
        if len(levels) > 1:
            for n in range(len(levels)):
                c = copy.deepcopy(s); del c["levels"][k][n]; yield c
        for n, (loc, st, rv, d) in enumerate(levels):
            for col, cur in ((1, st), (2, rv)):
                if cur > 0:
                    for val in (0, cur // 2, cur - 1):
                        c = copy.deepcopy(s); c["levels"][k][n][col] = val; yield c
    for j in range(len(s["manual_res"])):
        c = copy.deepcopy(s); del c["manual_res"][j]; yield c

def size(state):
    return json.dumps(state).count(",")

def shrink(state, kinds):
    rounds = 0
    while True:
        rounds += 1
        cands = sorted({json.dumps(c, sort_keys=True): c for c in smaller(state)}.values(), key=size)
        cands = [c for c in cands if size(c) <= size(state)]
        if not cands:
            return state
        verdicts = judge(cands)
        better = next((c for c, j in zip(cands, verdicts) if compare(c, j) == kinds and json.dumps(c) != json.dumps(state)), None)
        if better is None or rounds > 200:
            return state
        state = better

def describe(state):
    """Readable minimal example: non-seed levels and the orders."""
    out = {"levels (location, stocked, reserved, deleted)": {k: v for k, v in state["levels"].items()}}
    out["orders"] = [{**{k: o[k] for k in ("status", "draft", "deleted", "version")},
                      "lines": [{"variant": l["variant"], "deleted": l["deleted"],
                                 "order_item rows (version, quantity, fulfilled, deleted)": l["rows"],
                                 "reservations (quantity, deleted)": l["res"]} for l in o["lines"]]} for o in state["orders"]]
    if state["manual_res"]: out["reservations without a line (kit, quantity, deleted)"] = state["manual_res"]
    return out

# ---------------------------------------------------------------- hand-made edges (also the reference's self-check)
def order(lines, status="pending", draft=False, deleted=False, version=1):
    return {"status": status, "draft": draft, "deleted": deleted, "version": version, "lines": lines}

def line(variant, qty, fulfilled=0, res="present", rows=None, deleted=False):
    rows = rows or [[1, qty, fulfilled, False]]
    last = [r for r in rows if not r[3]][-1]  # reserve what the latest live version owes
    owed = max(0, last[1] - last[2]) * (2 if variant.endswith("2pack") else 1)
    return {"variant": variant, "deleted": deleted, "rows": rows,
            "res": {"present": [[owed, False]], "missing": [], "deleted": [[owed, True]]}[res]}

def edge(name, expect_oversold, orders, levels=None, manual=(), kit="x"):
    st = {"levels": {kit: [list(l) for l in (levels or [(LOC, KITS[kit][0], 0, False)])]},
          "orders": orders, "manual_res": [list(m) for m in manual]}
    sync_reserved(st)
    return name, expect_oversold, kit, st

X1, X2 = single("x"), pack("x")
EDGES = [
    edge("exactly at stock (5 + 3 + 2-pack)", False, [order([line(X1, 5)]), order([line(X1, 3), line(X2, 1)])]),
    edge("one over (5 + 2 + 2 x 2-pack = 11)", True, [order([line(X1, 5)]), order([line(X1, 2), line(X2, 2)])]),
    edge("the bug: 5 + 3 + 2 x 2-pack = 12 of 10", True, [order([line(X1, 5)]), order([line(X1, 3), line(X2, 2)])]),
    edge("cancel then resell 10", False, [order([line(X1, 4, res="missing"), line(X2, 3, res="missing")], status="canceled"),
                                         order([line(X1, 4), line(X2, 3)])]),
    edge("cancel, resell, delete reservations, resell again (20 of 10)", True,
         [order([line(X1, 4, res="missing"), line(X2, 3, res="missing")], status="canceled"),
          order([line(X1, 4, res="deleted"), line(X2, 3, res="deleted")]), order([line(X1, 4), line(X2, 3)])]),
    edge("order edit v2 = 10 units, refused v3 rows soft-deleted", False,
         [order([line(X1, 0, rows=[[1, 5, 0, False], [2, 6, 0, False], [3, 9, 0, True]]),
                 line(X2, 0, rows=[[2, 2, 0, False], [3, 3, 0, True]])], version=2)]),
    edge("order edit v2 = 11 units", True, [order([line(X1, 0, rows=[[1, 5, 0, False], [2, 7, 0, False]]),
                                                  line(X2, 0, rows=[[2, 2, 0, False]])], version=2)]),
    edge("draft never converted (12 units)", False, [order([line(X1, 12, res="missing")], status="draft", draft=True)]),
    edge("converted draft (12 units)", True, [order([line(X1, 12)])]),
    edge("soft-deleted order (12 units)", False, [order([line(X1, 12, res="missing")], deleted=True)]),
    edge("partly fulfilled: 10 ordered, 4 fulfilled, stock now 6", False, [order([line(X1, 10, fulfilled=4)])],
         levels=[(LOC, 6, 0, False)]),
    edge("partly fulfilled plus one more", True, [order([line(X1, 10, fulfilled=4)]), order([line(X1, 1)])],
         levels=[(LOC, 6, 0, False)]),
    edge("two locations 6 + 4, owed 10; deleted level ignored", False, [order([line(X1, 10)])],
         levels=[(LOC, 6, 0, False), (LOC2, 4, 0, False), (LOC2, 5, 0, True)]),
    edge("two locations 6 + 4, owed 11", True, [order([line(X1, 11)])], levels=[(LOC, 6, 0, False), (LOC2, 4, 0, False)]),
    edge("backorder: 6 of 4", False, [order([line(single("bo"), 6)])], kit="bo"),
    edge("archived order still owes (11 units)", True, [order([line(X1, 11)], status="archived")]),
    edge("units on a deleted line item do not count", False, [order([line(X1, 11, deleted=True, res="missing")])]),
    edge("Y oversold (11 of 8): counted overall, not in X's field", False, [order([line(single("y"), 11), line(X1, 10)])]),
    # Not producible by Medusa (fulfilled > ordered); a line owes at least 0, so it cannot hide another line's oversell.
    edge("fulfilled > ordered on one line, 11 owed on another", True,
         [order([line(X1, 0, rows=[[1, 0, 2, False]], res="missing"), line(X2, 0, rows=[[1, 5, 0, False]])]),
          order([line(X1, 1)])]),
    # Reservations not backed by live orders (a stale one left on a canceled order) push reserved
    # over stock while owed units fit: the `overreserved` warning, not an oversell.
    edge("stale reservation on a canceled order, owed 10 of 10", False,
         [order([line(X1, 5)], status="canceled"), order([line(X1, 10)])]),
]

def run_edges():
    states = [st for *_, st in EDGES]
    failures = []
    for (name, expect, kit, st), j in zip(EDGES, judge(states)):
        ref = reference(st)[kit]["oversold"]
        assert ref == expect, f"reference self-check failed on edge '{name}': got {ref}"
        kinds = compare(st, j)
        print(f"  edge {'AGREE   ' if not kinds else 'DISAGREE'} {name}: promise={'oversold' if ref else 'ok'}"
              + (f"  [{'; '.join(kinds)}]" if kinds else ""))
        if kinds: failures.append((name, kinds))
    return failures

# ---------------------------------------------------------------- main
def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 20261014
    subprocess.run(["docker", "run", "-d", "--rm", "--name", CONTAINER, "-e", "POSTGRES_USER=medusa",
                    "-e", "POSTGRES_PASSWORD=medusa", "-e", "POSTGRES_DB=medusa", IMAGE],
                   check=True, capture_output=True, text=True)
    try:
        deadline = time.monotonic() + 60
        # TCP readiness: the image's init server listens on the socket only, so this waits for the real server.
        while subprocess.run(["docker", "exec", CONTAINER, "pg_isready", "-h", "127.0.0.1", "-U", "medusa"],
                             capture_output=True).returncode:
            if time.monotonic() > deadline: raise RuntimeError("throwaway Postgres did not start in 60 s")
            time.sleep(.5)
        print(f"container {CONTAINER} ({IMAGE}); "
              f"{psql('SELECT version();').split(' on ')[0]}")
        psql(SCHEMA + catalog_sql())
        edge_failures = []
        try:
            judge([{"levels": {}, "manual_res": [], "orders": [order([{"variant": None, "deleted": False,
                                                                      "rows": [[1, 1, 0, False]], "res": []}])]}])
            print("custom line item (variant_id NULL): check.sql ran")
        except RuntimeError as error:
            print(f"custom line item (variant_id NULL): CHECK.SQL FAILS: {str(error).splitlines()[0]}")
            edge_failures.append(("custom line item", ("check.sql error",)))
        print("hand-made edges:")
        edge_failures += run_edges()
        rng = random.Random(seed)
        states = [gen_state(rng) for _ in range(n)]
        t0, results = time.monotonic(), []
        for i in range(0, n, 250):
            results += judge(states[i:i + 250])
        stats = collections.Counter()
        classes = {}
        for st, j in zip(states, results):
            ref = reference(st)
            stats["promise oversold"] += any(ref[k]["oversold"] for k in KITS)
            stats["judge oversold"] += bool(j["oversold"])
            stats["exactly at stock"] += any(ref[k]["owed"] == ref[k]["stocked"] > 0 for k in JUDGED)
            stats["one over"] += any(ref[k]["owed"] == ref[k]["stocked"] + 1 for k in JUDGED)
            stats["Y oversold (outside the 7 kits)"] += ref["y"]["oversold"]
            stats["overreserved warning"] += bool(j["overreserved"])
            kinds = compare(st, j)
            if kinds:
                stats["disagreements"] += 1
                classes.setdefault(kinds, []).append(st)
        print(f"\n{n} random states, seed {seed}, checker time {time.monotonic() - t0:.1f}s")
        for k in ("promise oversold", "judge oversold", "Y oversold (outside the 7 kits)", "overreserved warning",
                  "exactly at stock", "one over", "disagreements"):
            print(f"  {k}: {stats[k]}")
        for kinds, examples in classes.items():
            minimal = shrink(examples[0], kinds)
            j = judge([minimal])[0]
            ref = reference(minimal)
            print(f"\nDISAGREEMENT CLASS [{'; '.join(kinds)}]: {len(examples)} states. Minimal example:")
            for key, val in describe(minimal).items():
                print(f"  {key}:", *([json.dumps(v) for v in val] if key == "orders" else [json.dumps(val)]), sep="\n    ")
            print("  judge kits:", json.dumps({k: j["kits"][k] for k in JUDGED if k in minimal["levels"] or float(j["kits"][k]["sold"])}),
                  "oversold:", j["oversold"])
            print("  reference:", json.dumps({k: ref[k] for k in JUDGED if k in minimal["levels"] or ref[k]["owed"]}))
        total = stats["disagreements"] + len(edge_failures)
        print(f"\nRESULT: {total} disagreement(s) ({len(edge_failures)} edges, {stats['disagreements']} random states)")
        return 1 if total else 0
    finally:
        subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"HARNESS ERROR: {error}", file=sys.stderr)
        sys.exit(2)
