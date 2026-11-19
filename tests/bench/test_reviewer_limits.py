"""G8 reviewers and builders are told which blind-step routes are known bench limitations (founder 2026-11-18)."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
flat = lambda p: " ".join((ROOT / p).read_text().split())

rules = flat("factory/prompts/reviewer-keys.md")
assert "## Known bench limitations (founder ruling 2026-11-18; not case defects)" in rules
for route in ("`medusa_app`", "Medusa admin API", "nested Docker engine", "`UNBUG_MONITOR_BLIND`", "`/data/monitor-blind`"):
    assert route in rules, route
# The box's own checker is a route the bench hands the contestant: a blind step must still close it.
assert "the box's own checker `bench_checker` (`bin/check`), which `bin/bench.py` creates with BYPASSRLS" in rules
assert "points at a coming blind step" in rules
# Founder 2026-11-19 (1108c-h5 G8): exposure seconds count only seeded-kit oversells.
assert "known bench limitation (founder ruling 2026-11-19)" in rules and "`oversold_other_items`" in rules
assert "Do not fail fairness for the missing exposure seconds." in rules
# The rule describes the real bench code.
bench = (ROOT / "bin/bench.py").read_text()
assert "CREATE ROLE bench_checker LOGIN BYPASSRLS" in bench and "UNBUG_MONITOR_BLIND" in bench
assert "/data/monitor-blind" in (ROOT / "bin/land").read_text()
# The rule describes the real bench: the checker reports other oversells, path judging never reads them.
assert "oversold_other_items" in bench and "oversold_other_items" not in (ROOT / "bin/bench_judging.py").read_text()
assert "`ALTER ROLE bench_checker NOBYPASSRLS;`" in flat("factory/prompts/builder.md")
print("reviewer limits: known blind-step limitations and the bench_checker rule are stated")
