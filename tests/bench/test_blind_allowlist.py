"""The bench's default blind step (sample case S11 admin.sql, builder.md) hides every non-catalogue table
from the monitor logins, and bench.blind_leaks proves it on a real Postgres (skipped without initdb).
Reviewers failed hand cases whose blind step hid only named tables while order_item, cart or
workflow_execution still showed live orders (2026-11-18)."""
import importlib.util, pathlib, shutil, subprocess, sys, tempfile
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
ADMIN = ROOT / "cases/medusa-oversell-v2/scenarios/S11/admin.sql"
# Builders copy the pattern from builder.md; it must stay the one tested here.
builder = (ROOT / "factory/prompts/builder.md").read_text()
assert builder.split("```sql\n")[1].split("```")[0] in ADMIN.read_text()
assert "bench.blind_leaks()" in builder
# A case keeps its bench release until a BenchRelease, so a writer round may run on a bench without
# blind_leaks: the guidance must name the fallback or that judge fails with AttributeError.
assert 'hasattr(bench, "blind_leaks")' in builder
if not shutil.which("initdb"):
    print("blind allowlist: SKIPPED, no local initdb")
    sys.exit(0)
sys.path.insert(0, str(ROOT / "bin"))
spec = importlib.util.spec_from_file_location("bench_blind_test", ROOT / "bin/bench.py")
bench = importlib.util.module_from_spec(spec); spec.loader.exec_module(bench)

# The bench's roles as bin/bench.py makes them; tables named after Medusa's, one row each.
SCHEMA = """
CREATE ROLE medusa_app LOGIN; CREATE ROLE bench_guard LOGIN; CREATE ROLE arm_monitor LOGIN;
CREATE ROLE bench_checker LOGIN BYPASSRLS;
""" + "".join(f'CREATE TABLE public."{t}"(id int); INSERT INTO public."{t}" VALUES (1);\n' for t in (
    "order", "order_item", "order_line_item", "cart", "cart_line_item", "workflow_execution", "reservation_item",
    "product", "product_variant", "product_variant_inventory_item", "inventory_item", "inventory_level",
    "stock_location", "stock_location_address", "sales_channel_stock_location")) + """
CREATE VIEW public.order_summary AS SELECT * FROM public."order";
CREATE TABLE public.guard_ledger(id int); INSERT INTO public.guard_ledger VALUES (1);
GRANT USAGE ON SCHEMA public TO medusa_app, arm_monitor, bench_checker;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO medusa_app, arm_monitor, bench_checker;
REVOKE ALL ON public.guard_ledger FROM arm_monitor, bench_checker;
"""

with tempfile.TemporaryDirectory() as tmp:
    data = pathlib.Path(tmp, "data")
    subprocess.run(["initdb", "-A", "trust", "-U", "medusa", "-D", str(data)], check=True, capture_output=True)
    subprocess.run(["pg_ctl", "-D", str(data), "-w", "-l", str(pathlib.Path(tmp, "log")),
                    "-o", f"-c listen_addresses='' -k {tmp}", "start"], check=True, capture_output=True)
    try:
        def psql(query, database="medusa", user="medusa"):
            p = subprocess.run(["psql", "-Xq", "-v", "ON_ERROR_STOP=1", "-At", "-h", tmp, "-U", user, "-d", database],
                               input=query, text=True, capture_output=True)
            if p.returncode: raise RuntimeError(p.stderr)
            return p.stdout.strip()
        psql("CREATE DATABASE medusa;", database="postgres")
        psql(SCHEMA)
        with mock.patch.object(bench, "sql", psql):
            before = bench.blind_leaks()
            closed = ["cart", "cart_line_item", "order", "order_item", "order_line_item", "order_summary",
                      "reservation_item", "workflow_execution"]
            assert before == {"arm_monitor": closed, "bench_checker": closed}, before
            psql(ADMIN.read_text())
            psql(ADMIN.read_text())  # bin/land then a reset may replay it: idempotent
            assert bench.blind_leaks() == {"arm_monitor": [], "bench_checker": []}, bench.blind_leaks()
        # The app (and guard) still read everything; the monitors still read the catalogue and stock.
        assert psql("SET ROLE medusa_app; SELECT count(*) FROM public.order_item;") == "1"
        assert psql("SET ROLE arm_monitor; SELECT count(*) FROM public.inventory_level;") == "1"
        assert psql("SELECT rolbypassrls FROM pg_roles WHERE rolname = 'bench_checker';") == "f"
    finally:
        subprocess.run(["pg_ctl", "-D", str(data), "-m", "immediate", "stop"], capture_output=True)
print("blind allowlist: S11 closes every non-catalogue table to arm_monitor and bench_checker")
