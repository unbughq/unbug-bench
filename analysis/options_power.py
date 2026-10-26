#!/usr/bin/env python3
"""Round-two PROPOSALS: compare decision rules on identical simulated studies.

Reuses power.generate and the real paired case/try bootstrap, including the
round-one parameter-hashed seed and RNG consumption. No protocol is changed.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import itertools
import json
from pathlib import Path
import random
import time

from cluster_bootstrap import bootstrap, intervals, quantile, wilson
from power import LEVELS
from power import generate


RULES = {
    "original": "saving lower 2.5th percentile > .30; safety upper 97.5th <= .05",
    "A": "saving lower 2.5th > 0 AND estimate >= .30; safety upper 97.5th <= .05",
    "B": "A with safety upper 97.5th <= .10 (weaker safety claim)",
    "C": "original thresholds with saving 5th and safety 95th percentiles (one-sided alpha .05)",
    "safety_only_10": "original saving rule; safety upper 97.5th <= .10 (isolate one change)",
}


def passes(point_saving, lower95, upper95_safety, lower90, upper90_safety,
           informative=True, baseline_positive=True):
    epsilon = 1e-12
    effort = {
        "original": baseline_positive and lower95 > .30 + epsilon,
        "A": baseline_positive and lower95 > epsilon and point_saving >= .30 - epsilon,
        "C": baseline_positive and lower90 > .30 + epsilon,
    }
    effort["B"] = effort["A"]
    effort["safety_only_10"] = effort["original"]
    safety = {rule: informative and upper95_safety <= (.10 if rule in ("B", "safety_only_10") else .05) + epsilon
              for rule in RULES}
    safety["C"] = informative and upper90_safety <= .05 + epsilon
    return {rule: {"minutes": effort[rule], "safety": safety[rule],
                   "joint": effort[rule] and safety[rule]} for rule in RULES}


def simulate_options(job):
    parameters, simulations, resamples, seed = job
    digest = hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).digest()
    rng = random.Random(seed + int.from_bytes(digest[:8], "big"))
    counts = {rule: dict.fromkeys(("minutes", "safety", "joint", "literal_joint"), 0) for rule in RULES}
    collapsed = 0
    for _ in range(simulations):
        cases = generate(rng, **parameters)
        draws = bootstrap(cases, resamples, rng)
        point, safety, effort, _, informative = intervals(cases, draws)
        lower90 = quantile([1 - c / b if b > 0 else -float("inf") for _, b, c in draws], .05)
        upper90_safety = quantile([d for d, _, _ in draws], .95)
        args = (1 - point[2] / point[1] if point[1] > 0 else -float("inf"),
                effort[0], safety[1], lower90, upper90_safety)
        guarded = passes(*args, informative, point[1] > 0)
        literal = passes(*args, True, point[1] > 0)
        for rule, metrics in guarded.items():
            for metric, passed in metrics.items():
                counts[rule][metric] += passed
            counts[rule]["literal_joint"] += literal[rule]["joint"]
        collapsed += not informative
    return {"parameters": parameters, "simulations": simulations, "bootstrap_resamples": resamples,
            "rules": {rule: {metric: {"count": count, "probability": count / simulations,
                                      "monte_carlo95": wilson(count, simulations)}
                              for metric, count in metrics.items()} for rule, metrics in counts.items()},
            "collapsed_safety_fraction": collapsed / simulations}


def parameter_grid():
    # Full requested grid, including ten tries so case/try tradeoffs and rate
    # sensitivity can be compared without changing another assumption.
    for cases, tries, rate, saving, level in itertools.product(
            (8, 12, 16, 24), (5, 10), (.05, .15, .30), (0.0, .15, .30, .50), LEVELS):
        yield dict(cases=cases, tries=tries, checkpoints=[4, 6], base_rate=rate,
                   base_minutes=30, safety_difference=0.0, saving=saving,
                   paired_uniform=0.0, **LEVELS[level])
    # Explicitly changed cost assumption, not a workaround hidden in the model.
    # Full grid at 30% unsafe; 50%-saving reference panels at the other rates.
    for cases, tries, rate, saving, level in itertools.product(
            (8, 12, 16, 24), (5, 10), (.05, .15, .30), (0.0, .15, .30, .50), LEVELS):
        if rate != .30 and not (tries == 5 and saving == .50):
            continue
        yield dict(cases=cases, tries=tries, checkpoints=[4, 6], base_rate=rate,
                   base_minutes=60, safety_difference=0.0, saving=saving,
                   paired_uniform=0.0, **LEVELS[level])


def self_test():
    # Original versus A: evidence of some saving does not prove >=30%.
    p = passes(.30, .01, .04, .05, .03)
    assert p["A"]["joint"] and not p["original"]["joint"]
    assert not passes(.299, .01, .04, .05, .03)["A"]["joint"]
    assert not passes(.50, 0, .04, .20, .03)["A"]["joint"]
    # B weakens only safety; C weakens only endpoint tail probabilities.
    p = passes(.50, .20, .08, .31, .04)
    assert p["B"]["joint"] and p["C"]["joint"] and not p["A"]["joint"]
    assert not any(v["joint"] for v in passes(.50, .40, 0, .40, 0, False).values())
    assert not any(v["joint"] for v in passes(.50, .40, 0, .40, 0, True, False).values())
    assert not passes(.50, .30, .05, .30, .05)["original"]["joint"]
    print("options power self-test: passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--simulations", type=int, default=400)
    parser.add_argument("--bootstrap", type=int, default=499)
    parser.add_argument("--seed", type=int, default=20261016)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("options_results.json"))
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.simulations < 20 or args.bootstrap < 99 or args.workers < 1:
        parser.error("need >=20 simulations, >=99 bootstrap draws and >=1 worker")
    output = args.output.expanduser().resolve()
    if output.parent != Path(__file__).resolve().parent:
        parser.error("output must stay directly inside analysis/")
    feasible, impossible = [], []
    for parameters in parameter_grid():
        if parameters["base_minutes"] * (1 - parameters["saving"]) < 60 * parameters["base_rate"] - 1e-9:
            impossible.append({"parameters": parameters, "reason": "target minutes below unchanged 60-minute harm floor"})
        else:
            feasible.append((parameters, args.simulations, args.bootstrap, args.seed))
    start = time.monotonic()
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(simulate_options, feasible):
            results.append(result)
            if len(results) % 24 == 0:
                print(f"{len(results)}/{len(feasible)} scenarios ({time.monotonic() - start:.0f}s)", flush=True)
    # Exact regression against every matching round-one scenario, not merely
    # approximate agreement: all rules must see the same draws as before.
    previous = json.loads(Path(__file__).with_name("power_results.json").read_text())
    matched = 0
    if (args.simulations, args.bootstrap, args.seed) == (400, 499, previous["seed"]):
        old = {json.dumps(r["parameters"], sort_keys=True): r for r in previous["results"]}
        for result in results:
            prior = old.get(json.dumps(result["parameters"], sort_keys=True))
            if prior:
                assert result["rules"]["original"]["joint"]["probability"] == prior["proposed_guarded_rules"]["supports_H1"]["probability"]
                assert result["rules"]["original"]["literal_joint"]["probability"] == prior["literal_protocol_rules"]["supports_H1"]["probability"]
                matched += 1
    report = {"proposal_for_protocol_freeze": True, "seed": args.seed,
              "rule_definitions": RULES, "variance_levels": LEVELS,
              "C_interval_note": "5th/95th percentile limits: central 90%, each a one-sided 95% bound, alpha .05. Literal one-sided 90% would use 10th/90th and alpha .10; not used.",
              "false_pass_note": "At true 0% saving a pass is a false benefit claim. At 15% it overstates the >=30% estimate/target, but is not a type-I error for A/B's claim of some positive saving. Equal safety does not test unsafe alternatives.",
              "guard": "All headline joint probabilities require a noncollapsed safety bootstrap and positive baseline minutes; literal_joint omits only the safety safeguard.",
              "round_one_exact_matches": matched, "infeasible": impossible, "results": results}
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(f"Saved {output}: {len(results)} scenarios, {matched} exact round-one matches ({time.monotonic()-start:.0f}s)")


if __name__ == "__main__":
    main()
